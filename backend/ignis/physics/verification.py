"""Small cases intended to be executed with the actual Windows FDS binary."""

from copy import deepcopy


def verification_scene() -> dict:
    return {
        "id": "verification-box",
        "name": "2 m physical verification enclosure",
        "bounds_m": [2.0, 2.0, 2.0],
        "source_position_m": [1.0, 1.0, 0.4],
        "objects": [
            {
                "id": "sample",
                "role": "fuel",
                "material_id": "cellulose",
                "center_m": [1.0, 1.0, 0.2],
                "size_m": [0.4, 0.4, 0.4],
            },
        ],
        "vents": [
            {
                "id": "inlet",
                "role": "inlet",
                "center_m": [0.0, 1.0, 1.0],
                "size_m": [0.0, 0.4, 0.4],
                "normal": [1, 0, 0],
            },
            {
                "id": "outlet",
                "role": "outlet",
                "center_m": [2.0, 1.0, 1.0],
                "size_m": [0.0, 0.4, 0.4],
                "normal": [-1, 0, 0],
            },
        ],
        "sensors": [
            {"id": "near-source", "position_m": [1.0, 1.0, 0.7]},
            {"id": "downstream", "position_m": [1.7, 1.0, 1.0]},
        ],
    }


def verification_cases() -> dict[str, tuple[dict, dict]]:
    base = {
        "mesh_cell_m": 0.2,
        "sample_shape": [4, 4, 4],
        "duration_s": 5,
        "sample_interval_s": 0.5,
        "airflow_m_s": 0.2,
        "gravity_g": 0,
        "ignition_power_w": 0,
        "ignition_duration_s": 3,
    }
    return {
        "cold": (verification_scene(), deepcopy(base)),
        "transport": (verification_scene(), {**base, "ignition_power_w": 1000}),
        "coupled": (
            verification_scene(),
            {
                **base,
                "source_model": "coupled_combustion",
                "material_id": "pmma",
                "ignition_power_w": 8000,
                "ignition_duration_s": 60,
                "duration_s": 90,
                "sample_interval_s": 1,
                "gravity_g": 1,
            },
        ),
    }


def assess_verification(result: dict, manifest: dict, case: str) -> dict:
    """Transparent numerical smoke checks, not experimental validation criteria."""
    if case not in {"cold", "transport", "coupled"}:
        raise ValueError("Unknown verification case")
    metrics = result["metrics"]
    checks = []

    def add(name: str, observed: float | None, criterion: str, passed: bool) -> None:
        checks.append({"name": name, "observed": observed, "criterion": criterion, "passed": bool(passed)})

    add(
        "duration_s",
        metrics[-1]["time_s"],
        "reaches requested duration",
        metrics[-1]["time_s"] >= manifest["config"]["duration_s"] - 0.001,
    )
    add(
        "nonfinite_spatial_values",
        result["summary"]["nonfinite_spatial_measurements"],
        "equals 0",
        result["summary"]["nonfinite_spatial_measurements"] == 0,
    )
    expected_flows = {v["id"]: v["volume_flow_m3_s"] for v in manifest["vents"]}
    for identifier, expected in expected_flows.items():
        measured = metrics[-1]["vent_volume_flows_m3_s"].get(identifier)
        add(
            f"vent_{identifier}_m3_s",
            measured,
            f"{expected:.9g} ± max(1e-5, 1% of requested flow)",
            measured is not None and abs(measured - expected) <= max(1e-5, abs(expected) * 0.01),
        )
    if case == "cold":
        ambient = manifest["config"]["ambient_temperature_c"]
        temperature_error = max(abs(m["temperature_max_c"] - ambient) for m in metrics)
        oxygen_error = max(
            abs(m["oxygen_mean_percent"] - manifest["config"]["oxygen_percent"]) for m in metrics
        )
        add("temperature_max_error_c", temperature_error, "<= 0.05 °C", temperature_error <= 0.05)
        add(
            "oxygen_error_percentage_points", oxygen_error, "<= 0.005 percentage point", oxygen_error <= 0.005
        )
        add(
            "peak_hrr_w",
            result["summary"]["heat_release_peak_w"],
            "absolute value <= 0.01 W",
            abs(result["summary"]["heat_release_peak_w"]) <= 0.01,
        )
    else:
        hrr_threshold = 100 if case == "coupled" else 1
        add(
            "peak_hrr_w",
            result["summary"]["heat_release_peak_w"],
            f"> {hrr_threshold} W (resolved combustion response)",
            result["summary"]["heat_release_peak_w"] > hrr_threshold,
        )
        add(
            "temperature_peak_c",
            result["summary"]["temperature_peak_c"],
            "> initial temperature + 0.1 °C",
            result["summary"]["temperature_peak_c"] > manifest["config"]["ambient_temperature_c"] + 0.1,
        )
        add(
            "smoke_peak_kg_m3",
            result["summary"]["smoke_peak_mean_kg_m3"],
            "> 0 kg/m³",
            result["summary"]["smoke_peak_mean_kg_m3"] > 0,
        )
        if case == "coupled":
            measured_fluxes = [
                surface["fuel_mass_flux_kg_m2_s"]
                for metric in metrics
                for surface in metric.get("fuel_surfaces", {}).values()
                if surface["fuel_mass_flux_kg_m2_s"] is not None
            ]
            peak_flux = max(measured_fluxes, default=None)
            add(
                "measured_fuel_mass_flux_kg_m2_s",
                peak_flux,
                "> 1e-6 kg/(m² s) from actual surface device",
                peak_flux is not None and peak_flux > 1e-6,
            )
    return {
        "case": case,
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "scope": "software/solver integration smoke check; no NASA calibration or grid convergence assertion",
    }
