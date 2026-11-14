"""Fit the bounded incident emulator on Windows, without changing its FDS dataset.

Example: python tools/remote/train_incidents.py --home E:/IGNIS-Valley-dev
Validation chooses two fixed forest configurations. Test labels are evaluated
once after selection. No files in an existing model directory are overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from ignis.locking import ProcessLock
from ignis.ml.incidents import (
    COMPILER_VERSION,
    FEATURE_VERSION,
    GLOBAL_KEYS,
    INCIDENT_TYPES,
    MATERIAL_IDS,
    MAX_OBJECTS,
    MAX_VENTS,
    MODEL_ID,
    RANGES,
    SHAPE,
    build_features,
    decode_fields,
    decode_globals,
    encode_fields,
    encode_globals,
    file_sha,
    load_dataset,
    point_features,
    predict_arrays,
)
from ignis.physics.materials import MODEL_VERSION
from sklearn.ensemble import ExtraTreesRegressor

SEED = 20261114
MAX_TRAIN_POINTS = 60000


def write_json(path: Path, value) -> None:
    # Exclusive creation preserves partial or previous campaigns for inspection.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def training_arrays(records: list[dict], max_points: int):
    """Allocate capped float32 matrices directly, balanced by layout and then run."""
    train = [record for record in records if record["split"] == "train"]
    layouts = Counter(record["layout_id"] for record in train)
    if {record["config"]["incident_type"] for record in train} != set(INCIDENT_TYPES):
        raise ValueError("Training must cover all five incident families")
    if {record["config"]["gravity_g"] for record in train} != {0.0001, 1.0}:
        raise ValueError("Training must cover both gravity values")
    chosen = []
    for index, record in enumerate(train):
        rng = np.random.default_rng(SEED + index)
        # Initial state is imposed analytically, not learned from ambient duplicates.
        valid = record["masks"].copy()
        valid[record["times"] == 0] = False
        candidates = np.flatnonzero(valid)
        budget = max_points // (len(layouts) * layouts[record["layout_id"]])
        if budget < 16 or not len(candidates):
            raise ValueError("Insufficient training point budget or valid observations")
        chosen.append(np.sort(rng.choice(candidates, size=min(budget, len(candidates)), replace=False)))
    example = build_features(train[0]["scene"], train[0]["config"], train[0]["manifest"], [0.0])
    spatial_width = point_features(example, train[0]["manifest"], [0], [0]).shape[1]
    count = sum(len(indices) for indices in chosen)
    global_count = sum(np.sum(record["times"] > 0) for record in train)
    x = np.empty((count, spatial_width), dtype=np.float32)
    y = np.empty((count, 2), dtype=np.float32)
    weights = np.empty(count, dtype=np.float64)
    gx = np.empty((global_count, example.shape[1]), dtype=np.float32)
    gy = np.empty((global_count, len(GLOBAL_KEYS)), dtype=np.float32)
    gweights = np.empty(global_count, dtype=np.float64)
    offset, goffset, counts = 0, 0, []
    for record, indices in zip(train, chosen):
        frames, points = np.unravel_index(indices, record["masks"].shape)
        features = build_features(record["scene"], record["config"], record["manifest"], record["times"])
        size = len(indices)
        # A run expands only its own capped rows; no full-dataset expansion exists.
        x[offset:offset + size] = point_features(features, record["manifest"], frames, points)
        y[offset:offset + size] = record["fields"][frames, points]
        weights[offset:offset + size] = 1 / (layouts[record["layout_id"]] * size)
        offset += size
        keep = record["times"] > 0
        gsize = int(keep.sum())
        gx[goffset:goffset + gsize], gy[goffset:goffset + gsize] = features[keep], record["globals"][keep]
        gweights[goffset:goffset + gsize] = 1 / (layouts[record["layout_id"]] * gsize)
        goffset += gsize
        counts.append({"run_id": record["id"], "layout_id": record["layout_id"], "selected_points": size,
                       "available_points": int(record["masks"][keep].sum()), "global_frames": gsize})
    return (x, y, weights, gx, gy, gweights), counts


def _run_errors(record: dict, fields: np.ndarray, globals_: np.ndarray) -> dict:
    truth = decode_fields(record["fields"], postprocess=False)
    global_truth = decode_globals(record["globals"], postprocess=False)
    mask = record["masks"]
    delta = fields[mask] - truth[mask]
    global_delta = globals_ - global_truth
    encoded_delta = encode_fields(fields[mask]) - record["fields"][mask]
    encoded_global_delta = encode_globals(globals_) - record["globals"]
    hot = mask & (truth[:, :, 0] >= 25)
    smoky = mask & (truth[:, :, 1] >= 1e-7)
    result = {"run_id": record["id"], "layout_id": record["layout_id"], "scene_id": record.get("scene_id"),
              "incident_type": record["config"]["incident_type"], "gravity_g": record["config"]["gravity_g"],
              "frames": len(record["times"]), "observed_points": int(mask.sum()),
              "temperature_mae_c": float(np.abs(delta[:, 0]).mean()),
              "temperature_rmse_c": float(np.sqrt(np.mean(delta[:, 0] ** 2))),
              "smoke_mae_kg_m3": float(np.abs(delta[:, 1]).mean()),
              "smoke_rmse_kg_m3": float(np.sqrt(np.mean(delta[:, 1] ** 2))),
              "sample_temperature_peak_error_c": float(abs(fields[mask, 0].max() - truth[mask, 0].max())),
              "sample_smoke_peak_error_kg_m3": float(abs(fields[mask, 1].max() - truth[mask, 1].max())),
              "hot_temperature_mae_c": float(np.abs(fields[:, :, 0][hot] - truth[:, :, 0][hot]).mean()) if hot.any() else None,
              "smoky_smoke_mae_kg_m3": float(np.abs(fields[:, :, 1][smoky] - truth[:, :, 1][smoky]).mean()) if smoky.any() else None,
              "hot_observations": int(hot.sum()), "smoky_observations": int(smoky.sum()),
              "encoded_selection_error": float(np.abs(encoded_delta).mean() + np.abs(encoded_global_delta).mean())}
    for index, key in enumerate(GLOBAL_KEYS):
        result["fds_global_" + key + "_mae"] = float(np.abs(global_delta[:, index]).mean())
    return result


def summarize(rows: list[dict]) -> dict:
    """Macro aggregation gives each layout equal weight, then each run within it."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row["layout_id"], []).append(row)
    excluded = {"frames", "observed_points", "gravity_g", "hot_observations", "smoky_observations"}
    keys = [key for key in rows[0] if key not in excluded and
            (key.endswith("_mae") or key.endswith("_c") or key.endswith("_kg_m3") or key == "encoded_selection_error")]
    layouts = []
    for layout, values in grouped.items():
        aggregate = {"layout_id": layout, "runs": len(values)}
        for key in keys:
            observed = [row[key] for row in values if row[key] is not None]
            aggregate[key] = float(np.mean(observed)) if observed else None
        layouts.append(aggregate)
    macro = {}
    for key in keys:
        observed = [row[key] for row in layouts if row[key] is not None]
        macro[key] = float(np.mean(observed)) if observed else None
    return {"runs": len(rows), "layouts": len(layouts), "layout_balanced": macro, "per_layout": layouts,
            "aggregation": "Equal layouts, then equal runs; errors within each run cover all observed frames and gas points. Active-region errors exclude runs with no active observations.",
            "active_region_definitions": {"hot_temperature_c": 25, "smoky_kg_m3": 1e-7}}


def evaluate(records: list[dict], spatial=None, global_model=None) -> dict:
    """No frame/point subsampling in validation or test; ambient is the baseline."""
    rows = []
    for record in records:
        if spatial is None:
            fields = np.zeros((*record["masks"].shape, 2), dtype=float)
            fields[:, :, 0] = 20
            globals_ = np.tile([20, 20, 0, 0], (len(record["times"]), 1)).astype(float)
        else:
            fields, globals_ = predict_arrays(spatial, global_model, record["scene"], record["config"],
                                              record["manifest"], record["times"])
        rows.append(_run_errors(record, fields, globals_))
    scenarios = {}
    for family in INCIDENT_TYPES:
        subset = [row for row in rows if row["incident_type"] == family]
        if subset:
            scenarios[family] = summarize(subset)
    return {**summarize(rows), "per_run": rows, "per_incident_type": scenarios}


def train(home: Path, dataset_path: Path | None = None, max_points: int = MAX_TRAIN_POINTS) -> dict:
    home = Path(home)
    output = home / "runtime/models" / MODEL_ID
    if output.exists():
        raise FileExistsError("Existing incident model/campaign is preserved; choose a new version instead of overwriting.")
    if not 1000 <= max_points <= MAX_TRAIN_POINTS:
        raise ValueError(f"Training cap must be between 1000 and {MAX_TRAIN_POINTS} gas observations")
    started = time.perf_counter()
    dataset, records = load_dataset(dataset_path or home / "datasets/incidents-v1")
    validation = [record for record in records if record["split"] == "validation"]
    testing = [record for record in records if record["split"] == "test"]
    arrays, sampling_counts = training_arrays(records, max_points)
    x, y, weights, gx, gy, gweights = arrays
    print(json.dumps({"stage": "verified", "runs": len(records), "training_points": len(x),
                      "feature_count": x.shape[1], "matrix_mib": round(sum(a.nbytes for a in arrays) / 1024**2, 1)}), flush=True)
    candidates, best = [], None
    for leaf in (3, 8):
        parameters = {"n_estimators": 64, "max_depth": 14, "min_samples_leaf": leaf,
                      "max_features": 0.5, "n_jobs": 4, "random_state": SEED}
        spatial = ExtraTreesRegressor(**parameters).fit(x, y, sample_weight=weights)
        global_model = ExtraTreesRegressor(**parameters).fit(gx, gy, sample_weight=gweights)
        score = evaluate(validation, spatial, global_model)
        error = score["layout_balanced"]["encoded_selection_error"]
        candidates.append({"parameters": parameters, "validation": score})
        if best is None or error < best[0]:
            best = (error, spatial, global_model, parameters, score)
        print(json.dumps({"stage": "validation", "min_samples_leaf": leaf, "selection_error": error}), flush=True)
    _, spatial, global_model, parameters, validation_score = best
    del x, y, weights, gx, gy, gweights, arrays
    # Test data enter evaluation only after the final parameters are selected.
    metrics = {"validation": validation_score, "test": evaluate(testing, spatial, global_model)}
    baseline = {"name": "Ambient temperature, zero soot and zero chemical HRR",
                "validation": evaluate(validation), "test": evaluate(testing)}
    bounds = np.asarray([record["scene"]["bounds_m"] for record in records])
    train_records = [record for record in records if record["split"] == "train"]
    support = {record["geometry_signature"]: record["split"] + "_geometry" for record in records}
    metadata = {"id": MODEL_ID, "name": "Propagation localisée · Extra Trees",
                "kind": "incident_point_extra_trees", "feature_version": FEATURE_VERSION,
                "compiler_version": COMPILER_VERSION, "material_model_version": MODEL_VERSION,
                "dataset_id": dataset["dataset_id"], "dataset_manifest_sha256": dataset["manifest_sha256"],
                "trained_at": datetime.now(timezone.utc).isoformat(), "training_seconds": time.perf_counter() - started,
                "training_host": "Windows", "input_features": int(global_model.n_features_in_),
                "spatial_input_features": int(spatial.n_features_in_), "mesh_cell_m": 0.2,
                "sample_shape": list(SHAPE), "geometry_support": support,
                "domain": {"source_model": "coupled_combustion", "ignition_kind": "thermal",
                           "incident_types": list(INCIDENT_TYPES), "materials": list(MATERIAL_IDS),
                           "ranges": RANGES, "gravity_values": [0.0001, 1.0],
                           "source_duration_s": {family: 1 if family == "arc" else 10 for family in INCIDENT_TYPES},
                           "bounds_m": {"min": bounds.min(axis=0).tolist(), "max": bounds.max(axis=0).tolist()},
                           "max_objects": MAX_OBJECTS, "max_vents": MAX_VENTS,
                           "geometry_envelope_basis": "predeclared campaign geometry, including held-out layouts; no target labels"},
                "observed_training_ranges": {key: [min(row["config"][key] for row in train_records),
                                                    max(row["config"][key] for row in train_records)]
                                             for key in ("airflow_m_s", "oxygen_percent", "ignition_power_w")},
                "feature_schema": {"frame": "time, local source, five incident one-hot, SI controls, compartment bounds, 320 occupancy/substrate/coating/thickness cells, sorted physical object and vent slots",
                                   "point": "normalized xyz, source displacement/distance, nearest solid distance/substrate/coating/thickness",
                                   "excluded": ["scene_id", "scene_name", "layout_id", "run_id", "object_id", "component_id", "seed"]},
                "targets": {"spatial": ["temperature_c", "smoke_kg_m3"], "global": list(GLOBAL_KEYS),
                            "transform": "asinh with versioned fixed physical scales",
                            "missing": "gas observations with null channels excluded, solids never trained as zero targets"},
                "sampling": {"seed": SEED, "cap": max_points, "per_run": sampling_counts,
                             "weighting": "equal layout, equal run within layout; uniform valid noninitial observations within run",
                             "test_subsampled": False},
                "parameters": parameters, "selection": {"split": "validation", "metric": "layout-balanced mean encoded field MAE + mean encoded global MAE", "candidates": candidates},
                "split_run_ids": {split: [row["id"] for row in records if row["split"] == split]
                                  for split in ("train", "validation", "test")},
                "metrics": metrics, "ambient_baseline": baseline,
                "limitations": ["Modèle appris sur des calculs FDS exploratoires ; aucune validation contre des expériences NASA.",
                                "L’incident est imposé : aucun pronostic de panne électrique, d’allumage spontané ou de probabilité réelle de feu.",
                                "Maillage 0,20 m sans étude de convergence ; les 320 points sont des observations clairsemées du gaz.",
                                "Vitesse et oxygène spatiaux ne sont pas prédits ; aucun flux de fumée ne peut être déduit de ce modèle.",
                                "Les moyennes et maxima affichés proviennent du champ échantillonné ; les quantités FDS globales apprises sont séparées.",
                                "Arcs, feu couvant et batteries utilisent des profils équivalents, sans plasma ni électrochimie.",
                                "Une nouvelle géométrie dans l’enveloppe reste exploratoire ; consulter les erreurs du test de géométrie."]}
    # Claim a new output directory only after all checks and evaluation succeed.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    weights_path = output / "weights.joblib"
    with weights_path.open("xb") as stream:
        joblib.dump({"model_id": MODEL_ID, "feature_version": FEATURE_VERSION,
                     "spatial": spatial, "global": global_model}, stream, compress=3)
    metadata["weights_sha256"] = file_sha(weights_path)
    write_json(output / "metadata.json", metadata)
    write_json(output / "evaluation.json", {"metrics": metrics, "ambient_baseline": baseline})
    print(json.dumps({"stage": "complete", "output": str(output), "weights_sha256": metadata["weights_sha256"],
                      "test": metrics["test"]["layout_balanced"]}), flush=True)
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("IGNIS_HOME", "E:/IGNIS-Valley-dev")))
    parser.add_argument("--dataset", type=Path, help="Defaults to <home>/datasets/incidents-v1")
    parser.add_argument("--max-train-points", type=int, default=MAX_TRAIN_POINTS)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("The full incident campaign must train on the authorized Windows compute host.")
    with ProcessLock(args.home / "runtime/compute.lock"):
        train(args.home, args.dataset, args.max_train_points)
