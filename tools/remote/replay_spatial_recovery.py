"""Compare a frozen recovery model on the 60 previous diagnostic FDS cases.

No simulation or fitting. These already examined cases are a development
diagnostic, distinct from the new compact test reserved by recover_spatial.
"""

from __future__ import annotations

import argparse
import gzip
import json
import time
from pathlib import Path

import torch
from ignis.locking import ProcessLock
from ignis.ml.incidents import file_sha
from ignis.ml.spatial_dataset import load_spatial_case
from ignis.ml.spatial_network import SpatialSurrogate, geometry_channels
from recover_spatial import aggregate_detections, smoke_arrival
from train_spatial import run_metrics, summarize, write_json
from verify_spatial import classification, compare_metrics, physical_metrics, plot_case, state_sha


def replay(home, source, output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    original_report = json.loads((source / "report.json").read_text())
    if original_report["completed_runs"] != 60 or original_report["failures"]:
        raise ValueError("The source diagnostic is not complete")
    if file_sha(source / "plan.json") != original_report["plan_sha256"]:
        raise ValueError("Source diagnostic plan checksum mismatch")
    plan = json.loads((source / "plan.json").read_text())["runs"]
    directory = home / "runtime/models/spatial-recovery-v1"
    artifacts = {p.name: file_sha(p) for p in directory.iterdir() if p.is_file()}
    model = SpatialSurrogate(directory, device="cuda:0")
    torch.set_num_threads(4)
    before = state_sha(model.network)
    snapshot = json.loads((directory / "dataset-snapshot.json").read_text())
    trained_decks = {r["deck_sha256"] for r in snapshot["effective_partitions"]["train"]}
    rows, detections, plots, arrivals = [], [], [], []
    for item in plan:
        folder = source / "runs" / item["id"]
        audit = json.loads((folder / "audit.json").read_text())
        record = audit["record"]
        if record["id"] != item["id"] or record["fingerprint"] != item["fingerprint"]:
            raise ValueError("Source audit record differs from diagnostic plan")
        case = load_spatial_case(folder, record)
        if case["manifest"]["deck_sha256"] in trained_decks:
            raise ValueError("Diagnostic scenario was included in training")
        case["config"] = case["manifest"]["config"]
        case["static"] = geometry_channels(case["manifest"])
        fields, globals_ = model.predict_arrays(
            case["config"], case["manifest"], case["time_s"], batch_size=8
        )
        row = run_metrics(case, fields, globals_)
        compare_metrics(physical_metrics(case, fields, globals_), row)
        rows.append({**row, "group": item["group"]})
        detections.append({"run_id": item["id"], "group": item["group"], **classification(case, fields)})
        arrivals.append({"run_id": item["id"], "layout_id": row["layout_id"], **smoke_arrival(case, fields)})
        plots.append({**plot_case(case, fields), "group": item["group"]})
    if state_sha(model.network) != before or artifacts != {
        p.name: file_sha(p) for p in directory.iterdir() if p.is_file()
    }:
        raise ValueError("Replay modified the frozen model")
    groups = {}
    for group in ("similar", "novel_geometry"):
        selected = [{k: v for k, v in row.items() if k != "group"} for row in rows if row["group"] == group]
        groups[group] = {
            "model": summarize(selected),
            "diagnostics": aggregate_detections([r for r in detections if r["group"] == group]),
        }
    report = {
        "scope": "Replay of 60 already examined development diagnostics, NOT a new independent test",
        "completed_runs": len(rows),
        "groups": groups,
        "per_run": rows,
        "per_run_diagnostics": detections,
        "per_case_arrival": arrivals,
        "previous_results": original_report["groups"],
        "model_artifacts": artifacts,
        "source_plan_sha256": original_report["plan_sha256"],
        "script_sha256": file_sha(Path(__file__)),
        "device_name": torch.cuda.get_device_name(),
        "elapsed_seconds": time.perf_counter() - started,
        "unchanged_model": True,
        "diagnostic_cases_absent_from_training": True,
    }
    write_json(output / "report.json", report)
    with gzip.open(output / "plot-data.json.gz", "wt", encoding="utf-8") as stream:
        json.dump(plots, stream, allow_nan=False)
    print(json.dumps({"completed_runs": len(rows), "groups": groups, "elapsed_s": report["elapsed_seconds"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with ProcessLock(args.home / "runtime/compute.lock"):
        replay(args.home, args.source, args.output)


if __name__ == "__main__":
    main()
