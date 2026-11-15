"""Localized, prescribed incident boundary conditions, not fault probabilities.

The scene annotations select one resolved upper-face cell. This adapter does not
infer physical materials from rendering, nor relocate faults to a fuel sample.
"""

from __future__ import annotations

import itertools
import math

from .materials import MATERIALS

INCIDENT_COMPILER_VERSION = "ignis-incidents-1"
INCIDENT_TYPES = frozenset({"overheating", "arc", "flaming", "smoldering", "battery"})
THERMAL_INCIDENTS = frozenset({"overheating", "arc"})
EMISSION_INCIDENTS = frozenset({"smoldering", "battery"})
# An explicitly hypothetical emission factor, not a material measurement or a
# battery chemistry parameter. 0.02 kg/kg divided by 20 MJ/kg = 1e-9 kg/J.
SOOT_EMISSION_KG_J = 1e-9
_TOL = 1e-7


def validate_incident_config(config: dict) -> bool:
    """Validate the optional pair without mutating legacy configurations."""
    kind, component = config.get("incident_type"), config.get("component_id")
    if kind is None and component is None:
        return False
    if not isinstance(kind, str) or kind not in INCIDENT_TYPES:
        raise ValueError("incident_type must be overheating, arc, flaming, smoldering or battery")
    if not isinstance(component, str) or not component.strip():
        raise ValueError("An incident requires an explicit component_id")
    if config.get("ignition_kind", "thermal") != "thermal" and kind not in THERMAL_INCIDENTS:
        raise ValueError("Electrical I²R input is only an equivalent overheating or arc heat source")
    return True


def _point(value: object, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must contain three finite SI coordinates")
    if any(isinstance(v, bool) for v in value):
        raise ValueError(f"{label} must contain three finite SI coordinates")
    try:
        result = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain three finite SI coordinates") from exc
    if not all(math.isfinite(v) for v in result):
        raise ValueError(f"{label} must contain three finite SI coordinates")
    return result


def _patch_at(point: list[float], obj: dict, spacing: list[float]) -> list[float]:
    box = obj["bounds_m"]
    patch = []
    for axis in range(2):
        lo, hi = box[2 * axis : 2 * axis + 2]
        if not lo - _TOL <= point[axis] <= hi + _TOL:
            raise ValueError("Incident position is outside its object after mesh snapping; refine the mesh")
        first = round(lo / spacing[axis])
        last = round(hi / spacing[axis]) - 1
        index = min(last, max(first, math.floor(point[axis] / spacing[axis] + 1e-9)))
        patch.extend([index * spacing[axis], (index + 1) * spacing[axis]])
    return [*patch, box[5], box[5]]


def _patch_cover(patch: list[float], obj: dict, objects: list[dict], height: float) -> str | None:
    z = patch[5]
    if z >= height - _TOL:
        return "domain ceiling"
    for other in objects:
        if other["id"] == obj["id"]:
            continue
        box = other["bounds_m"]
        if (
            box[4] <= z + _TOL
            and box[5] > z + _TOL
            and all(
                min(patch[2 * a + 1], box[2 * a + 1]) > max(patch[2 * a], box[2 * a]) + _TOL for a in range(2)
            )
        ):
            return other["id"]
    return None


def locate_incident(
    scene: dict, config: dict, objects: list[dict], spacing: list[float], bounds: list[float]
) -> dict:
    """Resolve an annotated component to an exposed, single-cell VENT patch."""
    components = scene.get("components", [])
    if not isinstance(components, list) or any(not isinstance(c, dict) for c in components):
        raise ValueError("Scene components must be annotation records")
    identifiers = [c.get("id") for c in components]
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
        raise ValueError("Scene component ids must be nonempty strings")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate component id")
    component = next((c for c in components if c["id"] == config["component_id"]), None)
    if component is None:
        raise ValueError("Unknown incident component_id; no nearest-fuel fallback is permitted")
    obj = next((o for o in objects if o["id"] == component.get("object_id")), None)
    if obj is None:
        raise ValueError("Incident component must reference an existing physical fuel or obstacle object")
    if isinstance(component.get("face"), bool) or component.get("face") != 3:
        raise ValueError("Incident component face must be 3 (the original upper face)")
    point = _point(component.get("position_m"), "component.position_m")
    if any(not 0 <= point[a] <= bounds[a] for a in range(3)):
        raise ValueError("Incident position is outside the physical domain")
    original = obj["original_bounds_m"]
    if abs(point[2] - original[5]) > _TOL or any(
        not original[2 * a] - _TOL <= point[a] <= original[2 * a + 1] + _TOL for a in range(2)
    ):
        raise ValueError("Incident position must lie on the referenced object's original upper face")
    patch = _patch_at(point, obj, spacing)
    cover = _patch_cover(patch, obj, objects, bounds[2])
    if cover:
        raise ValueError(f"Incident patch is blocked after mesh snapping by {cover}")
    # Two annotated sites may not silently collapse to one numerical source.
    for other in components:
        if other["id"] == component["id"] or other.get("object_id") != obj["id"] or other.get("face") != 3:
            continue
        other_point = _point(other.get("position_m"), "component.position_m")
        try:
            other_patch = _patch_at(other_point, obj, spacing)
        except ValueError:
            continue  # A separately selected invalid site will fail its own validation.
        if all(abs(a - b) < _TOL for a, b in zip(patch, other_patch)):
            raise ValueError(
                f"Incident sites {component['id']} and {other['id']} share one mesh cell; refine the mesh"
            )
    return {
        "component_id": component["id"],
        "object_id": obj["id"],
        "face": 3,
        "requested_position_m": point,
        "position_m": [(patch[0] + patch[1]) / 2, (patch[2] + patch[3]) / 2, patch[5]],
        "bounds_m": patch,
        "area_m2": (patch[1] - patch[0]) * (patch[3] - patch[2]),
        "material_id": obj["material_id"],
        "combustible_material_id": obj.get("combustible_material_id"),
        "placement_basis": "one exposed upper-face mesh cell containing the annotated horizontal position",
        "annotation_provenance": component.get("provenance"),
    }


def incident_ramp(config: dict) -> list[tuple[float, float]]:
    """Piecewise-linear source profile, integrated only over the simulated time.

    A short simulation truncates a profile; it does not compress its rise time.
    """
    start = config["ignition_delay_s"]
    duration = config["ignition_duration_s"]
    end = config["duration_s"]
    if config["ignition_power_w"] <= 0 or duration <= 0 or start >= end:
        return []
    stop = start + duration
    epsilon = min(0.01, duration / 10)
    if config["incident_type"] == "battery":
        knots = [(0.0, 0.0), (start, 0.0), (start + duration * 0.25, 1.0), (stop - epsilon, 1.0), (stop, 0.0)]
    elif start > 0:
        knots = [(0.0, 0.0), (start, 0.0), (start + epsilon, 1.0), (stop - epsilon, 1.0), (stop, 0.0)]
    else:
        knots = [(0.0, 1.0), (stop - epsilon, 1.0), (stop, 0.0)]
    knots = sorted(dict(knots).items())
    result = [(t, f) for t, f in knots if t <= end]
    for (ta, fa), (tb, fb) in zip(knots, knots[1:]):
        if ta < end < tb:
            result.append((end, fa + (fb - fa) * (end - ta) / (tb - ta)))
            break
    return result


def surface_arguments(obj: dict) -> str:
    """Upper-face material model, including a coating on an inert obstacle."""
    material = obj.get("combustible_material_id")
    mid = f"IGNIS_SOLID_{material}" if material else f"INERT_{obj['material_id']}"
    return f"MATL_ID='{mid}', THICKNESS={obj['thermal_thickness_m']:.10g}, BACKING='INSULATED'"


def incident_surface_line(config: dict, source: dict, obj: dict, active: bool) -> str:
    """Generate exactly one source SURF; no thermal/chemical double counting."""
    kind = config["incident_type"]
    flux = config["ignition_power_w"] / 1000 / source["area_m2"] if active else 0.0
    if kind in THERMAL_INCIDENTS:
        arguments = surface_arguments(obj)
        if active:
            arguments += f", EXTERNAL_FLUX={flux:.10g}, RAMP_EF='SOURCE_RAMP'"
    elif kind == "flaming":
        fuel = obj.get("combustible_material_id") or config["material_id"]
        arguments = f"HRRPUA={flux:.10g}, SPEC_ID='IGNIS_FUEL_{fuel}'"
        if active:
            arguments += ", RAMP_Q='SOURCE_RAMP'"
    else:
        soot_flux = config["ignition_power_w"] * SOOT_EMISSION_KG_J / source["area_m2"] if active else 0.0
        arguments = f"NET_HEAT_FLUX={flux:.10g}, SPEC_ID(1)='SOOT', MASS_FLUX(1)={soot_flux:.10g}"
        if active:
            arguments += ", RAMP_Q='SOURCE_RAMP', RAMP_MF(1)='SOURCE_RAMP'"
    return f"&SURF ID='INCIDENT_SOURCE', {arguments} /"


def surface_measurement_position(
    obj: dict, objects: list[dict], source: dict, config: dict, spacing: list[float], bounds: list[float]
) -> list[float] | None:
    """Select an exposed reactive cell, excluding a prescribed burner/emitter."""
    box = obj["bounds_m"]
    target = (
        source["position_m"]
        if obj["id"] == source["object_id"]
        else [(box[0] + box[1]) / 2, (box[2] + box[3]) / 2, box[5]]
    )
    exclude_source = obj["id"] == source["object_id"] and config["incident_type"] not in THERMAL_INCIDENTS
    best, distance = None, math.inf
    axes = [range(round(box[2 * a] / spacing[a]), round(box[2 * a + 1] / spacing[a])) for a in range(2)]
    for ix, iy in itertools.product(*axes):
        center = [(ix + 0.5) * spacing[0], (iy + 0.5) * spacing[1], box[5]]
        patch = _patch_at(center, obj, spacing)
        if _patch_cover(patch, obj, objects, bounds[2]):
            continue
        if exclude_source and all(abs(a - b) < _TOL for a, b in zip(patch, source["bounds_m"])):
            continue
        current = sum((center[a] - target[a]) ** 2 for a in range(2))
        if current < distance:
            best, distance = center, current
    return best


def incident_metadata(config: dict, source: dict, ramp: list, energy: float) -> dict:
    kind = config["incident_type"]
    meaning = {
        "overheating": "prescribed external thermal flux into the selected surface; no imposed gas flame",
        "arc": "finite equivalent external thermal pulse; no electrical arc, plasma or ejecta physics",
        "flaming": "nominal chemical HRR of an already ignited source, oxygen limited; not an ignition prediction",
        "smoldering": "prescribed net surface heat and soot emission without an imposed gas flame; no smolder kinetics",
        "battery": "hypothetical net surface heat and soot growth/plateau profile; no electrochemistry or runaway kinetics",
    }[kind]
    thermal = kind in THERMAL_INCIDENTS
    return {
        "version": INCIDENT_COMPILER_VERSION,
        "type": kind,
        "component_id": source["component_id"],
        "source": source,
        "meaning": meaning,
        "source_model_config": config["source_model"],
        "source_model_dispatch": "incident_type selects the explicit boundary condition; source_model config is preserved",
        "power_w": config["ignition_power_w"],
        "requested_duration_s": config["ignition_duration_s"],
        "requested_delay_s": config["ignition_delay_s"],
        "nominal_power_duration_j": config["ignition_power_w"] * config["ignition_duration_s"],
        "ramp": ramp,
        "imposed_pulse_energy_j": energy,
        "energy_basis": "integral of prescribed external incident flux (before surface absorptivity)"
        if thermal
        else "integral of nominal fuel chemical power; actual HRR is measured by FDS"
        if kind == "flaming"
        else "integral of prescribed net boundary heat; excludes enthalpy carried by emitted soot",
        "ramp_basis": "linear growth over first 25% of requested duration, plateau, <=0.01 s shutdown"
        if kind == "battery"
        else "finite pulse with <=0.01 s onset after delay and shutdown; active at t=0 without a delay",
        "emission": {
            "species": "SOOT",
            "peak_mass_flow_kg_s": config["ignition_power_w"] * SOOT_EMISSION_KG_J,
            "imposed_mass_kg": energy * SOOT_EMISSION_KG_J,
            "assumed_soot_kg_j": SOOT_EMISSION_KG_J,
            "provenance": "hypothetical demonstration coefficient; no empirical smolder/battery calibration",
            "kinetics": "independent prescribed soot mass flux; no primary fuel gas, oxygen consumption or CO model",
        }
        if kind in EMISSION_INCIDENTS
        else None,
        "emitted_fuel_material_id": (source.get("combustible_material_id") or config["material_id"])
        if kind == "flaming"
        else None,
        "source_patch_reactive": thermal and source.get("combustible_material_id") in MATERIALS,
        "other_combustible_surfaces_reactive": True,
        "secondary_combustion_basis": "material-dependent pyrolysis on exposed upper faces; local devices are not whole-object ignition labels",
        "scientific_status": "prescribed_equivalent_incident_not_calibrated",
        "fault_probability": None,
        "references": [
            "https://pages.nist.gov/fds-smv/manuals.html",
            "https://github.com/firemodels/fds/blob/FDS-6.11.1/Source/read.f90",
        ],
    }
