"""Independent paired ventilation response metrics, using original FDS labels.

No inference or training happens here. A response is a signed change of the
thresholded affected region when only ventilation changes. Empty predictions
cannot improve centroid error silently: their missing coverage is reported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

FIELDS = ("heat", "smoke")
STATES = ("still", "slow", "fast", "reverse")
CONTRASTS = (("still", "slow"), ("still", "fast"), ("fast", "reverse"))
COMPARISON_TIMES_S = (5.0, 10.0, 15.0, 20.0, 25.0, 30.0)
MAX_INTERPOLATION_GAP_S = 2.5


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _config_without_airflow(case):
    return {key: value for key, value in case["config"].items() if key != "airflow_m_s"}


def _check_pair(left, right):
    if canonical(_config_without_airflow(left)) != canonical(_config_without_airflow(right)):
        raise ValueError("Paired cases differ in a condition other than airflow")
    for key in ("positions_m", "time_s"):
        if not np.array_equal(left[key], right[key]):
            raise ValueError("Paired observations use different coordinates or times")
    for key in ("objects", "sampling"):
        if canonical(left["manifest"][key]) != canonical(right["manifest"][key]):
            raise ValueError("Paired physical geometry or sampling differs")
    if canonical(left["manifest"]["incident"]["source"]) != canonical(
        right["manifest"]["incident"]["source"]
    ):
        raise ValueError("Paired sources differ")
    def vent_geometry(case):
        return sorted(
            canonical({key: v[key] for key in ("bounds_m", "normal", "area_m2")})
            for v in case["manifest"]["vents"]
        )
    if vent_geometry(left) != vent_geometry(right):
        raise ValueError("Paired vent geometry differs")


def _arrays(case, scores, thresholds):
    times = np.asarray(case["time_s"])
    positions = np.asarray(case["positions_m"])
    valid = np.asarray(case["field_mask"])
    truth = np.stack(
        [np.asarray(case["temperature_c"], dtype=np.float64) >= case["config"]["ambient_temperature_c"] + 5,
         np.asarray(case["smoke_kg_m3"], dtype=np.float64) >= 1e-6], axis=-1,
    )
    scores = np.asarray(scores)
    if (
        times.ndim != 1 or not len(times) or not np.isfinite(times).all()
        or np.any(np.diff(times) <= 0) or positions.ndim != 2 or positions.shape[1] != 3
        or not np.isfinite(positions).all() or truth.shape != (len(times), len(positions), 2)
        or valid.shape != truth.shape or valid.dtype != np.bool_ or scores.shape != truth.shape
    ):
        raise ValueError("Malformed paired observation arrays")
    if not np.isfinite(scores[valid]).all() or np.any((scores[valid] < 0) | (scores[valid] > 1)):
        raise ValueError("Invalid observed class scores")
    for channel, key in enumerate(("temperature_c", "smoke_kg_m3")):
        if not np.isfinite(np.asarray(case[key])[valid[..., channel]]).all():
            raise ValueError("Nonfinite observed physical label")
    valid = valid & (times > 0)[:, None, None]
    prediction = scores >= np.asarray([thresholds[name] for name in FIELDS])
    return truth, prediction, valid


def response_metrics(truth_a, truth_b, prediction_a, prediction_b, valid, positions):
    """All arrays are [time, point]; inputs already use matching physical grids."""
    truth_delta = truth_b.astype(np.int8) - truth_a.astype(np.int8)
    predicted_delta = prediction_b.astype(np.int8) - prediction_a.astype(np.int8)
    reference_changed = valid & (truth_delta != 0)
    predicted_changed = valid & (predicted_delta != 0)
    correct = reference_changed & (truth_delta == predicted_delta)
    tp = int(correct.sum())
    fp = int(predicted_changed.sum()) - tp
    fn = int(reference_changed.sum()) - tp
    eligible, missing, errors = 0, 0, []
    for a, b, pa, pb, observed in zip(truth_a, truth_b, prediction_a, prediction_b, valid):
        a, b, pa, pb = (value & observed for value in (a, b, pa, pb))
        if not (a.any() and b.any()):
            continue
        eligible += 1
        if not (pa.any() and pb.any()):
            missing += 1
            continue
        actual = positions[b].mean(axis=0) - positions[a].mean(axis=0)
        predicted = positions[pb].mean(axis=0) - positions[pa].mean(axis=0)
        errors.append(float(np.linalg.norm(actual - predicted)))
    return _summarize_counts({
        "tp": tp, "fp": fp, "fn": fn, "valid_sample_pairs": int(valid.sum()),
        "reference_change_count": int(reference_changed.sum()),
        "predicted_change_count": int(predicted_changed.sum()),
        "centroid_eligible_frames": eligible, "centroid_missing_prediction_frames": missing,
        "centroid_compared_frames": len(errors), "centroid_error_sum_m": sum(errors),
    })


def _summarize_counts(values):
    result = dict(values)
    tp, fp, fn = (result[key] for key in ("tp", "fp", "fn"))
    result["precision"] = tp / (tp + fp) if tp + fp else None
    result["recall"] = tp / (tp + fn) if tp + fn else None
    result["f1"] = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    n = result["centroid_compared_frames"]
    eligible = result["centroid_eligible_frames"]
    result["centroid_displacement_error_mean_m"] = result["centroid_error_sum_m"] / n if n else None
    result["centroid_prediction_coverage"] = n / eligible if eligible else None
    return result


def interpolate_case(case, scores, times):
    """Approximate common physical times; no extrapolation or binary interpolation.

    An exact observation uses only its own mask. Otherwise both observations
    must be valid and at most 2.5 seconds apart. Scores use the same brackets.
    """
    source_times = np.asarray(case["time_s"], dtype=np.float64)
    times = np.asarray(times, dtype=np.float64)
    if np.any(times < source_times[0]) or np.any(times > source_times[-1]):
        raise ValueError("Paired evaluation cannot extrapolate")
    upper = np.searchsorted(source_times, times)
    exact = source_times[upper] == times
    lower = np.where(exact, upper, upper - 1)
    gaps = source_times[upper] - source_times[lower]
    acceptable = gaps <= MAX_INTERPOLATION_GAP_S
    observed = np.asarray(case["field_mask"])
    valid = observed[lower] & observed[upper] & acceptable[:, None, None]
    fraction = np.divide(times - source_times[lower], gaps, out=np.zeros_like(times), where=gaps > 0)

    def interpolate(values, mask):
        values = np.asarray(values, dtype=np.float64)
        alpha = fraction.reshape((-1,) + (1,) * (values.ndim - 1))
        # Exact observations have upper==lower; invalid samples stay missing.
        return np.where(mask, values[lower] + alpha * (values[upper] - values[lower]), np.nan)

    result = dict(case)
    result.update(time_s=times, field_mask=valid,
                  temperature_c=interpolate(case["temperature_c"], valid[..., 0]),
                  smoke_kg_m3=interpolate(case["smoke_kg_m3"], valid[..., 1]))
    aligned_scores = interpolate(scores, valid)
    coverage = {
        "gap_rejected_times_s": times[~acceptable].tolist(),
        "valid_sample_channels_by_time": valid.sum(axis=(1, 2)).tolist(),
        "valid_sample_channels": int(valid.sum()),
    }
    return result, aligned_scores, coverage


def _aggregate(rows):
    keys = ("tp", "fp", "fn", "valid_sample_pairs", "reference_change_count", "predicted_change_count",
            "centroid_eligible_frames", "centroid_missing_prediction_frames", "centroid_compared_frames",
            "centroid_error_sum_m")
    result = _summarize_counts({key: sum(row[key] for row in rows) for key in keys})
    result["contrast_count"] = len(rows)
    result["no_reference_change_contrasts"] = sum(row["reference_change_count"] == 0 for row in rows)
    return result


def paired_metrics(cases, scores, thresholds):
    """Evaluate complete quartets, ignoring explicit zero-power control records."""
    if set(thresholds) != set(FIELDS) or any(
        not np.isfinite(v) or not 0 <= v <= 1.000002 for v in thresholds.values()
    ):
        raise ValueError("Invalid heat/smoke thresholds")
    if len(cases) != len(scores):
        raise ValueError("Each case needs a score array")
    groups = defaultdict(dict)
    ids = set()
    for case, score in zip(cases, scores):
        record = case["record"]
        if record["id"] in ids:
            raise ValueError("Duplicate paired case ID")
        ids.add(record["id"])
        group = record.get("ventilation_group_id")
        if group is None:
            continue
        state = record["ventilation_state"]
        if state not in STATES or state in groups[group]:
            raise ValueError("Duplicate or invalid ventilation state")
        _arrays(case, score, thresholds)  # Validate original, unmodified observations.
        groups[group][state] = (case, score)
    if not groups:
        raise ValueError("No complete ventilation groups supplied")
    rows, alignment = [], {}
    for group, states in sorted(groups.items()):
        if set(states) != set(STATES):
            raise ValueError("Incomplete ventilation quartet")
        identities = {
            (case["record"]["split"], case["record"]["layout_id"], case["record"]["structural_family"])
            for case, _ in states.values()
        }
        if len(identities) != 1:
            raise ValueError("Ventilation group crosses layouts, families or partitions")
        first_time = max(case["time_s"][0] for case, _ in states.values())
        last_time = min(case["time_s"][-1] for case, _ in states.values())
        times = [t for t in COMPARISON_TIMES_S if first_time <= t <= last_time]
        if not times:
            raise ValueError("No requested paired horizons are covered by every observation")
        alignment[group] = {
            "common_time_s": times,
            "out_of_domain_time_s": [t for t in COMPARISON_TIMES_S if t not in times],
            "cases": {},
        }
        aligned = {}
        for state, (case, score) in states.items():
            aligned_case, aligned_score, coverage = interpolate_case(case, score, times)
            alignment[group]["cases"][case["record"]["id"]] = coverage
            aligned[state] = (aligned_case, _arrays(aligned_case, aligned_score, thresholds))
        for first, second in CONTRASTS:
            left, (truth_a, prediction_a, valid_a) = aligned[first]
            right, (truth_b, prediction_b, valid_b) = aligned[second]
            _check_pair(left, right)
            values = {}
            for channel, name in enumerate(FIELDS):
                values[name] = response_metrics(
                    truth_a[..., channel], truth_b[..., channel], prediction_a[..., channel],
                    prediction_b[..., channel], (valid_a & valid_b)[..., channel], left["positions_m"],
                )
            rows.append({"group_id": group, "contrast": first + "_to_" + second,
                         "left_id": left["record"]["id"], "right_id": right["record"]["id"],
                         "family": left["record"]["structural_family"], "metrics": values})
    totals = {name: _aggregate([row["metrics"][name] for row in rows]) for name in FIELDS}
    by_family = {
        family: {name: _aggregate([row["metrics"][name] for row in rows if row["family"] == family])
                 for name in FIELDS}
        for family in sorted({row["family"] for row in rows})
    }
    return {"group_count": len(groups), "contrast_count": len(rows), "metrics": totals,
            "by_family": by_family, "pairs": rows,
            "alignment": alignment,
            "requested_time_s": list(COMPARISON_TIMES_S),
            "maximum_interpolation_gap_s": MAX_INTERPOLATION_GAP_S,
            "semantics": "Signed change of affected sampled regions at common physical times",
            "resampling": "Approximation: linear physical fields before thresholding and linear class scores; no extrapolation; both bracket masks required unless exact observation",
            "centroid_semantics": "Binary-region centroid displacement error in meters; missing predictions reported",
            "prediction_recomputed": False}


def load_cases(dataset, split):
    dataset = Path(dataset).resolve()
    index = json.loads((dataset / "index.json").read_bytes())
    if len(index["runs"]) != index["expected_runs"]:
        raise ValueError("Incomplete dataset index")
    cases = []
    for record in index["runs"]:
        if record["split"] != split:
            continue
        folder = (dataset / record["relative_path"]).resolve()
        if not folder.is_relative_to(dataset):
            raise ValueError("Unsafe dataset path")
        for name in ("fields.npz", "manifest.json"):
            if digest(folder / name) != record["file_hashes"][name]:
                raise ValueError("Original FDS observation or manifest checksum mismatch")
        manifest = json.loads((folder / "manifest.json").read_bytes())
        with np.load(folder / "fields.npz", allow_pickle=False) as values:
            case = {key: values[key].copy() for key in
                    ("time_s", "positions_m", "field_mask", "temperature_c", "smoke_kg_m3")}
        case.update(record=record, manifest=manifest, config=manifest["config"])
        cases.append(case)
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), required=True)
    parser.add_argument("--frozen-selection", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.split == "test":
        if args.frozen_selection is None:
            raise ValueError("Freeze selection before opening fresh test labels")
        selected = json.loads(args.frozen_selection.read_bytes())
        if selected.get("test_labels_used_for_selection") is not False:
            raise ValueError("Selection does not declare a preserved test holdout")
    source = json.loads(args.thresholds.read_bytes())
    thresholds = source.get("model", source)["score_thresholds"]
    cases = load_cases(args.dataset, args.split)
    with np.load(args.scores, allow_pickle=False) as saved:
        if set(saved.files) != {case["record"]["id"] for case in cases}:
            raise ValueError("Score archive population differs from the requested dataset partition")
        result = paired_metrics(cases, [saved[c["record"]["id"]] for c in cases], thresholds)
    result.update(split=args.split, scores_sha256=digest(args.scores),
                  thresholds_sha256=digest(args.thresholds), score_thresholds=thresholds,
                  dataset_index_sha256=digest(args.dataset / "index.json"),
                  frozen_selection_sha256=digest(args.frozen_selection) if args.frozen_selection else None)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "metrics": result["metrics"]}, allow_nan=False))


if __name__ == "__main__":
    main()
