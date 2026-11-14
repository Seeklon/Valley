from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from ignis.physics import compile_case

SHAPE = (8, 10, 4)
POINTS = int(np.prod(SHAPE))
METRICS = ["temperature_max_c", "temperature_mean_c", "oxygen_mean_percent",
           "smoke_mean_kg_m3", "heat_release_w"]
FIELD_SCALES = np.array([20, 0.1, 1e-6, 0.2, 0.2, 0.2], dtype=np.float32)
METRIC_SCALES = np.array([30, 1, 0.05, 1e-7, 2000], dtype=np.float32)


def geometry(scene, config):
    physical = dict(config)
    physical.update(mesh_cell_m=0.2, sample_shape=list(SHAPE))
    with tempfile.TemporaryDirectory(prefix="ignis-inference-geometry-") as directory:
        manifest = compile_case(scene, physical, Path(directory))
    return manifest


def features(scene: dict, config: dict, manifest: dict, times) -> np.ndarray:
    bounds = np.array(scene["bounds_m"], dtype=np.float32)
    source = np.array(scene["source_position_m"], dtype=np.float32) / bounds
    static = [config["gravity_g"], np.log10(max(config["gravity_g"], 1e-6)) / 6,
              config["airflow_m_s"] / 0.4, config["oxygen_percent"] / 21,
              config["ignition_power_w"] / 3000, config["ignition_duration_s"] / 25,
              float(config["material_id"] == "pmma"), *list(bounds / 8), *list(source)]
    for i in range(4):
        if i < len(scene["vents"]):
            vent = scene["vents"][i]
            static.extend([1 if vent["role"] == "inlet" else -1,
                           *list(np.array(vent["center_m"]) / bounds), *vent["normal"],
                           float(np.prod([v for v in vent["size_m"] if v > 0]))])
        else:
            static.extend([0] * 8)
    static.extend(float(v) for v in manifest["sampling"]["valid_mask"])
    data = []
    for time_s in times:
        duration = config["ignition_duration_s"]
        data.append([time_s / 60, min(time_s, duration) / 25,
                     max(0, time_s-duration) / 60, float(time_s <= duration), *static])
    return np.asarray(data, dtype=np.float32)


def encode_result(result: dict, config: dict):
    if len(result["frames"]) != len(result["metrics"]):
        raise ValueError("Spatial and scalar time samples do not match")
    values, masks = [], []
    for frame, metric in zip(result["frames"], result["metrics"]):
        if abs(frame["time_s"] - metric["time_s"]) > 1e-7:
            raise ValueError("Spatial and scalar observations are not synchronous")
        field = np.column_stack([np.array(frame["temperature_c"], dtype=np.float32) - 20,
                                 np.array(frame["oxygen_percent"], dtype=np.float32) - config["oxygen_percent"],
                                 np.array(frame["smoke_kg_m3"], dtype=np.float32),
                                 np.array(frame["velocity_m_s"], dtype=np.float32).reshape(-1, 3)])
        valid = np.array(frame["valid_mask"], dtype=bool)
        if np.any(~np.isfinite(field[valid])):
            raise ValueError("Invalid values in gas observations")
        field[~valid] = 0
        field = np.arcsinh(field / FIELD_SCALES)
        scalar = np.array([metric[key] for key in METRICS], dtype=np.float32)
        scalar -= np.array([20, 20, config["oxygen_percent"], 0, 0], dtype=np.float32)
        values.append(np.concatenate([field.ravel(), np.arcsinh(scalar / METRIC_SCALES)]))
        masks.append(np.concatenate([np.repeat(valid, 6), np.ones(len(METRICS))]))
    return np.asarray(values, dtype=np.float32), np.asarray(masks, dtype=np.float32)


def apply_initial_thermodynamics(encoded, times):
    """Known ambient T/composition at t=0; velocity perturbations remain learned."""
    initial = np.asarray(times) == 0
    indices = np.flatnonzero(initial)
    field = encoded[:, :POINTS*6].reshape(-1, POINTS, 6)
    field[indices, :, :3] = 0
    encoded[indices, POINTS*6:] = 0
    return encoded


def decode_outputs(encoded: np.ndarray, config: dict, *, postprocess=True):
    if postprocess:
        encoded = np.clip(encoded, -12, 12)
    fields = np.sinh(encoded[:, :POINTS*6].reshape(-1, POINTS, 6)) * FIELD_SCALES
    metrics = np.sinh(encoded[:, POINTS*6:]) * METRIC_SCALES
    fields[:, :, 0] += 20
    fields[:, :, 1] += config["oxygen_percent"]
    metrics += np.array([20, 20, config["oxygen_percent"], 0, 0], dtype=np.float32)
    if not postprocess:
        return fields, metrics
    fields[:, :, 0] = np.clip(fields[:, :, 0], -20, 2500)
    fields[:, :, 1] = np.clip(fields[:, :, 1], 0, 30)
    fields[:, :, 2] = np.maximum(0, fields[:, :, 2])
    metrics[:, :2] = np.clip(metrics[:, :2], -20, 2500)
    metrics[:, 2] = np.clip(metrics[:, 2], 0, 30)
    metrics[:, 3:] = np.maximum(0, metrics[:, 3:])
    return fields, metrics
