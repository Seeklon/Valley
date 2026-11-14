from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np

from ignis.provenance import physical_scene_sha

from .features import METRICS, POINTS, SHAPE, apply_initial_thermodynamics, decode_outputs, features, geometry


def network(input_features: int, output_features: int):
    import torch.nn as nn
    return nn.Sequential(nn.Linear(input_features, 256), nn.SiLU(), nn.Linear(256, 256), nn.SiLU(),
                         nn.Linear(256, 384), nn.SiLU(), nn.Linear(384, output_features))


class Surrogate:
    def __init__(self, metadata, predictor):
        self.metadata, self.predictor = metadata, predictor

    @classmethod
    def load(cls, directory: Path):
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        name = "weights.pt" if metadata["kind"] == "spatial_mlp" else "weights.joblib"
        path = directory / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["weights_sha256"]:
            raise ValueError("L’empreinte des poids du modèle ne correspond pas au manifeste.")
        if metadata["kind"] == "spatial_mlp":
            import torch
            torch.set_num_threads(2)
            checkpoint = torch.load(path, map_location="cpu", weights_only=True)
            predictor = network(metadata["input_features"], metadata["output_features"])
            predictor.load_state_dict(checkpoint["state_dict"])
            predictor.eval()
        else:
            import joblib
            predictor = joblib.load(path)
        return cls(metadata, predictor)

    def validate(self, config, scene=None):
        domain = self.metadata["domain"]
        if config.scene_id not in domain["scene_ids"]:
            raise ValueError("Cette scène n’appartient pas au domaine de ce modèle.")
        if config.source_model != domain["source_model"] or config.ignition_kind != "thermal":
            raise ValueError("Ce modèle prédit le transport d’une source prescrite ; utiliser FDS pour l’allumage couplé.")
        if config.material_id not in domain["materials"]:
            raise ValueError("Matériau hors du domaine appris.")
        if abs(config.mesh_cell_m - self.metadata["mesh_cell_m"]) > 1e-8:
            raise ValueError("Ce modèle utilise exclusivement la référence FDS à 0,20 m.")
        if scene is not None and physical_scene_sha(scene) != self.metadata["physical_scene_hashes"].get(scene["id"]):
            raise ValueError("La géométrie physique a changé depuis l’entraînement ; régénérer les données et entraîner un nouveau modèle.")
        if not any(abs(config.gravity_g - value) < 1e-8 for value in domain["gravity_values"]):
            raise ValueError("Ce modèle a été entraîné à 10⁻⁴ g et 1 g uniquement.")
        for key, (lo, hi) in domain["ranges"].items():
            if not lo <= getattr(config, key) <= hi:
                raise ValueError(f"{key} hors du domaine appris [{lo}, {hi}].")

    def encoded(self, inputs):
        if self.metadata["kind"] == "spatial_mlp":
            import torch
            with torch.inference_mode():
                return self.predictor(torch.from_numpy(inputs)).numpy()
        scalar = self.predictor.predict(inputs)
        return np.column_stack([np.zeros((len(inputs), POINTS*6), dtype=np.float32), scalar])

    def predict(self, scene, config):
        started = time.perf_counter()
        self.validate(config, scene)
        cfg = config.physical_config()
        manifest = geometry(scene, cfg)
        times = np.linspace(0, config.duration_s, int(config.duration_s)+1)
        encoded = self.encoded(features(scene, cfg, manifest, times))
        apply_initial_thermodynamics(encoded, times)
        field_values, metric_values = decode_outputs(encoded, cfg)
        valid = manifest["sampling"]["valid_mask"]
        positions = manifest["sampling"]["positions_m"]
        frames, metrics = [], []
        spatial = self.metadata["kind"] == "spatial_mlp"
        for index, t in enumerate(times):
            row = {"time_s": float(t), **dict(zip(METRICS, map(float, metric_values[index]))), "sensors": {}}
            if spatial:
                field = field_values[index]
                for sensor in scene["sensors"]:
                    distances = np.linalg.norm(np.array(positions) - np.array(sensor["position_m"]), axis=1)
                    distances[~np.array(valid)] = np.inf
                    point = int(distances.argmin())
                    row["sensors"][sensor["id"]] = {"temperature_c": float(field[point, 0]),
                        "oxygen_percent": float(field[point, 1]), "smoke_kg_m3": float(field[point, 2]),
                        "spatial_method": "nearest predicted display sample"}
                frames.append({"time_s": float(t), "shape": list(SHAPE), "bounds_m": scene["bounds_m"],
                               "valid_mask": valid, "sample_positions_m": positions,
                               "temperature_c": [float(field[i, 0]) if ok else None for i, ok in enumerate(valid)],
                               "oxygen_percent": [float(field[i, 1]) if ok else None for i, ok in enumerate(valid)],
                               "smoke_kg_m3": [float(field[i, 2]) if ok else None for i, ok in enumerate(valid)],
                               "velocity_m_s": [float(field[i, c]) if ok else None for i, ok in enumerate(valid) for c in (3, 4, 5)]})
            metrics.append(row)
        warnings = ["Prédiction apprise sur des simulations FDS exploratoires, sans validation de la combustion réelle en microgravité.",
                    "Le maillage de référence de 0,20 m n’est pas démontré convergé ; les 320 points affichés sont des observations clairsemées.",
                    "L’erreur sur familles réservées mesure l’émulation du simulateur, pas l’exactitude physique dans un véhicule réel.",
                    "La graine aléatoire n’est pas une entrée du réseau : la prédiction ne reproduit pas chaque fluctuation turbulente d’un run FDS."]
        if spatial:
            warnings.append("Prévisualisation exploratoire : le réseau ne contraint pas la cohérence entre température moyenne, maximum et valeurs du champ.")
        else:
            warnings.append("Ce modèle tabulaire prédit uniquement les métriques ; aucun champ 3D n’est produit.")
        if scene["id"] in self.metadata.get("geometry_holdout", []):
            warnings.append("Cette géométrie a été réservée au test ; consulter les erreurs de généralisation publiées.")
        for key, (lo, hi) in self.metadata.get("observed_training_ranges", {}).items():
            if not lo <= getattr(config, key) <= hi:
                warnings.append(f"{key} reste dans le plan d’expériences mais sort du support observé à l’entraînement [{lo:g}, {hi:g}].")
        return {"provenance": {"engine": "IGNIS learned surrogate", "engine_version": "2", "origin": "prediction",
                    "model_id": self.metadata["id"], "source_model": "prescribed_source",
                    "scientific_status": "learned_from_exploratory_fds", "warnings": warnings,
                    "training_dataset_id": self.metadata["dataset_id"], "weights_sha256": self.metadata["weights_sha256"],
                    "inference_seconds": round(time.perf_counter()-started, 4),
                    "initial_condition": "ambient thermodynamics at t=0; velocity perturbations learned",
                    "postprocessing": "physical range clipping", "seed_conditioned": False,
                    "validation_errors": self.metadata["metrics"], "solver_mesh": manifest["mesh"]},
                "frames": frames, "metrics": metrics,
                "summary": {"duration_s": config.duration_s,
                            "temperature_peak_c": max(m["temperature_max_c"] for m in metrics),
                            "heat_release_peak_w": max(m["heat_release_w"] for m in metrics)}}
