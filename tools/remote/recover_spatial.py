"""Bounded CUDA recovery experiment using verified, already available FDS data.

First compare the historical and region-balanced objectives on the same small
training subset. This is intentionally an overfit check, NOT a held-out score.
The later train mode uses a completed compact dataset's reserved geometries.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from ignis.locking import ProcessLock
from ignis.ml.incidents import COMPILER_VERSION, INCIDENT_TYPES, file_sha
from ignis.ml.spatial_network import (
    FEATURE_VERSION,
    SpatialUNet,
    architecture,
    encode_fields,
    encode_globals,
    input_tensor,
    masked_loss,
)
from ignis.ml.spatial_training import LOCALIZATION_VERSION, LOSS_VERSION, region_balanced_loss, support_loss
from ignis.physics.materials import MODEL_VERSION
from ignis.provenance import canonical_sha
from train_spatial import (
    CaseStore,
    ProgressLog,
    predict_case,
    publish,
    require_cuda,
    run_metrics,
    source_hashes,
    summarize,
    write_json,
)
from verify_spatial import classification, compare_metrics, physical_metrics, plot_case, state_sha

SEED = 20261115
MODEL_ID = "spatial-recovery-v1"


def sources():
    root = Path(__file__).resolve().parents[2]
    return {
        **source_hashes(),
        "tools/remote/recover_spatial.py": file_sha(Path(__file__)),
        "tools/remote/verify_spatial.py": file_sha(root / "tools/remote/verify_spatial.py"),
        "backend/ignis/ml/spatial_training.py": file_sha(root / "backend/ignis/ml/spatial_training.py"),
    }


def load_sources(home, *, compact=False, compact_path=None, log=None):
    """Snapshot and verify originals without editing any dataset or partition."""
    datasets = [("incidents-v1", False), ("spatial-corpus-v1", True)]
    if compact:
        datasets.append(("spatial-compact-v1", False))
    stores = {}
    for name, partial in datasets:
        directory = (
            compact_path if name == "spatial-compact-v1" and compact_path else home / "datasets" / name
        )
        store = CaseStore(directory, allow_incomplete=partial)
        if store.snapshot["dataset_id"] != name:
            raise ValueError("Recovery source dataset identity mismatch")
        store.verify(log)
        expected_shape = (8, 10, 4) if name == "incidents-v1" else (12, 16, 8)
        if tuple(store.shape) != expected_shape:
            raise ValueError("Recovery source sampling shape mismatch")
        stores[name] = store
    return stores


def prepared(case):
    """Cache compact targets/static inputs in host RAM; preserve actual coordinates."""
    case = dict(case)
    shape = tuple(case["shape"])
    raw = np.stack([case["temperature_c"], case["smoke_kg_m3"]], axis=-1)
    mask = case["field_mask"]
    ambient = case["config"]["ambient_temperature_c"]
    active = np.stack([raw[..., 0] >= ambient + 5, raw[..., 1] >= 1e-7], axis=-1) & mask
    case["encoded_fields"] = encode_fields(raw, ambient).transpose(0, 2, 1).reshape(-1, 2, *shape)
    case["observed"] = mask.transpose(0, 2, 1).reshape(-1, 2, *shape)
    case["active"] = active.transpose(0, 2, 1).reshape(-1, 2, *shape)
    case["encoded_globals"] = encode_globals(case["globals"], ambient)
    return case


def select_cases(stores, *, compact=False):
    """Only original training partitions supplement compact training.

    Exact duplicates (same FDS deck and physical geometry) are removed. A
    physical geometry cannot cross any partition, irrespective of dataset ID.
    Source corpus families must retain their original split.
    """
    partitions = {key: [] for key in ("train", "validation", "test")}
    used, signatures, families = set(), {}, {}
    order = ["spatial-compact-v1", "incidents-v1", "spatial-corpus-v1"] if compact else list(stores)
    for name in order:
        store = stores[name]
        for index, record in enumerate(store.records):
            split = record["split"]
            if name != "spatial-compact-v1" and split != "train":
                continue
            signature = record["geometry_signature"]
            if signature in signatures and signatures[signature] != split:
                raise ValueError("Geometry leaked between recovery partitions")
            signatures[signature] = split
            family = record.get("structural_family")
            if family and family in families and families[family] != split:
                raise ValueError("Structural family leaked between recovery partitions")
            if family:
                families[family] = split
            case = store.get(index)
            identity = (signature, case["manifest"]["deck_sha256"])
            if identity in used:
                continue
            used.add(identity)
            case = prepared(case)
            case["source_dataset"] = name
            partitions[split].append(case)
        store.cache.clear()
    return partitions


def survey(cases):
    rows = []
    for case in cases:
        after = case["time_s"] > 0
        active = case["active"][after]
        rows.append(
            {
                "dataset": case["source_dataset"],
                "run_id": case["record"]["id"],
                "layout_id": case["record"]["layout_id"],
                "incident_type": case["config"]["incident_type"],
                "sample_shape": case["shape"].tolist(),
                "observed": case["observed"][after].sum(axis=(0, 2, 3, 4)).tolist(),
                "active": active.sum(axis=(0, 2, 3, 4)).tolist(),
                "temperature_max_c": float(np.nanmax(case["temperature_c"])),
                "smoke_max_kg_m3": float(np.nanmax(case["smoke_kg_m3"])),
            }
        )
    return rows


def choose_small(cases):
    """Five incident types + one clear control; selection uses training data only."""
    selected = []
    for kind in INCIDENT_TYPES:
        candidates = [case for case in cases if case["config"]["incident_type"] == kind]
        # Prefer a strong measured event, independent of model predictions.
        selected.append(
            max(
                candidates,
                key=lambda c: float(np.nanmax(c["temperature_c"]))
                + float(np.arcsinh(np.nanmax(c["smoke_kg_m3"]) / 1e-6)),
            )
        )
    controls = [c for c in cases if not c["active"].any()]
    if controls:
        selected.append(min(controls, key=lambda c: c["record"]["id"]))
    return selected


def batch(case, frames, device):
    x = np.stack(
        [input_tensor(case["static"], case["config"], case["manifest"], case["time_s"][i]) for i in frames]
    )
    values = [
        x,
        case["encoded_fields"][frames],
        case["observed"][frames],
        case["encoded_globals"][frames],
        case["global_mask"][frames],
        case["active"][frames],
    ]
    return [torch.as_tensor(value, device=device) for value in values]


def field_loss(predicted, target, mask, active, objective):
    if objective == "historical":
        return masked_loss(predicted, target, mask, 1 + 4 * active)
    if objective == "balanced":
        return region_balanced_loss(predicted, target, mask, active)
    if objective == "localized":
        return masked_loss(predicted, target, mask, 1 + 4 * active) + 0.25 * support_loss(
            predicted, mask, active
        )
    raise ValueError("Unknown recovery objective")


def fit(network, cases, optimizer, rng, *, device, objective, frames_per_case, deadline, log, first):
    network.train()
    counts = Counter(c["record"]["layout_id"] for c in cases)
    weights = np.array([1 / counts[c["record"]["layout_id"]] for c in cases])
    weights /= weights.mean()
    total, frames_seen, steps = 0.0, 0, 0
    for index in rng.permutation(len(cases)):
        case = cases[index]
        available = np.flatnonzero(case["time_s"] > 0)
        selected = rng.permutation(available)[:frames_per_case]
        for start in range(0, len(selected), 8):
            if time.perf_counter() >= deadline:
                return total / max(1, frames_seen), steps, first, True
            x, y, mask, g, gm, active = batch(case, selected[start : start + 8], device)
            optimizer.zero_grad(set_to_none=True)
            predicted, globals_ = network(x)
            loss = (
                field_loss(predicted, y, mask, active, objective) + 0.25 * masked_loss(globals_, g, gm)
            ).mean() * weights[index]
            if not torch.isfinite(loss).item():
                raise ValueError("Nonfinite recovery loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(network.parameters(), 5.0, error_if_nonfinite=True)
            optimizer.step()
            if first:
                torch.cuda.synchronize()
                log.emit(
                    "cuda_training_started",
                    objective=objective,
                    device_name=torch.cuda.get_device_name(),
                    parameters=sum(p.numel() for p in network.parameters()),
                    allocated_bytes=torch.cuda.memory_allocated(),
                )
                first = False
            total += float(loss.item()) * len(x)
            frames_seen += len(x)
            steps += 1
    return total / max(1, frames_seen), steps, first, False


def aggregate_detections(rows):
    result = {}
    for kind in ("hot", "smoky"):
        counts = {key: sum(row[kind][key] for row in rows) for key in ("tp", "fp", "fn", "tn")}
        tp, fp, fn = (counts[key] for key in ("tp", "fp", "fn"))
        result[kind] = {
            **counts,
            "recall": tp / (tp + fn) if tp + fn else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "iou": tp / (tp + fp + fn) if tp + fp + fn else None,
        }
    return result


def smoke_arrival(case, fields):
    """First sampled threshold crossing; absent arrivals are right-censored.

    Only points observed throughout the full common time window are eligible.
    Timing errors condition on both arrivals; misses and false arrivals are
    reported separately and never turned into a zero error or end-time label.
    """
    times = np.asarray(case["time_s"])
    truth, predicted = case["smoke_kg_m3"], fields[..., 1]
    mask = case["field_mask"][..., 1]
    if truth.shape != predicted.shape or truth.shape != mask.shape or truth.shape[0] != len(times):
        raise ValueError("Arrival trajectories must share points and times")
    if len(times) < 2 or not np.isfinite(times).all() or not (np.diff(times) > 0).all():
        raise ValueError("Arrival times must be finite and strictly increasing")
    eligible = (mask & np.isfinite(truth) & np.isfinite(predicted)).all(axis=0)
    actual = truth[:, eligible] >= 1e-7
    forecast = predicted[:, eligible] >= 1e-7
    seen, called = actual.any(axis=0), forecast.any(axis=0)
    both = seen & called
    delta = times[forecast[:, both].argmax(axis=0)] - times[actual[:, both].argmax(axis=0)]
    return {
        "threshold_kg_m3": 1e-7,
        "window_start_s": float(times[0]),
        "window_end_s": float(times[-1]),
        "max_sampling_interval_s": float(np.diff(times).max()),
        "eligible_points": int(eligible.sum()),
        "excluded_incomplete_points": int((~eligible).sum()),
        "both_arrive": int(both.sum()),
        "missed_arrivals": int((seen & ~called).sum()),
        "false_arrivals_within_window": int((~seen & called).sum()),
        "neither_arrives_within_window": int((~seen & ~called).sum()),
        "conditional_mae_s": float(np.abs(delta).mean()) if len(delta) else None,
        "conditional_bias_s": float(delta.mean()) if len(delta) else None,
        "censoring": "No crossing in the observed window is right-censored; timing errors require both arrivals",
    }


def assess(network, cases, device, *, plots=False):
    rows, detections, pictures, selection, localized_selection = [], [], [], [], []
    arrivals = []
    started = time.perf_counter()
    for case in cases:
        fields, globals_ = predict_case(network, case, device=device, batch_size=8)
        row = run_metrics(case, fields, globals_)
        compare_metrics(physical_metrics(case, fields, globals_), row)
        rows.append(row)
        detections.append({"run_id": row["run_id"], **classification(case, fields)})
        arrivals.append(
            {"run_id": row["run_id"], "layout_id": row["layout_id"], **smoke_arrival(case, fields)}
        )
        detection = detections[-1]
        support_error = 0.0
        for kind in ("hot", "smoky"):
            counts = detection[kind]
            union = counts["tp"] + counts["fp"] + counts["fn"]
            iou = counts["tp"] / union if union else 1.0
            support_error += 0.5 * (1 - iou)
        localized_selection.append(
            {"layout_id": row["layout_id"], "value": row["encoded_selection_error"] + support_error}
        )
        # Same region-balanced formula applied to delivered, decoded fields.
        # Retained for diagnostic comparison, not the localization selector.
        shape = tuple(case["shape"])
        encoded = encode_fields(fields, case["config"]["ambient_temperature_c"])
        encoded = encoded.transpose(0, 2, 1).reshape(-1, 2, *shape)
        after = case["time_s"] > 0
        value = region_balanced_loss(
            *[
                torch.as_tensor(v[after])
                for v in (encoded, case["encoded_fields"], case["observed"], case["active"])
            ]
        )
        selection.append({"layout_id": row["layout_id"], "value": float(value.mean())})
        if plots:
            pictures.append(plot_case(case, fields))
    score = float(
        np.mean(
            [
                np.mean([r["value"] for r in selection if r["layout_id"] == layout])
                for layout in sorted({r["layout_id"] for r in selection})
            ]
        )
    )
    localized_score = float(
        np.mean(
            [
                np.mean([r["value"] for r in localized_selection if r["layout_id"] == layout])
                for layout in sorted({r["layout_id"] for r in localized_selection})
            ]
        )
    )
    by_incident = {}
    for kind in INCIDENT_TYPES:
        selected_rows = [r for r in rows if r["incident_type"] == kind]
        identifiers = {r["run_id"] for r in selected_rows}
        if selected_rows:
            by_incident[kind] = {
                **summarize(selected_rows),
                "diagnostics": aggregate_detections([r for r in detections if r["run_id"] in identifiers]),
            }
    return {
        **summarize(rows),
        "per_run": rows,
        "diagnostics": aggregate_detections(detections),
        "per_case_diagnostics": detections,
        "per_case_arrival": arrivals,
        "selection_loss": score,
        "localization_selection_error": localized_score,
        "per_incident_type": by_incident,
        "evaluation_wall_seconds": time.perf_counter() - started,
    }, pictures


def initialize():
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    network = SpatialUNet().to("cuda:0")
    optimizer = torch.optim.AdamW(network.parameters(), lr=1e-3, weight_decay=1e-4)
    return network, optimizer, np.random.default_rng(SEED)


def diagnostic(home, output, seconds, epochs, objectives=("historical", "balanced")):
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    log = ProgressLog(output / "progress.jsonl")
    try:
        compute = require_cuda()
        torch.set_num_threads(4)
        log.emit("diagnostic_started", **compute)
        stores = load_sources(home, log=log)
        all_train = select_cases(stores)["train"]
        small = choose_small(all_train)
        write_json(output / "sources.json", sources())
        write_json(output / "dataset-snapshots.json", {name: s.snapshot for name, s in stores.items()})
        write_json(output / "training-survey.json", survey(all_train))
        write_json(output / "small-set.json", survey(small))
        baseline, _ = assess(None, small, "cpu")
        results = {}
        # Identical network initialization, optimizer, case/frame order and epoch
        # cap. A wall deadline may yield unequal epochs; recorded explicitly.
        for number, objective in enumerate(objectives):
            network, optimizer, rng = initialize()
            first, steps, history = True, 0, []
            deadline = min(
                started + seconds,
                time.perf_counter()
                + max(1, (seconds - (time.perf_counter() - started)) / (len(objectives) - number)),
            )
            for epoch in range(1, epochs + 1):
                loss, updates, first, stopped = fit(
                    network,
                    small,
                    optimizer,
                    rng,
                    device="cuda:0",
                    objective=objective,
                    frames_per_case=1000,
                    deadline=deadline,
                    log=log,
                    first=first,
                )
                steps += updates
                history.append({"epoch": epoch, "training_loss": loss, "steps": steps})
                if epoch % 10 == 0 or stopped:
                    log.emit("diagnostic_epoch", objective=objective, **history[-1])
                if stopped:
                    break
            metrics, plots = assess(network, small, "cuda:0", plots=True)
            results[objective] = {
                "metrics": metrics,
                "epochs": len(history),
                "steps": steps,
                "history": history,
            }
            with gzip.open(output / (objective + "-plots.json.gz"), "wt", encoding="utf-8") as stream:
                json.dump(plots, stream, allow_nan=False)
            torch.save(
                {
                    "state_dict": {k: v.detach().cpu() for k, v in network.state_dict().items()},
                    "architecture": architecture(),
                    "scope": "small training-set overfit diagnostic",
                },
                output / (objective + "-diagnostic.pt"),
            )
            log.emit(
                "diagnostic_objective_complete",
                objective=objective,
                diagnostics=metrics["diagnostics"],
                selection_loss=metrics["selection_loss"],
            )
            del network, optimizer
            torch.cuda.empty_cache()
        report = {
            "scope": "Overfit on TRAINING cases, not generalisation or a deployable model",
            "compute": compute,
            "elapsed_seconds": time.perf_counter() - started,
            "budget_seconds": seconds,
            "cases": len(small),
            "baseline": baseline,
            "results": results,
            "recipe": {
                "seed": SEED,
                "lr": 0.001,
                "loss": LOSS_VERSION,
                "localization_version": LOCALIZATION_VERSION,
                "objectives": list(objectives),
                "batch_size": 8,
                "epochs_requested": epochs,
            },
            "source_sha256": sources(),
        }
        write_json(output / "report.json", report)
        log.emit("diagnostic_completed", elapsed_seconds=report["elapsed_seconds"])
        return report
    finally:
        log.close()


def train(home, output, seconds, epochs, objective="historical", compact_path=None):
    """Fit fresh weights; select on compact validation only, test once at end."""
    if (home / "runtime/models" / MODEL_ID).exists():
        raise FileExistsError("Existing recovery model is preserved; no compute started")
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    log = ProgressLog(output / "progress.jsonl")
    try:
        compute = require_cuda()
        torch.set_num_threads(4)
        stores = load_sources(home, compact=True, compact_path=compact_path, log=log)
        parts = select_cases(stores, compact=True)
        snapshots = {name: s.snapshot for name, s in stores.items()}
        write_json(output / "dataset-snapshots.json", snapshots)
        write_json(output / "sources.json", sources())
        write_json(output / "training-survey.json", survey(parts["train"]))
        log.emit(
            "recovery_dataset_verified",
            counts={k: len(v) for k, v in parts.items()},
            layouts={k: len({c["record"]["layout_id"] for c in v}) for k, v in parts.items()},
        )
        network, optimizer, rng = initialize()
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=4, min_lr=5e-5
        )
        first, steps, history, best = True, 0, [], None
        # Leave time for verification, the one final test, serialization and reload.
        deadline = started + max(1, seconds - 120)
        for epoch in range(1, epochs + 1):
            learning_rate = optimizer.param_groups[0]["lr"]
            loss, updates, first, stopped = fit(
                network,
                parts["train"],
                optimizer,
                rng,
                device="cuda:0",
                objective=objective,
                frames_per_case=16,
                deadline=deadline,
                log=log,
                first=first,
            )
            steps += updates
            validation, _ = assess(network, parts["validation"], "cuda:0")
            value = validation["localization_selection_error"]
            improved = best is None or value < best[0]
            if improved:
                best = (
                    value,
                    {k: v.detach().cpu().clone() for k, v in network.state_dict().items()},
                    validation,
                    epoch,
                )
            scheduler.step(value)
            history.append(
                {
                    "epoch": epoch,
                    "training_loss": loss,
                    "learning_rate": learning_rate,
                    "steps": steps,
                    "validation_loss": value,
                    "diagnostics": validation["diagnostics"],
                }
            )
            log.emit("recovery_epoch", **history[-1], best_epoch=best[3])
            if stopped or epoch - best[3] >= 20 or time.perf_counter() >= deadline:
                break
        if not steps:
            raise RuntimeError("Compute deadline left no training steps; no model published")
        network.load_state_dict(best[1], strict=True)
        log.emit("selected_weights", epoch=best[3], test_evaluations_so_far=0)
        before = state_sha(network)
        test, pictures = assess(network, parts["test"], "cuda:0", plots=True)
        baseline, _ = assess(None, parts["test"], "cpu")
        if state_sha(network) != before:
            raise ValueError("Test evaluation changed model weights")
        compute.update(
            peak_allocated_bytes=torch.cuda.max_memory_allocated(),
            peak_reserved_bytes=torch.cuda.max_memory_reserved(),
        )
        # Separate functional reload check against the exact saved checkpoint.
        payload = {
            "model_id": MODEL_ID,
            "feature_version": FEATURE_VERSION,
            "architecture": architecture(),
            "state_dict": best[1],
        }
        snapshot = {
            "sources": snapshots,
            "source_directories": {name: str(store.directory) for name, store in stores.items()},
            "effective_partitions": {
                k: [
                    {
                        "dataset": c["source_dataset"],
                        "id": c["record"]["id"],
                        "geometry_signature": c["record"]["geometry_signature"],
                        "deck_sha256": c["manifest"]["deck_sha256"],
                    }
                    for c in v
                ]
                for k, v in parts.items()
            },
        }
        shapes = sorted({tuple(c["shape"].tolist()) for c in parts["train"]})
        metadata = {
            "id": MODEL_ID,
            "kind": "incident_3d_unet",
            "feature_version": FEATURE_VERSION,
            "compiler_version": COMPILER_VERSION,
            "material_model_version": MODEL_VERSION,
            "architecture": architecture(),
            "sample_shape": [12, 16, 8],
            "supported_sample_shapes": [list(s) for s in shapes],
            "dataset_id": "spatial-compact-v1+verified-original-training",
            "dataset_snapshot_sha256": canonical_sha(snapshot),
            "source_sha256": sources(),
            "training_compute": compute,
            "training_seconds": time.perf_counter() - started,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "parameter_count": sum(p.numel() for p in network.parameters()),
            "provisional": True,
            "automatic_ui_activation": False,
            "training": {
                "loss": {
                    "localized": LOCALIZATION_VERSION,
                    "balanced": LOSS_VERSION,
                    "historical": "historical-observed-smoothl1-active5",
                }[objective],
                "objective": objective,
                "lr": 0.001,
                "scheduler": {
                    "kind": "ReduceLROnPlateau",
                    "factor": 0.5,
                    "patience": 4,
                    "min_lr": 5e-5,
                    "early_stop_patience": 20,
                },
                "seed": SEED,
                "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
                "cudnn_deterministic": torch.backends.cudnn.deterministic,
                "cudnn_benchmark": torch.backends.cudnn.benchmark,
                "best_epoch": best[3],
                "epochs": len(history),
                "history": history,
                "budget_seconds": seconds,
                "frames_per_case_per_epoch": 16,
                "batch_size": 8,
                "selection": "layout/run macro encoded composite + .5*(1-hot IoU) + .5*(1-smoke IoU); empty union IoU=1",
                "test_selection": "never; evaluated once after selection",
            },
            "metrics": {"validation": best[2], "test": test},
            "ambient_baseline": baseline,
            "limitations": [
                "Synthetic FDS targets, no experimental NASA validation",
                "Exploratory conditional consequences of a prescribed incident, not failure probability",
                "No claim of arbitrary-geometry generalisation or resolved velocity fields",
            ],
        }
        destination = home / "runtime/models" / MODEL_ID
        publish(
            destination,
            metadata,
            payload,
            {"model": metadata["metrics"], "ambient_baseline": baseline},
            snapshot,
        )
        from ignis.ml.spatial_network import SpatialSurrogate

        restored = SpatialSurrogate(destination, device="cuda:0")
        if state_sha(restored.network) != before:
            raise ValueError("Reloaded model differs from tested weights")
        sample = parts["validation"][0]
        expected = predict_case(network, sample, device="cuda:0", batch_size=8)[0]
        actual = restored.predict_arrays(
            sample["config"], sample["manifest"], sample["time_s"], batch_size=8
        )[0]
        observed = sample["field_mask"]
        if not np.allclose(actual[observed], expected[observed], rtol=1e-5, atol=1e-10):
            raise ValueError("Reloaded public inference does not reproduce evaluated predictions")
        with gzip.open(output / "test-plots.json.gz", "wt", encoding="utf-8") as stream:
            json.dump(pictures, stream, allow_nan=False)
        write_json(
            output / "report.json",
            {
                "model_directory": str(destination),
                "metadata": metadata,
                "reload_verified": True,
                "weights_state_sha256": before,
                "elapsed_seconds": time.perf_counter() - started,
            },
        )
        log.emit(
            "recovery_completed",
            model_directory=str(destination),
            test=test["diagnostics"],
            elapsed_seconds=time.perf_counter() - started,
        )
    finally:
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("diagnostic", "train"))
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--dataset", type=Path, help="Completed compact dataset directory")
    parser.add_argument(
        "--objectives",
        nargs="+",
        choices=("historical", "balanced", "localized"),
        default=["historical", "balanced"],
    )
    parser.add_argument("--objective", choices=("historical", "balanced", "localized"), default="historical")
    args = parser.parse_args()
    if os.name != "nt" or not 60 <= args.seconds <= 1800 or not 1 <= args.epochs <= 200:
        raise ValueError("Recovery requires Windows and bounded seconds/epochs")
    if not (args.home / "datasets/spatial-corpus-v1/PAUSE").exists():
        raise RuntimeError("The original corpus must remain paused")
    with ProcessLock(args.home / "runtime/compute.lock"):
        if args.mode == "diagnostic":
            diagnostic(args.home, args.output, args.seconds, args.epochs, tuple(args.objectives))
        else:
            train(args.home, args.output, args.seconds, args.epochs, args.objective, args.dataset)


if __name__ == "__main__":
    main()
