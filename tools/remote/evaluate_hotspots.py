"""Read-only CUDA comparison on 100 explicitly frozen prospective FDS cases.

Native train/validation/test labels describe structural families only: every
selected case is held out from fitting and selection in this comparison.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

import torch
from hotspot_spatial import aligned_assessment
from ignis.locking import ProcessLock
from ignis.ml.spatial_dataset import file_sha
from ignis.ml.spatial_network import FEATURE_VERSION, SpatialUNet, architecture
from ignis.provenance import canonical_sha
from recover_spatial import aggregate_detections, prepared, sources
from train_spatial import CaseStore, ProgressLog, require_cuda, summarize, write_json
from verify_spatial import state_sha

IDENTITY_KEYS = ("id", "layout_id", "fingerprint", "split")
NATIVE_COUNTS = {"train": 60, "validation": 20, "test": 20}


def layout_index(value):
    match = re.fullmatch(r"procedural-(\d{4})", str(value))
    if match is None:
        raise ValueError("Expected a procedural layout identity")
    return int(match[1])


def validate_membership(membership):
    if not isinstance(membership, dict):
        raise ValueError("Prospective membership must be a JSON object")
    if (
        membership.get("schema_version") != 1
        or membership.get("dataset_id") != "spatial-compact-v1"
        or membership.get("purpose") != "prospective-test-only"
        or not re.fullmatch(r"[0-9a-f]{64}", str(membership.get("plan_design_sha256", "")))
    ):
        raise ValueError("Incompatible prospective membership schema or design hash")
    rows = membership.get("runs", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Prospective membership must contain case records")
    if len(rows) != 100 or len({r.get("id") for r in rows}) != 100:
        raise ValueError("Prospective membership requires exactly 100 distinct cases")
    for row in rows:
        if (
            any(key not in row for key in IDENTITY_KEYS)
            or not 100 <= layout_index(row["layout_id"]) < 150
            or not isinstance(row["id"], str)
            or not row["id"].startswith(row["layout_id"] + "-")
            or not re.fullmatch(r"[0-9a-f]{64}", str(row["fingerprint"]))
            or row["split"] not in NATIVE_COUNTS
        ):
            raise ValueError("Prospective cases must belong to layouts 0100..0149 with exact fingerprints")
    if Counter(r["layout_id"] for r in rows) != {f"procedural-{i:04d}": 2 for i in range(100, 150)}:
        raise ValueError("Prospective membership requires two cases on each of 50 new layouts")
    if Counter(r["split"] for r in rows) != NATIVE_COUNTS:
        raise ValueError("Native family counts must remain 60/20/20; all are prospective test cases")
    return sorted(rows, key=lambda row: row["id"])


def freeze_membership(plan):
    """Pure plan projection; no target data, clock, compiler or solver is read."""
    design = {key: value for key, value in plan.items() if key not in {"design_sha256", "preflight"}}
    if design.get("dataset_id") != "spatial-compact-v1" or design.get("expected_runs") != 300:
        raise ValueError("Prospective evaluation requires the planned 300-case compact dataset")
    membership = {
        "schema_version": 1,
        "dataset_id": "spatial-compact-v1",
        "purpose": "prospective-test-only",
        "plan_design_sha256": canonical_sha(design),
        "runs": [
            {key: record[key] for key in IDENTITY_KEYS}
            for record in design["runs"]
            if layout_index(record["layout_id"]) >= 100
        ],
    }
    membership["runs"] = validate_membership(membership)
    return membership


def match_records(records, membership):
    """Match the completed index to the frozen identities, never to target values."""
    frozen = validate_membership(membership)
    if len(records) != 300 or len({r["id"] for r in records}) != 300:
        raise ValueError("Expected the complete 300-case dataset")
    if Counter(r["layout_id"] for r in records) != {f"procedural-{i:04d}": 2 for i in range(150)}:
        raise ValueError("Dataset layouts differ from the planned 0000..0149 range")
    available = {r["id"]: (i, r) for i, r in enumerate(records) if layout_index(r["layout_id"]) >= 100}
    if set(available) != {r["id"] for r in frozen}:
        raise ValueError("Prospective membership differs from completed case identities")
    for row in frozen:
        actual = available[row["id"]][1]
        if actual.get("status", "completed") != "completed" or any(
            actual.get(key) != row[key] for key in IDENTITY_KEYS
        ):
            raise ValueError("Prospective fingerprint, native split or completion changed: " + row["id"])
    return [available[row["id"]][0] for row in frozen]


def load_prospective_cases(store, membership):
    if store.snapshot["dataset_id"] != "spatial-compact-v1" or tuple(store.shape) != (12, 16, 8):
        raise ValueError("Expected the verified compact 12x16x8 dataset")
    indices = match_records(store.records, membership)
    old_geometry = {r["geometry_signature"] for r in store.records if layout_index(r["layout_id"]) < 100}
    new_geometry = {store.records[i]["geometry_signature"] for i in indices}
    if old_geometry & new_geometry or len(new_geometry) != 50:
        raise ValueError(
            "Prospective layouts must be 50 distinct physical geometries absent from development"
        )
    cases = []
    for index in indices:
        case = prepared(store.get(index))
        case["source_dataset"] = store.snapshot["dataset_id"]
        cases.append(case)
    store.cache.clear()
    for layout in {case["record"]["layout_id"] for case in cases}:
        pair = [case for case in cases if case["record"]["layout_id"] == layout]
        if {case["config"]["gravity_g"] for case in pair} != {0.0001, 1.0}:
            raise ValueError("Every new layout must retain its two planned gravities")
    if Counter(case["config"]["incident_type"] for case in cases) != {
        kind: 20 for kind in ("overheating", "arc", "flaming", "smoldering", "battery")
    }:
        raise ValueError("Prospective set must retain 20 cases for each incident type")
    return cases


def parse_checkpoints(entries):
    result = {}
    for entry in entries:
        name, separator, filename = entry.partition("=")
        if (
            not separator
            or not filename
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name)
            or name == "ambient"
            or name in result
        ):
            raise ValueError("Use distinct --checkpoint NAME=PATH entries; ambient is reserved")
        result[name] = Path(filename)
    if not 1 <= len(result) <= 3 or len({p.resolve() for p in result.values()}) != len(result):
        raise ValueError("Compare one to three distinct checkpoint files")
    return result


def load_checkpoint(path, *, device="cuda:0"):
    before = file_sha(path)
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(payload, dict) or payload.get("feature_version") != FEATURE_VERSION:
        raise ValueError("Checkpoint feature schema is incompatible")
    declared = payload.get("architecture", {})
    widths = declared.get("widths", [])
    if not widths or widths[0] not in (16, 24, 32) or declared != architecture(widths[0]):
        raise ValueError("Checkpoint architecture does not match the implemented spatial model")
    network = SpatialUNet(base_channels=widths[0])
    network.load_state_dict(payload["state_dict"], strict=True)
    if any(not torch.isfinite(value).all().item() for value in network.state_dict().values()):
        raise ValueError("Checkpoint contains nonfinite weights")
    network.requires_grad_(False).eval().to(device)
    if file_sha(path) != before:
        raise ValueError("Checkpoint changed while being loaded")
    metadata = {key: value for key, value in payload.items() if key != "state_dict"}
    json.dumps(metadata, allow_nan=False)  # Persist the exact non-tensor checkpoint metadata.
    return network, {
        "path": str(path.resolve()),
        "file_sha256": before,
        "state_sha256": state_sha(network),
        "checkpoint_metadata": metadata,
    }


def verify_checkpoint_history(checkpoint, prospective_geometry):
    """Check every recorded historical partition/source, before any inference."""
    path = checkpoint.with_name("dataset-snapshot.json")
    before = file_sha(path)  # An absent sidecar is an error, never an unchecked pass.
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict):
        raise ValueError("Incompatible checkpoint dataset snapshot")
    groups = []
    if "effective_partitions" in snapshot and "runs" not in snapshot:
        parts = snapshot["effective_partitions"]
        if not isinstance(parts, dict) or set(parts) != {"train", "validation", "test"}:
            raise ValueError("Incompatible historical effective partitions")
        groups.extend(parts.values())
        historical_sources = snapshot.get("sources", {})
        if not isinstance(historical_sources, dict) or any(
            not isinstance(s, dict) for s in historical_sources.values()
        ):
            raise ValueError("Incompatible historical source snapshots")
        groups.extend(source.get("runs") for source in historical_sources.values())
    elif "runs" in snapshot and "effective_partitions" not in snapshot:
        groups.append(snapshot["runs"])
    else:
        raise ValueError("Incompatible checkpoint dataset snapshot")
    if any(not isinstance(rows, list) for rows in groups):
        raise ValueError("Historical snapshot must contain case lists")
    rows = [row for group in groups for row in group]
    if not rows or any(
        not isinstance(row, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("geometry_signature", "")))
        for row in rows
    ):
        raise ValueError("Historical snapshot lacks verified geometry signatures")
    historical = {row["geometry_signature"] for row in rows}
    if not prospective_geometry or historical & prospective_geometry:
        raise ValueError("Prospective geometry overlaps checkpoint historical datasets")
    if file_sha(path) != before:
        raise ValueError("Checkpoint dataset snapshot changed during verification")
    return {
        "path": str(path.resolve()),
        "file_sha256": before,
        "historical_records_checked": len(rows),
        "historical_geometry_count": len(historical),
        "prospective_geometry_count": len(prospective_geometry),
        "no_geometry_overlap": True,
        "scope": "All recorded effective partitions and source snapshots; records may repeat across sources",
    }


def grouped_metrics(metrics, cases):
    """Aggregate actual case identities; native family labels never select weights."""
    info = {case["record"]["id"]: case for case in cases}
    if len(info) != len(cases):
        raise ValueError("Duplicate evaluation cases")
    indexed = {}
    keys = ["per_run", "per_case_diagnostics", "peak_alignment"]
    if "per_case_arrival" in metrics:
        keys.append("per_case_arrival")
    for key in keys:
        rows = metrics[key]
        values = {row["run_id"]: row for row in rows}
        if len(values) != len(rows) or set(values) != set(info):
            raise ValueError("Evaluation rows do not match the exact prospective membership")
        if any(
            row.get("layout_id", info[name]["record"]["layout_id"]) != info[name]["record"]["layout_id"]
            for name, row in values.items()
        ):
            raise ValueError("Evaluation row changed its physical layout identity")
        indexed[key] = values

    def group(ids):
        summary = summarize([indexed["per_run"][name] for name in ids])
        summary["diagnostics"] = aggregate_detections([indexed["per_case_diagnostics"][name] for name in ids])
        summary["case_ids"] = ids
        peaks = [
            indexed["peak_alignment"][name] for name in ids if indexed["peak_alignment"][name]["peak_is_hot"]
        ]
        fields = ("peak_location_amplitude_error_c", "peak_displacement_at_true_time_m", "peak_time_error_s")
        layouts = sorted({row["layout_id"] for row in peaks})
        averages = {}
        for field in fields:
            per_layout = [
                sum(row[field] for row in peaks if row["layout_id"] == layout)
                / sum(row["layout_id"] == layout for row in peaks)
                for layout in layouts
            ]
            averages[field] = sum(per_layout) / len(per_layout) if per_layout else None
        summary["hot_peak_alignment"] = {
            "cases": len(peaks),
            "layouts": len(layouts),
            "layout_balanced": averages,
        }
        return summary

    return {
        "interpretation": "All cases are prospective test; native split labels describe structural families only",
        "native_split": {
            split: group(sorted(name for name, case in info.items() if case["record"]["split"] == split))
            for split in NATIVE_COUNTS
        },
        "gravity_g": {
            str(gravity): group(
                sorted(name for name, case in info.items() if case["config"]["gravity_g"] == gravity)
            )
            for gravity in sorted({case["config"]["gravity_g"] for case in cases})
        },
        "native_split_by_gravity_g": {
            split: {
                str(gravity): group(
                    sorted(
                        name
                        for name, case in info.items()
                        if case["record"]["split"] == split and case["config"]["gravity_g"] == gravity
                    )
                )
                for gravity in sorted({case["config"]["gravity_g"] for case in cases})
            }
            for split in NATIVE_COUNTS
        },
    }


def write_plots(path, plots):
    with path.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as stream:
            stream.write(json.dumps(plots, allow_nan=False).encode("utf-8"))


def run_evaluation(args):
    if not 1 <= args.seconds <= 180:
        raise ValueError("Evaluation budget must be 1..180 seconds")
    checkpoints = parse_checkpoints(args.checkpoint)
    membership_sha = file_sha(args.membership)
    membership = json.loads(args.membership.read_text(encoding="utf-8"))
    validate_membership(membership)
    pause = args.home / "datasets/spatial-corpus-v1/PAUSE"
    if not pause.is_file():
        raise RuntimeError("Original corpus must remain paused")
    if args.output.exists():
        raise FileExistsError("Existing evaluation evidence is preserved")
    if args.output.resolve().is_relative_to(args.dataset.resolve()):
        raise ValueError("Evaluation output must be outside the immutable dataset")
    files_before = {name: file_sha(path) for name, path in checkpoints.items()}
    with ProcessLock(args.home / "runtime/compute.lock"):
        started = time.perf_counter()
        deadline = started + args.seconds

        def guard():
            if time.perf_counter() >= deadline:
                raise TimeoutError("Evaluation exceeded its deadline; no complete comparison is published")
            if not pause.is_file():
                raise RuntimeError("Original corpus is no longer paused")

        args.output.mkdir(parents=True, exist_ok=False)
        log = ProgressLog(args.output / "progress.jsonl")
        try:
            compute = require_cuda()
            torch.set_num_threads(4)
            source_hashes = {
                **sources(),
                "tools/remote/hotspot_spatial.py": file_sha(Path(__file__).with_name("hotspot_spatial.py")),
                "tools/remote/evaluate_hotspots.py": file_sha(Path(__file__)),
            }
            store = CaseStore(args.dataset)
            match_records(store.records, membership)
            index = json.loads((args.dataset / "manifest.json").read_text(encoding="utf-8"))
            if index.get("design_sha256") != membership["plan_design_sha256"] or not index.get(
                "frozen_index_sha256"
            ):
                raise ValueError("Completed dataset does not match the frozen prospective design")

            class VerificationLog:
                def emit(self, stage, **values):
                    guard()
                    log.emit(stage, **values)

            store.verify(VerificationLog())
            guard()
            cases = load_prospective_cases(store, membership)
            prospective_geometry = {case["record"]["geometry_signature"] for case in cases}
            histories = {
                name: verify_checkpoint_history(path, prospective_geometry)
                for name, path in checkpoints.items()
            }
            write_json(args.output / "membership.json", membership)
            write_json(args.output / "sources.json", source_hashes)
            log.emit("prospective_evaluation_started", cases=len(cases), **compute)
            results = {}
            for name, path in [("ambient", None), *checkpoints.items()]:
                guard()
                network, model = (
                    (None, {"kind": "analytical ambient baseline"}) if path is None else load_checkpoint(path)
                )
                if path is not None and model["file_sha256"] != files_before[name]:
                    raise ValueError("Checkpoint changed since comparison began")
                if path is not None:
                    model["dataset_snapshot"] = histories[name]
                batches = 0

                def check_forward(module, values):
                    nonlocal batches
                    guard()
                    if values[0].device.type != "cuda" or next(module.parameters()).device.type != "cuda":
                        raise RuntimeError("Model inference must execute on CUDA")
                    batches += 1

                hook = network.register_forward_pre_hook(check_forward) if network is not None else None
                try:
                    with torch.inference_mode():
                        metrics, plots = aligned_assessment(network, cases)
                    guard()
                    if network is not None:
                        if (
                            not batches
                            or state_sha(network) != model["state_sha256"]
                            or file_sha(path) != model["file_sha256"]
                        ):
                            raise ValueError("Assessment changed weights or failed to run on CUDA")
                        restored, reload_meta = load_checkpoint(path, device="cpu")
                        if reload_meta["state_sha256"] != model["state_sha256"]:
                            raise ValueError("Exact checkpoint reload failed")
                        del restored
                        model["exact_reload_verified"] = True
                    model["cuda_forward_batches"] = batches
                    groups = grouped_metrics(metrics, cases)
                    if len(plots) != len(cases) or {row["run_id"] for row in plots} != {
                        case["record"]["id"] for case in cases
                    }:
                        raise ValueError("Plot exports do not match the prospective membership")
                    write_json(
                        args.output / f"{name}-report.json",
                        {"model": model, "metrics": metrics, "groups": groups},
                    )
                    write_plots(args.output / f"{name}-plots.json.gz", plots)
                    results[name] = {
                        "model": model,
                        "report": f"{name}-report.json",
                        "plots": f"{name}-plots.json.gz",
                    }
                    log.emit("prospective_model_evaluated", name=name, diagnostics=metrics["diagnostics"])
                finally:
                    if hook is not None:
                        hook.remove()
                    del network
                    torch.cuda.empty_cache()
            guard()
            if (
                file_sha(args.membership) != membership_sha
                or file_sha(args.dataset / "manifest.json") != store.source_sha
            ):
                raise ValueError("Membership or source dataset changed during evaluation")
            if any(file_sha(path) != files_before[name] for name, path in checkpoints.items()):
                raise ValueError("A checkpoint file changed during comparison")
            if any(
                file_sha(Path(history["path"])) != history["file_sha256"] for history in histories.values()
            ):
                raise ValueError("A checkpoint dataset snapshot changed during comparison")
            if any(
                file_sha(Path(__file__).resolve().parents[2] / path) != digest
                for path, digest in source_hashes.items()
            ):
                raise ValueError("Evaluation source code changed during execution")
            report = {
                "scope": "100 prospective cases only; no training, model selection or UI activation",
                "completed": True,
                "cases": 100,
                "layouts": 50,
                "native_family_counts": NATIVE_COUNTS,
                "all_cases_used_only_for_evaluation": True,
                "model_selection_performed": False,
                "membership_file_sha256": membership_sha,
                "membership_canonical_sha256": canonical_sha(membership),
                "dataset_snapshot_sha256": store.snapshot_sha,
                "source_manifest_sha256": store.source_sha,
                "source_sha256": source_hashes,
                "checkpoint_histories": histories,
                "compute": compute,
                "results": results,
                "budget_seconds": args.seconds,
                "elapsed_seconds": time.perf_counter() - started,
                "budget_basis": "Checked during dataset verification and before every CUDA batch; timeout leaves partial evidence only",
            }
            guard()
            write_json(args.output / "report.json", report)
            log.emit("prospective_evaluation_completed", elapsed_seconds=report["elapsed_seconds"])
            return report
        finally:
            log.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--membership", type=Path, required=True)
    parser.add_argument("--checkpoint", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=180)
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 180:
        parser.error("Evaluation budget must be 1..180 seconds")
    parse_checkpoints(args.checkpoint)
    return args


if __name__ == "__main__":
    if os.name != "nt":
        raise RuntimeError("Real evaluation runs on the authorized Windows CUDA workstation")
    run_evaluation(parse_args())
