"""Independently recompute POC metrics from the exact browser replay files.

No model import, inference, training, or simulator is used. Temperature and
score stay separate; unknown samples and t=0 never become classification labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


def metrics(counts: dict) -> dict:
    tp, fp, fn, tn = (int(counts[k]) for k in ("tp", "fp", "fn", "tn"))

    def ratio(a, b):
        return a / b if b else None

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn),
        "iou": ratio(tp, tp + fp + fn), "f1": ratio(2 * tp, 2 * tp + fp + fn),
        "false_positive_rate": ratio(fp, fp + tn), "n_valid": tp + fp + fn + tn,
    }


def compare(actual, expected, context):
    for key in ("tp", "fp", "fn", "tn", "precision", "recall", "iou", "false_positive_rate"):
        if key not in actual:
            raise ValueError(f"{context}: missing metric {key}")
        x, y = actual[key], expected[key]
        if y is None:
            if x is not None:
                raise ValueError(f"{context}: undefined {key} must stay null, received {x}")
        elif x is None or not math.isclose(float(x), y, rel_tol=1e-8, abs_tol=1e-10):
            raise ValueError(f"{context}: {key}: export {x}, recomputed {y}")
    for key in ("f1", "n_valid"):
        if key in actual and actual[key] != expected[key]:
            if actual[key] is None or expected[key] is None or not math.isclose(
                float(actual[key]), expected[key], rel_tol=1e-8, abs_tol=1e-10
            ):
                raise ValueError(f"{context}: {key} mismatch")


def verify(directory: Path):
    index_path = directory / "hotspots.json"
    data = json.loads(index_path.read_text())
    if data["schema_version"] != "hotspot-poc-1":
        raise ValueError("Unexpected export version")
    model = data["model"]
    threshold, delta = float(model["score_threshold"]), float(model["heat_delta_c"])
    if not 0 <= threshold <= 1.000001 or delta != 5:
        raise ValueError("POC threshold contract changed")
    counts = defaultdict(Counter)
    group_counts = defaultdict(lambda: defaultdict(Counter))
    layouts, identifiers, rows = {}, set(), []
    for entry in data["cases"]:
        identifier, split = entry["id"], entry["split"]
        if identifier in identifiers or split not in {"train", "validation", "test"}:
            raise ValueError("Duplicate case or invalid partition")
        identifiers.add(identifier)
        if layouts.setdefault(entry["layout_id"], split) != split:
            raise ValueError(f"Layout crosses partitions: {entry['layout_id']}")
        url = entry["url"]
        relative = url.removeprefix("/poc/")
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory.resolve()) or path.suffix != ".json":
            raise ValueError("Case path escapes the export")
        raw = path.read_bytes()
        case = json.loads(raw)
        if case["id"] != identifier:
            raise ValueError("Case URL and identity disagree")
        for key, value in (("score_threshold", threshold), ("heat_delta_c", delta)):
            if key in case and case[key] != value:
                raise ValueError(f"Case and index {key} disagree: {identifier}")
        if "split" in case and case["split"] != split:
            raise ValueError(f"Case and index partition disagree: {identifier}")
        position = np.asarray(case["sample_positions_m"], dtype=float)
        if position.ndim != 2 or position.shape[1] != 3 or not np.isfinite(position).all():
            raise ValueError(f"Invalid coordinates: {identifier}")
        bounds = np.asarray(case["scene"]["bounds_m"], dtype=float)
        if bounds.shape != (3,) or np.any(bounds <= 0) or np.any(position < 0) or np.any(position > bounds):
            raise ValueError(f"Coordinates outside scene: {identifier}")
        n, last, case_counts = len(position), -1.0, Counter(tp=0, fp=0, fn=0, tn=0)
        ambient = float(case["conditions"]["ambient_temperature_c"])
        if ambient != entry["ambient_temperature_c"]:
            raise ValueError("Index and case ambient temperatures differ")
        for frame in case["frames"]:
            t = float(frame["time_s"])
            if not math.isfinite(t) or t <= last or t < 0:
                raise ValueError("Nonmonotonic observed times")
            last = t
            temperature = np.asarray(frame["temperature_c"], dtype=float)
            score = np.asarray(frame["hotspot_score"], dtype=float)
            mask = np.asarray(frame.get("valid_mask", [True] * n), dtype=bool)
            if temperature.shape != (n,) or score.shape != (n,) or mask.shape != (n,):
                raise ValueError("Frame arrays and coordinates have different lengths")
            valid = mask & np.isfinite(temperature)
            if np.any(valid & ~np.isfinite(score)) or np.any(np.isfinite(score) & ((score < 0) | (score > 1))):
                raise ValueError("Missing or invalid classification scores")
            for key, derived in (
                ("hotspot_truth", temperature >= ambient + delta),
                ("predicted_hot_mask", score >= threshold),
            ):
                if key in frame:
                    exported = frame[key]
                    if len(exported) != n or any(
                        (type(value) is not bool or value != bool(derived[i]))
                        if valid[i] else value is not None
                        for i, value in enumerate(exported)
                    ):
                        raise ValueError(f"{identifier} at {t}: {key} disagrees with values or valid mask")
            if not t > 0:
                continue
            truth = temperature[valid] >= ambient + delta
            prediction = score[valid] >= threshold
            case_counts.update({
                "tp": int(np.sum(truth & prediction)), "fp": int(np.sum(~truth & prediction)),
                "fn": int(np.sum(truth & ~prediction)), "tn": int(np.sum(~truth & ~prediction)),
            })
        calculated = metrics(case_counts)
        compare(entry["metrics"], calculated, identifier)
        if "metrics" in case:
            compare(case["metrics"], calculated, f"{identifier} replay")
        counts[split].update(case_counts)
        if "gravity_g" in entry:
            gravity = "microgravity" if entry["gravity_g"] < 0.01 else "earth"
            group_counts[split][gravity].update(case_counts)
            activity = "sample_active" if case_counts["tp"] + case_counts["fn"] else "sample_inactive"
            group_counts[split][activity].update(case_counts)
        rows.append({"id": identifier, "split": split, "sha256": hashlib.sha256(raw).hexdigest(),
                     "frames": len(case["frames"]), "positions": n, "metrics": calculated})
    splits = {}
    for split, count in counts.items():
        splits[split] = metrics(count)
        compare(data["metrics"][split], splits[split], split)
        expected_groups = data["metrics"][split].get("groups", {})
        if expected_groups:
            verified_groups = {}
            for name in ("microgravity", "earth", "sample_active", "sample_inactive"):
                group = group_counts[split][name]
                for key in ("tp", "fp", "fn", "tn"):
                    group.setdefault(key, 0)
                verified_groups[name] = metrics(group)
                compare(expected_groups[name], verified_groups[name], f"{split}/{name}")
            splits[split]["groups"] = verified_groups
    return {"verified": True, "no_inference_or_training": True, "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
            "model_id": model["id"], "score_threshold": threshold, "heat_delta_c": delta,
            "case_counts": dict(Counter(r["split"] for r in rows)), "layout_count": len(layouts),
            "metrics": splits, "cases": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.directory)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, allow_nan=False))
