"""Fit and evaluate restricted empirical ignition delay on the authorized Windows PC."""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from ignis.engine import write_json
from ignis.locking import ProcessLock
from ignis.preignition.learning import IGNITION_MODEL_ID
from sklearn.linear_model import Ridge


def features(points, degree):
    x = np.log(np.asarray([p["current_a"] for p in points]))
    return np.stack([x**d for d in range(1, degree+1)], axis=1)


def weights(points):
    counts = Counter(p["family_id"] for p in points)
    return np.asarray([1/counts[p["family_id"]] for p in points])


def evaluate(points, predicted, horizon=1.0):
    true = np.asarray([p["ignition_delay_s"] for p in points])
    errors = np.asarray(predicted)-true
    sample_weights = weights(points)
    alert_time = np.maximum(0, np.asarray(predicted)-horizon)
    lead = true-alert_time
    rows = [{"point_id": p["id"], "current_a": p["current_a"], "facility": p["facility"],
             "observed_delay_s": float(y), "predicted_delay_s": float(v), "error_s": float(e),
             "alert_time_s": float(a), "lead_time_s": float(lead_time)}
            for p, y, v, e, a, lead_time in zip(points, true, predicted, errors, alert_time, lead)]
    return {"points": len(points), "current_groups": len(set(p["family_id"] for p in points)),
            "mae_s": float(np.average(np.abs(errors), weights=sample_weights)),
            "max_absolute_error_s": float(np.abs(errors).max()),
            "log_rmse": float(np.sqrt(np.average((np.log(predicted)-np.log(true))**2, weights=sample_weights))),
            "relative_mae": float(np.average(np.abs(errors)/true, weights=sample_weights)),
            "alert_horizon_s": horizon, "alerts_before_observed_ignition": int((lead > 0).sum()),
            "missed_or_late_alerts": int((lead <= 0).sum()),
            "minimum_lead_time_s": float(lead.min()), "median_lead_time_s": float(np.median(lead)),
            "false_alarms_per_hour": None,
            "false_alarm_limitation": "Published figure has only igniting cases; no normal-operation denominator",
            "aggregation": "Equal weight per current group for regression metrics; alert counts are plotted observations",
            "predictions": rows}


def main():
    home = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    root = home / "app"
    output = home / "runtime/prevention/models" / IGNITION_MODEL_ID
    if output.exists():
        raise ValueError("Model archive already exists; use a new model version for a new training run")
    dataset_path = root / "data/prevention/ignition/dataset.json"
    blob = dataset_path.read_bytes()
    data = json.loads(blob)
    if hashlib.sha256((dataset_path.parent/data["source_file"]).read_bytes()).hexdigest() != data["source_sha256"]:
        raise ValueError("Original source PDF changed")
    partitions = {key: [p for p in data["points"] if p["split"] == key]
                  for key in ["train", "validation", "test"]}
    groups = {key: {p["family_id"] for p in values} for key, values in partitions.items()}
    if any(groups[a] & groups[b] for a, b in [("train", "validation"), ("train", "test"), ("validation", "test")]):
        raise ValueError("Current groups leak across partitions")
    train, val, test = [partitions[key] for key in ["train", "validation", "test"]]
    start = time.monotonic()
    candidates = []
    for degree in (1, 2, 3):
        model = Ridge(alpha=1e-5)
        model.fit(features(train, degree), np.log([p["ignition_delay_s"] for p in train]), sample_weight=weights(train))
        pred = np.exp(model.predict(features(val, degree)))
        score = evaluate(val, pred)
        # Check monotonicity over the TRAINING domain, independently of test outcomes.
        grid = [{"current_a": x} for x in np.linspace(3.5, 18, 100)]
        monotone = bool(np.all(np.diff(model.predict(features(grid, degree))) <= 0))
        candidates.append((score["log_rmse"] if monotone else float("inf"), degree, model, score, monotone))
    _, degree, model, validation, _ = min(candidates, key=lambda c: (c[0], c[1]))
    if not any(c[4] for c in candidates):
        raise ValueError("No physically monotone candidate")
    predictions = np.exp(model.predict(features(test, degree)))
    # Baseline coefficient fixed on training, with expected I^-2 heating dependence.
    scale = float(np.average([p["ignition_delay_s"]*p["current_a"]**2 for p in train], weights=weights(train)))
    baseline = [scale/p["current_a"]**2 for p in test]
    output.mkdir(parents=True, exist_ok=True)
    params = {"degree": degree, "intercept": float(model.intercept_),
              "coefficients": [float(v) for v in model.coef_]}
    write_json(output / "parameters.json", params)
    metadata = {
        "id": IGNITION_MODEL_ID, "name": "Délai d’allumage · régression expérimentale",
        "target": "ignition_delay_s", "origin": "published_experimental_figure_digitization",
        "trained_at": datetime.now(timezone.utc).isoformat(), "training_host": "Windows",
        "training_seconds": time.monotonic()-start, "dataset_id": data["dataset_id"],
        "dataset_sha256": hashlib.sha256(blob).hexdigest(), "source_sha256": data["source_sha256"],
        "source_id": "GUO-2023", "source_url": data["url"], "is_nasa_dataset": False,
        "method": "Ridge regression of log(delay) on polynomial log(current); degree selected on validation only",
        "selection_metric": "Current-group-weighted validation log RMSE; monotonicity checked on training domain",
        "selected_degree": degree,
        "candidates": [{"degree": d, "validation_log_rmse": s["log_rmse"], "monotone": m}
                       for _, d, _, s, m in candidates],
        "domain": {"current_a": [3.5, 18], "material_preset": "nichrome_ldpe_guo2023",
                   "gravity_g_range": [0.00001, .03], "airflow_m_s": 0,
                   "wire_length_m": .07, "core_radius_m": .00025, "insulation_thickness_m": .00015,
                   "context": data["protocol"]["associated_numerical_context"],
                   "conditional_on": "Published igniting cases, initially quiescent gas, constant maintained current; nominal atmosphere of associated numerical model"},
        "partition": {key: {"points": len(values), "current_groups": len(groups[key]),
                             "ids": [p["id"] for p in values]} for key, values in partitions.items()},
        "metrics": {"validation": validation, "test": evaluate(test, predictions),
                    "baseline_test": evaluate(test, baseline)},
        "parameters_sha256": hashlib.sha256((output / "parameters.json").read_bytes()).hexdigest(),
        "calibrated_probability": False, "uncertainty_interval": None,
        "limitations": data["limitations"] + ["Current is the only learned explanatory variable; gravity, ventilation and materials are NOT learned effects"],
    }
    write_json(output / "metadata.json", metadata)
    print(json.dumps({"model": IGNITION_MODEL_ID, "selected_degree": degree,
                      "test": metadata["metrics"]["test"], "baseline_test": metadata["metrics"]["baseline_test"]}), flush=True)


if __name__ == "__main__":
    home = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    with ProcessLock(home / "runtime/compute.lock"):
        main()
