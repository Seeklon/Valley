"""Generate bounded precursor trajectories and fit history forecasts on Windows.

Whole parameter families (including gravity and cutoff pairs) stay together.
Labels are simulated insulation temperature, never ignition or absence of fire.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from ignis.engine import write_json
from ignis.locking import ProcessLock
from ignis.preignition.learning import THERMAL_FEATURES, THERMAL_MODEL_ID, thermal_features
from ignis.preignition.thermal import simulate_thermal
from sklearn.ensemble import ExtraTreesRegressor

SEED = 20261114
OBSERVATION_TIMES = [.1, .2, .5, 1, 2, 5, 10]
HORIZONS = [.1, .25, .5, 1, 2, 5, 10, 20]


def scenarios(families=96):
    if families < 12:
        raise ValueError("At least twelve families are required")
    rng = np.random.default_rng(SEED)
    shuffled = rng.permutation(np.arange(1, families-1)).tolist()
    training_count = round(.68*families)
    validation_count = (families-training_count)//2
    training = {0, families-1, *shuffled[:training_count-2]}
    validation = set(shuffled[training_count-2:training_count-2+validation_count])
    currents = np.linspace(0, 20, families)
    rows = []
    for i, current in enumerate(currents):
        # Fixed before any solve or label inspection. All four variants share split.
        split = "train" if i in training else "validation" if i in validation else "test"
        air = 0.0 if i % 3 == 0 else float(rng.uniform(.01, .5))
        ambient = 20.0 if i % 4 == 0 else float(rng.uniform(0, 50))
        cutoff = float(rng.choice([.2, .5, 1, 2, 5, 10]))
        for gravity in [.0001, 1.0]:
            for intervention in [None, cutoff]:
                rows.append({"id": f"f{i:03d}-g{gravity:g}-{'on' if intervention is None else 'cut'}",
                    "family_id": f"f{i:03d}", "split": split,
                    "config": {"current_a": float(current), "airflow_m_s": air,
                        "gravity_g": gravity, "ambient_temperature_c": ambient,
                        "oxygen_percent": 21.0, "pressure_pa": 101325.0,
                        "duration_s": 30.0, "cutoff_s": intervention}})
    return rows


def solve(row):
    cfg = row["config"]
    trace = simulate_thermal({"material_preset": "nichrome_ldpe_guo2023",
        "current_a": cfg["current_a"], "airflow_m_s": cfg["airflow_m_s"], "gravity_g": cfg["gravity_g"],
        "duration_s": cfg["duration_s"], "cutoff_s": cfg["cutoff_s"],
        "ambient_temperature_k": cfg["ambient_temperature_c"]+273.15,
        "support_temperature_k": cfg["ambient_temperature_c"]+273.15,
        "radiant_temperature_k": cfg["ambient_temperature_c"]+273.15,
        "sample_interval_s": .1, "max_step_s": .02})
    points = [{"time_s": p["time_s"], "surface_temperature_c": p["surface_temperature_k"]-273.15,
               "current_a": p["current_a"], "conductor_temperature_c": p["conductor_temperature_k"]-273.15,
               "pyrolyzed_fraction": p["pyrolyzed_fraction"]} for p in trace["samples"]]
    windows = []
    requested = 0
    times = np.asarray([p["time_s"] for p in points])
    temperatures = np.asarray([p["surface_temperature_c"] for p in points])
    for observed_at in OBSERVATION_TIMES:
        history = [p for p in points if p["time_s"] <= observed_at+1e-9]
        for horizon in HORIZONS:
            requested += 1
            target_time = observed_at+horizon
            if len(history) < 2 or times[-1] < target_time:
                continue
            # No future temperature, event, stop time or hidden node enters x.
            x = thermal_features(history, cfg, target_time, cfg["current_a"])
            target = float(np.interp(target_time, times, temperatures))
            slope = (history[-1]["surface_temperature_c"]-history[-2]["surface_temperature_c"])/(history[-1]["time_s"]-history[-2]["time_s"])
            windows.append({"scenario_id": row["id"], "family_id": row["family_id"], "split": row["split"],
                "target_time_s": target_time, "target_temperature_c": target,
                "persistence_c": history[-1]["surface_temperature_c"],
                "linear_c": history[-1]["surface_temperature_c"]+horizon*slope,
                **dict(zip(THERMAL_FEATURES, x.tolist()))})
    return {**row, "summary": trace["summary"], "events": trace["events"],
            "requested_windows": requested, "available_windows": len(windows)}, points, windows


def balanced_weights(rows):
    counts = Counter(r["family_id"] for r in rows)
    return np.asarray([1/counts[r["family_id"]] for r in rows])


def metrics(rows, predictions):
    errors = np.asarray(predictions)-np.asarray([r["target_temperature_c"] for r in rows])
    return {"windows": len(rows), "families": len({r["family_id"] for r in rows}),
            "mae_c": float(np.average(np.abs(errors), weights=balanced_weights(rows))),
            "rmse_c": float(np.sqrt(np.average(errors**2, weights=balanced_weights(rows)))),
            "max_absolute_error_c": float(np.max(np.abs(errors))),
            "aggregation": "Equal total weight per family among windows with valid physical targets"}


def main(args):
    home = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    campaign = home / "runtime/prevention/datasets" / ("thermal-benchmark-v1" if args.benchmark else "thermal-families-v1")
    output = home / "runtime/prevention/models" / THERMAL_MODEL_ID
    if (campaign.exists() and any(campaign.iterdir())) or (not args.benchmark and output.exists()):
        raise ValueError("Archive already exists; preserve it and assign a new dataset/model version before another campaign")
    campaign.mkdir(parents=True, exist_ok=True)
    plan = scenarios(12 if args.benchmark else args.families)
    plan_path = campaign / "plan.json"
    write_json(plan_path, {"seed": SEED, "scenarios": plan, "split_unit": "family_id",
                           "observation_times_s": OBSERVATION_TIMES, "horizons_s": HORIZONS})
    start = time.monotonic()
    trajectory_rows, manifest, windows = [], [], []
    with ProcessPoolExecutor(max_workers=2) as pool:
        for index, (record, points, samples) in enumerate(pool.map(solve, plan)):
            manifest.append(record)
            windows.extend(samples)
            trajectory_rows.extend({"scenario_id": record["id"], "family_id": record["family_id"],
                                    "split": record["split"], **p} for p in points)
            if (index+1) % 16 == 0:
                print(json.dumps({"completed": index+1, "total": len(plan), "seconds": time.monotonic()-start}), flush=True)
    pq.write_table(pa.Table.from_pylist(trajectory_rows), campaign / "trajectories.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(windows), campaign / "windows.parquet", compression="zstd")
    write_json(campaign / "trajectories.json", manifest)
    coverage = {split: {"families": len({r["family_id"] for r in manifest if r["split"] == split}),
        "trajectories": sum(r["split"] == split for r in manifest),
        "completed_trajectories": sum(r["split"] == split and r["summary"]["status"] == "completed" for r in manifest),
        "requested_windows": sum(r["requested_windows"] for r in manifest if r["split"] == split),
        "available_windows": sum(r["available_windows"] for r in manifest if r["split"] == split)}
        for split in ["train", "validation", "test"]}
    digest = {name: hashlib.sha256((campaign / name).read_bytes()).hexdigest()
              for name in ["plan.json", "trajectories.json", "trajectories.parquet", "windows.parquet"]}
    source_hashes = {str(p.relative_to(home / "app")): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [home / "app/tools/remote/train_thermal.py", *sorted((home / "app/backend/ignis/preignition").glob("*.py"))]}
    dataset = {"id": campaign.name, "seed": SEED, "training_host": "Windows", "coverage": coverage,
               "hashes": digest, "source_hashes": source_hashes,
               "generation_seconds": time.monotonic()-start, "ignition_labels": False,
               "limitations": ["Synthetic two-node temperatures, not independently validated experimental histories",
                   "Targets beyond the fixed-geometry validity limit are unavailable, not negative fire labels",
                   "Metrics are conditional on available windows; they do not measure accuracy after scope termination"]}
    write_json(campaign / "metadata.json", dataset)
    if args.benchmark:
        print(json.dumps({"benchmark": dataset}), flush=True)
        return
    partitions = {split: [r for r in windows if r["split"] == split] for split in coverage}
    groups = {split: {r["family_id"] for r in values} for split, values in partitions.items()}
    if any(groups[a] & groups[b] for a, b in [("train", "validation"), ("train", "test"), ("validation", "test")]):
        raise ValueError("Family leakage across partitions")
    arrays = {split: np.asarray([[r[k] for k in THERMAL_FEATURES] for r in rows]) for split, rows in partitions.items()}
    train, val, test = [partitions[k] for k in ["train", "validation", "test"]]
    candidates = []
    for leaf in (1, 3, 8):
        model = ExtraTreesRegressor(n_estimators=96, min_samples_leaf=leaf, max_depth=20,
                                    random_state=SEED, n_jobs=2)
        model.fit(arrays["train"], [r["target_temperature_c"] for r in train], sample_weight=balanced_weights(train))
        score = metrics(val, model.predict(arrays["validation"]))
        candidates.append((score["mae_c"], leaf, model, score))
    _, leaf, model, validation = min(candidates, key=lambda x: (x[0], x[1]))
    predicted = model.predict(arrays["test"])
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output / "weights.joblib", compress=3)
    prediction_rows = [{"scenario_id": r["scenario_id"], "family_id": r["family_id"],
        "elapsed_s": r["elapsed_s"], "horizon_s": r["horizon_s"], "target_temperature_c": r["target_temperature_c"],
        "predicted_temperature_c": float(p)} for r, p in zip(test, predicted)]
    write_json(output / "test-predictions.json", prediction_rows)
    metadata = {"id": THERMAL_MODEL_ID, "name": "Température future · historique simulé",
        "target": "surface_temperature_c", "origin": "synthetic_local_thermal_model",
        "training_host": "Windows", "trained_at": datetime.now(timezone.utc).isoformat(),
        "dataset_id": dataset["id"], "dataset": dataset, "features": THERMAL_FEATURES,
        "method": "ExtraTrees regression; min_samples_leaf selected on validation only; no full-data refit",
        "selected_min_samples_leaf": leaf,
        "candidates": [{"min_samples_leaf": n, "validation_mae_c": v["mae_c"]} for _, n, _, v in candidates],
        "domain": {"current_a": [0, 20], "airflow_m_s": [0, .5], "ambient_temperature_c": [0, 50],
                   "gravity_g": [.0001, 1], "elapsed_s": [.1, 10], "horizon_s": [.1, 20],
                   "pressure_pa": 101325, "material_preset": "nichrome_ldpe_guo2023"},
        "metrics": {"validation": validation, "test": metrics(test, predicted),
                    "persistence_test": metrics(test, [r["persistence_c"] for r in test]),
                    "linear_test": metrics(test, [r["linear_c"] for r in test])},
        "weights_sha256": hashlib.sha256((output / "weights.joblib").read_bytes()).hexdigest(),
        "ignition_supported": False, "calibrated_probability": False, "uncertainty_interval": None,
        "limitations": dataset["limitations"] + ["No unseen-material, unseen-scene or real-sensor evaluation",
            "Geometry and thermal properties are fixed to the NiCr/LDPE laboratory preset",
            "Oxygen chemistry is absent; the model does not predict ignition or extinguishment",
            "Inference target coverage is clipped using the separately simulated physical scenario; coverage is not a learned prediction"]}
    write_json(output / "metadata.json", metadata)
    print(json.dumps({"model": THERMAL_MODEL_ID, "metrics": metadata["metrics"], "coverage": coverage}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--families", type=int, default=96)
    args = parser.parse_args()
    if not 12 <= args.families <= 1024:
        parser.error("families must be between 12 and 1024")
    home = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    with ProcessLock(home / "runtime/compute.lock"):
        main(args)
