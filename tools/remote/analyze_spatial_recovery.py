"""Summarize completed recovery reports locally, without fitting or inference.

python tools/remote/analyze_spatial_recovery.py --directory evidence/incidents/spatial-recovery

Reads training-report.json (or report.json), replay-report.json and
test-plots.json.gz. Prints JSON; --output writes a new file exclusively.
Arrival summaries are preserved only when supplied by the trajectory evaluator:
peak-frame exports cannot reconstruct per-point arrivals or censoring.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean


def indexed(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Expected a nonempty list of case records")
    result = {}
    for row in rows:
        identifier = row.get("run_id")
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise ValueError("Missing or duplicate run_id")
        result[identifier] = row
    return result


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite numeric observation")
    return value


def mean_present(values):
    available = [finite(value) for value in values if value is not None]
    return fmean(available) if available else None


def equal_numbers(actual, expected, label):
    if actual.keys() != expected.keys():
        raise ValueError("Metric membership changed: " + label)
    for key, value in actual.items():
        reference = expected[key]
        if value is None or reference is None:
            if value is not reference:
                raise ValueError("Metric availability changed: " + label + ":" + key)
        elif not math.isclose(finite(value), finite(reference), rel_tol=1e-9, abs_tol=1e-15):
            raise ValueError("Metric mismatch: " + label + ":" + key)


def layout_macro(rows, keys):
    layouts = sorted({row["layout_id"] for row in rows})
    if not layouts or any(not isinstance(layout, str) or not layout for layout in layouts):
        raise ValueError("Missing physical layout identifiers")
    per_layout = [
        {key: mean_present([row[key] for row in rows if row["layout_id"] == layout]) for key in keys}
        for layout in layouts
    ]
    return {key: mean_present([row[key] for row in per_layout]) for key in keys}


def rates(counts, *, empty_iou=None):
    tp, fp, fn = (counts[key] for key in ("tp", "fp", "fn"))
    return {
        "recall": tp / (tp + fn) if tp + fn else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "iou": tp / (tp + fp + fn) if tp + fp + fn else empty_iou,
    }


def summarize(rows, detections, keys):
    measured = indexed(rows)
    if measured.keys() - detections.keys():
        raise ValueError("Missing per-case diagnostic counts")
    micro, macro = {}, {}
    for kind in ("hot", "smoky"):
        totals = dict.fromkeys(("tp", "fp", "fn", "tn"), 0)
        per_case = []
        for identifier, row in measured.items():
            counts = detections[identifier][kind]
            for key in totals:
                if type(counts[key]) is not int or counts[key] < 0:
                    raise ValueError("Invalid classification count")
                totals[key] += counts[key]
            per_case.append({"layout_id": row["layout_id"], **rates(counts, empty_iou=1.0)})
        micro[kind] = {**totals, **rates(totals)}
        macro[kind] = layout_macro(per_case, ("recall", "precision", "iou"))
    return {
        "runs": len(rows),
        "layouts": len({row["layout_id"] for row in rows}),
        "layout_balanced": layout_macro(rows, keys),
        "diagnostics": micro,
        "diagnostics_layout_macro": macro,
    }


def gravity(identifier):
    labels = [name for name in ("microg", "earth") if name in identifier.split("-")]
    if len(labels) > 1:
        raise ValueError("Ambiguous gravity identifier: " + identifier)
    return labels[0] if labels else "unspecified"


def checked_summary(report, rows, detections):
    summary = summarize(rows, detections, report["layout_balanced"].keys())
    if (summary["runs"], summary["layouts"]) != (report["runs"], report["layouts"]):
        raise ValueError("Reported case/layout counts differ from individual records")
    equal_numbers(summary["layout_balanced"], report["layout_balanced"], "layout macro")
    if "diagnostics" in report:
        for kind in ("hot", "smoky"):
            equal_numbers(summary["diagnostics"][kind], report["diagnostics"][kind], kind)
    # Preserve already published macro values after independently checking them.
    summary["layout_balanced"] = report["layout_balanced"]
    return summary


def report_summary(report):
    rows = report["per_run"]
    detections = indexed(report["per_case_diagnostics"])
    measured = indexed(rows)
    if measured.keys() != detections.keys():
        raise ValueError("Diagnostic membership differs from per-run metrics")
    result = checked_summary(report, rows, detections)
    for name, selector in (
        ("by_gravity", lambda row: gravity(row["run_id"])),
        ("by_incident_type", lambda row: row["incident_type"]),
    ):
        result[name] = {
            group: summarize(
                [row for row in rows if selector(row) == group], detections, report["layout_balanced"]
            )
            for group in sorted({selector(row) for row in rows})
        }
    for kind, published in report.get("per_incident_type", {}).items():
        equal_numbers(result["by_incident_type"][kind]["layout_balanced"], published["layout_balanced"], kind)
        result["by_incident_type"][kind]["layout_balanced"] = published["layout_balanced"]
    arrivals = report.get("per_case_arrival")
    if arrivals is not None:
        if indexed(arrivals).keys() != measured.keys():
            raise ValueError("Arrival summary membership differs from evaluated cases")
        result["smoke_arrival"] = {
            "status": "provided_by_trajectory_evaluator",
            "per_case": arrivals,
            "source_report_summary": report.get("smoke_arrival"),
        }
    else:
        result["smoke_arrival"] = {
            "status": "unavailable",
            "reason": "No trajectory-derived arrival summary; peak frames do not provide common point/time observations",
        }
    if "localization_selection_error" in report:
        result["reported_selection_error"] = report["localization_selection_error"]
    return result


def check_peak_exports(cases, report):
    plots, rows = indexed(cases), indexed(report["per_run"])
    if plots.keys() != rows.keys():
        raise ValueError("Test figure exports differ from test metric membership")
    for identifier, case in plots.items():
        times = [finite(t) for t in case["time_s"]]
        if not times or any(a >= b for a, b in zip(times, times[1:])):
            raise ValueError("Invalid exported observation times")
        for field in ("fds_max", "model_max"):
            if len(case[field]) != len(times) or any(len(v) != 2 for v in case[field]):
                raise ValueError("Invalid exported field maxima")
            for values in case[field]:
                for value in values:
                    finite(value)
                if values[1] < 0:
                    raise ValueError("Negative soot maximum")
        peaks = {}
        for channel, key in enumerate(("temperature_peak_error_c", "smoke_peak_error_kg_m3")):
            peaks[key] = abs(
                max(v[channel] for v in case["model_max"]) - max(v[channel] for v in case["fds_max"])
            )
        equal_numbers(peaks, {key: rows[identifier][key] for key in peaks}, "exported peaks:" + identifier)
    return len(plots)


def analyze(directory):
    training_path = directory / "training-report.json"
    if not training_path.exists():
        training_path = directory / "report.json"
    paths = {
        "training": training_path,
        "replay": directory / "replay-report.json",
        "test_plots": directory / "test-plots.json.gz",
    }
    loaded, inputs = {}, {}
    for name, path in paths.items():
        raw = path.read_bytes()
        loaded[name] = json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)
        inputs[name] = {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}
    training, replay = loaded["training"], loaded["replay"]
    metadata = training["metadata"]
    if not training["reload_verified"] or not replay["unchanged_model"]:
        raise ValueError("Reports do not confirm reload/frozen-model verification")
    replay_rows = indexed(replay["per_run"])
    if (
        len(replay_rows) != replay["completed_runs"]
        or replay_rows.keys() != indexed(replay["per_run_diagnostics"]).keys()
    ):
        raise ValueError("Replay completion/count membership differs")
    if {row["group"] for row in replay_rows.values()} != replay["groups"].keys():
        raise ValueError("Replay group membership differs")
    if metadata["weights_sha256"] != replay["model_artifacts"]["weights.pt"]:
        raise ValueError("Training and replay refer to different weights")
    test = metadata["metrics"]["test"]
    plot_count = check_peak_exports(loaded["test_plots"], test)
    if indexed(test["per_run"]).keys() & indexed(replay["per_run"]).keys():
        raise ValueError("Reserved test overlaps the known diagnostic")
    replay_summaries = {}
    for group, published in replay["groups"].items():
        selected = [row for row in replay["per_run"] if row["group"] == group]
        identifiers = {row["run_id"] for row in selected}
        combined = {
            **published["model"],
            "per_run": selected,
            "per_case_diagnostics": [
                row for row in replay["per_run_diagnostics"] if row["run_id"] in identifiers
            ],
            "diagnostics": published["diagnostics"],
        }
        if "per_case_arrival" in replay:
            combined["per_case_arrival"] = [
                row for row in replay["per_case_arrival"] if row["run_id"] in identifiers
            ]
        replay_summaries[group] = report_summary(combined)
    return {
        "schema_version": "spatial-recovery-analysis-1",
        "scope": "Post-training reporting only; no fitting, checkpoint selection or test-driven tuning",
        "inputs": inputs,
        "model_id": metadata["id"],
        "objective": metadata["training"]["objective"],
        "epochs": metadata["training"]["epochs"],
        "best_epoch": metadata["training"]["best_epoch"],
        "elapsed_training_seconds": training["elapsed_seconds"],
        "validation": report_summary(metadata["metrics"]["validation"]),
        "reserved_test": report_summary(test),
        "ambient_baseline_test": report_summary(metadata["ambient_baseline"]),
        "test_peak_exports_verified": plot_count,
        "known_diagnostic_replay": {"scope": replay["scope"], "groups": replay_summaries},
        "interpretation": {
            "physical_metrics": "Mean within case, then mean cases within layout, then mean layouts; missing values remain missing",
            "micro_diagnostics": "Pooled correlated point/time counts; not independent fires",
            "macro_diagnostics": "Per-case rates then equal layouts; undefined precision/recall excluded, empty-union IoU=1",
            "arrival": "Only trajectory evaluator summaries are reused; no nonarrival is replaced by the final time",
            "reference": "Synthetic FDS, not NASA experimental validation",
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = analyze(args.directory)
    text = json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    else:
        print(text, end="")
