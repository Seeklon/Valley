"""Bounded, point-conditioned emulator of localized FDS incident fields.

Only temperature and soot in gas cells are learned spatially. The independently
learned FDS domain statistics are kept separate from summaries of those samples.
No electrical failure probability or time to ignition is inferred by this model.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path

import numpy as np

from ignis.physics import compile_case
from ignis.physics.materials import INERT_MATERIALS, MATERIALS, MODEL_VERSION
from ignis.provenance import canonical_sha

MODEL_ID = "incident-field-v1"
COMPILER_VERSION = "ignis-incidents-1"
FEATURE_VERSION = "incident-point-features-1"
SHAPE = (8, 10, 4)
POINTS = int(np.prod(SHAPE))
MAX_OBJECTS = 24
MAX_VENTS = 8
INCIDENT_TYPES = ("overheating", "arc", "flaming", "smoldering", "battery")
MATERIAL_IDS = tuple(sorted((*MATERIALS, *INERT_MATERIALS)))
GLOBAL_KEYS = ("temperature_max_c", "temperature_mean_c", "smoke_mean_kg_m3", "heat_release_w")
FIELD_SCALES = np.array([20.0, 1e-6])
GLOBAL_SCALES = np.array([30.0, 20.0, 1e-7, 1000.0])
RANGES = {"ignition_power_w": (500.0, 3000.0), "airflow_m_s": (0.05, 0.4),
          "oxygen_percent": (18.0, 24.0), "duration_s": (1.0, 30.0)}
Result = dict


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value, key: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a finite number")
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{key} must be a finite number") from exc
    if not np.isfinite(number):
        raise ValueError(f"{key} must be a finite number")
    return number


def validate_conditions(config: dict) -> None:
    if config.get("source_model") != "coupled_combustion" or config.get("ignition_kind", "thermal") != "thermal":
        raise ValueError("Le modèle incident exige coupled_combustion et ignition_kind=thermal.")
    family = config.get("incident_type")
    if family not in INCIDENT_TYPES:
        raise ValueError("Famille d’incident hors du domaine appris.")
    if not config.get("component_id"):
        raise ValueError("Un composant physique localisé est requis.")
    for key, (lo, hi) in RANGES.items():
        if not lo <= _number(config.get(key), key) <= hi:
            raise ValueError(f"{key} hors du domaine appris [{lo}, {hi}].")
    if _number(config.get("gravity_g"), "gravity_g") not in (0.0001, 1.0):
        raise ValueError("Gravité apprise : 0.0001 ou 1 g uniquement.")
    duration = 1.0 if family == "arc" else 10.0
    if _number(config.get("ignition_duration_s"), "ignition_duration_s") != duration:
        raise ValueError(f"Le profil {family} utilise une durée de source de {duration:g} s.")
    for key, expected in (("mesh_cell_m", 0.2), ("ambient_temperature_c", 20.0),
                          ("pressure_pa", 101325.0), ("ignition_delay_s", 0.0),
                          ("sample_interval_s", 1.0)):
        if _number(config.get(key, expected), key) != expected:
            raise ValueError(f"{key} doit rester à {expected:g} pour ce modèle.")
    if tuple(config.get("sample_shape", SHAPE)) != SHAPE:
        raise ValueError("Le champ appris utilise 8×10×4 observations.")


def compile_geometry(scene: dict, config: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="ignis-incident-geometry-") as directory:
        return compile_case(scene, config, Path(directory))


def _sampling(manifest: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if manifest.get("compiler_version") != COMPILER_VERSION:
        raise ValueError("Compiler version incompatible avec incident-field-v1.")
    sample = manifest["sampling"]
    if tuple(sample["shape"]) != SHAPE:
        raise ValueError("Sampling shape incompatible avec incident-field-v1.")
    bounds = np.asarray(sample["bounds_m"], dtype=float)
    positions = np.asarray(sample["positions_m"], dtype=float)
    mask = np.asarray(sample["valid_mask"], dtype=bool)
    if (bounds.shape != (3,) or positions.shape != (POINTS, 3) or mask.shape != (POINTS,)
            or not np.isfinite(bounds).all() or not np.isfinite(positions).all()
            or np.any(bounds <= 0) or np.any(positions <= 0) or np.any(positions >= bounds)
            or not mask.any()):
        raise ValueError("Invalid incident sampling geometry")
    return bounds, positions, mask


def _objects(manifest: dict) -> list[dict]:
    objects = manifest["objects"]
    if len(objects) > MAX_OBJECTS or len(manifest["vents"]) > MAX_VENTS:
        raise ValueError(f"Le modèle accepte au plus {MAX_OBJECTS} objets et {MAX_VENTS} bouches.")
    for obj in objects:
        if obj["material_id"] not in MATERIAL_IDS:
            raise ValueError("Unknown physical material in incident geometry")
        if obj.get("combustible_material_id") is not None and obj["combustible_material_id"] not in MATERIALS:
            raise ValueError("Unknown combustible surface material in incident geometry")
        if not 0.00005 <= _number(obj["thermal_thickness_m"], "thermal_thickness_m") <= 0.1:
            raise ValueError("Thermal thickness outside compiler domain")
    return sorted(objects, key=lambda obj: (*obj["bounds_m"], obj["material_id"],
                                           obj.get("combustible_material_id") or "", obj["thermal_thickness_m"]))


def _source(manifest: dict) -> dict:
    source = manifest.get("incident", {}).get("source")
    if not source or source.get("material_id") not in MATERIAL_IDS:
        raise ValueError("Localized incident source missing from compiler manifest")
    if source.get("face") != 3:
        raise ValueError("Ce modèle utilise une source sur la face supérieure du composant.")
    bounds, _, _ = _sampling(manifest)
    position = np.asarray(source["position_m"], dtype=float)
    if position.shape != (3,) or not np.isfinite(position).all() or np.any(position < 0) or np.any(position > bounds):
        raise ValueError("Source position outside compartment")
    return source


def _properties(material_id: str) -> list[float]:
    if material_id in MATERIALS:
        material = MATERIALS[material_id]
        raw = [material["density_kg_m3"], material["conductivity_w_m_k"],
               material["specific_heat_kj_kg_k"], material["emissivity"],
               material["heat_of_combustion_kj_kg"], material["soot_yield"]]
    else:
        raw = [*INERT_MATERIALS[material_id], 0, 0]
    return (np.asarray(raw) / [8000, 205, 3, 1, 30000, 0.05]).tolist()


def geometry_signature(manifest: dict) -> str:
    """A provenance label, never a predictor input or an exact-match admission gate."""
    objects = [{k: obj.get(k) for k in ("bounds_m", "material_id", "combustible_material_id", "thermal_thickness_m")}
               for obj in _objects(manifest)]
    vents = sorted(({k: vent[k] for k in ("bounds_m", "normal", "role")}
                    for vent in manifest["vents"]), key=lambda vent: (*vent["bounds_m"], vent["role"]))
    return canonical_sha({"bounds_m": manifest["sampling"]["bounds_m"], "objects": objects, "vents": vents})


def build_features(scene: dict, config: dict, manifest: dict, times) -> np.ndarray:
    """One row per actual time, with fixed geometry slots sorted without IDs.

    The cell table contains gas occupancy, substrate/coating codes and thickness.
    The object table retains sub-sampling-scale objects, one-hot materials, exact
    compiled boxes and thermal properties. Vent slots retain boxes, normal, role
    and signed flow. Slot overflow raises; no physical object is silently dropped.
    """
    validate_conditions(config)
    bounds, positions, valid = _sampling(manifest)
    if not np.allclose(bounds, scene["bounds_m"], rtol=0, atol=1e-8):
        raise ValueError("Scene and compiled compartment bounds differ")
    source, objects = _source(manifest), _objects(manifest)
    static = [*list(bounds / 8), *list(np.asarray(source["position_m"]) / bounds),
              source["area_m2"] / 4, source["face"] / 3,
              *[float(source["material_id"] == material) for material in MATERIAL_IDS],
              *[float(source.get("combustible_material_id") == material) for material in MATERIAL_IDS],
              *[float(config.get("material_id", "cellulose") == material) for material in MATERIALS],
              *[float(config["incident_type"] == family) for family in INCIDENT_TYPES],
              config["ignition_power_w"] / 3000, config["ignition_duration_s"] / 10,
              config["gravity_g"], np.log10(config["gravity_g"]) / 4,
              config["airflow_m_s"] / 0.4, config["oxygen_percent"] / 21]
    cells = np.zeros((POINTS, 4), dtype=np.float32)
    cells[:, 0] = valid
    object_features = []
    for obj in objects:
        box = np.asarray(obj["bounds_m"]).reshape(3, 2)
        inside = np.all((positions > box[:, 0]) & (positions < box[:, 1]), axis=1)
        cells[inside, 1] = (MATERIAL_IDS.index(obj["material_id"]) + 1) / len(MATERIAL_IDS)
        coating = obj.get("combustible_material_id")
        cells[inside, 2] = (MATERIAL_IDS.index(coating) + 1) / len(MATERIAL_IDS) if coating else 0
        cells[inside, 3] = obj["thermal_thickness_m"] / 0.1
        object_features.extend([1, *(box / bounds[:, None]).ravel(),
                                *[float(obj["material_id"] == material) for material in MATERIAL_IDS],
                                *[float(coating == material) for material in MATERIALS],
                                obj["thermal_thickness_m"] / 0.1, *_properties(obj["material_id"]),
                                *_properties(coating or obj["material_id"])])
    object_width = 1 + 6 + len(MATERIAL_IDS) + len(MATERIALS) + 1 + 12
    object_features.extend([0] * ((MAX_OBJECTS - len(objects)) * object_width))
    static.extend(cells.ravel().tolist())
    static.extend(object_features)
    vents = sorted(manifest["vents"], key=lambda vent: (*vent["bounds_m"], *vent["normal"], vent["role"]))
    for vent in vents:
        static.extend([1 if vent["role"] == "inlet" else -1,
                       *(np.asarray(vent["bounds_m"]).reshape(3, 2) / bounds[:, None]).ravel(),
                       *vent["normal"], vent["area_m2"] / 4, vent["volume_flow_m3_s"]])
    static.extend([0] * ((MAX_VENTS - len(vents)) * 12))
    times = np.asarray(times, dtype=float)
    if times.ndim != 1 or not len(times) or not np.isfinite(times).all() or np.any(times < 0) or np.any(times > 30 + 1e-6):
        raise ValueError("Times outside the 0–30 s incident horizon")
    duration = config["ignition_duration_s"]
    time_features = np.column_stack([times / 30, np.minimum(times, duration) / 10,
                                     np.maximum(0, times - duration) / 30, times < duration])
    result = np.empty((len(times), 4 + len(static)), dtype=np.float32)
    result[:, :4], result[:, 4:] = time_features, static
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite physical feature")
    return result


def point_features(frame_features: np.ndarray, manifest: dict, frame_indices, point_indices) -> np.ndarray:
    """Expand only requested gas rows; training never creates rows for missing cells."""
    bounds, positions, _ = _sampling(manifest)
    source = np.asarray(_source(manifest)["position_m"])
    delta = (positions - source) / bounds
    object_distances = []
    objects = _objects(manifest)
    for obj in objects:
        box = np.asarray(obj["bounds_m"]).reshape(3, 2)
        distance = np.maximum(np.maximum(box[:, 0] - positions, positions - box[:, 1]), 0)
        object_distances.append(np.linalg.norm(distance / bounds, axis=1))
    nearest = np.argmin(object_distances, axis=0)
    local = np.column_stack([positions / bounds, delta, np.linalg.norm(delta, axis=1),
                             np.min(object_distances, axis=0),
                             [(MATERIAL_IDS.index(objects[i]["material_id"]) + 1) / len(MATERIAL_IDS) for i in nearest],
                             [(MATERIAL_IDS.index(objects[i]["combustible_material_id"]) + 1) / len(MATERIAL_IDS)
                              if objects[i].get("combustible_material_id") else 0 for i in nearest],
                             [objects[i]["thermal_thickness_m"] / 0.1 for i in nearest]])
    frame_indices, point_indices = np.asarray(frame_indices), np.asarray(point_indices)
    result = np.empty((len(frame_indices), frame_features.shape[1] + local.shape[1]), dtype=np.float32)
    result[:, :frame_features.shape[1]] = frame_features[frame_indices]
    result[:, frame_features.shape[1]:] = local[point_indices]
    return result


def encode_fields(values, ambient_c: float = 20) -> np.ndarray:
    return np.arcsinh((np.asarray(values, dtype=float) - [ambient_c, 0]) / FIELD_SCALES).astype(np.float32)


def decode_fields(encoded, ambient_c: float = 20, *, postprocess: bool = True) -> np.ndarray:
    encoded = np.asarray(encoded, dtype=float)
    values = np.sinh(np.clip(encoded, -12, 12) if postprocess else encoded) * FIELD_SCALES + [ambient_c, 0]
    if not postprocess:
        return values
    values[..., 0] = np.clip(values[..., 0], -20, 2500)
    values[..., 1] = np.maximum(values[..., 1], 0)
    return values


def encode_globals(values, ambient_c: float = 20) -> np.ndarray:
    return np.arcsinh((np.asarray(values, dtype=float) - [ambient_c, ambient_c, 0, 0]) / GLOBAL_SCALES).astype(np.float32)


def decode_globals(encoded, ambient_c: float = 20, *, postprocess: bool = True) -> np.ndarray:
    encoded = np.asarray(encoded, dtype=float)
    values = np.sinh(np.clip(encoded, -12, 12) if postprocess else encoded) * GLOBAL_SCALES + [ambient_c, ambient_c, 0, 0]
    if not postprocess:
        return values
    values[..., :2] = np.clip(values[..., :2], -20, 2500)
    values[..., 2:] = np.maximum(values[..., 2:], 0)
    return values


def encode_result(result: dict, manifest: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return actual times, encoded fields, observation masks, encoded FDS globals."""
    bounds, positions, geometry_mask = _sampling(manifest)
    frames, metrics = result["frames"], result["metrics"]
    if not frames or len(frames) != len(metrics):
        raise ValueError("Spatial and global time samples must match")
    times, fields, masks, globals_ = [], [], [], []
    for frame, metric in zip(frames, metrics):
        t = _number(frame["time_s"], "time_s")
        if abs(t - _number(metric["time_s"], "metric.time_s")) > 1e-6 or (times and t <= times[-1]):
            raise ValueError("Unordered or asynchronous incident observations")
        if (tuple(frame["shape"]) != SHAPE or not np.array_equal(frame["valid_mask"], geometry_mask)
                or not np.allclose(frame["sample_positions_m"], positions, rtol=0, atol=1e-8)
                or not np.allclose(frame["bounds_m"], bounds, rtol=0, atol=1e-8)):
            raise ValueError("Result sampling differs from compiled geometry")
        values = np.column_stack([np.asarray(frame["temperature_c"], dtype=float),
                                  np.asarray(frame["smoke_kg_m3"], dtype=float)])
        if values.shape != (POINTS, 2) or np.isinf(values).any():
            raise ValueError("Invalid spatial incident values")
        # Null observations stay excluded, including gas-device data gaps.
        observed = geometry_mask & np.isfinite(values).all(axis=1)
        if not observed.any():
            raise ValueError("No valid gas observations in incident frame")
        if np.any(values[observed, 1] < -1e-12):
            raise ValueError("Negative soot concentration")
        encoded = encode_fields(values)
        encoded[~observed] = np.nan
        scalar = np.asarray([metric[key] for key in GLOBAL_KEYS], dtype=float)
        if not np.isfinite(scalar).all():
            raise ValueError("Missing or nonfinite learned global target")
        times.append(t)
        fields.append(encoded)
        masks.append(observed)
        globals_.append(encode_globals(scalar))
    if times[0] < 0 or times[-1] > 30 + 1e-6:
        raise ValueError("Incident result outside time domain")
    return np.asarray(times), np.asarray(fields), np.asarray(masks), np.asarray(globals_)


def predict_arrays(spatial, global_model, scene: dict, config: dict, manifest: dict, times):
    """Use chunks to avoid allocating all 320 repeated geometry rows per frame."""
    features = build_features(scene, config, manifest, times)
    _, _, mask = _sampling(manifest)
    fields = np.full((len(times), POINTS, 2), np.nan)
    ti, pi = np.nonzero(np.broadcast_to(mask, (len(times), POINTS)))
    for start in range(0, len(ti), 1024):
        t, p = ti[start:start + 1024], pi[start:start + 1024]
        inputs = point_features(features, manifest, t, p)
        fields[t, p] = decode_fields(spatial.predict(inputs))
    globals_ = decode_globals(global_model.predict(features))
    initial = np.asarray(times) == 0
    for index in np.flatnonzero(initial):
        fields[index, mask] = [20.0, 0.0]
        globals_[index] = [20.0, 20.0, 0.0, 0.0]
    if not np.isfinite(fields[:, mask]).all() or not np.isfinite(globals_).all():
        raise ValueError("Nonfinite model prediction")
    return fields, globals_


def validate_splits(runs: list[dict]) -> None:
    if not runs or len({run["id"] for run in runs}) != len(runs):
        raise ValueError("Empty dataset or duplicate run IDs")
    groups = {split: set() for split in ("train", "validation", "test")}
    for run in runs:
        if run["split"] not in groups or not run.get("layout_id"):
            raise ValueError("A layout_id and explicit train/validation/test split are required")
        groups[run["split"]].add(run["layout_id"])
        if run.get("scene_id") == "crossflow" and run["split"] != "test":
            raise ValueError("Crossflow geometry must remain held out for test")
    if any(not group for group in groups.values()):
        raise ValueError("All three dataset splits must be nonempty")
    if any(groups[a] & groups[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("Layout leakage across dataset splits")


def load_dataset(directory: Path) -> tuple[dict, list[dict]]:
    """Verify immutable inputs before any fitting; retain only compact target arrays."""
    directory = Path(directory).resolve()
    manifest_path = directory / "manifest.json"
    dataset = json.loads(manifest_path.read_text(encoding="utf-8"))
    if dataset.get("compiler_version") != COMPILER_VERSION:
        raise ValueError("Incompatible incident dataset compiler version")
    if dataset.get("expected_runs", len(dataset["runs"])) != len(dataset["runs"]):
        raise ValueError("Incident campaign is incomplete")
    if any(run.get("status", "completed") != "completed" for run in dataset["runs"]):
        raise ValueError("Only completed incident runs may enter training")
    validate_splits(dataset["runs"])
    records, geometry_splits = [], {}
    for run in dataset["runs"]:
        folder = (directory / run["relative_path"]).resolve()
        if not folder.is_relative_to(directory):
            raise ValueError("Run path leaves the dataset directory")
        if file_sha(folder / "result.json") != run["result_sha256"]:
            raise ValueError(f"Result checksum mismatch: {run['id']}")
        scene = json.loads((folder / "scene.json").read_text(encoding="utf-8"))
        config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        compiled = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if canonical_sha(scene) != run["scene_sha256"] or compiled.get("scene_sha256") != canonical_sha(scene):
            raise ValueError(f"Scene checksum mismatch: {run['id']}")
        if canonical_sha(config) != canonical_sha(run["config"]):
            raise ValueError(f"Run config mismatch: {run['id']}")
        fingerprint = canonical_sha({"scene": scene, "config": config, "compiler": COMPILER_VERSION})
        if "fingerprint" in run and run["fingerprint"] != fingerprint:
            raise ValueError(f"Run fingerprint mismatch: {run['id']}")
        validate_conditions(compiled["config"])
        if compiled.get("material_model_version") != MODEL_VERSION:
            raise ValueError(f"Material model version mismatch: {run['id']}")
        rebuilt = compile_geometry(scene, config)
        for key in ("compiler_version", "deck_sha256", "config_sha256", "sampling", "objects", "vents", "incident"):
            if canonical_sha(compiled.get(key)) != canonical_sha(rebuilt.get(key)):
                raise ValueError(f"Compiled {key} differs from reconstruction: {run['id']}")
        signature = geometry_signature(compiled)
        if signature in geometry_splits and geometry_splits[signature] != run["split"]:
            raise ValueError("Physical layout leakage despite different layout IDs")
        geometry_splits[signature] = run["split"]
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        provenance = result["provenance"]
        checks = {"compiler_version": COMPILER_VERSION, "material_model_version": MODEL_VERSION,
                  "scene_sha256": canonical_sha(scene), "config_sha256": canonical_sha(compiled["config"]),
                  "input_sha256": compiled["deck_sha256"]}
        if any(provenance.get(key) != expected for key, expected in checks.items()):
            raise ValueError(f"Result provenance mismatch: {run['id']}")
        if provenance.get("origin") != "simulation":
            raise ValueError("Only solver simulations may provide incident training labels")
        if (folder / "ignis.fds").exists() and file_sha(folder / "ignis.fds") != compiled["deck_sha256"]:
            raise ValueError(f"FDS deck checksum mismatch: {run['id']}")
        times, fields, masks, globals_ = encode_result(result, compiled)
        if times[0] != 0 or abs(times[-1] - compiled["config"]["duration_s"]) > 0.01:
            raise ValueError(f"Incomplete incident trajectory: {run['id']}")
        records.append({**run, "scene": scene, "config": compiled["config"], "manifest": compiled,
                        "geometry_signature": signature, "times": times, "fields": fields,
                        "masks": masks, "globals": globals_})
    dataset["manifest_sha256"] = file_sha(manifest_path)
    return dataset, records


class IncidentSurrogate:
    def __init__(self, directory: Path):
        import joblib

        directory = Path(directory)
        self.metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        expected = {"id": MODEL_ID, "kind": "incident_point_extra_trees", "feature_version": FEATURE_VERSION,
                    "compiler_version": COMPILER_VERSION, "material_model_version": MODEL_VERSION}
        if any(self.metadata.get(key) != value for key, value in expected.items()):
            raise ValueError("Incompatible incident model metadata; legacy weights cannot be reused.")
        path = directory / "weights.joblib"
        if file_sha(path) != self.metadata.get("weights_sha256"):
            raise ValueError("Incident model weights checksum mismatch.")
        payload = joblib.load(path)
        if payload.get("model_id") != MODEL_ID or payload.get("feature_version") != FEATURE_VERSION:
            raise ValueError("Incompatible incident model payload.")
        self.spatial, self.global_model = payload["spatial"], payload["global"]
        for model, key in ((self.spatial, "spatial_input_features"), (self.global_model, "input_features")):
            if model.n_features_in_ != self.metadata[key]:
                raise ValueError("Incident estimator feature dimensions do not match metadata.")
            model.n_jobs = 4

    def _validated_manifest(self, scene: dict, config: dict) -> dict:
        validate_conditions({**scene.get("defaults", {}), **config})
        manifest = compile_geometry(scene, config)
        validate_conditions(manifest["config"])
        bounds, _, _ = _sampling(manifest)
        _source(manifest)
        _objects(manifest)
        envelope = self.metadata["domain"]["bounds_m"]
        if np.any(bounds < np.asarray(envelope["min"]) - 1e-8) or np.any(bounds > np.asarray(envelope["max"]) + 1e-8):
            raise ValueError("Dimensions du compartiment hors de l’enveloppe étudiée.")
        features = build_features(scene, manifest["config"], manifest, [0.0])
        if features.shape[1] != self.metadata["input_features"]:
            raise ValueError("Incident feature schema differs from the trained model.")
        return manifest

    def validate(self, scene: dict, config: dict) -> None:
        self._validated_manifest(scene, config)

    def predict(self, scene: dict, config: dict) -> Result:
        started = time.perf_counter()
        manifest = self._validated_manifest(scene, config)
        cfg = manifest["config"]
        duration = cfg["duration_s"]
        times = np.arange(0.0, duration + 1e-8, 1.0)
        if times[-1] < duration - 1e-8:
            times = np.append(times, duration)
        fields, globals_ = predict_arrays(self.spatial, self.global_model, scene, cfg, manifest, times)
        _, positions, mask = _sampling(manifest)
        frames, metrics = [], []
        for index, t in enumerate(times):
            values = fields[index]
            scalar = dict(zip(GLOBAL_KEYS, map(float, globals_[index])))
            sensors = {}
            for sensor in manifest.get("sensors", []):
                if not sensor["valid"]:
                    sensors[sensor["id"]] = {"temperature_c": None, "smoke_kg_m3": None,
                                               "spatial_method": "unavailable: sensor in solid"}
                    continue
                distances = np.linalg.norm(positions - sensor["position_m"], axis=1)
                distances[~mask] = np.inf
                nearest = int(np.argmin(distances))
                sensors[sensor["id"]] = {"temperature_c": float(values[nearest, 0]),
                    "smoke_kg_m3": float(values[nearest, 1]), "sample_distance_m": float(distances[nearest]),
                    "spatial_method": "nearest predicted gas sample; not a resolved surface temperature"}
            metrics.append({"time_s": float(t), "temperature_max_c": float(values[mask, 0].max()),
                            "temperature_mean_c": float(values[mask, 0].mean()),
                            "smoke_mean_kg_m3": float(values[mask, 1].mean()),
                            "heat_release_w": scalar["heat_release_w"], "sensors": sensors,
                            "field_summary_basis": "unweighted valid gas samples; not full-volume FDS statistics",
                            "fds_global_prediction": scalar})
            frames.append({"time_s": float(t), "shape": list(SHAPE), "bounds_m": manifest["sampling"]["bounds_m"],
                           "valid_mask": mask.tolist(), "sample_positions_m": positions.tolist(),
                           "temperature_c": [float(v) if ok else None for v, ok in zip(values[:, 0], mask)],
                           "smoke_kg_m3": [float(v) if ok else None for v, ok in zip(values[:, 1], mask)]})
        signature = geometry_signature(manifest)
        status = self.metadata.get("geometry_support", {}).get(signature, "unseen_geometry_exploratory")
        warnings = list(self.metadata.get("limitations", []))
        if status == "unseen_geometry_exploratory":
            warnings.append("Géométrie inédite : estimation exploratoire sans validation sur ce compartiment.")
        elif status == "test_geometry":
            warnings.append("Géométrie réservée au test : consulter ses erreurs publiées de généralisation.")
        for key, limits in self.metadata.get("observed_training_ranges", {}).items():
            if not limits[0] <= cfg[key] <= limits[1]:
                warnings.append(f"{key} sort du support observé à l’entraînement {limits}.")
        return {"provenance": {"engine": "IGNIS incident Extra Trees", "engine_version": "1",
                    "origin": "prediction", "model_id": MODEL_ID, "source_model": "coupled_combustion",
                    "incident_type": cfg["incident_type"], "component_id": cfg["component_id"],
                    "incident": manifest["incident"], "material_model_version": MODEL_VERSION,
                    "compiler_version": COMPILER_VERSION, "scientific_status": "learned_from_exploratory_fds",
                    "training_dataset_id": self.metadata["dataset_id"],
                    "weights_sha256": self.metadata["weights_sha256"], "geometry_status": status,
                    "geometry_signature": signature, "warnings": warnings,
                    "inference_seconds": round(time.perf_counter() - started, 4),
                    "initial_condition": "ambient temperature and zero soot at t=0",
                    "postprocessing": "bounded inverse asinh; nonnegative soot and HRR",
                    "predicted_fields": ["temperature_c", "smoke_kg_m3"], "seed_conditioned": False,
                    "validation_errors": self.metadata.get("metrics", {}), "solver_mesh": manifest["mesh"]},
                "frames": frames, "metrics": metrics,
                "summary": {"duration_s": duration,
                            "temperature_peak_c": max(row["temperature_max_c"] for row in metrics),
                            "smoke_peak_mean_kg_m3": max(row["smoke_mean_kg_m3"] for row in metrics),
                            "heat_release_peak_w": max(row["heat_release_w"] for row in metrics),
                            "temperature_smoke_basis": "sampled gas field; 320 positions with solids excluded",
                            "heat_release_basis": "independently learned full-domain FDS integral"}}
