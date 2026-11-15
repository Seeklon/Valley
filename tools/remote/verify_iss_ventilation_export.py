"""Audit ventilation replays and both archived model comparisons against FDS.

Uses no PyTorch and never trains or changes the selected model. Run only after
the fresh test has been opened by the frozen training/evaluation procedure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from evaluate_iss_ventilation import load_cases, paired_metrics
from verify_iss_poc_export import canonical_sha, compare, confusion, file_sha, group_checks, metric, verify


def archive_path(directory, entry):
    path = (directory / entry["relative_path"]).resolve()
    if not path.is_relative_to(directory.resolve()) or file_sha(path) != entry["sha256"]:
        raise ValueError("Comparison archive checksum or path mismatch")
    return path


def absolute_metrics(cases, scores, thresholds, expected, entries):
    result = {}
    for channel, name in enumerate(("heat", "smoke")):
        rows = []
        per_case = {row["id"]: row for row in expected[name]["cases"]}
        if set(per_case) != {case["record"]["id"] for case in cases}:
            raise ValueError("Comparison per-case population mismatch")
        for case, score in zip(cases, scores):
            valid = case["field_mask"][..., channel] & (case["time_s"] > 0)[:, None]
            value = np.asarray(score)[..., channel]
            if value.shape != valid.shape or not np.isfinite(value[valid]).all() or np.any(
                (value[valid] < 0) | (value[valid] > 1)
            ):
                raise ValueError("Invalid archived scores")
            key = "temperature_c" if name == "heat" else "smoke_kg_m3"
            threshold = case["config"]["ambient_temperature_c"] + 5 if name == "heat" else 1e-6
            truth = np.asarray(case[key], dtype=np.float64) >= threshold
            counts = confusion(truth, value >= thresholds[name], valid)
            identifier = case["record"]["id"]
            compare(per_case[identifier], metric(counts), name + "/" + identifier)
            rows.append((entries[identifier], counts))
        result[name] = group_checks(expected[name], rows, "comparison/" + name)
    return result


def verify_comparisons(model_directory, dataset, previous_model_directory):
    report = json.loads((model_directory / "report.json").read_bytes())
    index = json.loads((model_directory / "demo/index.json").read_bytes())
    frozen = json.loads((model_directory / "frozen-selection.json").read_bytes())
    previous = json.loads((previous_model_directory / "report.json").read_bytes())["model"]
    if frozen.get("test_labels_used_for_selection") is not False:
        raise ValueError("Missing frozen test holdout declaration")
    if canonical_sha(report["model"]) != canonical_sha(index["model"]):
        raise ValueError("Model report and replay index disagree")
    if canonical_sha(report["metrics"]) != canonical_sha(index["metrics"]):
        raise ValueError("Candidate metrics in report and replay index disagree")
    if canonical_sha(report["selection"]) != canonical_sha(frozen):
        raise ValueError("Report selection differs from frozen selection")
    if file_sha(previous_model_directory / "weights.pt") != previous["weights_sha256"] or (
        previous["weights_sha256"] != index["model"]["warm_start"]["weights_sha256"]
    ):
        raise ValueError("Baseline does not use the frozen V2 weights")
    if index["model"]["architecture"] != previous["architecture"]:
        raise ValueError("Ventilation adaptation changed architecture")
    expected_thresholds = {
        "v2_frozen": previous["score_thresholds"],
        "v2_recalibrated": frozen["v2_recalibrated_thresholds"],
    }
    if index["comparison_thresholds"] != expected_thresholds:
        raise ValueError("Baseline thresholds differ from frozen selection")
    if report["old_test_observations_read"] is not False or report["fresh_test_read_after_freeze"] is not True:
        raise ValueError("Unexpected test selection policy")
    entries = {row["id"]: row for row in index["cases"]}
    comparisons = {}
    for split in ("validation", "test"):
        cases = load_cases(dataset, split)
        identifiers = {case["record"]["id"] for case in cases}
        compared = report["comparisons"][split]
        if canonical_sha(compared) != canonical_sha(index["comparisons"][split]):
            raise ValueError("Replay index comparison differs from the report")
        archives, scores = {}, {}
        for kind in ("v2", "candidate"):
            path = archive_path(model_directory, report["score_archives"][split][kind])
            with np.load(path, allow_pickle=False) as values:
                if set(values.files) != identifiers:
                    raise ValueError("Comparison archive population mismatch")
                scores[kind] = [values[case["record"]["id"]].copy() for case in cases]
            archives[kind] = file_sha(path)
        result = {"archives_sha256": archives}
        for kind, thresholds in expected_thresholds.items():
            result[kind] = absolute_metrics(cases, scores["v2"], thresholds, compared[kind], entries)
        result["candidate"] = absolute_metrics(
            cases, scores["candidate"], index["model"]["score_thresholds"], index["metrics"][split], entries,
        )
        for kind, thresholds, saved in (
            ("v2", expected_thresholds["v2_recalibrated"], "v2_recalibrated_paired"),
            ("candidate", index["model"]["score_thresholds"], "candidate_paired"),
        ):
            paired = paired_metrics(cases, scores[kind], thresholds)
            if canonical_sha(paired) != canonical_sha(compared[saved]):
                raise ValueError("Paired response report differs from archived scores and FDS: " + saved)
            result[saved] = paired
        for case, score in zip(cases, scores["candidate"]):
            record = case["record"]
            entry = entries[record["id"]]
            for key in ("ventilation_group_id", "ventilation_state", "ventilation_axis", "reverse_ventilation"):
                if entry.get(key) != record.get(key):
                    raise ValueError("Replay ventilation identity differs from FDS record")
            path = (model_directory / "demo" / entry["url"]).resolve()
            if not path.is_relative_to((model_directory / "demo").resolve()):
                raise ValueError("Replay comparison path escapes export")
            replay = json.loads(path.read_bytes())
            for channel, name in enumerate(("heat", "smoke")):
                replay_scores = np.asarray([f[name + "_score"] for f in replay["frames"]], dtype=float)
                mask = case["field_mask"][..., channel]
                if not np.array_equal(replay_scores[mask], score[..., channel][mask]):
                    raise ValueError("Replay differs from archived candidate scores")
        comparisons[split] = result
    return {
        "verified": True, "architecture_unchanged": True, "prediction_recomputed": False,
        "baseline_weights_sha256": previous["weights_sha256"], "comparisons": comparisons,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--previous-model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.model_dir / "demo", args.dataset, args.model_dir)
    result["ventilation_comparison"] = verify_comparisons(args.model_dir, args.dataset, args.previous_model_dir)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key not in ("cases", "ventilation_comparison")}))


if __name__ == "__main__":
    main()
