"""Validated scene-to-FDS compiler, intentionally independent of the web server."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from .materials import (
    INERT_MATERIALS,
    MATERIALS,
    MODEL_VERSION,
    fuel_species_line,
    reaction_line,
    solid_material_lines,
)

ENGINE_VERSION = "6.11.1"
COMPILER_VERSION = "ignis-fds-2"
MAX_CELLS = 750_000
MAX_ESTIMATED_CSV_BYTES = 256 * 1024**2
DEFAULTS = {
    "source_model": "prescribed_source",
    "gravity_g": 0.0001,
    "airflow_m_s": 0.2,
    "oxygen_percent": 21.0,
    "material_id": "cellulose",
    "ignition_power_w": 500.0,
    "ignition_duration_s": 15.0,
    "ignition_delay_s": 0.0,
    "duration_s": 60.0,
    "mesh_cell_m": 0.2,
    "sample_interval_s": 1.0,
    "sample_shape": [8, 10, 4],
    "ambient_temperature_c": 20.0,
    "pressure_pa": 101325.0,
    "seed": 42,
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _finite(value: Any, name: str, lower: float, upper: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number, not boolean")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or not lower <= number <= upper:
        raise ValueError(f"{name} must be within [{lower}, {upper}]")
    return number


def _vec(value: Any, name: str, lower: float, upper: float) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must contain three SI coordinates")
    return [_finite(x, f"{name}[{i}]", lower, upper) for i, x in enumerate(value)]


def _num(values: list[float] | tuple[float, ...]) -> str:
    return ",".join(f"{v:.10g}" for v in values)


def _bounds(center: list[float], size: list[float]) -> list[float]:
    return [v for c, s in zip(center, size) for v in (c - s / 2, c + s / 2)]


def _inside(point: list[float], box: list[float]) -> bool:
    # All measurement points are cell centers, never ambiguous boundary points.
    return all(box[2 * a] < point[a] < box[2 * a + 1] for a in range(3))


def _overlap(first: list[float], second: list[float]) -> bool:
    return all(
        min(first[2 * a + 1], second[2 * a + 1]) - max(first[2 * a], second[2 * a]) > 1e-8 for a in range(3)
    )


def _smooth_count(minimum: int) -> int:
    # FDS pressure solver is efficient for factors 2, 3 and 5.
    for count in range(max(4, minimum), max(8, minimum * 2 + 1)):
        rest = count
        for factor in (2, 3, 5):
            while rest % factor == 0:
                rest //= factor
        if rest == 1:
            return count
    raise ValueError("Cannot construct an admissible mesh")


def _snap_box(box: list[float], spacing: list[float], ijk: list[int]) -> list[float]:
    result = []
    for axis in range(3):
        # Explicit snapping means devices and FDS see precisely the same solids.
        lo = math.floor(box[2 * axis] / spacing[axis] + 0.5)
        hi = math.floor(box[2 * axis + 1] / spacing[axis] + 0.5)
        lo = max(0, min(ijk[axis] - 1, lo))
        hi = max(lo + 1, min(ijk[axis], hi))
        result.extend([lo * spacing[axis], hi * spacing[axis]])
    return result


def _validate_config(scene: dict, config: dict) -> dict:
    combined = {**DEFAULTS, **scene.get("defaults", {}), **config}
    ranges = {
        "gravity_g": (0.0, 1.0),
        "airflow_m_s": (0.0, 2.0),
        "oxygen_percent": (10.0, 30.0),
        "ignition_power_w": (0.0, 200_000.0),
        "ignition_duration_s": (0.0, 1800.0),
        "ignition_delay_s": (0.0, 1800.0),
        "duration_s": (0.1, 1800.0),
        "mesh_cell_m": (0.025, 1.0),
        "sample_interval_s": (0.05, 60.0),
        "ambient_temperature_c": (-20.0, 60.0),
        "pressure_pa": (50000.0, 120000.0),
    }
    for key, limits in ranges.items():
        combined[key] = _finite(combined[key], key, *limits)
    if combined["source_model"] not in {"prescribed_source", "coupled_combustion"}:
        raise ValueError("Unsupported source_model")
    if combined["material_id"] not in MATERIALS:
        raise ValueError("material_id must be cellulose or pmma")
    shape = combined["sample_shape"]
    if not isinstance(shape, (list, tuple)) or len(shape) != 3:
        raise ValueError("sample_shape must contain three integers")
    if any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 32 for v in shape):
        raise ValueError("sample_shape must contain integers between 1 and 32")
    if math.prod(shape) > 4096:
        raise ValueError("At most 4096 spatial sampling points per run")
    combined["sample_shape"] = list(shape)
    seed = combined["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
        raise ValueError("seed must be an integer in [0, 2^31)")
    if combined.get("ignition_kind", "thermal") in {"electrical", "resistive"}:
        if combined["source_model"] != "coupled_combustion":
            raise ValueError("Electrical I²R input is surface heating in coupled_combustion only")
        resistance = _finite(combined.get("resistance_ohm", 2.0), "resistance_ohm", 0.01, 100000.0)
        efficiency = _finite(combined.get("heat_fraction", 1.0), "heat_fraction", 0.0, 1.0)
        if "current_a" in combined:
            current = _finite(combined["current_a"], "current_a", 0.0, 10000.0)
            power = current * current * resistance * efficiency
            combined["current_a"] = current
        else:
            voltage = _finite(combined.get("voltage_v", 28.0), "voltage_v", 0.0, 600.0)
            power = voltage * voltage / resistance * efficiency
            combined["voltage_v"] = voltage
        if power > 200_000:
            raise ValueError("Electrical heat deposition exceeds the 200 kW demonstration limit")
        combined.update(resistance_ohm=resistance, heat_fraction=efficiency)
        combined["ignition_power_w"] = power
        if "cutoff_s" in combined:
            combined["ignition_duration_s"] = min(
                combined["ignition_duration_s"],
                _finite(combined["cutoff_s"], "cutoff_s", 0, 1800),
            )
    elif combined.get("ignition_kind", "thermal") != "thermal":
        raise ValueError("ignition_kind must be thermal or resistive")
    return combined


def compile_case(scene: dict, config: dict, output_dir: Path) -> dict:
    """Write a reproducible ``ignis.fds`` and ``manifest.json``; never run FDS.

    Raises ValueError before writing a case when geometry or controls are invalid.
    A nonempty run directory is not silently overwritten.
    """
    cfg = _validate_config(scene, config)
    bounds = _vec(scene.get("bounds_m"), "bounds_m", 0.2, 30.0)
    domain = [v for extent in bounds for v in (0.0, extent)]
    ijk = [_smooth_count(math.ceil(v / cfg["mesh_cell_m"] - 1e-9)) for v in bounds]
    if math.prod(ijk) > MAX_CELLS:
        raise ValueError(f"Mesh exceeds the configured {MAX_CELLS:,}-cell resource ceiling")
    if any(count > cells for count, cells in zip(cfg["sample_shape"], ijk)):
        raise ValueError("Sampling shape must not exceed the numerical mesh on any axis")
    spacing = [bounds[a] / ijk[a] for a in range(3)]
    warnings = [
        "Exploratory FDS 6.11.1 calculation; not calibrated or validated against NASA microgravity experiments.",
        "Coarse LES grid and mixing-controlled gas chemistry cannot establish microgravity flame extinction limits.",
        "Ventilation exchanges fresh ambient gas with external reservoirs; it is not a closed recirculating spacecraft HVAC loop.",
        "Soot is a prescribed reaction yield; CO toxicity, battery runaway, arcs and plasma are not modeled.",
    ]
    objects = []
    seen = set()
    for index, obj in enumerate(scene.get("objects", [])):
        if obj.get("role") in {"wall", "decoration"}:
            continue
        if obj.get("role") not in {"fuel", "obstacle"}:
            raise ValueError(f"Object {index}: unknown physical role")
        oid = str(obj.get("id", f"object-{index}"))
        if oid in seen:
            raise ValueError(f"Duplicate object id: {oid}")
        seen.add(oid)
        center = _vec(obj.get("center_m"), f"{oid}.center_m", -30, 30)
        size = _vec(obj.get("size_m"), f"{oid}.size_m", 1e-5, 30)
        original = _bounds(center, size)
        if any(original[2 * a] < -1e-7 or original[2 * a + 1] > bounds[a] + 1e-7 for a in range(3)):
            raise ValueError(f"Object {oid} lies outside the physical domain")
        snapped = _snap_box(original, spacing, ijk)
        if any(abs(a - b) > 1e-7 for a, b in zip(original, snapped)):
            warnings.append(f"Object {oid}: proxy snapped to mesh; original and calculated bounds recorded.")
        material = cfg["material_id"] if obj["role"] == "fuel" else obj.get("material_id", "aluminium")
        if material not in MATERIALS and material not in INERT_MATERIALS:
            raise ValueError(f"Object {oid}: unsupported physical material {material}")
        if obj["role"] == "obstacle" and material in MATERIALS:
            raise ValueError(f"Object {oid}: combustible material must explicitly use role=fuel")
        thickness = obj.get(
            "thermal_thickness_m", MATERIALS.get(material, {}).get("default_thickness_m", 0.01)
        )
        thickness = _finite(thickness, f"{oid}.thermal_thickness_m", 0.00005, 0.1)
        objects.append(
            {
                "id": oid,
                "fds_id": f"OBJ_{index:03d}",
                "role": obj["role"],
                "material_id": material,
                "original_bounds_m": original,
                "bounds_m": snapped,
                "thermal_thickness_m": thickness,
            }
        )
    for first, second in itertools.combinations(objects, 2):
        if _overlap(first["bounds_m"], second["bounds_m"]):
            raise ValueError(
                f"Discretized proxies overlap: {first['id']} and {second['id']}; refine mesh or separate objects"
            )
    fuel_objects = [o for o in objects if o["role"] == "fuel"]
    if not fuel_objects and cfg["ignition_power_w"] > 0:
        raise ValueError("A source requires at least one role=fuel object")
    source_position = _vec(
        scene.get("source_position_m", [v / 2 for v in bounds]), "source_position_m", 0, 30
    )
    if any(source_position[a] > bounds[a] for a in range(3)):
        raise ValueError("source_position_m is outside the compartment")
    source = min(
        fuel_objects,
        key=lambda o: sum(
            (
                source_position[a]
                - ((o["bounds_m"][2 * a] + o["bounds_m"][2 * a + 1]) / 2 if a < 2 else o["bounds_m"][5])
            )
            ** 2
            for a in range(3)
        ),
        default=None,
    )
    for fuel in fuel_objects:
        if fuel["bounds_m"][5] >= bounds[2] - 1e-8:
            raise ValueError(f"Fuel {fuel['id']} has no exposed upper face")
        for other in objects:
            if other is fuel:
                continue
            if abs(other["bounds_m"][4] - fuel["bounds_m"][5]) < 1e-8 and all(
                min(fuel["bounds_m"][2 * a + 1], other["bounds_m"][2 * a + 1])
                > max(fuel["bounds_m"][2 * a], other["bounds_m"][2 * a]) + 1e-8
                for a in range(2)
            ):
                raise ValueError(f"Fuel {fuel['id']} upper face is covered by {other['id']}")

    vents = []
    for index, vent in enumerate(scene.get("vents", [])):
        role = vent.get("role")
        if role not in {"inlet", "outlet"}:
            raise ValueError("Vent role must be inlet or outlet")
        center = _vec(vent.get("center_m"), "vent.center_m", 0, 30)
        size = _vec(vent.get("size_m"), "vent.size_m", 0, 30)
        normal = _vec(vent.get("normal"), "vent.normal", -1, 1)
        axes = [a for a in range(3) if abs(normal[a]) > 1e-8]
        if len(axes) != 1 or abs(abs(normal[axes[0]]) - 1) > 1e-8:
            raise ValueError("Vents must have an axis-aligned unit normal")
        axis = axes[0]
        if min(abs(center[axis]), abs(center[axis] - bounds[axis])) > 1e-7:
            raise ValueError("Vents must lie on a domain boundary")
        box = _bounds(center, size)
        box[2 * axis] = box[2 * axis + 1] = center[axis]
        for a in range(3):
            if a == axis:
                continue
            if size[a] <= 0 or box[2 * a] < -1e-7 or box[2 * a + 1] > bounds[a] + 1e-7:
                raise ValueError("Vent rectangle is empty or outside the domain")
        snapped = _snap_box(box, spacing, ijk)
        snapped[2 * axis] = snapped[2 * axis + 1] = center[axis]
        area = math.prod(snapped[2 * a + 1] - snapped[2 * a] for a in range(3) if a != axis)
        for obj in objects:
            if obj["bounds_m"][2 * axis] - 1e-8 <= center[axis] <= obj["bounds_m"][2 * axis + 1] + 1e-8:
                if all(
                    min(snapped[2 * a + 1], obj["bounds_m"][2 * a + 1])
                    > max(snapped[2 * a], obj["bounds_m"][2 * a]) + 1e-8
                    for a in range(3)
                    if a != axis
                ):
                    raise ValueError(f"Vent {vent.get('id', index)} blocked by {obj['id']}")
        for other in vents:
            if (
                other["axis"] == axis
                and abs(other["bounds_m"][2 * axis] - center[axis]) < 1e-8
                and all(
                    min(snapped[2 * a + 1], other["bounds_m"][2 * a + 1])
                    > max(snapped[2 * a], other["bounds_m"][2 * a]) + 1e-8
                    for a in range(3)
                    if a != axis
                )
            ):
                raise ValueError("Vent rectangles overlap after mesh snapping")
        vents.append(
            {
                "id": str(vent.get("id", f"vent-{index}")),
                "fds_id": f"VENT_{index:03d}",
                "role": role,
                "axis": axis,
                "normal": normal,
                "bounds_m": snapped,
                "original_bounds_m": box,
                "area_m2": area,
            }
        )
    inlet_area = sum(v["area_m2"] for v in vents if v["role"] == "inlet")
    outlet_area = sum(v["area_m2"] for v in vents if v["role"] == "outlet")
    if cfg["airflow_m_s"] > 0 and (not inlet_area or not outlet_area):
        raise ValueError("Nonzero airflow requires both inlet and outlet")
    volume_flow = cfg["airflow_m_s"] * inlet_area
    for vent in vents:
        total_area = inlet_area if vent["role"] == "inlet" else outlet_area
        vent["volume_flow_m3_s"] = volume_flow * vent["area_m2"] / total_area if total_area else 0
        if vent["role"] == "inlet":
            vent["volume_flow_m3_s"] *= -1

    # Exact mole-to-mass conversion for explicitly dry O2/N2 background.
    x_o2 = cfg["oxygen_percent"] / 100
    y_o2 = x_o2 * 31.9988 / (x_o2 * 31.9988 + (1 - x_o2) * 28.0134)
    lines = [
        "! Generated by IGNIS. SI inputs; FDS heat release uses kW. See manifest.json.",
        "&HEAD CHID='ignis', TITLE='IGNIS exploratory compartment simulation' /",
        f"&MESH IJK={','.join(map(str, ijk))}, XB={_num(domain)} /",
        f"&TIME T_END={cfg['duration_s']:.10g} /",
        f"&MISC TMPA={cfg['ambient_temperature_c']:.10g}, P_INF={cfg['pressure_pa']:.10g}, "
        f"GVEC=0.0,0.0,{-9.80665 * cfg['gravity_g']:.10g}, Y_O2_INFTY={y_o2:.12g}, "
        f"Y_CO2_INFTY=0.0, HUMIDITY=0.0, RND_SEED={cfg['seed']} /",
        fuel_species_line(cfg["material_id"]),
        reaction_line(cfg["material_id"]),
        f"&DUMP DT_DEVC={cfg['sample_interval_s']:.10g}, DT_HRR={cfg['sample_interval_s']:.10g}, "
        "SMOKE3D=F, COLUMN_DUMP_LIMIT=F, SIG_FIGS=8 /",
    ]
    # Fixed geometry enclosures, each face represented by a 1 cm conductive sheet.
    for mid, (rho, conductivity, cp, emissivity) in INERT_MATERIALS.items():
        lines.append(
            f"&MATL ID='INERT_{mid}', DENSITY={rho:.9g}, CONDUCTIVITY={conductivity:.9g}, SPECIFIC_HEAT={cp:.9g}, EMISSIVITY={emissivity:.9g} /"
        )
        extra = ", DEFAULT=T" if mid == "aluminium" else ""
        lines.append(
            f"&SURF ID='LINER_{mid}', MATL_ID='INERT_{mid}', THICKNESS=0.01, BACKING='INSULATED'{extra} /"
        )
    if cfg["source_model"] == "coupled_combustion":
        lines.extend(solid_material_lines(cfg["material_id"]))

    start = cfg["ignition_delay_s"]
    stop = min(start + cfg["ignition_duration_s"], cfg["duration_s"])
    active = source is not None and cfg["ignition_power_w"] > 0 and stop > start
    ramp = []
    if active:
        epsilon = min(0.01, (stop - start) / 10)
        ramp = (
            [(0.0, 0.0), (start, 0.0), (start + epsilon, 1.0), (stop - epsilon, 1.0), (stop, 0.0)]
            if start > 0
            else [(0.0, 1.0), (stop - epsilon, 1.0), (stop, 0.0)]
        )
        # Merge duplicate t=0 without adding an artificial finite startup pulse.
        ramp = sorted(dict(ramp).items())
        lines.extend(f"&RAMP ID='SOURCE_RAMP', T={t:.10g}, F={f:.10g} /" for t, f in ramp)

    source_area = None
    source_flux = None
    for obj in objects:
        if obj["role"] == "fuel":
            area = (obj["bounds_m"][1] - obj["bounds_m"][0]) * (obj["bounds_m"][3] - obj["bounds_m"][2])
            target = obj is source and active
            flux = cfg["ignition_power_w"] / 1000 / area if target else 0
            if obj is source:
                source_area, source_flux = area, flux
            sid = f"FUEL_{obj['fds_id']}"
            if cfg["source_model"] == "coupled_combustion":
                extra = f", EXTERNAL_FLUX={flux:.10g}, RAMP_EF='SOURCE_RAMP'" if target else ""
                lines.append(
                    f"&SURF ID='{sid}', MATL_ID='IGNIS_SOLID', THICKNESS={obj['thermal_thickness_m']:.10g}, BACKING='INSULATED'{extra} /"
                )
            elif target:
                lines.append(f"&SURF ID='{sid}', HRRPUA={flux:.10g}, RAMP_Q='SOURCE_RAMP' /")
            else:
                sid = "LINER_aluminium"
            lines.append(
                f"&OBST ID='{obj['fds_id']}', XB={_num(obj['bounds_m'])}, SURF_IDS='{sid}','LINER_aluminium','LINER_aluminium' /"
            )
        else:
            lines.append(
                f"&OBST ID='{obj['fds_id']}', XB={_num(obj['bounds_m'])}, SURF_ID='LINER_{obj['material_id']}' /"
            )
    for vent in vents:
        lines.append(f"&SURF ID='{vent['fds_id']}', VOLUME_FLOW={vent['volume_flow_m3_s']:.12g}, TAU_V=0.0 /")
        lines.append(f"&VENT XB={_num(vent['bounds_m'])}, SURF_ID='{vent['fds_id']}' /")

    # Every field is a real FDS point-device output. Never interpolate masked solids.
    axes = [
        [
            (math.floor((i + 0.5) * ijk[a] / cfg["sample_shape"][a]) + 0.5) * spacing[a]
            for i in range(cfg["sample_shape"][a])
        ]
        for a in range(3)
    ]
    positions = [list(p) for p in itertools.product(*axes)]
    valid_mask = [not any(_inside(p, o["bounds_m"]) for o in objects) for p in positions]
    if not any(valid_mask):
        raise ValueError("Spatial sampling contains no gas points; adjust objects or sampling shape")
    fields = {
        "T": ("TEMPERATURE", None),
        "O2": ("VOLUME FRACTION", "OXYGEN"),
        "S": ("DENSITY", "SOOT"),
        "U": ("U-VELOCITY", None),
        "V": ("V-VELOCITY", None),
        "W": ("W-VELOCITY", None),
    }

    def add_device(identifier: str, position: list[float], field: str) -> None:
        quantity, species = fields[field]
        spec = f", SPEC_ID='{species}'" if species else ""
        lines.append(
            f"&DEVC ID='{identifier}', XYZ={_num(position)}, QUANTITY='{quantity}'{spec}, TIME_AVERAGED=F /"
        )

    for index, (position, valid) in enumerate(zip(positions, valid_mask)):
        if valid:
            for field in fields:
                add_device(f"P{index:04d}_{field}", position, field)
    sensors = []
    for index, sensor in enumerate(scene.get("sensors", [])):
        position = _vec(sensor.get("position_m"), "sensor.position_m", 0, 30)
        if any(not 0 < position[a] < bounds[a] for a in range(3)):
            raise ValueError(f"Sensor {sensor.get('id', index)} must be strictly inside the gas domain")
        sampled = [(min(ijk[a] - 1, int(position[a] / spacing[a])) + 0.5) * spacing[a] for a in range(3)]
        valid = not any(_inside(sampled, o["bounds_m"]) for o in objects)
        identifier = f"S{index:03d}"
        sensors.append(
            {
                "id": str(sensor.get("id", identifier)),
                "fds_id": identifier,
                "position_m": position,
                "sampled_cell_center_m": sampled,
                "valid": valid,
            }
        )
        if valid:
            for field in fields:
                add_device(f"{identifier}_{field}", position, field)
        else:
            warnings.append(
                f"Sensor {sensor.get('id', index)} lies in a solid after discretization; no measurement emitted."
            )

    global_devices = {
        "G_TMAX": ("TEMPERATURE", "MAX", None),
        "G_TMEAN": ("TEMPERATURE", "VOLUME MEAN", None),
        "G_O2": ("VOLUME FRACTION", "VOLUME MEAN", "OXYGEN"),
        "G_SOOT": ("DENSITY", "VOLUME MEAN", "SOOT"),
        "G_HRR": ("HRRPUV", "VOLUME INTEGRAL", None),
        "G_MASS": ("DENSITY", "VOLUME INTEGRAL", None),
    }
    for identifier, (quantity, statistic, species) in global_devices.items():
        spec = f", SPEC_ID='{species}'" if species else ""
        lines.append(
            f"&DEVC ID='{identifier}', XB={_num(domain)}, QUANTITY='{quantity}'{spec}, SPATIAL_STATISTIC='{statistic}', TIME_AVERAGED=F /"
        )
    for vent in vents:
        lines.append(
            f"&DEVC ID='FLOW_{vent['fds_id']}', XB={_num(domain)}, QUANTITY='NORMAL VELOCITY', SURF_ID='{vent['fds_id']}', SPATIAL_STATISTIC='SURFACE INTEGRAL', TIME_AVERAGED=F /"
        )
    surface_devices = []
    if cfg["source_model"] == "coupled_combustion":
        for obj in fuel_objects:
            box = obj["bounds_m"]
            center = [(box[0] + box[1]) / 2, (box[2] + box[3]) / 2, box[5]]
            prefix = f"SURFACE_{obj['fds_id']}"
            for suffix, quantity, extra in [
                ("T", "WALL TEMPERATURE", ""),
                ("M", "MASS FLUX", ", SPEC_ID='IGNIS_FUEL'"),
                ("D", "WALL THICKNESS", ""),
                ("Q", "NET HEAT FLUX", ""),
            ]:
                lines.append(
                    f"&DEVC ID='{prefix}_{suffix}', XYZ={_num(center)}, IOR=3, QUANTITY='{quantity}'{extra}, TIME_AVERAGED=F /"
                )
            surface_devices.append(
                {
                    "object_id": obj["id"],
                    "fds_id": prefix,
                    "position_m": center,
                    "measurement_basis": "one cell at upper-face center; not an area mean",
                }
            )
    lines.append("&TAIL /")
    deck = "\n".join(lines) + "\n"
    pulse_integral = sum((tb - ta) * (fa + fb) / 2 for (ta, fa), (tb, fb) in zip(ramp, ramp[1:]))
    sample_count = sum(valid_mask)
    estimated_csv_bytes = int(
        (sample_count * 6 + len(sensors) * 6 + len(surface_devices) * 4 + 10)
        * 24
        * (math.ceil(cfg["duration_s"] / cfg["sample_interval_s"]) + 1)
    )
    if estimated_csv_bytes > MAX_ESTIMATED_CSV_BYTES:
        raise ValueError(
            "Estimated device output exceeds 256 MiB; increase sampling interval or reduce sampling shape"
        )
    manifest = {
        "schema_version": 1,
        "engine": "FDS",
        "engine_version": ENGINE_VERSION,
        "compiler_version": COMPILER_VERSION,
        "material_model_version": MODEL_VERSION,
        "chid": "ignis",
        "input_file": "ignis.fds",
        "scene_id": scene.get("id"),
        "scene_sha256": hashlib.sha256(_json_bytes(scene)).hexdigest(),
        "config_sha256": hashlib.sha256(_json_bytes(cfg)).hexdigest(),
        "deck_sha256": hashlib.sha256(deck.encode()).hexdigest(),
        "config": cfg,
        "mesh": {"shape": ijk, "bounds_m": bounds, "cell_size_m": spacing, "cell_count": math.prod(ijk)},
        "sampling": {
            "shape": cfg["sample_shape"],
            "bounds_m": bounds,
            "axes_m": axes,
            "positions_m": positions,
            "valid_mask": valid_mask,
            "order": "x,y,z; z fastest",
            "method": "FDS cell values at gas-only DEVC points; velocity components use nearest staggered cell faces",
            "interval_s": cfg["sample_interval_s"],
            "time_averaged": False,
        },
        "objects": objects,
        "vents": vents,
        "sensors": sensors,
        "surface_devices": surface_devices,
        "source": {
            "object_id": source["id"] if source else None,
            "area_m2": source_area,
            "flux_kw_m2": source_flux,
            "ramp": ramp,
            "imposed_pulse_energy_j": pulse_integral * cfg["ignition_power_w"],
            "meaning": "nominal chemical HRR, oxygen limited"
            if cfg["source_model"] == "prescribed_source"
            else "incident external surface heat flux; chemical HRR computed by FDS",
        },
        "material": deepcopy(MATERIALS[cfg["material_id"]]),
        "air": {
            "oxygen_mole_fraction": x_o2,
            "oxygen_mass_fraction": y_o2,
            "humidity_percent": 0.0,
            "co2_mass_fraction": 0.0,
        },
        "ventilation": {
            "inlet_volume_flow_m3_s": volume_flow,
            "outlet_volume_flow_m3_s": volume_flow,
            "balance": "prescribed volumetric balance, not equal mass flux when temperatures differ",
        },
        "scientific_status": "exploratory_not_calibrated",
        "warnings": warnings,
        "estimates": {
            "device_count": sample_count * 6
            + sum(s["valid"] for s in sensors) * 6
            + len(global_devices)
            + len(vents)
            + len(surface_devices) * 4,
            "csv_bytes_uncompressed": estimated_csv_bytes,
        },
    }
    output_dir = Path(output_dir)
    if (output_dir / "ignis.fds").exists() or (output_dir / "manifest.json").exists():
        raise FileExistsError("Case inputs already exist; use a unique run directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    # write_text translates LF to CRLF on Windows, which would invalidate the
    # byte-level hash computed above. The solver accepts the canonical LF bytes.
    (output_dir / "ignis.fds").write_bytes(deck.encode("ascii"))
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    return manifest
