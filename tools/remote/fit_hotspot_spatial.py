"""Fit fresh hotspot weights on compact TRAIN/validation only, with bounded CUDA.

The historical localization selector is unchanged. The old test partition is
verified for integrity but never used for metrics, fitting or model selection.
Outputs are offline evidence and checkpoints, never a published UI model.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import time
from pathlib import Path

import torch
from hotspot_spatial import (
    SEED,
    DeviceCache,
    aligned_assessment,
    amplitude_anchor,
    initialize,
    load_partition,
)
from ignis.locking import ProcessLock
from ignis.ml.spatial_dataset import file_sha
from ignis.ml.spatial_network import FEATURE_VERSION, SpatialUNet, architecture, masked_loss
from recover_spatial import assess, sources, survey
from train_spatial import CaseStore, ProgressLog, require_cuda, write_json
from verify_spatial import state_sha


def fit_cases(store):
    if store.snapshot["dataset_id"] != "spatial-compact-v1" or tuple(store.shape) != (12, 16, 8):
        raise ValueError("Hotspot fitting requires the compact 12x16x8 dataset")
    counts = {split: len(store.by_split[split]) for split in ("train", "validation")}
    if counts != {"train": 120, "validation": 40}:
        raise ValueError("Expected the completed 200-case compact design: 120 train and 40 validation")
    parts = {split: load_partition(store, split) for split in ("train", "validation")}
    for split, cases in parts.items():
        if any(c["record"]["split"] != split for c in cases):
            raise ValueError("Development case belongs to the wrong partition")
    return parts


def objective_loss(predicted, target, observed, globals_, global_target, global_mask, active, recipe):
    if recipe not in ("hot", "hot_peak"):
        raise ValueError("Fitting recipe must be hot or hot_peak")
    per_frame = masked_loss(predicted, target, observed, 1 + 4 * active)
    if recipe == "hot_peak":
        per_frame = per_frame + 0.5 * amplitude_anchor(predicted, target, observed, active)
    return (per_frame + 0.25 * masked_loss(globals_, global_target, global_mask)).mean()


def selection_value(metrics):
    value = float(metrics["localization_selection_error"])
    if not math.isfinite(value):
        raise ValueError("Nonfinite validation localization error")
    return value


def validation_assessment(network, cases):
    if not cases or any(c["record"]["split"] != "validation" for c in cases):
        raise ValueError("Checkpoint selection requires validation cases only")
    return assess(network, cases, "cuda:0")[0]


def save_weights(path, state, width, recipe, step):
    with path.open("xb") as stream:
        torch.save(
            {
                "state_dict": state,
                "architecture": architecture(width),
                "feature_version": FEATURE_VERSION,
                "recipe": recipe,
                "selected_step": step,
                "scope": "offline train/validation development",
            },
            stream,
        )


def source_snapshot():
    root = Path(__file__).resolve().parents[2]
    return {
        **sources(),
        **{
            path.as_posix(): file_sha(root / path)
            for path in (Path("tools/remote/hotspot_spatial.py"), Path("tools/remote/fit_hotspot_spatial.py"))
        },
    }


def run_fit(args):
    pause = args.home / "datasets/spatial-corpus-v1/PAUSE"
    if not pause.is_file():
        raise RuntimeError("Original corpus must remain paused")
    if args.output.exists():
        raise FileExistsError("Existing fit output is preserved")
    if args.output.resolve().is_relative_to(args.dataset.resolve()):
        raise ValueError("Fit output must be outside the immutable source dataset")
    with ProcessLock(args.home / "runtime/compute.lock"):
        args.output.mkdir(parents=True, exist_ok=False)
        started = time.perf_counter()
        log = ProgressLog(args.output / "progress.jsonl")
        try:
            compute = require_cuda()
            torch.set_num_threads(4)
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
            torch.use_deterministic_algorithms(True, warn_only=True)
            source_hashes = source_snapshot()
            write_json(args.output / "sources.json", source_hashes)
            log.emit("hotspot_fit_started", recipe=args.recipe, **compute)
            store = CaseStore(args.dataset)
            store.verify(log)
            parts = fit_cases(store)
            write_json(args.output / "dataset-snapshot.json", store.snapshot)
            write_json(args.output / "training-survey.json", survey(parts["train"]))
            cache = DeviceCache(parts["train"])
            cache_bytes = cache.bytes
            log.emit("device_cache_ready", bytes=cache_bytes, frames=len(cache.addresses), cases=120)
            network, optimizer, rng = initialize(args.width)
            initial_sha = state_sha(network)
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.steps, eta_min=1e-5)
            deadline = started + args.seconds - min(120, args.seconds / 4)
            best, history, steps = None, [], 0

            def evaluate(step, loss):
                nonlocal best
                metrics = validation_assessment(network, parts["validation"])
                value = selection_value(metrics)
                improved = best is None or value < best["value"]
                if improved:
                    state = {k: v.detach().cpu().clone() for k, v in network.state_dict().items()}
                    path = args.output / f"best-step-{step:06d}.pt"
                    save_weights(path, state, args.width, args.recipe, step)
                    best = {"value": value, "step": step, "state": state, "checkpoint": path.name}
                row = {
                    "step": step,
                    "training_loss": loss,
                    "validation_localization_error": value,
                    "improved": improved,
                    "best_step": best["step"],
                    "diagnostics": metrics["diagnostics"],
                    "elapsed_seconds": time.perf_counter() - started,
                }
                history.append(row)
                write_json(args.output / f"validation-step-{step:06d}.json", metrics)
                log.emit("hotspot_fit_validation", **row)

            for step in range(1, args.steps + 1):
                if time.perf_counter() >= deadline or not pause.is_file():
                    break
                network.train()
                x, y, mask, g, gm, active = cache.batch(rng, args.recipe, args.batch_size)
                optimizer.zero_grad(set_to_none=True)
                predicted, global_ = network(x)
                loss = objective_loss(predicted, y, mask, global_, g, gm, active, args.recipe)
                if not torch.isfinite(loss).item():
                    raise ValueError("Nonfinite hotspot fitting loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(network.parameters(), 5, error_if_nonfinite=True)
                optimizer.step()
                scheduler.step()
                steps = step
                if step == 1:
                    torch.cuda.synchronize()
                    log.emit(
                        "cuda_training_started",
                        recipe=args.recipe,
                        device=str(x.device),
                        parameters=sum(p.numel() for p in network.parameters()),
                        batch_size=args.batch_size,
                        initial_weights_sha256=initial_sha,
                    )
                if step % 250 == 0:
                    evaluate(step, float(loss.item()))
            if not steps:
                raise RuntimeError("Budget left no training update; no fitted model saved")
            if steps % 250:
                evaluate(steps, float(loss.item()))
            network.load_state_dict(best["state"], strict=True)
            selected_sha = state_sha(network)
            del cache, optimizer
            torch.cuda.empty_cache()
            final_metrics = {}
            for split in ("train", "validation"):
                metrics, plots = aligned_assessment(network, parts[split])
                final_metrics[split] = metrics
                with (args.output / f"{split}-plots.json.gz").open("xb") as raw:
                    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as stream:
                        stream.write(json.dumps(plots, allow_nan=False).encode("utf-8"))
            if state_sha(network) != selected_sha:
                raise ValueError("Final assessment changed the selected weights")
            weights_path = args.output / "weights.pt"
            save_weights(weights_path, best["state"], args.width, args.recipe, best["step"])
            restored = SpatialUNet(base_channels=args.width).to("cuda:0")
            restored.load_state_dict(
                torch.load(weights_path, map_location="cpu", weights_only=True)["state_dict"], strict=True
            )
            if state_sha(restored) != selected_sha:
                raise ValueError("Saved weights failed exact reload verification")
            if source_snapshot() != source_hashes:
                raise ValueError("Training sources changed during execution")
            if file_sha(args.dataset / "manifest.json") != store.source_sha:
                raise ValueError("Dataset manifest changed during execution")
            compute.update(
                peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                peak_reserved_bytes=torch.cuda.max_memory_reserved(),
            )
            elapsed = time.perf_counter() - started
            report = {
                "scope": "Offline training/validation development; no test metrics or UI activation",
                "recipe": args.recipe,
                "steps": steps,
                "steps_requested": args.steps,
                "batch_size": args.batch_size,
                "width": args.width,
                "seed": SEED,
                "budget_seconds": args.seconds,
                "elapsed_seconds": elapsed,
                "budget_overrun_seconds": max(0, elapsed - args.seconds),
                "budget_basis": "Stop updates before deadline; finish validation, archival and reload",
                "selected_step": best["step"],
                "selected_checkpoint": best["checkpoint"],
                "selection_metric": "localization_selection_error",
                "selection_split": "validation",
                "best_validation_localization_error": best["value"],
                "history": history,
                "metrics": final_metrics,
                "test_metric_evaluations": 0,
                "source_sha256": source_hashes,
                "dataset_snapshot_sha256": store.snapshot_sha,
                "initial_weights_sha256": initial_sha,
                "weights_state_sha256": selected_sha,
                "weights_file_sha256": file_sha(weights_path),
                "exact_weight_reload": True,
                "compute": compute,
                "gpu_cache_bytes": cache_bytes,
                "partition_counts": {split: len(cases) for split, cases in parts.items()},
                "cuda_determinism": "cudnn deterministic; warn-only algorithms; trilinear backward may vary",
            }
            write_json(args.output / "report.json", report)
            log.emit(
                "hotspot_fit_completed", selected_step=best["step"], steps=steps, elapsed_seconds=elapsed
            )
            return report
        finally:
            log.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recipe", choices=("hot", "hot_peak"), required=True)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--steps", type=int, default=10000)
    parser.add_argument("--batch-size", type=int, choices=(32,), default=32)
    parser.add_argument("--width", type=int, choices=(16, 24, 32), default=24)
    args = parser.parse_args(argv)
    if not 120 <= args.seconds <= 3600 or not 1 <= args.steps <= 20000:
        parser.error("Fitting requires 120..3600 seconds and 1..20000 updates")
    return args


if __name__ == "__main__":
    if os.name != "nt":
        raise RuntimeError("Real training runs on the authorized Windows workstation")
    run_fit(parse_args())
