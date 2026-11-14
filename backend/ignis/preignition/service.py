from __future__ import annotations

import functools
import hashlib
import json
import threading
import uuid

from ..engine import write_json
from ..locking import ProcessLock
from .evidence import ranked_findings
from .learning import IGNITION_MODEL_ID, THERMAL_MODEL_ID, IgnitionDelayModel, ThermalHistoryModel
from .schema import PreventionConfig


def components_for_scenes(scenes):
    components = []
    for scene in scenes:
        bounds = scene["bounds_m"]
        positions = [(.36, .18, .5), (.80, .43, .62), (.27, .78, .3), (.70, .78, .25)]
        for index, (label, kind, material, factor) in enumerate([
            ("Fil témoin · tableau de bord", "wire", "nichrome_ldpe_guo2023", 1.0),
            ("Fil témoin · panneau latéral", "wire", "nichrome_ldpe_guo2023", 1.5),
            ("Faisceau cuivre · isolant non identifié", "wire", "uncharacterized_copper_wire", .75),
            ("Batterie · mécanisme non couvert", "battery", "uncharacterized_battery", 0),
        ]):
            components.append({"id": f"{scene['id']}-c{index+1:02d}", "scene_id": scene["id"],
                "name": label, "kind": kind, "material_id": material,
                "position_m": [round(p*b, 5) for p, b in zip(positions[index], bounds)],
                "object_id": "soyuz_console" if scene["id"] == "soyuz" and index == 0 else None,
                "current_factor": factor, "supported": index < 2,
                "provenance": "Emplacement d’étude hypothétique ; les fils témoins NiCr/LDPE sont des échantillons de laboratoire, pas des équipements qualifiés de ce véhicule.",
                "limitations": ["Écoulement local imposé comme hypothèse ; aucun champ CFD de cabine n’est inféré de la position du marqueur."]})
    return components


@functools.lru_cache(maxsize=24)
def thermal_scenario(encoded: str):
    from .thermal import simulate_thermal

    return simulate_thermal(json.loads(encoded))


class PreventionService:
    def __init__(self, settings, scenes):
        self.settings = settings
        self.components = components_for_scenes(scenes)
        self.scene_ids = [s["id"] for s in scenes]
        self.directory = settings.runtime / "prevention"
        (self.directory / "analyses").mkdir(parents=True, exist_ok=True)
        self.ignition_model = None
        self.thermal_model = None
        self.model_errors = []
        self.slot = threading.BoundedSemaphore(1)

    def load(self):
        for name, model_type, attr in [(IGNITION_MODEL_ID, IgnitionDelayModel, "ignition_model"),
                                       (THERMAL_MODEL_ID, ThermalHistoryModel, "thermal_model")]:
            directory = self.directory / "models" / name
            if not directory.exists():
                continue
            try:
                setattr(self, attr, model_type(directory))
            except (ValueError, OSError, KeyError, ImportError):
                self.model_errors.append(f"Le modèle {name} ne peut pas être chargé ou vérifié.")

    def catalog(self):
        defaults = PreventionConfig().model_dump(mode="json")
        parameters = {
            "current_a": ("Courant de référence", "A", 0, 20, .1),
            "airflow_m_s": ("Vitesse locale supposée", "m/s", 0, .5, .01),
            "gravity_g": ("Gravité", "g", 0, 1, .00001),
            "ambient_temperature_c": ("Température ambiante", "°C", 0, 50, 1),
            "oxygen_percent": ("Oxygène", "% vol", 15, 30, .1),
            "pressure_pa": ("Pression", "Pa", 60000, 120000, 100),
            "duration_s": ("Durée du scénario", "s", 2, 60, .5),
            "observation_cutoff_s": ("Instant observé", "s", 0, 59, .1),
            "horizon_s": ("Horizon", "s", .1, 20, .1),
            "cutoff_s": ("Coupure programmée", "s", .1, 60, .1),
        }
        return {"version": "ignis-prevention-1", "scene_ids": self.scene_ids,
                "default_scene_id": "soyuz", "components": self.components, "defaults": defaults,
                "parameters": {k: dict(zip(["label", "unit", "min", "max", "step"], v)) for k, v in parameters.items()},
                "models": [m.metadata for m in [self.ignition_model, self.thermal_model] if m],
                "limitations": ["Délai conditionnel à un protocole de laboratoire ; aucune probabilité d’incendie de mission.",
                                 "Les historiques thermiques sont simulés. Aucun capteur réel n’est connecté.",
                                 "Les positions et équipements sont des hypothèses d’étude, sans qualification du Soyouz réel.",
                                 *self.model_errors]}

    def evidence(self, component_id=None, **conditions):
        material = "nichrome_ldpe_guo2023"
        if component_id:
            component = next((c for c in self.components if c["id"] == component_id), None)
            if component is None:
                raise ValueError("Composant inconnu.")
            material = component["material_id"]
        return ranked_findings(self.settings.root, material=material, **conditions)

    @staticmethod
    def thermal_config(config, current):
        return {"material_preset": "nichrome_ldpe_guo2023", "current_a": current,
                "duration_s": config["duration_s"], "sample_interval_s": .1, "max_step_s": .02,
                "cutoff_s": config["cutoff_s"], "ambient_temperature_k": config["ambient_temperature_c"]+273.15,
                "radiant_temperature_k": config["ambient_temperature_c"]+273.15,
                "support_temperature_k": config["ambient_temperature_c"]+273.15,
                "airflow_m_s": config["airflow_m_s"], "gravity_g": config["gravity_g"],
                "oxygen_percent": config["oxygen_percent"], "pressure_pa": config["pressure_pa"]}

    def assess_component(self, component, config):
        current = config["current_a"] * component["current_factor"]
        result = {"component_id": component["id"], "status": "unsupported", "reasons": [],
                  "current_a": current, "observations": [], "forecast": [], "learned_forecast": [],
                  "estimate": None, "interval": None, "ignition_probability": None,
                  "thermal": None, "evidence_ids": []}
        evidence = self.evidence(component["id"], gravity_g=config["gravity_g"],
                                 airflow_m_s=config["airflow_m_s"], oxygen_percent=config["oxygen_percent"],
                                 pressure_pa=config["pressure_pa"])
        result["evidence_ids"] = [f["id"] for f in evidence["findings"][:6]]
        if not component["supported"]:
            result["reasons"] = ["Matériau ou mécanisme non caractérisé : aucune estimation n’est fabriquée."]
            return result
        if self.ignition_model:
            reasons = self.ignition_model.reasons(config, current, component["material_id"])
            if reasons:
                result.update(status="out_of_domain", reasons=reasons)
            else:
                delay = self.ignition_model.delay(current)
                remaining = delay-config["observation_cutoff_s"]
                result.update(status="available", estimate={
                    "ignition_delay_s": delay, "remaining_time_s": remaining,
                    "within_horizon": 0 < remaining <= config["horizon_s"],
                    "phase": "before_estimated_ignition" if remaining > 0 else "estimated_ignition_reached",
                    "model_id": IGNITION_MODEL_ID,
                    "domain": "Fil NiCr/LDPE 70 mm, air initialement calme, courant constant, microgravité groupée.",
                    "conditional_on": "Cas publiés ayant allumé ; courant maintenu et contexte nominal de l’étude. Pas de fréquence réelle de panne.",
                })
                result["reasons"] = ["Délai appris sur des points expérimentaux publiés, avec groupes de courant réservés au test.",
                                     "L’effet propre de la gravité n’est pas appris ; les installations sont regroupées.",
                                     "Incertitude non quantifiée ; un délai au-delà de l’horizon ne signifie pas absence de danger."]
                result["evidence_ids"].insert(0, "GUO-2023")
        else:
            result.update(status="model_unavailable", reasons=["Les poids du modèle de délai ne sont pas disponibles."])
        try:
            trace = thermal_scenario(json.dumps(self.thermal_config(config, current), sort_keys=True))
            points = []
            for p in trace["samples"]:
                # Mass fraction is diagnostic of the physics, never an ignition label.
                mass = trace.get("summary", {}).get("initial_insulation_mass_kg")
                fraction = p.get("pyrolyzed_fraction", p["pyrolyzed_mass_kg"]/mass if mass else 0)
                points.append({"time_s": p["time_s"], "current_a": p["current_a"],
                    "conductor_temperature_c": p["conductor_temperature_k"]-273.15,
                    "surface_temperature_c": p["surface_temperature_k"]-273.15,
                    "pyrolyzed_fraction": fraction})
            observed = [p for p in points if p["time_s"] <= config["observation_cutoff_s"]+1e-9]
            forecast = [p for p in points if p["time_s"] > config["observation_cutoff_s"]+1e-9]
            result.update(observations=observed, forecast=forecast)
            thermal = {"status": "exploratory_local_model", "ignition_supported": False,
                       "summary": trace["summary"], "model_id": None,
                       "limitations": [*trace.get("limitations", []),
                           "La couverture temporelle de la prévision apprise est bornée par la projection physique ; sa durée de validité n’est pas prédite par le ML."]}
            result["thermal"] = thermal
            if self.thermal_model and len(observed) >= 2:
                target_times = [p["time_s"] for p in forecast
                                if p["time_s"] <= config["observation_cutoff_s"]+config["horizon_s"]+1e-9
                                and .1-1e-8 <= p["time_s"]-observed[-1]["time_s"] <= 20]
                try:
                    result["learned_forecast"] = self.thermal_model.predict(observed, config, target_times, current)
                    if result["learned_forecast"]:
                        thermal["model_id"] = THERMAL_MODEL_ID
                except ValueError as exc:
                    thermal["limitations"].append(str(exc))
            elif not self.thermal_model:
                thermal["limitations"].append("Le modèle appris de température n’est pas chargé.")
            else:
                thermal["limitations"].append("Au moins deux instants observés sont nécessaires à la prévision apprise.")
        except (ValueError, RuntimeError) as exc:
            result["thermal"] = {"status": "out_of_domain", "ignition_supported": False,
                                  "summary": {}, "model_id": None, "limitations": [str(exc)]}
        return result

    def analyze(self, spec: PreventionConfig):
        if spec.scene_id not in self.scene_ids:
            raise ValueError("Scène inconnue.")
        if not self.slot.acquire(blocking=False):
            raise RuntimeError("Une analyse de prévention est déjà en cours.")
        try:
            with ProcessLock(self.settings.runtime / "compute.lock"):
                files = list((self.directory / "analyses").glob("*.json"))
                if len(files) >= self.settings.max_runs:
                    raise RuntimeError("Quota d’analyses atteint ; archiver les résultats avant de continuer.")
                config = spec.model_dump(mode="json")
                assessments = [self.assess_component(c, config) for c in self.components if c["scene_id"] == spec.scene_id]
                evidence_snapshot = self.evidence(gravity_g=config["gravity_g"],
                    oxygen_percent=config["oxygen_percent"], airflow_m_s=config["airflow_m_s"],
                    pressure_pa=config["pressure_pa"])
                component_evidence = {c["component_id"]: self.evidence(c["component_id"],
                    gravity_g=config["gravity_g"], oxygen_percent=config["oxygen_percent"],
                    airflow_m_s=config["airflow_m_s"], pressure_pa=config["pressure_pa"]) for c in assessments}
                snapshot_hash = hashlib.sha256(json.dumps(evidence_snapshot, sort_keys=True,
                                                         ensure_ascii=False).encode()).hexdigest()
                identifier = uuid.uuid4().hex
                result = {"id": identifier, "config": config, "observation_cutoff_s": spec.observation_cutoff_s,
                          "horizon_s": spec.horizon_s, "origin": "simulation_and_published_experiments",
                          "target": {"event_kind": "ignition", "name": "Délai d’allumage sous protocole expérimental",
                                     "unit": "s", "criterion": "Premier allumage observé des fils NiCr/LDPE publiés ; distinct de la fusion ou pyrolyse calculée."},
                          "components": assessments,
                          "evidence_snapshot": evidence_snapshot,
                          "evidence_snapshots_by_component": component_evidence,
                          "provenance": {"version": "ignis-prevention-1", "observation_origin": "synthetic_local_thermal_model",
                                         "evidence_snapshot_sha256": snapshot_hash,
                                         "component_evidence_sha256": hashlib.sha256(json.dumps(component_evidence,
                                             sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                                         "ignition_origin": "GUO-2023, experimental Figure 5 (not NASA labels)",
                                         "source_pdf_sha256": self.ignition_model.metadata["source_sha256"] if self.ignition_model else None,
                                         "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
                                         "learned_models": [m.metadata for m in [self.ignition_model, self.thermal_model] if m],
                                         "coupling": "Prescribed local airflow; no CFD-to-wire field coupling or spacecraft qualification"},
                          "limitations": ["Cette analyse ne calcule pas une probabilité d’incendie réelle.",
                                           "Le délai expérimental et la thermique locale sont deux modèles distincts ; le second ne simule pas l’allumage gazeux.",
                                           "La projection thermique est arrêtée à sa limite de validité ; les points manquants ne sont pas prolongés.",
                                           "Les températures observées dans ce rejeu sont simulées, sans instrumentation réelle.",
                                           "Un instant d’allumage estimé dépassé n’est pas une flamme détectée."],
                          "export_url": f"/api/prevention/analyses/{identifier}/export"}
                write_json(self.directory / "analyses" / f"{identifier}.json", result)
                return result
        finally:
            self.slot.release()

    def get(self, identifier):
        if len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
            raise ValueError("Analyse inconnue.")
        path = self.directory / "analyses" / f"{identifier}.json"
        if not path.is_file():
            raise ValueError("Analyse inconnue.")
        return json.loads(path.read_text(encoding="utf-8"))
