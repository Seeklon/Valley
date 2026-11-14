"""Input and energy checks for the thermal precursor model.

These checks establish numerical consistency; they do not validate predicted
temperatures against experiments or establish an ignition model.
"""

import math
from collections.abc import Mapping
from numbers import Real

from .materials import get_material

THERMAL_DEFAULTS = {
    "material_preset": "nichrome_ldpe_guo2023",
    "wire_length_m": 0.07,
    "core_radius_m": 0.00025,
    "insulation_thickness_m": 0.00015,
    "current_a": 2.0,
    "current_profile": None,
    "cutoff_s": None,
    "duration_s": 300.0,
    "sample_interval_s": 1.0,
    "max_step_s": 0.05,
    "ambient_temperature_k": 293.15,
    "radiant_temperature_k": None,
    "support_temperature_k": None,
    "initial_conductor_temperature_k": None,
    "initial_insulation_temperature_k": None,
    "initial_melt_fraction": 0.0,
    "airflow_m_s": 0.0,
    "gravity_g": 0.0,
    "pressure_pa": 101325.0,
    "oxygen_percent": 21.0,
    "support_conductance_w_k": 0.0,
    "resistance_temperature_coefficient_per_k": 0.0,
    "heat_transfer_mode": "auto",
    "heat_transfer_coefficient_w_m2_k": None,
    "gas_conduction_radius_m": 0.07,
    "radiation_enabled": True,
    "pyrolysis_enabled": True,
    "maximum_temperature_k": 1200.0,
    "maximum_pyrolyzed_fraction": 0.01,
    "pyrolysis_report_fraction": 0.001,
    "surface_limit_k": None,
    "surface_limit_source": None,
    "relative_tolerance": 1e-6,
}


def _number(name: str, value, lower: float, upper: float, *, strict_lower: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if value > upper or value < lower or (strict_lower and value == lower):
        left = "(" if strict_lower else "["
        raise ValueError(f"{name} must be in {left}{lower}, {upper}]")
    return value


def normalize_thermal_config(config: dict) -> dict:
    """Validate strictly, copying input so that the simulator is a pure function."""
    if not isinstance(config, Mapping):
        raise ValueError("Thermal config must be an object")
    unknown = sorted(set(config) - set(THERMAL_DEFAULTS))
    if unknown:
        raise ValueError(f"Unknown thermal config fields: {', '.join(unknown)}")
    result = THERMAL_DEFAULTS | dict(config)
    get_material(result["material_preset"])
    ranges = {
        "wire_length_m": (0.001, 10.0),
        "core_radius_m": (1e-5, 0.05),
        "insulation_thickness_m": (1e-6, 0.05),
        "current_a": (-100.0, 100.0),
        "duration_s": (0.0, 3600.0),
        "sample_interval_s": (0.0, 3600.0),
        "max_step_s": (1e-5, 1.0),
        "ambient_temperature_k": (150.0, 1000.0),
        "airflow_m_s": (0.0, 30.0),
        "gravity_g": (0.0, 2.0),
        "pressure_pa": (10000.0, 500000.0),
        "oxygen_percent": (0.0, 100.0),
        "support_conductance_w_k": (0.0, 100.0),
        "resistance_temperature_coefficient_per_k": (0.0, 0.01),
        "gas_conduction_radius_m": (1e-5, 100.0),
        "initial_melt_fraction": (0.0, 1.0),
        "maximum_temperature_k": (400.0, 1500.0),
        "maximum_pyrolyzed_fraction": (0.0, 0.1),
        "pyrolysis_report_fraction": (0.0, 0.1),
        "relative_tolerance": (1e-9, 1e-3),
    }
    strictly_positive = {"duration_s", "sample_interval_s", "maximum_pyrolyzed_fraction"}
    for name, (lower, upper) in ranges.items():
        result[name] = _number(name, result[name], lower, upper, strict_lower=name in strictly_positive)
    for name in (
        "radiant_temperature_k",
        "support_temperature_k",
        "initial_conductor_temperature_k",
        "initial_insulation_temperature_k",
    ):
        value = result["ambient_temperature_k"] if result[name] is None else result[name]
        result[name] = _number(name, value, 150.0, 1400.0)
    for name in ("initial_conductor_temperature_k", "initial_insulation_temperature_k"):
        if result[name] >= result["maximum_temperature_k"]:
            raise ValueError(f"{name} must be below maximum_temperature_k")
    if result["initial_melt_fraction"] != 0.0:
        material = get_material(result["material_preset"])
        if result["initial_insulation_temperature_k"] != material.melting_temperature_k:
            raise ValueError("A nonzero initial_melt_fraction requires the melting temperature")
    coldest = min(result[name] for name in result if name.endswith("temperature_k"))
    if 1 + result["resistance_temperature_coefficient_per_k"] * (coldest - 293.15) <= 0:
        raise ValueError("The supplied temperature coefficient permits nonpositive resistance")
    outer_radius = result["core_radius_m"] + result["insulation_thickness_m"]
    if result["gas_conduction_radius_m"] <= outer_radius:
        raise ValueError("gas_conduction_radius_m must exceed the wire outer radius")
    if result["pyrolysis_report_fraction"] >= result["maximum_pyrolyzed_fraction"]:
        raise ValueError("pyrolysis_report_fraction must be smaller than maximum_pyrolyzed_fraction")
    for name in ("radiation_enabled", "pyrolysis_enabled"):
        if not isinstance(result[name], bool):
            raise ValueError(f"{name} must be boolean")
    if result["heat_transfer_mode"] not in {"auto", "prescribed_h", "adiabatic"}:
        raise ValueError("heat_transfer_mode must be auto, prescribed_h or adiabatic")
    if result["heat_transfer_mode"] == "prescribed_h":
        result["heat_transfer_coefficient_w_m2_k"] = _number(
            "heat_transfer_coefficient_w_m2_k", result["heat_transfer_coefficient_w_m2_k"], 0.0, 10000.0
        )
    elif result["heat_transfer_coefficient_w_m2_k"] is not None:
        raise ValueError("A prescribed heat transfer coefficient requires heat_transfer_mode=prescribed_h")
    if result["surface_limit_k"] is not None:
        result["surface_limit_k"] = _number("surface_limit_k", result["surface_limit_k"], 150.0, 1500.0)
        source = result["surface_limit_source"]
        if not isinstance(source, str) or not source.strip() or len(source) > 2000:
            raise ValueError("surface_limit_source must describe the user-defined thermal limit")
    elif result["surface_limit_source"] is not None:
        raise ValueError("surface_limit_source requires surface_limit_k")
    if result["cutoff_s"] is not None:
        result["cutoff_s"] = _number("cutoff_s", result["cutoff_s"], 0.0, result["duration_s"])
    if result["duration_s"] / result["max_step_s"] > 200000:
        raise ValueError("Requested duration/max_step_s exceeds the 200000-step budget")
    if result["duration_s"] / result["sample_interval_s"] > 20000:
        raise ValueError("Requested sampling exceeds 20000 intervals")
    profile = result["current_profile"]
    if profile is None:
        profile = [{"time_s": 0.0, "current_a": result["current_a"]}]
    if not isinstance(profile, list) or not 1 <= len(profile) <= 128:
        raise ValueError("current_profile must contain 1 to 128 time/current objects")
    normalized_profile = []
    previous_time = -1.0
    for entry in profile:
        if not isinstance(entry, Mapping) or set(entry) != {"time_s", "current_a"}:
            raise ValueError("Each current_profile entry needs exactly time_s and current_a")
        time_s = _number("current_profile.time_s", entry["time_s"], 0.0, result["duration_s"])
        current_a = _number("current_profile.current_a", entry["current_a"], -100.0, 100.0)
        if time_s <= previous_time:
            raise ValueError("current_profile times must be strictly increasing")
        normalized_profile.append({"time_s": time_s, "current_a": current_a})
        previous_time = time_s
    if normalized_profile[0]["time_s"] != 0.0:
        raise ValueError("current_profile must start at time_s=0")
    result["current_profile"] = normalized_profile
    return result


def audit_energy_balance(samples: list[dict], absolute_tolerance_j: float = 1e-6) -> dict:
    """Recompute balances from exported columns, independently of the reported residual."""
    if not samples:
        raise ValueError("At least one sample is required")
    residuals = []
    scale = 1.0
    for sample in samples:
        terms = [
            sample["input_energy_j"],
            sample["stored_energy_j"],
            sample["loss_energy_j"],
            sample["pyrolysis_energy_j"],
            sample["carried_energy_j"],
        ]
        if not all(math.isfinite(value) for value in terms):
            raise ValueError("Nonfinite energy in thermal trajectory")
        residuals.append(terms[0] - sum(terms[1:]))
        scale = max(scale, *(abs(value) for value in terms))
    maximum = max(abs(value) for value in residuals)
    return {
        "passed": maximum <= absolute_tolerance_j,
        "maximum_absolute_error_j": maximum,
        "maximum_relative_error": maximum / scale,
        "absolute_tolerance_j": absolute_tolerance_j,
        "experimental_validation": False,
    }
