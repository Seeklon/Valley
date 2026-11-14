"""Small incident workflow built on the existing FDS worker and scene contract."""
from __future__ import annotations

import copy
import tempfile
import threading
from pathlib import Path

import numpy as np

from .locking import ProcessLock
from .schema import RunConfig

MODEL_ID = "incident-field-v1"
INCIDENTS = [
    {"id": "overheating", "name": "Surchauffe", "description": "Chauffage local de la surface combustible.",
     "defaults": {"ignition_power_w": 1000, "ignition_duration_s": 10},
     "limitations": ["Puissance de défaut imposée ; aucun calcul de circuit ni de fréquence de panne."]},
    {"id": "arc", "name": "Arc / court-circuit", "description": "Impulsion de chaleur au point de défaut.",
     "defaults": {"ignition_power_w": 3000, "ignition_duration_s": 1},
     "limitations": ["Énergie thermique équivalente ; plasma et projections non résolus."]},
    {"id": "flaming", "name": "Feu déclaré", "description": "Foyer enflammé de puissance imposée.",
     "defaults": {"ignition_power_w": 1000, "ignition_duration_s": 10},
     "limitations": ["L'incident a déjà commencé ; le combustible des objets voisins peut réagir."]},
    {"id": "smoldering", "name": "Feu couvant", "description": "Apport prescrit de gaz chauds et de suie.",
     "defaults": {"ignition_power_w": 500, "ignition_duration_s": 10},
     "limitations": ["Émissions équivalentes ; cinétique du feu couvant non résolue."]},
    {"id": "battery", "name": "Batterie", "description": "Profil équivalent de chaleur et d'émissions.",
     "defaults": {"ignition_power_w": 3000, "ignition_duration_s": 10},
     "limitations": ["Profil hypothétique ; électrochimie, explosions et gaz toxiques non résolus."]},
]


def incident_scene(scene: dict) -> dict:
    """Apply explicit study annotations only to new incident calculations.

    The existing scene, archives and legacy model identities remain unchanged.
    Imported scenes can supply these properties directly through Blender.
    """
    result = copy.deepcopy(scene)
    annotations = result.get("incident_annotations", {})
    if annotations:
        result["components"] = copy.deepcopy(annotations.get("components", []))
        for obj in result["objects"]:
            surface = annotations.get("surface_materials", {}).get(obj["id"])
            if surface:
                obj["combustible_material_id"] = surface["material_id"]
                obj["thermal_thickness_m"] = surface["thickness_m"]
            obj["critical"] = obj["id"] in annotations.get("critical_object_ids", [])
        passage_ids = set(annotations.get("passage_sensor_ids", []))
        for sensor in result.get("sensors", []):
            if sensor["id"] in passage_ids:
                sensor["kind"] = "passage"
    return result


def consequences(scene: dict, config: dict, result: dict) -> dict:
    """Exposure diagnostics on the SAME sparse field for ML and FDS.

    Thresholds are explicit exploratory comparisons, not ignition/tenability limits.
    Missing fields never become safe values. Equipment values are nearest gas samples.
    """
    frames = result.get("frames", [])
    targets = [o for o in scene.get("objects", []) if o["role"] in {"fuel", "obstacle"}
               and o.get("visual_type") != "physical_only"]
    component = next((c for c in scene.get("components", []) if c["id"] == config.get("component_id")), {})
    targets = [o for o in targets if o["id"] != component.get("object_id")]
    passages = [s for s in scene.get("sensors", []) if s.get("kind") == "passage"]
    exposed, critical, touched_passages = set(), set(), set()
    unknown_targets, unknown_passages = set(), set()
    hot_peak, smoky_peak, heat_peak, smoke_peak, first = None, None, None, None, None
    observed = False
    def missing_frame():
        unknown_targets.update(o["id"] for o in targets)
        unknown_passages.update(s["id"] for s in passages)
    for frame in frames:
        positions = np.asarray(frame.get("sample_positions_m", []), dtype=float)
        if positions.ndim != 2 or positions.shape[1:] != (3,) or not len(positions):
            missing_frame()
            continue
        n = len(positions)
        valid = np.asarray(frame.get("valid_mask", [True]*n), dtype=bool)
        if valid.shape != (n,):
            missing_frame()
            continue
        valid &= np.isfinite(positions).all(axis=1)
        def field(key, factor=1):
            values = np.asarray(frame.get(key, []), dtype=float)
            return values * factor if values.shape == (n,) else np.full(n, np.nan)
        t, smoke = field("temperature_c"), field("smoke_kg_m3", 1e6)
        tv, sv = valid & np.isfinite(t), valid & np.isfinite(smoke)
        if not (tv.any() or sv.any()):
            missing_frame()
            continue
        observed = True
        bounds = frame.get("bounds_m", scene["bounds_m"])
        voxel_volume = float(np.prod(bounds)) / n
        if tv.any():
            heat_peak = max(heat_peak if heat_peak is not None else -273.15, float(t[tv].max()))
            hot_peak = max(hot_peak or 0, float(np.sum(tv & (t >= 60))) * voxel_volume)
        if sv.any():
            smoke_peak = max(smoke_peak or 0, float(smoke[sv].max()))
            smoky_peak = max(smoky_peak or 0, float(np.sum(sv & (smoke >= 10))) * voxel_volume)
        # Never assign a remote hot sample to an unsampled piece of equipment.
        spacing = [float(np.max(np.diff(np.unique(positions[:, axis]))))
                   if len(np.unique(positions[:, axis])) > 1 else float(bounds[axis])
                   for axis in range(3)]
        radius = float(np.linalg.norm(spacing)) / 2
        points = positions[valid]
        temperatures, soot = t[valid], smoke[valid]
        def exposure(point):
            distances = np.linalg.norm(points - point, axis=1)
            nearest = int(np.argmin(distances))
            if distances[nearest] > radius + 1e-6:
                return None
            tt, ss = temperatures[nearest], soot[nearest]
            if tt >= 60 or ss >= 10:
                return True
            return False if np.isfinite(tt) and np.isfinite(ss) else None
        for obj in targets:
            point = list(obj["center_m"])
            point[2] += obj["size_m"][2] / 2
            status = exposure(point)
            if status is None:
                unknown_targets.add(obj["id"])
            elif status:
                exposed.add(obj["id"])
                if obj.get("critical"):
                    critical.add(obj["id"])
                first = min(first, frame["time_s"]) if first is not None else frame["time_s"]
        for sensor in passages:
            status = exposure(sensor["position_m"])
            if status is None:
                unknown_passages.add(sensor["id"])
            elif status:
                touched_passages.add(sensor["id"])
                first = min(first, frame["time_s"]) if first is not None else frame["time_s"]
    unknown_targets -= exposed
    unknown_passages -= touched_passages
    unknown_critical = any(o["id"] in unknown_targets and o.get("critical") for o in targets)
    return {"heat_peak_c": heat_peak, "hot_volume_peak_m3": hot_peak,
            "smoke_peak_mg_m3": smoke_peak, "smoky_volume_peak_m3": smoky_peak,
            "exposed_equipment_count": len(exposed) if observed and not unknown_targets else None,
            "critical_exposed_count": len(critical) if observed and not unknown_critical else None,
            "passages_exposed_count": len(touched_passages) if passages and observed and not unknown_passages else None,
            "first_exposure_s": first, "exposed_equipment_ids": sorted(exposed),
            "unobserved_equipment_ids": sorted(unknown_targets),
            "thresholds": {"temperature_c": 60, "smoke_mg_m3": 10},
            "basis": "Seuils exploratoires sur gaz échantillonné, volumes approximatifs et sondes gazeuses proches des équipements ; exposition, pas preuve d'allumage ni seuil de survie."}



class IncidentService:
    def __init__(self, settings, scenes):
        self.settings = settings
        self.scenes = {s["id"]: incident_scene(s) for s in scenes}
        self.model = None
        self.model_error = None
        self.slot = threading.BoundedSemaphore(1)

    def load(self):
        directory = self.settings.models_dir / MODEL_ID
        if not directory.exists():
            return
        try:
            from .ml.incidents import IncidentSurrogate
            self.model = IncidentSurrogate(directory)
        except (ValueError, OSError, KeyError, ImportError) as exc:
            self.model_error = f"Modèle indisponible : {exc}"

    def scene(self, spec: RunConfig) -> dict:
        scene = self.scenes.get(spec.scene_id)
        if scene is None:
            raise ValueError("Scène inconnue.")
        if not spec.incident_type or not any(c["id"] == spec.component_id for c in scene.get("components", [])):
            raise ValueError("Équipement de départ inconnu pour cette scène.")
        return scene

    def validate(self, spec: RunConfig):
        from .physics import compile_case
        scene = self.scene(spec)
        with tempfile.TemporaryDirectory(prefix="ignis-incident-check-") as directory:
            compile_case(scene, spec.physical_config(), Path(directory))
        if spec.mode == "prediction":
            if not self.model:
                raise ValueError(self.model_error or "Le modèle de propagation n'est pas encore entraîné sur ce poste.")
            self.model.validate(scene, spec.physical_config())

    def complete(self, scene, config, result):
        result.setdefault("summary", {})["consequences"] = consequences(scene, config, result)
        return result

    def quality_note(self):
        if not self.model:
            return None
        metadata = self.model.metadata
        score = metadata.get("metrics", {}).get("test", {}).get("layout_balanced", {})
        baseline = metadata.get("ambient_baseline", {}).get("test", {}).get("layout_balanced", {})
        key = "temperature_mae_c"
        if key in score and key in baseline and score[key] >= baseline[key]:
            return ("Pilote exploratoire : l’erreur moyenne de température ne surpasse pas encore "
                    "la référence ambiante. Ne pas utiliser pour conclure à une zone sûre.")
        return None

    def predict(self, spec: RunConfig):
        scene = self.scene(spec)
        if not self.model:
            raise ValueError(self.model_error or "Le modèle de propagation n'est pas disponible.")
        result = self.complete(scene, spec.physical_config(), self.model.predict(scene, spec.physical_config()))
        if note := self.quality_note():
            result.setdefault("provenance", {}).setdefault("warnings", []).append(note)
        return result

    def predict_map(self, spec: RunConfig):
        scene = self.scene(spec)
        if not self.slot.acquire(blocking=False):
            raise RuntimeError("Une carte est déjà en cours de calcul.")
        try:
            with ProcessLock(self.settings.runtime / "compute.lock"):
                if not self.model:
                    raise ValueError(self.model_error or "Le modèle de propagation n'est pas disponible.")
                rows = []
                for component in scene.get("components", []):
                    case = spec.model_copy(update={"mode": "prediction", "model_id": MODEL_ID,
                                                   "component_id": component["id"]})
                    try:
                        result = self.predict(case)
                        rows.append({"component_id": component["id"], "result": result, "error": None})
                    except ValueError as exc:
                        rows.append({"component_id": component["id"], "result": None, "error": str(exc)})
                return {"config": spec.model_dump(mode="json"), "components": rows, "model_id": MODEL_ID}
        finally:
            self.slot.release()

    def catalog(self):
        components = [{**c, "scene_id": scene_id} for scene_id, scene in self.scenes.items()
                      for c in scene.get("components", [])]
        return {"version": "ignis-incidents-1", "incidents": INCIDENTS, "components": components,
                "model": {**self.model.metadata, "available": True, "quality_note": self.quality_note()} if self.model else {
                    "available": False, "id": MODEL_ID, "name": "Propagation · Extra Trees",
                    "limitations": [self.model_error or "Entraînement requis sur des incidents localisés."]},
                "defaults": RunConfig(scene_id="soyuz", source_model="coupled_combustion", duration_s=30,
                                      ignition_power_w=1000, ignition_duration_s=10).model_dump(mode="json")}
