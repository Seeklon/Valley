"""Verify ISS browser replays independently of the network and training code.

Recompute both channels, groups and baselines. With --dataset, compare every
exported observation, mask, coordinate and time directly to the stored FDS NPZ.
This verifies delivery fidelity, not the experimental validity of FDS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

FIELDS = {
    "heat": ("temperature_c", "hotspot_truth", "predicted_hot_mask", "temperature_c", 0),
    "smoke": ("soot_kg_m3", "smoke_truth", "predicted_smoke_mask", "smoke_kg_m3", 1),
}
COUNTS = ("tp", "fp", "fn", "tn")


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dataset_binding(dataset, index):
    """Bind the entire exported population to immutable source records."""
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    frozen_path = dataset / "index.json"
    if file_sha(frozen_path) != manifest.get("frozen_index_sha256"):
        raise ValueError("Dataset frozen index checksum mismatch")
    frozen = json.loads(frozen_path.read_bytes())
    for key in ("dataset_id", "expected_runs", "schema_version", "compiler_version", "material_model_version", "plan_sha256", "design_sha256"):
        if frozen.get(key) != manifest.get(key):
            raise ValueError("Dataset frozen identity mismatch")
    if file_sha(dataset / "plan.json") != manifest["plan_sha256"]:
        raise ValueError("Dataset plan checksum mismatch")
    records = {row["id"]: row for row in manifest["runs"]}
    if len(records) != len(manifest["runs"]):
        raise ValueError("Duplicate dataset record")
    if manifest.get("record_directory"):
        directory = manifest["record_directory"]
        if Path(directory).name != directory:
            raise ValueError("Unsafe dataset record directory")
        for path in sorted((dataset / directory).glob("*.json")):
            record = json.loads(path.read_bytes())
            if record["id"] != path.stem:
                raise ValueError("Dataset record identity mismatch")
            records[record["id"]] = record
    merged = {**manifest, "runs": list(records.values())}
    if canonical_sha(sorted(frozen["runs"], key=lambda row: row["id"])) != canonical_sha(sorted(records.values(), key=lambda row: row["id"])):
        raise ValueError("Dataset records differ from frozen index")
    if len(records) != manifest["expected_runs"] or len(index["cases"]) != len(records) or {e["id"] for e in index["cases"]} != set(records):
        raise ValueError("Export population differs from complete dataset")
    for entry in index["cases"]:
        record = records[entry["id"]]
        if record.get("status") != "completed":
            raise ValueError("Dataset case is not completed")
        for exported, original in (("split", "split"), ("layout_id", "layout_id"), ("module_id", "structural_family"), ("family", "structural_family")):
            if entry[exported] != record[original]:
                raise ValueError("Export partition or layout differs from dataset")
        folder = (dataset / record["relative_path"]).resolve()
        if not folder.is_relative_to(dataset.resolve()):
            raise ValueError("Dataset case path escapes directory")
        # Validate the exact files used by this independent observation check.
        for name in ("fields.npz", "manifest.json", "scene.json", "config.json", "ignis.fds"):
            if file_sha(folder / name) != record["file_hashes"].get(name):
                raise ValueError("Dataset case checksum mismatch: " + name)
    return records, merged, file_sha(manifest_path)


def model_binding(model_directory, index, records, merged, manifest_sha):
    model = index["model"]
    snapshot = json.loads((model_directory / "dataset-snapshot.json").read_bytes())
    if canonical_sha(snapshot) != model["dataset_sha256"]:
        raise ValueError("Model dataset snapshot checksum mismatch")
    if file_sha(model_directory / "weights.pt") != model["weights_sha256"]:
        raise ValueError("Model weights checksum mismatch")
    if snapshot["source_manifest_sha256"] != manifest_sha or snapshot["source_merged_index_sha256"] != canonical_sha(merged):
        raise ValueError("Model snapshot is bound to another dataset")
    snapshot_records = {row["id"]: row for row in snapshot["runs"]}
    if len(snapshot_records) != len(snapshot["runs"]) or set(snapshot_records) != set(records):
        raise ValueError("Model snapshot population mismatch")
    for identifier, row in snapshot_records.items():
        original = {k: v for k, v in row.items() if k != "geometry_signature"}
        if canonical_sha(original) != canonical_sha(records[identifier]):
            raise ValueError("Model snapshot record differs from dataset")
    selection = json.loads((model_directory / "frozen-selection.json").read_bytes())
    for expected, actual in ((model["score_thresholds"], selection["score_thresholds"]),
                             (model["state_sha256"], selection["state_sha256"]),
                             (model["selected_step"], selection["step"])):
        if expected != actual:
            raise ValueError("Export differs from frozen model selection")
    if selection["test_labels_used_for_selection"] is not False:
        raise ValueError("Selection did not preserve the test holdout")


def metric(counts):
    tp, fp, fn, tn = (int(counts.get(key, 0)) for key in COUNTS)

    def ratio(a, b):
        return a / b if b else None

    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=ratio(tp, tp + fp),
                recall=ratio(tp, tp + fn), iou=ratio(tp, tp + fp + fn),
                f1=ratio(2 * tp, 2 * tp + fp + fn),
                false_positive_rate=ratio(fp, fp + tn), n_valid=tp + fp + fn + tn)


def compare(actual, expected, context):
    for key, value in expected.items():
        other = actual.get(key)
        if key not in actual or (value is None and other is not None) or (
            value is not None and (other is None or not math.isclose(float(other), value, rel_tol=1e-8, abs_tol=1e-10))
        ):
            raise ValueError(f"{context}: {key}: export {other}, recomputed {value}")


def confusion(truth, predicted, valid):
    return Counter(tp=int(np.sum(valid & truth & predicted)), fp=int(np.sum(valid & ~truth & predicted)),
                   fn=int(np.sum(valid & truth & ~predicted)), tn=int(np.sum(valid & ~truth & ~predicted)))


def physical_geometry(scene):
    geometry = {"bounds_m": scene["bounds_m"]}
    for kind in ("objects", "vents"):
        geometry[kind] = sorted(
            [[*row["center_m"], *row["size_m"]] for row in scene[kind]]
        )
    return hashlib.sha256(json.dumps(geometry, sort_keys=True).encode()).hexdigest()


def verify_dataset_case(case, folder):
    """Exact float32 observations and float64 locations survive JSON round trips."""
    with np.load(folder / "fields.npz", allow_pickle=False) as packed:
        if not np.array_equal(case["sample_positions_m"], packed["positions_m"]):
            raise ValueError("Replay coordinates differ from FDS")
        if not np.array_equal(case["shape"], packed["shape"]):
            raise ValueError("Replay sampling shape differs from FDS")
        if not np.array_equal(case["scene"]["bounds_m"], packed["bounds_m"]):
            raise ValueError("Replay domain bounds differ from FDS")
        if not np.array_equal([frame["time_s"] for frame in case["frames"]], packed["time_s"]):
            raise ValueError("Replay chronology differs from FDS")
        for name, (measurement, _, _, stored_key, channel) in FIELDS.items():
            actual = np.asarray([f[measurement] for f in case["frames"]], dtype=float)
            masks = np.asarray([f[name + "_valid_mask"] for f in case["frames"]])
            if not np.array_equal(masks, packed["field_mask"][..., channel]):
                raise ValueError(f"{name}: replay observation mask differs from FDS")
            if not np.array_equal(actual[masks], packed[stored_key][masks]):
                raise ValueError(f"{name}: replay values differ from FDS")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    config = manifest["config"]
    for name in ("ambient_temperature_c", "gravity_g", "airflow_m_s", "oxygen_percent", "incident_type", "duration_s"):
        if case["conditions"][name] != config[name]:
            raise ValueError(f"Replay {name} differs from FDS")
    if case["conditions"]["source_position_m"] != manifest["incident"]["source"]["position_m"]:
        raise ValueError("Replay source differs from FDS")
    if case["scene"]["source"] != manifest["incident"]["source"]:
        raise ValueError("Replay source patch differs from FDS")
    for exported, original in (("power_w", "ignition_power_w"), ("source_duration_s", "ignition_duration_s")):
        if case["conditions"][exported] != config[original]:
            raise ValueError("Replay source condition differs from FDS")
    for kind in ("objects", "vents"):
        original = {row["id"]: row for row in manifest[kind]}
        if {row["id"] for row in case["scene"][kind]} != set(original):
            raise ValueError("Replay geometry objects differ from FDS")
        for row in case["scene"][kind]:
            source = original[row["id"]]
            box = np.asarray(source["bounds_m"]).reshape(3, 2)
            if not np.array_equal(row["center_m"], box.mean(axis=1)) or not np.array_equal(row["size_m"], np.diff(box, axis=1)[:, 0]):
                raise ValueError("Replay box differs from FDS")
            for key in ("material_id", "combustible_material_id", "thermal_thickness_m", "role", "normal"):
                if row.get(key) != source.get(key):
                    raise ValueError("Replay material, role or normal differs from FDS")


def group_checks(expected, rows, context):
    total = metric(sum((Counter(row) for _, row in rows), Counter()))
    compare(expected, total, context)
    if "groups" in expected:
        checks = {
            "microgravity": lambda e, c: e["gravity_g"] < 0.01,
            "earth": lambda e, c: e["gravity_g"] >= 0.01,
            "sample_inactive": lambda e, c: c["tp"] + c["fn"] == 0,
        }
        for name, predicate in checks.items():
            counts = sum((Counter(c) for e, c in rows if predicate(e, c)), Counter())
            compare(expected["groups"][name], metric(counts), context + "/" + name)
        for kind, attribute in (("module", "module_id"), ("microgravity_module", "module_id"), ("incident_type", "incident_type")):
            for name in {e[attribute] for e, _ in rows}:
                counts = sum((Counter(c) for e, c in rows if e[attribute] == name and (
                    kind != "microgravity_module" or e["gravity_g"] < 0.01
                )), Counter())
                compare(expected["groups"][kind][name], metric(counts), context + "/" + kind + "/" + name)
    inactive = [c for _, c in rows if c["tp"] + c["fn"] == 0]
    for key, value in (("case_count", len(rows)), ("sample_inactive_cases", len(inactive)),
                       ("sample_inactive_cases_with_false_alarm", sum(c["fp"] > 0 for c in inactive))):
        if key in expected and expected[key] != value:
            raise ValueError(f"{context}: {key} disagrees")
    return total


def verify_retraining_comparison(directory, dataset, model_directory, previous_model_directory):
    """Recompute old-weight comparisons from FDS observations and archived scores.

    Run after verify() bound the new replays, dataset and selected model files.
    This checks comparison arithmetic/provenance; it does not re-execute v1.
    """
    index = json.loads((directory / "index.json").read_bytes())
    previous = json.loads((previous_model_directory / "report.json").read_bytes())["model"]
    previous_selection = json.loads((previous_model_directory / "frozen-selection.json").read_bytes())
    selection = json.loads((model_directory / "frozen-selection.json").read_bytes())
    old_sha = file_sha(previous_model_directory / "weights.pt")
    if old_sha != previous["weights_sha256"] or old_sha != index["model"]["warm_start"]["weights_sha256"]:
        raise ValueError("Comparison weights differ from frozen v1")
    if previous["architecture"] != index["model"]["architecture"]:
        raise ValueError("Retraining changed architecture")
    thresholds = index["comparison_thresholds"]
    expected = {
        "v1_frozen": previous_selection["score_thresholds"],
        "v1_recalibrated": selection["v1_recalibrated_thresholds"],
    }
    if thresholds != expected or thresholds["v1_frozen"] != previous["score_thresholds"]:
        raise ValueError("Comparison thresholds differ from frozen selection")
    for values in thresholds.values():
        if set(values) != set(FIELDS) or any(not math.isfinite(v) or not 0 <= v <= 1.000002 for v in values.values()):
            raise ValueError("Invalid comparison thresholds")
    source = json.loads((dataset / "index.json").read_bytes())
    records = {row["id"]: row for row in source["runs"]}
    splits = {row["split"] for row in index["cases"]} - {"train"}
    if set(index["comparisons"]) != splits:
        raise ValueError("Comparison partitions differ from evaluation cases")
    result = {}
    for split in sorted(splits):
        compared = index["comparisons"][split]
        if compared["same_cases_as_retrained_model"] is not True:
            raise ValueError("Comparison is not paired on the same cases")
        entries = [row for row in index["cases"] if row["split"] == split]
        archive = compared["v1_score_archive"]
        path = (model_directory / archive["relative_path"]).resolve()
        if not path.is_relative_to(model_directory.resolve()) or file_sha(path) != archive["sha256"]:
            raise ValueError("Comparison score archive checksum or path mismatch")
        groups = defaultdict(list)
        with np.load(path, allow_pickle=False) as saved:
            if set(saved.files) != {row["id"] for row in entries}:
                raise ValueError("Comparison score population differs from evaluation cases")
            for entry in entries:
                record = records[entry["id"]]
                folder = (dataset / record["relative_path"]).resolve()
                if not folder.is_relative_to(dataset.resolve()) or file_sha(folder / "fields.npz") != record["file_hashes"]["fields.npz"]:
                    raise ValueError("Comparison FDS source checksum or path mismatch")
                with np.load(folder / "fields.npz", allow_pickle=False) as observations:
                    scores = saved[entry["id"]]
                    masks = observations["field_mask"].copy()
                    if scores.shape != masks.shape or masks.dtype != np.bool_:
                        raise ValueError("Comparison score dimensions or masks differ from observations")
                    masks[observations["time_s"] <= 0] = False
                    if not np.isfinite(scores[masks]).all() or np.any((scores[masks] < 0) | (scores[masks] > 1)):
                        raise ValueError("Invalid observed comparison scores")
                    for name, (_, _, _, stored, channel) in FIELDS.items():
                        physical = entry["ambient_temperature_c"] + 5 if name == "heat" else 1e-6
                        truth = observations[stored].astype(np.float64) >= physical
                        for kind, values in thresholds.items():
                            counts = confusion(truth, scores[..., channel] >= values[name], masks[..., channel])
                            groups[(kind, name)].append((entry, counts))
        result[split] = {}
        for (kind, name), rows in groups.items():
            total = group_checks(compared[kind][name], rows, split + "/" + kind + "/" + name)
            result[split].setdefault(kind, {})[name] = total
    return dict(verified=True, prediction_recomputed=False, architecture_unchanged=True,
                previous_weights_sha256=old_sha, metrics=result)


def verify(directory: Path, dataset: Path | None = None, model_directory: Path | None = None):
    directory = directory.resolve()
    index_path = directory / "index.json"
    index = json.loads(index_path.read_bytes())
    if index["schema_version"] != "iss-poc-1":
        raise ValueError("Unknown ISS export schema")
    model = index["model"]
    for key in ("weights_sha256", "state_sha256", "dataset_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", model[key]):
            raise ValueError("Missing model provenance hash")
    thresholds = model["score_thresholds"]
    if set(thresholds) != set(FIELDS) or any(not math.isfinite(v) or not 0 <= v <= 1.000002 for v in thresholds.values()):
        raise ValueError("Invalid score thresholds")
    if model["heat_delta_c"] != 5 or model["smoke_threshold_kg_m3"] != 1e-6:
        raise ValueError("Physical label thresholds changed")
    records = None
    if dataset is not None:
        dataset = dataset.resolve()
        records, merged, manifest_sha = dataset_binding(dataset, index)
        if model_directory is not None:
            model_binding(model_directory, index, records, merged, manifest_sha)
    elif model_directory is not None:
        raise ValueError("Model provenance verification also requires --dataset")
    rows, layouts, geometries, identifiers = [], {}, {}, set()
    grouped = defaultdict(list)
    baseline_grouped = defaultdict(list)
    for entry in index["cases"]:
        identifier, split = entry["id"], entry["split"]
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", identifier) or identifier in identifiers or split not in {"train", "validation", "test"}:
            raise ValueError("Invalid case identity or partition")
        identifiers.add(identifier)
        if layouts.setdefault(entry["layout_id"], split) != split:
            raise ValueError("Layout crosses partitions")
        url = entry["url"]
        if url.startswith("/poc/iss/"):
            url = url.removeprefix("/poc/iss/")
        path = (directory / url).resolve()
        if not path.is_relative_to(directory) or path.suffix != ".json":
            raise ValueError("Case path escapes export")
        raw = path.read_bytes()
        if "sha256" in entry and hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("Replay checksum differs from index")
        case = json.loads(raw)
        for key in ("id", "split", "layout_id", "module_id"):
            if case[key] != entry[key]:
                raise ValueError("Case identity differs from index")
        for key in ("score_thresholds", "heat_delta_c", "smoke_threshold_kg_m3"):
            if case[key] != model[key]:
                raise ValueError("Case thresholds differ from model")
        positions = np.asarray(case["sample_positions_m"], dtype=float)
        bounds = np.asarray(case["scene"]["bounds_m"], dtype=float)
        if positions.ndim != 2 or positions.shape[1] != 3 or bounds.shape != (3,) or not np.isfinite(positions).all() or not np.isfinite(bounds).all() or np.any(bounds <= 0) or np.any(positions <= 0) or np.any(positions >= bounds):
            raise ValueError("Invalid physical coordinates")
        axes = [np.unique(positions[:, i]) for i in range(3)]
        if list(map(len, axes)) != case["shape"] or not np.array_equal(positions, np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)):
            raise ValueError("Cartesian sample order changed")
        geometry = physical_geometry(case["scene"])
        if geometries.setdefault(geometry, split) != split:
            raise ValueError("Physical geometry crosses partitions")
        for key in ("ambient_temperature_c", "gravity_g", "airflow_m_s", "incident_type"):
            if case["conditions"][key] != entry[key]:
                raise ValueError("Case conditions differ from index")
        if dataset is not None:
            verify_dataset_case(case, dataset / records[identifier]["relative_path"])
        per_field = {name: Counter() for name in FIELDS}
        baseline = {(name, kind): Counter() for name in FIELDS for kind in ("all_cold", "source_proximity")}
        source_box = np.asarray(case["scene"]["source"]["bounds_m"]).reshape(3, 2)
        delta = np.maximum(np.maximum(source_box[:, 0] - positions, positions - source_box[:, 1]), 0)
        nearby = np.exp(-np.linalg.norm(delta, axis=1)).astype(np.float32)
        last = -1
        for frame in case["frames"]:
            current = frame["time_s"]
            if not math.isfinite(current) or current < 0 or current <= last:
                raise ValueError("Invalid chronology")
            last = current
            for name, (measurement, truth_key, predicted_key, _, _) in FIELDS.items():
                values = np.asarray(frame[measurement], dtype=float)
                scores = np.asarray(frame[name + "_score"], dtype=float)
                raw_mask = frame[name + "_valid_mask"]
                valid = np.asarray(raw_mask, dtype=bool)
                if any(type(v) is not bool for v in raw_mask) or any(v.shape != (len(positions),) for v in (values, scores, valid)):
                    raise ValueError("Misaligned channel arrays")
                if not np.isfinite(values[valid]).all() or not np.isfinite(scores[valid]).all() or np.any((scores[valid] < 0) | (scores[valid] > 1)):
                    raise ValueError("Missing or invalid observed score/value")
                physical_threshold = case["conditions"]["ambient_temperature_c"] + 5 if name == "heat" else 1e-6
                # Compare the stored values promoted to float64 with the exact
                # documented physical threshold, matching the browser contract.
                truth = values >= physical_threshold
                predicted = scores >= thresholds[name]
                for key, derived in ((truth_key, truth), (predicted_key, predicted)):
                    if len(frame[key]) != len(positions) or any(
                        (type(value) is not bool or value != bool(derived[i])) if valid[i] else value is not None
                        for i, value in enumerate(frame[key])
                    ):
                        raise ValueError(f"{identifier}: {key} disagrees with values or masks")
                if any(frame[measurement][i] is not None or frame[name + "_score"][i] is not None for i in np.flatnonzero(~valid)):
                    raise ValueError("Unobserved samples must stay null")
                if current > 0:
                    per_field[name].update(confusion(truth, predicted, valid))
                    baseline[(name, "all_cold")].update(confusion(truth, np.zeros_like(truth), valid))
                    if "baseline_source_proximity_thresholds" in index:
                        baseline[(name, "source_proximity")].update(confusion(truth, nearby >= index["baseline_source_proximity_thresholds"][name], valid))
        for name, counts in per_field.items():
            compare(entry["metrics"][name], metric(counts), identifier + "/" + name)
            compare(case["metrics"][name], metric(counts), identifier + "/replay/" + name)
            grouped[(split, name)].append((entry, counts))
            for kind in ("all_cold", "source_proximity"):
                baseline_grouped[(split, name, kind)].append((entry, baseline[(name, kind)]))
        rows.append(dict(id=identifier, split=split, sha256=hashlib.sha256(raw).hexdigest(),
                         positions=len(positions), frames=len(case["frames"]),
                         metrics={k: metric(v) for k, v in per_field.items()}))
    result = defaultdict(dict)
    for (split, name), group in grouped.items():
        result[split][name] = group_checks(index["metrics"][split][name], group, split + "/" + name)
        if "baselines" in index:
            for kind in ("all_cold", "source_proximity"):
                group_checks(index["baselines"][split][name][kind], baseline_grouped[(split, name, kind)], split + "/" + name + "/" + kind)
    if index["default_case_id"] not in identifiers:
        raise ValueError("Default replay does not exist")
    return dict(verified=True, no_inference_or_training=True, fds_observations_verified=dataset is not None,
                model_files_verified=model_directory is not None, prediction_recomputed=False,
                index_sha256=hashlib.sha256(index_path.read_bytes()).hexdigest(), model_id=model["id"],
                weights_sha256=model["weights_sha256"], layout_count=len(layouts),
                case_counts=dict(Counter(row["split"] for row in rows)), metrics=dict(result), cases=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--previous-model-dir", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.directory, args.dataset, args.model_dir)
    if args.previous_model_dir is not None:
        if args.dataset is None or args.model_dir is None:
            parser.error("Comparison verification requires --dataset and --model-dir")
        report["retraining_comparison"] = verify_retraining_comparison(
            args.directory, args.dataset, args.model_dir, args.previous_model_dir
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, allow_nan=False))
