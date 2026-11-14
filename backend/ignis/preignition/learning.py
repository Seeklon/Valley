"""Models have separate domains, labels and provenance. No synthetic fire probability."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

IGNITION_MODEL_ID = "ignition-delay-guo-v1"
THERMAL_MODEL_ID = "thermal-history-forest-v1"


def read_verified(directory: Path, name: str, expected: str) -> bytes:
    blob = (directory / name).read_bytes()
    if hashlib.sha256(blob).hexdigest() != expected:
        raise ValueError("L’empreinte des paramètres appris est incorrecte.")
    return blob


class IgnitionDelayModel:
    def __init__(self, directory: Path):
        self.metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        if self.metadata.get("id") != IGNITION_MODEL_ID:
            raise ValueError("Modèle de délai inconnu.")
        self.parameters = json.loads(read_verified(directory, "parameters.json", self.metadata["parameters_sha256"]))

    def reasons(self, config: dict, current_a: float, material: str) -> list[str]:
        reasons = []
        if material != "nichrome_ldpe_guo2023":
            reasons.append("Le modèle ne couvre que le fil de laboratoire NiCr/LDPE de Guo et al.")
        low, high = self.metadata["domain"]["current_a"]
        if not low <= current_a <= high:
            reasons.append(f"Courant hors de la plage expérimentale publiée [{low:g}, {high:g}] A.")
        if not 0.00001 <= config["gravity_g"] <= .03:
            reasons.append("La gravité sort de la plage des trois installations de microgravité publiées.")
        if abs(config["airflow_m_s"]) > 1e-9:
            reasons.append("L’effet d’une ventilation forcée sur l’allumage n’est pas appris par ce modèle.")
        for key, nominal, label in [("ambient_temperature_c", 20, "température ambiante"),
                                     ("oxygen_percent", 21, "oxygène"), ("pressure_pa", 101325, "pression")]:
            if abs(config[key]-nominal) > 1e-6:
                reasons.append(f"La {label} diffère du contexte nominal associé à la publication.")
        if config["cutoff_s"] is not None:
            reasons.append("Une coupure modifie le protocole à courant constant maintenu ; délai hors domaine.")
        return reasons

    def delay(self, current_a: float) -> float:
        low, high = self.metadata["domain"]["current_a"]
        if not np.isfinite(current_a) or not low <= current_a <= high:
            raise ValueError("Courant hors domaine.")
        x = np.log(current_a)
        z = self.parameters["intercept"] + sum(c*x**(i+1) for i, c in enumerate(self.parameters["coefficients"]))
        delay = float(np.exp(z))
        if not np.isfinite(delay) or delay <= 0:
            raise ValueError("Délai prédit invalide.")
        return delay


THERMAL_FEATURES = ["elapsed_s", "surface_temperature_c", "surface_lag_025_c",
                    "surface_lag_1_c", "current_a", "future_current_a", "horizon_s",
                    "scheduled_on_time_s", "airflow_m_s", "gravity_g", "ambient_temperature_c"]


def thermal_features(observations: list[dict], config: dict, target_time: float, current_a: float):
    """The caller supplies only history. No future samples, stop/event time or hidden state."""
    if not observations:
        raise ValueError("Historique thermique absent.")
    times = np.asarray([p["time_s"] for p in observations], dtype=float)
    temps = np.asarray([p["surface_temperature_c"] for p in observations], dtype=float)
    if not np.isfinite(times).all() or not np.isfinite(temps).all() or np.any(np.diff(times) <= 0):
        raise ValueError("Historique non fini ou non ordonné.")
    t = float(times[-1])
    horizon = target_time-t
    if not 0 < horizon <= 20.001:
        raise ValueError("Horizon de température hors domaine.")
    last_current = observations[-1]["current_a"]
    cutoff = config["cutoff_s"]
    # A scheduled intervention is known input; an event inferred after the fact is not.
    on_time = horizon if cutoff is None else min(horizon, max(0, cutoff-t))
    future_current = current_a if on_time > 0 else 0
    return np.asarray([t, temps[-1], np.interp(max(0, t-.25), times, temps),
                       np.interp(max(0, t-1), times, temps), last_current, future_current,
                       horizon, on_time, config["airflow_m_s"], config["gravity_g"],
                       config["ambient_temperature_c"]], dtype=float)


class ThermalHistoryModel:
    def __init__(self, directory: Path):
        import joblib

        self.metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        if self.metadata.get("id") != THERMAL_MODEL_ID:
            raise ValueError("Modèle thermique inconnu.")
        read_verified(directory, "weights.joblib", self.metadata["weights_sha256"])
        # Only application-owned, hash-verified local artifacts; no user-uploaded pickles.
        self.model = joblib.load(directory / "weights.joblib")

    def predict(self, history, config, target_times, current_a):
        if not target_times:
            return []
        if not history:
            raise ValueError("Historique thermique absent.")
        for key, value in (("current_a", current_a), ("airflow_m_s", config["airflow_m_s"]),
                           ("ambient_temperature_c", config["ambient_temperature_c"]),
                           ("elapsed_s", history[-1]["time_s"])):
            lo, hi = self.metadata["domain"][key]
            if not lo <= value <= hi:
                raise ValueError("Prévision thermique hors domaine : " + key)
        if config["gravity_g"] not in self.metadata["domain"]["gravity_g"]:
            raise ValueError("Gravité non couverte par l’apprentissage thermique.")
        if abs(config["pressure_pa"]-self.metadata["domain"]["pressure_pa"]) > 1e-6:
            raise ValueError("Pression non couverte par l’apprentissage thermique.")
        lo, hi = self.metadata["domain"]["horizon_s"]
        if any(not lo-1e-8 <= t-history[-1]["time_s"] <= hi+1e-8 for t in target_times):
            raise ValueError("Horizon non couvert par l’apprentissage thermique.")
        x = np.stack([thermal_features(history, config, t, current_a) for t in target_times])
        y = self.model.predict(x)
        if not np.isfinite(y).all():
            raise ValueError("Prévision thermique non finie.")
        return [{"time_s": float(t), "surface_temperature_c": float(v)} for t, v in zip(target_times, y)]
