"""Reload a frozen spatial checkpoint on CUDA and audit its existing test split.

This is a reproducibility and inference audit, not a new independent test set.
No fitting, parameter selection or campaign mutation takes place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from ignis.ml.incidents import GLOBAL_KEYS, file_sha
from ignis.ml.spatial_network import SpatialSurrogate
from ignis.provenance import canonical_sha
from train_spatial import CaseStore, run_metrics, source_hashes, summarize


def state_sha(network):
    digest = hashlib.sha256()
    for key, value in sorted(network.state_dict().items()):
        digest.update(key.encode())
        digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def physical_metrics(case, fields, globals_, *, exclude_initial=False):
    """Compute physical errors independently of the training evaluator."""
    rows = {}
    masks = case["field_mask"].copy()
    global_mask = case["global_mask"].copy()
    if exclude_initial:
        masks[case["time_s"] == 0] = False
        global_mask[case["time_s"] == 0] = False
    for channel, name, unit, target, threshold in (
        (0, "temperature", "c", case["temperature_c"], case["config"]["ambient_temperature_c"] + 5),
        (1, "smoke", "kg_m3", case["smoke_kg_m3"], 1e-7),
    ):
        valid = masks[..., channel]
        prediction = fields[..., channel]
        error = np.abs(prediction - target)
        rows[f"{name}_mae_{unit}"] = float(np.mean(error[valid])) if valid.any() else None
        rows[f"{name}_peak_error_{unit}"] = (
            float(abs(prediction[valid].max() - target[valid].max())) if valid.any() else None
        )
        active = valid & (target >= threshold)
        prefix = "hot" if channel == 0 else "smoky"
        rows[f"{prefix}_{name}_mae_{unit}"] = float(error[active].mean()) if active.any() else None
    for channel, name in enumerate(GLOBAL_KEYS):
        mask = global_mask[:, channel]
        error = np.abs(globals_[:, channel] - case["globals"][:, channel])
        rows[f"fds_global_{name}_mae"] = float(error[mask].mean()) if mask.any() else None
    return rows


def classification(case, fields):
    """Diagnostic thresholds are fixed to training's active-region definitions."""
    result = {}
    for channel, name, target, threshold in (
        (0, "hot", case["temperature_c"], case["config"]["ambient_temperature_c"] + 5),
        (1, "smoky", case["smoke_kg_m3"], 1e-7),
    ):
        mask = case["field_mask"][..., channel] & (case["time_s"] > 0)[:, None]
        truth, predicted = target[mask] >= threshold, fields[..., channel][mask] >= threshold
        result[name] = {
            "tp": int((truth & predicted).sum()),
            "fn": int((truth & ~predicted).sum()),
            "fp": int((~truth & predicted).sum()),
            "tn": int((~truth & ~predicted).sum()),
        }
    return result


def compare_metrics(actual, expected):
    for key, value in actual.items():
        reference = expected[key]
        if value is None or reference is None:
            if value != reference:
                raise ValueError("Metric availability changed: " + key)
        elif not np.isclose(value, reference, rtol=1e-5, atol=1e-12):
            raise ValueError(f"Metric mismatch for {key}: {value} vs {reference}")


def plot_case(case, fields):
    gas = case["valid_mask"][0]
    target = np.stack([case["temperature_c"], case["smoke_kg_m3"]], axis=-1)
    observed = np.where(case["field_mask"], target, np.nan)
    frames = {}
    for channel, name in enumerate(("temperature", "smoke")):
        frame = int(np.nanargmax(np.nanmax(observed[..., channel], axis=1)))
        mask = case["field_mask"][frame, :, channel]
        frames[name] = {
            "time_s": float(case["time_s"][frame]),
            "positions_m": case["positions_m"][mask].tolist(),
            "fds": observed[frame, mask, channel].tolist(),
            "model": fields[frame, mask, channel].tolist(),
        }
    return {
        "run_id": case["record"]["id"],
        "incident_type": case["config"]["incident_type"],
        "time_s": case["time_s"].tolist(),
        "fds_max": np.nanmax(observed, axis=1).tolist(),
        "model_max": np.nanmax(fields[:, gas], axis=1).tolist(),
        "bounds_m": case["bounds_m"].tolist(),
        "objects": case["manifest"]["objects"],
        "source": case["manifest"]["incident"]["source"],
        "peak_frames": frames,
    }


def audit(home: Path, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    directory = home / "runtime/models/spatial-pilot-v1"
    artifacts = {p.name: file_sha(p) for p in directory.iterdir() if p.is_file()}
    snapshot = json.loads((directory / "dataset-snapshot.json").read_text())
    metadata = json.loads((directory / "metadata.json").read_text())
    historical = json.loads((directory / "evaluation.json").read_text())
    if canonical_sha(snapshot) != metadata["dataset_snapshot_sha256"]:
        raise ValueError("Stored dataset snapshot checksum mismatch")
    if not torch.cuda.is_available():
        raise RuntimeError("This audit requires the Windows CUDA workstation")
    torch.set_num_threads(4)
    torch.cuda.set_per_process_memory_fraction(0.25, 0)
    store = CaseStore(home / "datasets" / snapshot["dataset_id"])
    store.verify()
    if store.source_sha != snapshot["source_manifest_sha256"]:
        raise ValueError("Dataset index differs from training")
    pinned = {record["id"]: record for record in snapshot["runs"]}
    if set(pinned) != {record["id"] for record in store.records}:
        raise ValueError("Dataset case membership changed since training")
    for record in store.records:
        if any(record.get(key) != value for key, value in pinned[record["id"]].items()):
            raise ValueError("Dataset case changed since training: " + record["id"])
    print(json.dumps({"stage": "verified_frozen_dataset", "cases": len(store.records)}), flush=True)
    model = SpatialSurrogate(directory, device="cuda:0")
    before_state = state_sha(model.network)
    cuda_batches = []

    def check_device(module, args):
        if args[0].device.type != "cuda" or next(module.parameters()).device.type != "cuda":
            raise RuntimeError("Inference did not execute on CUDA")
        cuda_batches.append(len(args[0]))

    hook = model.network.register_forward_pre_hook(check_device)
    first = store.get(store.by_split["test"][0])
    model.predict_arrays(first["config"], first["manifest"], first["time_s"][:4])
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    rows, baselines, without_initial, plots, timings, detections = [], [], [], [], [], []
    for index in store.by_split["test"]:
        case = store.get(index)
        torch.cuda.synchronize()
        start = time.perf_counter()
        fields, globals_ = model.predict_arrays(case["config"], case["manifest"], case["time_s"])
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - start
        timings.append({"run_id": case["record"]["id"], "frames": len(fields), "seconds": elapsed})
        gas = case["valid_mask"]
        if not np.isfinite(fields[gas]).all() or not np.isnan(fields[~gas]).all():
            raise ValueError("Invalid gas predictions or solid masks")
        row = run_metrics(case, fields, globals_)
        independent = physical_metrics(case, fields, globals_)
        compare_metrics(independent, row)
        rows.append(row)
        without_initial.append({**row, **physical_metrics(case, fields, globals_, exclude_initial=True)})
        ambient = case["config"]["ambient_temperature_c"]
        base_fields = np.broadcast_to([ambient, 0.0], fields.shape)
        base_globals = np.tile([ambient, ambient, 0.0, 0.0], (len(fields), 1))
        baseline = run_metrics(case, base_fields, base_globals)
        compare_metrics(physical_metrics(case, base_fields, base_globals), baseline)
        baselines.append(baseline)
        detections.append({"run_id": row["run_id"], **classification(case, fields)})
        plots.append(plot_case(case, fields))
        print(json.dumps({"stage": "test_case", **timings[-1]}), flush=True)
    hook.remove()
    model_summary, baseline_summary = summarize(rows), summarize(baselines)
    compare_metrics(model_summary["layout_balanced"], historical["model"]["test"]["layout_balanced"])
    compare_metrics(
        baseline_summary["layout_balanced"], historical["ambient_baseline"]["test"]["layout_balanced"]
    )
    for fresh, previous in (
        (rows, historical["model"]["test"]["per_run"]),
        (baselines, historical["ambient_baseline"]["test"]["per_run"]),
    ):
        old = {row["run_id"]: row for row in previous}
        for row in fresh:
            compare_metrics({key: row[key] for key in model_summary["layout_balanced"]}, old[row["run_id"]])
    if state_sha(model.network) != before_state:
        raise ValueError("Inference changed the loaded parameters")
    if artifacts != {p.name: file_sha(p) for p in directory.iterdir() if p.is_file()}:
        raise ValueError("Model artifacts changed during verification")
    detection_summary = {}
    for kind in ("hot", "smoky"):
        counts = {key: sum(row[kind][key] for row in detections) for key in ("tp", "fn", "fp", "tn")}
        detection_summary[kind] = {
            **counts,
            "recall": counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else None,
            "precision": counts["tp"] / (counts["tp"] + counts["fp"])
            if counts["tp"] + counts["fp"]
            else None,
        }
    # The composite here is only reproduced for t=0-inclusive historical scores.
    without_initial_summary = summarize(without_initial)
    for values in [without_initial_summary["layout_balanced"], *without_initial_summary["per_layout"]]:
        values.pop("encoded_selection_error")
    report = {
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Repeated inference on the existing held-out test set; no new independent validation",
        "initial_condition": "t=0 forced ambient / zero soot; historical metrics include it; diagnostics exclude it",
        "thresholds": {"hot_temperature_above_ambient_c": 5, "smoke_kg_m3": 1e-7},
        "reference": "FDS simulations, not real experiments; smoke target is soot mass concentration",
        "aggregation": "Mean within each run, then equal-weight runs within layouts, then equal-weight layouts",
        "diagnostic_aggregation": "Micro counts over observed point/time pairs for t>0; correlated, not independent samples",
        "passed_integrity_checks": [
            "dataset hashes",
            "physical-layout separation",
            "compiler reconstruction",
            "CUDA forward hooks",
            "finite gas outputs",
            "solid masks",
            "independent physical metrics",
            "historical metrics reproduced",
            "unchanged parameters",
            "unchanged saved artifacts",
        ],
        "model_artifact_hashes": artifacts,
        "source_sha256": {**source_hashes(), "tools/remote/verify_spatial.py": file_sha(Path(__file__))},
        "device": str(model.device),
        "device_name": torch.cuda.get_device_name(),
        "torch_version": str(torch.__version__),
        "cuda_version": torch.version.cuda,
        "cuda_forward_batches_including_warmup": len(cuda_batches),
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "latency_basis": "Synchronized warm inference including geometry encoding and GPU/CPU transfers; excludes disk reads",
        "total_inference_seconds": sum(row["seconds"] for row in timings),
        "timings": timings,
        "model": {**model_summary, "per_run": rows},
        "ambient_baseline": {**baseline_summary, "per_run": baselines},
        "model_excluding_initial": without_initial_summary,
        "diagnostics": detection_summary,
        "per_case_diagnostics": detections,
    }
    for name, value in (("audit.json", report), ("plot-data.json", plots)):
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
    print(
        json.dumps(
            {
                "stage": "audit_complete",
                "output": str(output),
                "diagnostics": detection_summary,
                "total_inference_seconds": report["total_inference_seconds"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.home, args.output)
