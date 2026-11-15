"""Bounded, training-only CUDA hotspot diagnostics on immutable FDS datasets.

Uniform and hot-time recipes use the same initialized network, update count,
batch size and loss. Optional hot_peak adds a local amplitude anchor. No old
test partition is evaluated, no existing model is overwritten or activated.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import torch
from ignis.locking import ProcessLock
from ignis.ml.spatial_network import SpatialUNet, architecture, input_tensor, masked_loss
from recover_spatial import assess, prepared, sources, survey
from torch.nn import functional as F
from train_spatial import CaseStore, ProgressLog, predict_case, require_cuda, write_json
from verify_spatial import state_sha

SEED = 20261116
RECIPES = ("uniform", "hot", "hot_peak")


def load_partition(store, split):
    if split not in ("train", "validation"):
        raise ValueError("Old test targets are excluded from hotspot development")
    result = []
    for index in store.by_split[split]:
        case = prepared(store.get(index))
        case["source_dataset"] = store.snapshot["dataset_id"]
        result.append(case)
    store.cache.clear()
    return result


def small_training_set(cases):
    """Six observed thermal events and two sample-inactive controls, train only."""
    if not cases or any(c["record"]["split"] != "train" for c in cases):
        raise ValueError("Diagnostic selection is restricted to training cases")
    selected = []
    for micro in (True, False):
        group = [c for c in cases if (c["config"]["gravity_g"] < 0.01) == micro]
        used_layouts = set()
        for kind in ("overheating", "flaming", "battery"):
            candidates = [
                c
                for c in group
                if c["config"]["incident_type"] == kind and c["record"]["layout_id"] not in used_layouts
            ]
            case = max(candidates, key=lambda c: float(np.nanmax(c["temperature_c"])))
            selected.append(case)
            used_layouts.add(case["record"]["layout_id"])
        controls = [c for c in group if not c["active"].any()]
        if not controls:
            raise ValueError("A sample-inactive control is required in each gravity")
        selected.append(min(controls, key=lambda c: c["record"]["id"]))
    if len({c["record"]["id"] for c in selected}) != 8:
        raise ValueError("Diagnostic cases must be distinct")
    return selected


def frame_probabilities(cases, recipe):
    """Equal case mass; hot recipe mixes uniform times and top thermal quartile.

    This deliberately changes the training distribution, never evaluation.
    Quiet times retain nonzero probability. All choices use training labels.
    """
    if recipe not in RECIPES or not cases:
        raise ValueError("Unknown or empty sampling recipe")
    probabilities, addresses = [], []
    for number, case in enumerate(cases):
        if case["record"]["split"] != "train":
            raise ValueError("Sampling targets must come from training only")
        frames = np.flatnonzero(case["time_s"] > 0)
        if not len(frames):
            raise ValueError("No post-initial training observation")
        weights = np.full(len(frames), 1 / len(frames), dtype=np.float64)
        if recipe != "uniform":
            observed = case["field_mask"][frames, :, 0]
            values = np.where(observed, case["temperature_c"][frames], -np.inf)
            peaks = values.max(axis=1)
            hot = peaks >= case["config"]["ambient_temperature_c"] + 5
            if hot.any():
                threshold = np.quantile(peaks[hot], 0.75)
                favored = hot & (peaks >= threshold)
                weights = 0.5 * weights + 0.5 * favored / favored.sum()
        probabilities.extend(weights / len(cases))
        addresses.extend((number, int(frame)) for frame in frames)
    probability = np.asarray(probabilities)
    if not np.isclose(probability.sum(), 1) or (probability <= 0).any():
        raise ValueError("Sampling probabilities must cover every observed time")
    return probability, addresses


def amplitude_anchor(predicted, target, observed, active):
    """Anchor each field's observed maximum at its true location in encoded units.

    Missing fields and entirely inactive fields contribute nothing. The
    historical all-observed regression remains responsible for false positives.
    """
    if predicted.shape != target.shape or observed.shape != target.shape or active.shape != target.shape:
        raise ValueError("Amplitude tensors must have identical shapes")
    mask = observed.bool().flatten(2)
    truth = target.flatten(2)
    at = torch.where(mask, truth, -torch.inf).argmax(dim=2, keepdim=True)
    peak = torch.where(mask, truth, 0).gather(2, at).squeeze(2)
    guess = predicted.flatten(2).gather(2, at).squeeze(2)
    present = (active.bool().flatten(2) & mask).any(dim=2)
    error = F.smooth_l1_loss(guess, peak, reduction="none")
    return torch.where(present, error, 0).sum(dim=1) / present.sum(dim=1).clamp_min(1)


def peak_alignment(case, fields):
    """Physical temperature errors at measured peaks, excluding missing/initial data.

    A high prediction elsewhere cannot satisfy the amplitude-at-truth metric.
    The global FDS maximum is deliberately not used as a voxel target.
    """
    mask = case["field_mask"][..., 0] & (case["time_s"] > 0)[:, None]
    if not mask.any():
        raise ValueError("Peak alignment requires post-initial temperature observations")
    truth = np.where(mask, case["temperature_c"], -np.inf)
    prediction = np.where(mask, fields[..., 0], -np.inf)
    t, p = np.unravel_index(np.argmax(truth), truth.shape)
    pt, pp = np.unravel_index(np.argmax(prediction), prediction.shape)
    same_time_peak = int(np.argmax(prediction[t]))
    positions = case["positions_m"]
    return {
        "run_id": case["record"]["id"],
        "layout_id": case["record"]["layout_id"],
        "gravity_g": case["config"]["gravity_g"],
        "incident_type": case["config"]["incident_type"],
        "sampled_peak_c": float(truth[t, p]),
        "prediction_at_true_peak_c": float(prediction[t, p]),
        "peak_location_amplitude_error_c": float(abs(prediction[t, p] - truth[t, p])),
        "true_peak_time_s": float(case["time_s"][t]),
        "predicted_peak_c": float(prediction[pt, pp]),
        "predicted_peak_time_s": float(case["time_s"][pt]),
        "peak_time_error_s": float(abs(case["time_s"][pt] - case["time_s"][t])),
        "peak_displacement_at_true_time_m": float(np.linalg.norm(positions[p] - positions[same_time_peak])),
        "global_peak_displacement_m": float(np.linalg.norm(positions[p] - positions[pp])),
        "true_peak_position_m": positions[p].tolist(),
        "peak_is_hot": bool(truth[t, p] >= case["config"]["ambient_temperature_c"] + 5),
        "ties": "first maximum in measured time/point order; displacement is not informative for flat fields",
    }


def aligned_assessment(network, cases):
    metrics, plots = assess(network, cases, "cuda:0", plots=True)
    metrics["peak_alignment"] = [
        peak_alignment(case, predict_case(network, case, device="cuda:0", batch_size=8)[0]) for case in cases
    ]
    return metrics, plots


class DeviceCache:
    """Cache the selected small volumes once; mixed-case batches stay on CUDA."""

    def __init__(self, cases, device="cuda:0"):
        shapes = {tuple(c["shape"]) for c in cases}
        if len(shapes) != 1:
            raise ValueError("One exact observation shape per GPU cache; no interpolation")
        self.probabilities = {}
        addresses = None
        for recipe in RECIPES:
            probability, entries = frame_probabilities(cases, recipe)
            if addresses is not None and addresses != entries:
                raise ValueError("Recipe changed target membership")
            addresses = entries
            self.probabilities[recipe] = probability
        self.addresses = addresses
        columns = {name: [] for name in ("x", "y", "mask", "g", "gm", "active")}
        for number, frame in addresses:
            c = cases[number]
            columns["x"].append(input_tensor(c["static"], c["config"], c["manifest"], c["time_s"][frame]))
            for name, key in (
                ("y", "encoded_fields"),
                ("mask", "observed"),
                ("g", "encoded_globals"),
                ("gm", "global_mask"),
                ("active", "active"),
            ):
                columns[name].append(c[key][frame])
        self.values = {name: torch.as_tensor(np.stack(rows), device=device) for name, rows in columns.items()}
        self.bytes = sum(value.numel() * value.element_size() for value in self.values.values())

    def batch(self, rng, recipe, size):
        indices = rng.choice(len(self.addresses), size=size, replace=True, p=self.probabilities[recipe])
        indices = torch.as_tensor(indices, device=self.values["x"].device)
        return [value.index_select(0, indices) for value in self.values.values()]


def initialize(width, initial=None):
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    network = SpatialUNet(base_channels=width).to("cuda:0")
    if initial is not None:
        network.load_state_dict(initial, strict=True)
    optimizer = torch.optim.AdamW(network.parameters(), lr=1e-3, weight_decay=1e-4)
    return network, optimizer, np.random.default_rng(SEED)


def run_diagnostics(args):
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    log = ProgressLog(args.output / "progress.jsonl")
    try:
        compute = require_cuda()
        torch.set_num_threads(4)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        # Trilinear CUDA backward is not guaranteed bitwise deterministic.
        torch.use_deterministic_algorithms(True, warn_only=True)
        log.emit("hotspot_diagnostic_started", **compute)
        store = CaseStore(args.dataset)
        store.verify(log)
        cases = small_training_set(load_partition(store, "train"))
        write_json(args.output / "small-set.json", survey(cases))
        source_hashes = {
            **sources(),
            "tools/remote/hotspot_spatial.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        write_json(args.output / "sources.json", source_hashes)
        write_json(args.output / "dataset-snapshot.json", store.snapshot)
        cache = DeviceCache(cases)
        log.emit("device_cache_ready", bytes=cache.bytes, frames=len(cache.addresses), cases=len(cases))
        network, _, _ = initialize(args.width)
        initial = {k: v.detach().cpu().clone() for k, v in network.state_dict().items()}
        initial_sha = state_sha(network)
        del network
        results = {}
        for number, recipe in enumerate(args.recipes):
            network, optimizer, rng = initialize(args.width, initial)
            assert state_sha(network) == initial_sha
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.steps, eta_min=1e-5)
            deadline = min(
                started + args.seconds - 15,
                time.perf_counter()
                + max(
                    1, (args.seconds - (time.perf_counter() - started) - 30) / (len(args.recipes) - number)
                ),
            )
            history, steps = [], 0
            recipe_started = time.perf_counter()
            for step in range(1, args.steps + 1):
                if time.perf_counter() >= deadline:
                    break
                network.train()
                x, y, mask, g, gm, active = cache.batch(rng, recipe, args.batch_size)
                optimizer.zero_grad(set_to_none=True)
                predicted, global_ = network(x)
                per_frame = masked_loss(predicted, y, mask, 1 + 4 * active)
                if recipe == "hot_peak":
                    per_frame = per_frame + 0.5 * amplitude_anchor(predicted, y, mask, active)
                loss = (per_frame + 0.25 * masked_loss(global_, g, gm)).mean()
                if not torch.isfinite(loss).item():
                    raise ValueError("Nonfinite hotspot training loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(network.parameters(), 5, error_if_nonfinite=True)
                optimizer.step()
                scheduler.step()
                steps = step
                if step == 1:
                    torch.cuda.synchronize()
                    log.emit(
                        "cuda_training_started",
                        recipe=recipe,
                        parameters=sum(p.numel() for p in network.parameters()),
                        batch_size=args.batch_size,
                    )
                if step % 250 == 0:
                    metrics, _ = assess(network, cases, "cuda:0")
                    row = {
                        "step": step,
                        "loss": float(loss.item()),
                        "diagnostics": metrics["diagnostics"],
                        "physical": metrics["layout_balanced"],
                        "elapsed_seconds": time.perf_counter() - recipe_started,
                    }
                    history.append(row)
                    log.emit("hotspot_diagnostic_progress", recipe=recipe, **row)
            if not steps:
                raise RuntimeError("No optimizer step; diagnostic is incomplete")
            metrics, plots = aligned_assessment(network, cases)
            weights = {k: v.detach().cpu().clone() for k, v in network.state_dict().items()}
            torch.save(
                {
                    "state_dict": weights,
                    "architecture": architecture(args.width),
                    "scope": "TRAIN-only overfit diagnostic",
                },
                args.output / (recipe + ".pt"),
            )
            with gzip.open(args.output / (recipe + "-plots.json.gz"), "wt", encoding="utf-8") as stream:
                json.dump(plots, stream, allow_nan=False)
            results[recipe] = {
                "steps": steps,
                "elapsed_seconds": time.perf_counter() - recipe_started,
                "initial_weights_sha256": initial_sha,
                "final_weights_sha256": state_sha(network),
                "metrics": metrics,
                "history": history,
            }
            write_json(args.output / (recipe + "-report.json"), results[recipe])
            log.emit(
                "hotspot_recipe_completed", recipe=recipe, steps=steps, diagnostics=metrics["diagnostics"]
            )
            del network, optimizer
            torch.cuda.empty_cache()
        compute.update(
            peak_allocated_bytes=torch.cuda.max_memory_allocated(),
            peak_reserved_bytes=torch.cuda.max_memory_reserved(),
        )
        report = {
            "scope": "Training-set diagnostic only; no held-out/generalisation claim or UI activation",
            "source_sha256": source_hashes,
            "compute": compute,
            "results": results,
            "elapsed_seconds": time.perf_counter() - started,
            "budget_seconds": args.seconds,
            "recipes": args.recipes,
            "steps_requested": args.steps,
            "batch_size": args.batch_size,
            "seed": SEED,
            "width": args.width,
            "training_cases": [c["record"]["id"] for c in cases],
            "gpu_cache_bytes": cache.bytes,
            "identical_initial_weights": True,
            "cuda_determinism": "cudnn deterministic; warn-only deterministic algorithms; trilinear backward may vary",
        }
        write_json(args.output / "report.json", report)
        log.emit("hotspot_diagnostic_completed", elapsed_seconds=report["elapsed_seconds"])
    finally:
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=900)
    parser.add_argument("--steps", type=int, default=3000)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--width", type=int, choices=(16, 24, 32), default=24)
    parser.add_argument("--recipes", nargs="+", choices=RECIPES, default=["uniform", "hot"])
    args = parser.parse_args()
    if (
        os.name != "nt"
        or not 60 <= args.seconds <= 1800
        or not 1 <= args.steps <= 20000
        or not 1 <= args.batch_size <= 128
    ):
        raise ValueError("Hotspot diagnostics require Windows and bounded compute")
    if len(set(args.recipes)) != len(args.recipes):
        raise ValueError("Recipes must be distinct")
    if args.output.exists():
        raise FileExistsError("Existing evidence is preserved")
    if not (args.home / "datasets/spatial-corpus-v1/PAUSE").exists():
        raise RuntimeError("Original corpus must remain paused")
    with ProcessLock(args.home / "runtime/compute.lock"):
        run_diagnostics(args)


if __name__ == "__main__":
    main()
