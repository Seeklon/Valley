"""Two-node, conservative electrothermal precursor model for a NiCr/LDPE wire.

No gas chemistry, flame, electrical arc or probabilistic ignition model is
implemented here. Every temperature returned by this module is simulated.
"""

import math
from bisect import bisect_left
from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp

from .materials import (
    GAS_CONSTANT_J_MOL_K,
    REFERENCE_TEMPERATURE_K,
    STEFAN_BOLTZMANN_W_M2_K4,
    WireMaterial,
    get_material,
)
from .validation import audit_energy_balance, normalize_thermal_config

SCHEMA_VERSION = "ignis.thermal-precursor.v1"


@dataclass
class _Wire:
    config: dict
    material: WireMaterial

    def __post_init__(self):
        c = self.config
        m = self.material
        self.length = c["wire_length_m"]
        self.radius = c["core_radius_m"]
        self.outer_radius = self.radius + c["insulation_thickness_m"]
        self.area = 2 * math.pi * self.outer_radius * self.length
        core_volume = math.pi * self.radius**2 * self.length
        polymer_volume = math.pi * (self.outer_radius**2 - self.radius**2) * self.length
        self.core_mass = core_volume * m.conductor_density_kg_m3
        self.core_capacity = self.core_mass * m.conductor_heat_capacity_j_kg_k
        self.initial_polymer_mass = polymer_volume * m.insulation_density_kg_m3
        self.reference_resistance = m.resistivity_reference_ohm_m * self.length / (math.pi * self.radius**2)
        self.initial = np.zeros(9)
        self.initial[0] = self.core_capacity * (
            c["initial_conductor_temperature_k"] - REFERENCE_TEMPERATURE_K
        )
        self.initial[1] = self.initial_polymer_mass * m.insulation_enthalpy(
            c["initial_insulation_temperature_k"], c["initial_melt_fraction"]
        )
        self.initial[2] = self.initial_polymer_mass
        self.initial_energy = self.initial[0] + self.initial[1]

    def temperatures(self, state) -> tuple[float, float, float]:
        # The floor only regularizes rejected RK trial states outside the mass
        # domain. Accepted integration stops before 10% mass loss at most.
        mass = max(float(state[2]), self.initial_polymer_mass * 1e-8)
        core = REFERENCE_TEMPERATURE_K + float(state[0]) / self.core_capacity
        surface, melted = self.material.insulation_state(float(state[1]) / mass)
        return core, surface, melted

    def heat_transfer(self, surface_k: float) -> tuple[float, str]:
        c = self.config
        if c["heat_transfer_mode"] == "adiabatic":
            return 0.0, "gas_heat_transfer_disabled"
        if c["heat_transfer_mode"] == "prescribed_h":
            return c["heat_transfer_coefficient_w_m2_k"], "user_prescribed_coefficient"

        # Constant transport properties of room-temperature air are engineering
        # approximations, not measurements of this experiment. Density follows
        # the ideal gas law at film temperature. See PREIGNITION_PHYSICS.md.
        conductivity = 0.0257  # W/(m K)
        viscosity = 1.81e-5  # Pa s
        heat_capacity = 1005.0  # J/(kg K)
        film_k = max(1.0, 0.5 * (surface_k + c["ambient_temperature_k"]))
        density = c["pressure_pa"] / (287.05 * film_k)
        prandtl = viscosity * heat_capacity / conductivity
        diameter = 2 * self.outer_radius
        conduction_h = conductivity / (
            self.outer_radius * math.log(c["gas_conduction_radius_m"] / self.outer_radius)
        )
        candidates = [(conduction_h, "finite_radius_stagnant_gas_conduction")]
        reynolds = density * c["airflow_m_s"] * diameter / viscosity
        # Conservative lower bound for Churchill--Bernstein cylinder crossflow.
        if reynolds * prandtl >= 0.4 and reynolds <= 1e7:
            nusselt = 0.3 + (
                0.62
                * reynolds**0.5
                * prandtl ** (1 / 3)
                / (1 + (0.4 / prandtl) ** (2 / 3)) ** 0.25
                * (1 + (reynolds / 282000) ** (5 / 8)) ** (4 / 5)
            )
            candidates.append((nusselt * conductivity / diameter, "forced_cylinder_crossflow"))

        # This prototype reserves the terrestrial natural-convection relation
        # for 1 g. Residual/intermediate gravity is not silently extrapolated.
        if math.isclose(c["gravity_g"], 1.0, abs_tol=1e-9, rel_tol=0.0):
            kinematic_viscosity = viscosity / density
            diffusivity = conductivity / (density * heat_capacity)
            rayleigh = (
                9.80665
                * abs(surface_k - c["ambient_temperature_k"])
                * diameter**3
                / (film_k * kinematic_viscosity * diffusivity)
            )
            if 1e-5 <= rayleigh <= 1e12:
                nusselt = (
                    0.6 + 0.387 * rayleigh ** (1 / 6) / (1 + (0.559 / prandtl) ** (9 / 16)) ** (8 / 27)
                ) ** 2
                candidates.append((nusselt * conductivity / diameter, "terrestrial_horizontal_cylinder"))
        return max(candidates, key=lambda pair: pair[0])

    def fluxes(self, state, current_a: float) -> dict:
        c = self.config
        m = self.material
        core, surface, melted = self.temperatures(state)
        # Positive floors only keep rejected RK stages evaluable; any accepted
        # trajectory remains in the declared temperature and mass domain.
        core = max(1.0, core)
        surface = max(1.0, surface)
        resistance = self.reference_resistance * max(
            1e-9, 1 + c["resistance_temperature_coefficient_per_k"] * (core - REFERENCE_TEMPERATURE_K)
        )
        conductivity = m.solid_conductivity_w_m_k * (1 - melted) + m.liquid_conductivity_w_m_k * melted
        conductance = 2 * math.pi * conductivity * self.length / math.log(self.outer_radius / self.radius)
        transfer_h, regime = self.heat_transfer(surface)
        emissivity = m.solid_emissivity * (1 - melted) + m.liquid_emissivity * melted
        radiation = (
            emissivity * STEFAN_BOLTZMANN_W_M2_K4 * self.area * (surface**4 - c["radiant_temperature_k"] ** 4)
            if c["radiation_enabled"]
            else 0.0
        )
        mass_loss_rate = 0.0
        if c["pyrolysis_enabled"] and melted >= 1.0:
            # First-order remaining-mass kinetics, not an FDS input parameter
            # copied across versions with different density conventions.
            rate = m.pyrolysis_prefactor_per_s * math.exp(
                -m.pyrolysis_activation_energy_j_mol / (GAS_CONSTANT_J_MOL_K * surface)
            )
            mass_loss_rate = max(float(state[2]), 0.0) * rate
        specific_enthalpy = float(state[1]) / max(float(state[2]), self.initial_polymer_mass * 1e-8)
        return {
            "resistance_ohm": resistance,
            "voltage_v": current_a * resistance,
            "joule_power_w": current_a**2 * resistance,
            "core_to_insulation_power_w": conductance * (core - surface),
            "convection_power_w": transfer_h * self.area * (surface - c["ambient_temperature_k"]),
            "radiation_power_w": radiation,
            "support_power_w": c["support_conductance_w_k"] * (core - c["support_temperature_k"]),
            "pyrolysis_power_w": mass_loss_rate * m.pyrolysis_enthalpy_j_kg,
            "carried_power_w": mass_loss_rate * specific_enthalpy,
            "mass_loss_rate_kg_s": mass_loss_rate,
            "heat_transfer_coefficient_w_m2_k": transfer_h,
            "heat_transfer_regime": regime,
        }

    def derivative(self, state, current_a: float):
        f = self.fluxes(state, current_a)
        return np.array(
            [
                f["joule_power_w"] - f["core_to_insulation_power_w"] - f["support_power_w"],
                f["core_to_insulation_power_w"]
                - f["convection_power_w"]
                - f["radiation_power_w"]
                - f["pyrolysis_power_w"]
                - f["carried_power_w"],
                -f["mass_loss_rate_kg_s"],
                f["joule_power_w"],
                f["convection_power_w"],
                f["radiation_power_w"],
                f["support_power_w"],
                f["pyrolysis_power_w"],
                f["carried_power_w"],
            ]
        )

    def sample(self, time_s: float, state) -> dict:
        current_a = _current_at(self.config, time_s)
        core, surface, melted = self.temperatures(state)
        stored = float(state[0] + state[1] - self.initial_energy)
        loss = float(state[4] + state[5] + state[6])
        input_energy, pyrolysis, carried = (float(state[index]) for index in (3, 7, 8))
        return {
            "time_s": float(time_s),
            "current_a": current_a,
            "conductor_temperature_k": float(core),
            "surface_temperature_k": float(surface),
            "melt_fraction": float(melted),
            "remaining_insulation_mass_kg": float(state[2]),
            "pyrolyzed_mass_kg": float(max(0.0, self.initial_polymer_mass - state[2])),
            "pyrolyzed_fraction": float(max(0.0, 1 - state[2] / self.initial_polymer_mass)),
            "input_energy_j": input_energy,
            "stored_energy_j": stored,
            "convection_energy_j": float(state[4]),
            "radiation_energy_j": float(state[5]),
            "support_energy_j": float(state[6]),
            "loss_energy_j": loss,
            "pyrolysis_energy_j": pyrolysis,
            "carried_energy_j": carried,
            "balance_error_j": input_energy - stored - loss - pyrolysis - carried,
            **self.fluxes(state, current_a),
        }


def _current_at(config: dict, time_s: float) -> float:
    if config["cutoff_s"] is not None and time_s >= config["cutoff_s"]:
        return 0.0
    current = config["current_profile"][0]["current_a"]
    for entry in config["current_profile"]:
        if entry["time_s"] > time_s:
            break
        current = entry["current_a"]
    return current


def _event_functions(wire: _Wire):
    c = wire.config
    material = wire.material
    functions = []
    names = []

    def add(name, function, direction=1, terminal=False):
        function.direction = direction
        function.terminal = terminal
        functions.append(function)
        names.append(name)

    def polymer_enthalpy(state):
        return state[1] / max(state[2], wire.initial_polymer_mass * 1e-8)

    add("melting_started", lambda t, y: polymer_enthalpy(y) - material.melting_start_enthalpy_j_kg)
    add("melting_completed", lambda t, y: polymer_enthalpy(y) - material.melting_end_enthalpy_j_kg)
    if c["pyrolysis_enabled"]:
        if c["pyrolysis_report_fraction"] > 0:
            add(
                "mass_loss_reporting_fraction_reached",
                lambda t, y: y[2] - wire.initial_polymer_mass * (1 - c["pyrolysis_report_fraction"]),
                direction=-1,
            )
        add(
            "fixed_geometry_mass_loss_limit",
            lambda t, y: y[2] - wire.initial_polymer_mass * (1 - c["maximum_pyrolyzed_fraction"]),
            direction=-1,
            terminal=True,
        )
    add(
        "maximum_temperature_limit",
        lambda t, y: max(wire.temperatures(y)[:2]) - c["maximum_temperature_k"],
        terminal=True,
    )
    if c["surface_limit_k"] is not None:
        limit_enthalpy = material.insulation_enthalpy(c["surface_limit_k"])
        add("user_surface_thermal_limit", lambda t, y: polymer_enthalpy(y) - limit_enthalpy)
    return names, functions


def simulate_thermal(config: dict) -> dict:
    """Return a reproducible thermal trajectory with SI units and energy accounting.

    Integration continues after electrical cutoff unless the declared model
    domain is exceeded. A completed trajectory is never an absence-of-fire
    label. ``summary.ignition_supported`` is always false.
    """
    c = normalize_thermal_config(config)
    wire = _Wire(c, get_material(c["material_preset"]))
    event_names, event_functions = _event_functions(wire)
    boundaries = {0.0, c["duration_s"]}
    boundaries.update(entry["time_s"] for entry in c["current_profile"])
    if c["cutoff_s"] is not None:
        boundaries.add(c["cutoff_s"])
    boundaries = sorted(boundaries)
    state = wire.initial.copy()
    solutions = []
    events = []
    termination_reason = None

    initial_specific_h = state[1] / state[2]
    for name, threshold in (
        ("melting_started", wire.material.melting_start_enthalpy_j_kg),
        ("melting_completed", wire.material.melting_end_enthalpy_j_kg),
    ):
        if initial_specific_h >= threshold:
            events.append({"type": name, "time_s": 0.0, "initial_condition": True})
    if c["surface_limit_k"] is not None and c["initial_insulation_temperature_k"] >= c["surface_limit_k"]:
        events.append({"type": "user_surface_thermal_limit", "time_s": 0.0, "initial_condition": True})

    for left, right in zip(boundaries, boundaries[1:]):
        current = _current_at(c, (left + right) / 2)
        solution = solve_ivp(
            lambda t, y: wire.derivative(y, current),
            (left, right),
            state,
            method="RK45",
            dense_output=True,
            events=event_functions,
            rtol=c["relative_tolerance"],
            atol=np.array([1e-9, 1e-9, wire.initial_polymer_mass * 1e-9] + [1e-9] * 6),
            max_step=c["max_step_s"],
        )
        if not solution.success:
            raise RuntimeError(f"Thermal integration failed: {solution.message}")
        solutions.append(solution)
        state = solution.y[:, -1]
        for name, times in zip(event_names, solution.t_events):
            for time_s in times:
                # Report first attainment only, including an initial condition.
                # This also avoids inventing repeated events at equilibrium on
                # the phase boundary (an event function identically zero).
                if not any(event["type"] == name for event in events):
                    events.append({"type": name, "time_s": float(time_s), "initial_condition": False})
        if solution.status == 1:
            termination_reason = next(
                name
                for name, function, times in zip(event_names, event_functions, solution.t_events)
                if function.terminal and len(times) and abs(times[-1] - solution.t[-1]) < 1e-7
            )
            break

    end_time = float(solutions[-1].t[-1])
    times = {0.0, end_time}
    count = math.floor(end_time / c["sample_interval_s"])
    times.update(index * c["sample_interval_s"] for index in range(1, count + 1))
    times.update(value for value in boundaries if value < end_time)
    ends = [float(solution.t[-1]) for solution in solutions]
    samples = []
    for time_s in sorted(times):
        solution = solutions[min(bisect_left(ends, time_s), len(solutions) - 1)]
        samples.append(wire.sample(time_s, solution.sol(time_s)))
    if c["cutoff_s"] is not None and c["cutoff_s"] <= end_time:
        events.append({"type": "electrical_cutoff", "time_s": c["cutoff_s"], "initial_condition": False})
    events.sort(key=lambda event: (event["time_s"], event["type"]))
    for event in events:
        event["ignition_event"] = False

    temperatures = [wire.temperatures(column) for sol in solutions for column in sol.y.T]
    final = samples[-1]
    energy_audit = audit_energy_balance(samples)
    if not energy_audit["passed"]:
        raise RuntimeError("Thermal trajectory failed its cumulative energy balance check")

    def first_event(name):
        return next((event["time_s"] for event in events if event["type"] == name), None)

    limitations = [
        "Thermal precursor model only: no gas transport, gas reaction, flame, ignition probability or arc.",
        "All temperature histories are simulated; no experimental thermal validation has been performed.",
        "Two uniform thermal nodes; surface_temperature_k is a lumped insulation temperature, not a resolved field.",
        "Fixed wire geometry; melt flow, swelling, exposure of the conductor and significant mass loss are absent.",
        "Energy of removed polymer uses its instantaneous condensed-phase specific enthalpy plus pyrolysis heat.",
        "Oxygen concentration is context only; oxygen chemistry, oxidizing metal and composition-dependent gas properties are absent.",
        "No cabin solver coupling: ambient temperature, airflow, surroundings and supports are prescribed.",
        "No electrical contact resistance, protection-circuit dynamics, fault frequency or mission-risk estimate.",
        "Completion without a thermal event is not evidence that fire cannot occur.",
    ]
    if c["heat_transfer_mode"] == "auto":
        limitations += [
            "Stagnant gas heat loss uses steady cylindrical conduction to the configured outer isothermal radius.",
            "Air conductivity, viscosity and heat capacity are fixed room-temperature engineering approximations.",
            "Forced convection assumes perpendicular cylinder crossflow; orientation and recirculation are not solved.",
            "The maximum of valid conduction/convection coefficients is a dominance approximation, not a mixed-convection solution.",
            "Natural convection is included only at 1 g; all other gravity values omit residual buoyancy.",
            "Outside the forced-correlation Reynolds-Prandtl range, heat loss falls back to the other available terms.",
        ]
    if c["support_conductance_w_k"] == 0:
        limitations.append(
            "Support conductance is zero: axially adiabatic supports are an explicit scenario assumption."
        )
    if c["resistance_temperature_coefficient_per_k"] != 0:
        limitations.append(
            "Nonzero resistance temperature coefficient is user supplied and is not calibrated to Guo's wire."
        )
    if not c["pyrolysis_enabled"]:
        limitations.append(
            "Pyrolysis has been disabled for a numerical/control scenario; hot polymer is not physically complete."
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "config": c,
        "samples": samples,
        "events": events,
        "summary": {
            "status": "scope_limit_reached" if termination_reason else "completed",
            "termination_reason": termination_reason,
            "ignition_supported": False,
            "ignition_time_s": None,
            "ignition_probability": None,
            "experimental_validation": False,
            "temperature_origin": "simulation",
            "requested_duration_s": c["duration_s"],
            "observed_duration_s": end_time,
            "peak_conductor_temperature_k": max(value[0] for value in temperatures),
            "peak_surface_temperature_k": max(value[1] for value in temperatures),
            "melting_onset_time_s": first_event("melting_started"),
            "melting_complete_time_s": first_event("melting_completed"),
            "surface_limit_time_s": first_event("user_surface_thermal_limit"),
            "mass_loss_reporting_time_s": first_event("mass_loss_reporting_fraction_reached"),
            "final_melt_fraction": final["melt_fraction"],
            "pyrolyzed_mass_kg": final["pyrolyzed_mass_kg"],
            "pyrolyzed_fraction": final["pyrolyzed_mass_kg"] / wire.initial_polymer_mass,
            "initial_conductor_mass_kg": wire.core_mass,
            "initial_insulation_mass_kg": wire.initial_polymer_mass,
            "reference_resistance_ohm": wire.reference_resistance,
            "input_energy_j": final["input_energy_j"],
            "stored_energy_j": final["stored_energy_j"],
            "loss_energy_j": final["loss_energy_j"],
            "pyrolysis_energy_j": final["pyrolysis_energy_j"],
            "carried_energy_j": final["carried_energy_j"],
            "balance_error_j": final["balance_error_j"],
            "energy_audit": energy_audit,
            "integration_steps": sum(len(sol.t) - 1 for sol in solutions),
            "function_evaluations": sum(sol.nfev for sol in solutions),
        },
        "provenance": {
            "material": wire.material.provenance(),
            "solver": "Two-node enthalpy ODE; scipy.integrate.solve_ivp RK45, piecewise constant current",
            "forced_convection": "https://doi.org/10.1115/1.3450685",
            "terrestrial_natural_convection": "https://doi.org/10.1016/0017-9310(75)90222-7",
            "gas_conduction": "Steady radial Fourier conduction between two coaxial isothermal cylinders",
            "initial_conditions_origin": "Scenario assumptions, not measured thermal histories",
            "user_surface_limit_source": c["surface_limit_source"],
            "electrical_temperature_coefficient_origin": (
                "Guo constant-resistance assumption"
                if c["resistance_temperature_coefficient_per_k"] == 0
                else "User-supplied sensitivity assumption; not calibrated"
            ),
        },
        "limitations": limitations,
    }
