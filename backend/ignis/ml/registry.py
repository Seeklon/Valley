from __future__ import annotations

import json
import threading
from pathlib import Path


class ModelRegistry:
    def __init__(self, directory: Path):
        self.directory = directory
        self.models = {}
        self.errors = []
        self.lock = threading.Lock()

    def load(self):
        for path in sorted(self.directory.glob("*/metadata.json")):
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
                if meta.get("id") == "incident-field-v1":
                    continue  # Loaded by IncidentService with its geometry-aware contract.
                from .surrogate import Surrogate
                model = Surrogate.load(path.parent)
                self.models[meta["id"]] = {"meta": meta, "predictor": model}
            except Exception as exc:
                self.errors.append({"id": path.parent.name, "status": "failed", "loaded": False,
                                    "message": str(exc)})

    def list(self) -> list[dict]:
        return [{**entry["meta"], "status": "ready", "loaded": True} for entry in self.models.values()] + self.errors

    def select(self, config, scene=None):
        selected = config.model_id or next(iter(self.models), None)
        if selected not in self.models:
            raise ValueError("Aucun modèle entraîné n’est chargé pour cette demande.")
        model = self.models[selected]["predictor"]
        model.validate(config, scene)
        return model

    def predict(self, scene: dict, config):
        with self.lock:
            return self.select(config, scene).predict(scene, config)
