"""Numerical verification, deliberately not an experimental validation claim."""

import copy
import math

import pytest
from ignis.preignition.materials import NICHROME_LDPE_GUO2023 as MATERIAL
from ignis.preignition.thermal import simulate_thermal
from ignis.preignition.validation import audit_energy_balance, normalize_thermal_config


def closed_system(**changes):
    return {
        "duration_s": 2.0,
        "sample_interval_s": 0.05,
        "max_step_s": 0.02,
        "heat_transfer_mode": "adiabatic",
        "radiation_enabled": False,
        "pyrolysis_enabled": False,
        **changes,
    }


def test_unpowered_equilibrium_and_copied_configuration():
    config = {"current_a": 0.0, "duration_s": 1.0, "sample_interval_s": 0.1}
    original = copy.deepcopy(config)
    result = simulate_thermal(config)
    assert config == original
    assert result["summary"]["status"] == "completed"
    for sample in result["samples"]:
        assert sample["conductor_temperature_k"] == pytest.approx(293.15, abs=1e-10)
        assert sample["surface_temperature_k"] == pytest.approx(293.15, abs=1e-10)
        assert sample["input_energy_j"] == 0.0
        assert sample["pyrolyzed_mass_kg"] == 0.0
    assert result["summary"]["ignition_supported"] is False
    assert result["summary"]["ignition_time_s"] is None
    assert result["summary"]["ignition_probability"] is None


def analytical_two_node_temperatures(time_s, current_a):
    # Independently assemble the closed-form solution below fusion. The heat
    # capacity-weighted mean heats linearly; the node difference relaxes
    # exponentially. This verifies the actual thermal solution, not just its
    # accounting columns.
    length, radius, outer = 0.07, 0.00025, 0.0004
    conductor_capacity = 8410.0 * math.pi * radius**2 * length * 481.0
    insulation_capacity = 920.0 * math.pi * (outer**2 - radius**2) * length * 2300.0
    conductance = 2 * math.pi * 0.34 * length / math.log(outer / radius)
    resistance = 1.1e-6 * length / (math.pi * radius**2)
    power = current_a**2 * resistance
    capacity = conductor_capacity + insulation_capacity
    decay = conductance * (1 / conductor_capacity + 1 / insulation_capacity)
    difference = power * insulation_capacity / (conductance * capacity) * (1 - math.exp(-decay * time_s))
    mean = 293.15 + power * time_s / capacity
    return (
        mean + insulation_capacity / capacity * difference,
        mean - conductor_capacity / capacity * difference,
    )


def test_closed_form_two_node_heating_and_exact_total_energy():
    result = simulate_thermal(closed_system(current_a=0.5))
    for sample in result["samples"]:
        expected_core, expected_insulation = analytical_two_node_temperatures(sample["time_s"], 0.5)
        assert sample["conductor_temperature_k"] == pytest.approx(expected_core, abs=3e-6)
        assert sample["surface_temperature_k"] == pytest.approx(expected_insulation, abs=3e-6)
        expected_energy = 0.5**2 * (1.1e-6 * 0.07 / (math.pi * 0.00025**2)) * sample["time_s"]
        assert sample["stored_energy_j"] == pytest.approx(expected_energy, abs=1e-9)


def test_piecewise_current_integral_and_off_grid_cutoff():
    config = closed_system(
        duration_s=4.0,
        sample_interval_s=0.17,
        current_profile=[
            {"time_s": 0.0, "current_a": 1.0},
            {"time_s": 1.0, "current_a": -2.0},
            {"time_s": 3.0, "current_a": 3.0},
        ],
        cutoff_s=2.35,
    )
    result = simulate_thermal(config)
    resistance = result["summary"]["reference_resistance_ohm"]
    expected_input = resistance * (1.0 + 4.0 * 1.35)
    assert result["samples"][-1]["input_energy_j"] == pytest.approx(expected_input, abs=1e-8)
    after = [sample for sample in result["samples"] if sample["time_s"] >= 2.35]
    assert after[0]["time_s"] == 2.35
    assert all(sample["current_a"] == 0.0 for sample in after)
    assert all(sample["input_energy_j"] == pytest.approx(expected_input, abs=1e-8) for sample in after)
    assert result["summary"]["observed_duration_s"] == 4.0


def test_surface_keeps_heating_after_short_electrical_cutoff():
    result = simulate_thermal(
        closed_system(
            current_a=18.0,
            cutoff_s=0.01,
            duration_s=0.5,
            sample_interval_s=0.005,
            max_step_s=0.002,
        )
    )
    after = [sample for sample in result["samples"] if sample["time_s"] >= 0.01]
    assert after[-1]["surface_temperature_k"] > after[0]["surface_temperature_k"] + 5.0
    assert after[-1]["conductor_temperature_k"] < after[0]["conductor_temperature_k"]
    assert result["summary"]["ignition_supported"] is False
    assert all(event["ignition_event"] is False for event in result["events"])


def test_fusion_stores_latent_heat_at_constant_temperature():
    result = simulate_thermal(
        closed_system(
            current_a=5.0,
            duration_s=2.0,
            sample_interval_s=0.005,
            surface_limit_k=391.15,
            surface_limit_source="Test of the sourced LDPE melting temperature; not ignition",
        )
    )
    plateau = [sample for sample in result["samples"] if 0.01 < sample["melt_fraction"] < 0.99]
    assert len(plateau) >= 5
    assert all(sample["surface_temperature_k"] == 391.15 for sample in plateau)
    assert result["summary"]["melting_complete_time_s"] > result["summary"]["melting_onset_time_s"] > 0
    assert result["summary"]["surface_limit_time_s"] == pytest.approx(
        result["summary"]["melting_onset_time_s"], abs=1e-8
    )
    assert len([event for event in result["events"] if event["type"] == "user_surface_thermal_limit"]) == 1
    first, last = plateau[0], plateau[-1]
    core_capacity = result["summary"]["initial_conductor_mass_kg"] * 481.0
    latent_delta = (
        last["stored_energy_j"]
        - first["stored_energy_j"]
        - core_capacity * (last["conductor_temperature_k"] - first["conductor_temperature_k"])
    )
    expected = (
        result["summary"]["initial_insulation_mass_kg"]
        * 140600.0
        * (last["melt_fraction"] - first["melt_fraction"])
    )
    assert latent_delta == pytest.approx(expected, abs=1e-8)


def test_pyrolysis_stops_at_declared_geometry_limit_with_removed_enthalpy():
    result = simulate_thermal({"current_a": 5.0, "duration_s": 15.0, "sample_interval_s": 0.1})
    summary, final = result["summary"], result["samples"][-1]
    assert summary["termination_reason"] == "fixed_geometry_mass_loss_limit"
    assert summary["observed_duration_s"] < 15.0
    assert final["pyrolyzed_fraction"] == pytest.approx(0.01, abs=1e-8)
    assert summary["mass_loss_reporting_time_s"] < summary["observed_duration_s"]
    assert final["carried_energy_j"] > 0
    assert final["pyrolysis_energy_j"] == pytest.approx(final["pyrolyzed_mass_kg"] * 962000, abs=1e-8)
    assert audit_energy_balance(result["samples"])["passed"]
    # Forgetting advected material enthalpy must fail the independent audit.
    damaged = copy.deepcopy(result["samples"])
    damaged[-1]["carried_energy_j"] = 0.0
    assert not audit_energy_balance(damaged)["passed"]


def test_cooling_balances_convection_radiation_and_support_conduction():
    result = simulate_thermal(
        {
            "current_a": 0.0,
            "duration_s": 2.0,
            "sample_interval_s": 0.1,
            "initial_conductor_temperature_k": 350.0,
            "initial_insulation_temperature_k": 350.0,
            "heat_transfer_mode": "prescribed_h",
            "heat_transfer_coefficient_w_m2_k": 30.0,
            "support_conductance_w_k": 0.02,
        }
    )
    final = result["samples"][-1]
    assert final["conductor_temperature_k"] < 350
    assert final["surface_temperature_k"] < 350
    assert final["convection_energy_j"] > 0
    assert final["radiation_energy_j"] > 0
    assert final["support_energy_j"] > 0
    assert final["stored_energy_j"] == pytest.approx(-final["loss_energy_j"], abs=1e-8)


def test_microgravity_retains_gas_heat_loss_and_forced_flow_can_change_it():
    base = {"current_a": 1.0, "duration_s": 3.0, "sample_interval_s": 0.5}
    micro = simulate_thermal(base)
    terrestrial = simulate_thermal(base | {"gravity_g": 1.0})
    forced = simulate_thermal(base | {"airflow_m_s": 0.2})
    assert micro["samples"][-1]["convection_energy_j"] > 0
    assert terrestrial["samples"][-1]["surface_temperature_k"] < micro["samples"][-1]["surface_temperature_k"]
    assert forced["samples"][-1]["surface_temperature_k"] < micro["samples"][-1]["surface_temperature_k"]
    assert forced["samples"][-1]["heat_transfer_regime"] == "forced_cylinder_crossflow"


def test_intermediate_gravity_and_oxygen_are_not_hidden_chemical_models():
    base = {"current_a": 1.0, "duration_s": 0.5, "sample_interval_s": 0.1}
    reference = simulate_thermal(base)
    changed = simulate_thermal(base | {"gravity_g": 0.03, "oxygen_percent": 30.0})
    assert reference["samples"] == changed["samples"]
    assert any("all other gravity" in item for item in changed["limitations"])
    assert any("Oxygen concentration is context only" in item for item in changed["limitations"])


def test_temperature_dependent_resistance_is_explicit_and_changes_heating():
    config = closed_system(current_a=1.0)
    constant = simulate_thermal(config)
    varying = simulate_thermal(config | {"resistance_temperature_coefficient_per_k": 0.004})
    assert constant["samples"][-1]["resistance_ohm"] == constant["samples"][0]["resistance_ohm"]
    assert varying["samples"][-1]["resistance_ohm"] > varying["samples"][0]["resistance_ohm"]
    assert varying["samples"][-1]["input_energy_j"] > constant["samples"][-1]["input_energy_j"]
    assert "User-supplied" in varying["provenance"]["electrical_temperature_coefficient_origin"]


def test_time_refinement_converges_to_analytical_transient():
    target_time = 0.15
    expected = analytical_two_node_temperatures(target_time, 0.5)
    errors = []
    for maximum_step in (0.1, 0.02, 0.005):
        result = simulate_thermal(
            closed_system(
                current_a=0.5,
                duration_s=target_time,
                sample_interval_s=target_time,
                max_step_s=maximum_step,
                relative_tolerance=1e-3,
            )
        )
        final = result["samples"][-1]
        errors.append(
            max(
                abs(final["conductor_temperature_k"] - expected[0]),
                abs(final["surface_temperature_k"] - expected[1]),
            )
        )
    assert errors[-1] < errors[0] / 100
    assert errors[-1] < 1e-8


def test_phase_event_and_mass_loss_limit_are_stable_under_time_refinement():
    coarse = simulate_thermal({"current_a": 5.0, "duration_s": 15.0, "max_step_s": 0.04})
    fine = simulate_thermal({"current_a": 5.0, "duration_s": 15.0, "max_step_s": 0.01})
    for name in ("melting_onset_time_s", "melting_complete_time_s", "observed_duration_s"):
        assert coarse["summary"][name] == pytest.approx(fine["summary"][name], abs=0.002)
    assert coarse["summary"]["peak_surface_temperature_k"] == pytest.approx(
        fine["summary"]["peak_surface_temperature_k"], abs=0.1
    )


def test_thermal_guard_is_a_scope_limit_and_not_fire():
    result = simulate_thermal(closed_system(current_a=18.0, maximum_temperature_k=450.0))
    assert result["summary"]["termination_reason"] == "maximum_temperature_limit"
    assert result["summary"]["ignition_time_s"] is None
    assert result["summary"]["peak_conductor_temperature_k"] == pytest.approx(450.0, abs=1e-6)


@pytest.mark.parametrize(
    "config",
    [
        {"current_a": float("nan")},
        {"duration_s": 0},
        {"current_profile": [{"time_s": 1.0, "current_a": 1.0}]},
        {"current_profile": [{"time_s": 0.0, "current_a": 1.0}, {"time_s": 0.0, "current_a": 2.0}]},
        {"surface_limit_k": 500.0},
        {"heat_transfer_coefficient_w_m2_k": 30.0},
        {"gas_conduction_radius_m": 0.0001},
        {"material_preset": "spacecraft_cable"},
        {"unknown_ignition_temperature": 600.0},
    ],
)
def test_invalid_or_unsupported_physics_is_rejected(config):
    with pytest.raises(ValueError):
        normalize_thermal_config(config)


def test_material_solidification_releases_the_documented_latent_heat():
    lower = MATERIAL.insulation_enthalpy(390.15)
    upper = MATERIAL.insulation_enthalpy(392.15)
    assert upper - lower == 2300.0 + 140600.0 + 2500.0
    assert MATERIAL.insulation_state(MATERIAL.melting_start_enthalpy_j_kg + 70300) == (391.15, 0.5)
