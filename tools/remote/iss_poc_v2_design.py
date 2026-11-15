"""Diverse, bounded ISS-inspired FDS design; independent of the frozen v1 data.

All scene coordinates and sources are mesh aligned. Entire layouts and exact
condition grids are reserved per split before any solver output is observed.
"""

from __future__ import annotations

import copy

import numpy as np
from ignis.provenance import canonical_sha

if __package__:
    from . import iss_poc_design as previous
else:
    import iss_poc_design as previous

original = previous.original
DATASET_ID = "iss-poc-20261115-v2"
DESIGN_VERSION = "iss-inspired-poc-design-2"
SEED = 2026111502
SAMPLE_SHAPE = [12, 16, 8]
FAMILIES = (*previous.FAMILIES, "habitat-cargo", "habitat-capsule", "habitat-central-racks")
SPLITS = ("train",) * 5 + ("validation",) + ("test",) * 2
CONDITIONS = {
    "train": {"air": [0.04, 0.12, 0.22, 0.34], "power": [1200, 2000, 3200, 4400], "duration": [10, 16, 24]},
    "validation": {"air": [0.08, 0.18, 0.28], "power": [1600, 2600, 3800], "duration": [12, 20, 26]},
    "test": {"air": [0.06, 0.16, 0.30], "power": [1400, 2400, 4000], "duration": [14, 18, 22]},
}


def normalized_geometry(scene: dict) -> str:
    """Geometry alone: neither naming, material changes nor scale can hide reuse."""
    return canonical_sha(
        sorted(
            [
                {
                    key: [round(v / scene["bounds_m"][a], 8) for a, v in enumerate(obj[key])]
                    for key in ("center_m", "size_m")
                }
                for obj in scene["objects"]
            ],
            key=lambda o: (*o["center_m"], *o["size_m"]),
        )
    )


def compartment(family: str, variant: int) -> tuple[dict, float]:
    if family not in FAMILIES or variant not in range(len(SPLITS)):
        raise ValueError("Unknown v2 compartment")
    fi = FAMILIES.index(family)
    rng = np.random.default_rng(SEED + fi * 1000 + variant)
    cell = round(float(rng.uniform(0.138, 0.162)), 6)
    shapes = {
        "iss-laboratory": [24, 32, 20],
        "iss-node": [24, 24, 24],
        "iss-service": [20, 36, 24],
        "habitat-cargo": [24, 32, 20],
        "habitat-capsule": [24, 24, 24],
        "habitat-central-racks": [24, 36, 20],
    }
    shape = shapes[family]
    if family == "iss-laboratory":
        boxes = [
            ("rack-port-front", [1, 5, 3, 10, 0, 10]),
            ("rack-starboard-front", [19, 23, 3, 10, 0, 10]),
            ("rack-port-aft", [1, 5, 21, 28, 0, 10]),
            ("rack-starboard-aft", [19, 23, 21, 28, 0, 10]),
        ]
        baffles = [("cross-baffle", [10, 13, 14, 17, 0, 6])]
    elif family == "iss-node":
        boxes = [
            ("avionics-port", [1, 6, 3, 9, 0, 10]),
            ("avionics-starboard", [18, 23, 15, 21, 0, 10]),
            ("utility-bay", [1, 6, 15, 21, 0, 10]),
        ]
        baffles = [("hatch-baffle", [11, 13, 17, 21, 0, 6]), ("passage-baffle", [11, 13, 3, 6, 0, 5])]
    elif family == "iss-service":
        boxes = [
            ("power-cabinet", [1, 5, 3, 10, 0, 10]),
            ("battery-cabinet", [15, 19, 14, 21, 0, 10]),
            ("cable-bay", [1, 5, 26, 33, 0, 10]),
        ]
        baffles = [("service-baffle", [8, 11, 21, 25, 0, 6])]
    elif family == "habitat-cargo":
        boxes = [
            ("cargo-port-forward", [2, 8, 3, 10, 0, 9]),
            ("cargo-starboard-forward", [16, 22, 3, 10, 0, 9]),
            ("cargo-port-aft", [2, 8, 21, 28, 0, 9]),
            ("cargo-starboard-aft", [16, 22, 21, 28, 0, 9]),
        ]
        baffles = [("cargo-divider", [10, 13, 14, 17, 0, 8])]
    elif family == "habitat-capsule":
        boxes = [
            ("seat-console-port", [2, 7, 3, 9, 0, 8]),
            ("seat-console-starboard", [17, 22, 3, 9, 0, 8]),
            ("rear-avionics", [9, 15, 16, 21, 0, 11]),
        ]
        baffles = [("pod-side-panel", [2, 4, 14, 18, 0, 6])]
    else:
        boxes = [
            ("central-rack-forward", [9, 15, 3, 9, 0, 10]),
            ("central-rack-middle", [9, 15, 15, 21, 0, 10]),
            ("central-rack-aft", [9, 15, 26, 32, 0, 10]),
        ]
        baffles = [("port-divider", [3, 5, 15, 19, 0, 6]), ("starboard-divider", [20, 22, 25, 29, 0, 8])]
    changed = []
    for i, (name, box) in enumerate(boxes):
        box = list(box)
        dy = int(rng.integers(-2, 3))
        box[2] += dy
        box[3] += dy + int(rng.integers(-1, 2))
        if box[0] < shape[0] / 2:
            box[1] += int(rng.integers(-1, 3))
        else:
            box[0] -= int(rng.integers(-1, 3))
        # Resolve the gas immediately above source-bearing surfaces rather than
        # adding a hot target to an unobserved point after the simulation.
        observed_z = [int((j + 0.5) * shape[2] / SAMPLE_SHAPE[2]) for j in range(SAMPLE_SHAPE[2])]
        box[5] = int(rng.choice([z for z in observed_z if 6 <= z <= 13]))
        support = ("aluminium", "steel", "insulation", "glass")[(variant + fi + i) % 4]
        coating = ("pmma", "cellulose", "pmma", "cellulose", None)[(variant + 2 * i + fi) % 5]
        thickness = (0.0006, 0.001, 0.0018, 0.003, 0.005)[(variant + i + 2 * fi) % 5]
        changed.append((name, box, support, coating, thickness))
    for i, (name, box) in enumerate(baffles):
        box = list(box)
        box[0] += int(rng.integers(-1, 2))
        box[1] = box[0] + int(rng.integers(1, 4))
        box[5] = int(rng.integers(4, 11))
        changed.append((name, box, ("steel", "aluminium")[(variant + i) % 2], None, 0.002))
    objects = []
    for i, (name, box, support, coating, thickness) in enumerate(changed):
        physical = [round(n * cell, 6) for n in box]
        obj = {
            "id": name,
            "name": name.replace("-", " ").title(),
            "role": "obstacle",
            "kind": "equipment" if i < len(boxes) else "baffle",
            "material_id": support,
            "center_m": [(physical[2 * a] + physical[2 * a + 1]) / 2 for a in range(3)],
            "size_m": [physical[2 * a + 1] - physical[2 * a] for a in range(3)],
            "thermal_thickness_m": thickness,
        }
        if coating:
            obj["combustible_material_id"] = coating
        objects.append(obj)
    components = []
    for i in range(3):
        box = changed[i][1]
        point = []
        for axis in range(2):
            sampled = [int((j + 0.5) * shape[axis] / SAMPLE_SHAPE[axis]) for j in range(SAMPLE_SHAPE[axis])]
            candidates = [j for j in sampled if box[2 * axis] <= j < box[2 * axis + 1]]
            point.append(round((int(rng.choice(candidates)) + 0.5) * cell, 6))
        point.append(round(box[5] * cell, 6))
        components.append(
            {
                "id": f"electrical-{i:02d}",
                "object_id": objects[i]["id"],
                "kind": "electrical",
                "face": 3,
                "critical": i == 0,
                "position_m": point,
                "provenance": "Synthetic upper-face electrical source; not actual ISS equipment",
            }
        )
    bounds = [round(n * cell, 6) for n in shape]
    # Vary the actual boundary axis and inlet/outlet assignment, not a label.
    axis = (variant + fi) % 2
    reverse = ((variant + fi) // 2) % 2
    tangent = 1 - axis
    vents = []
    for i, role in enumerate(("inlet", "outlet")):
        wall = (i + reverse) % 2
        center = [bounds[0] / 2, bounds[1] / 2, (14 + (variant % 2)) * cell]
        center[axis] = bounds[axis] * wall
        center[tangent] = (shape[tangent] // 2 + int(rng.integers(-2, 3))) * cell
        size = [0.0, 0.0, (4 + 2 * (variant % 3)) * cell]
        size[tangent] = (6 + 2 * ((variant + i) % 3)) * cell
        normal = [0, 0, 0]
        normal[axis] = 1 if wall == 0 else -1
        vents.append({"id": role, "role": role, "center_m": center, "size_m": size, "normal": normal})
    scene = {
        "id": f"{family}-v2-{variant:02d}",
        "name": f"{family.replace('iss-', '').title()} · v2 {variant + 1}",
        "units": "m",
        "coordinate_system": "right-handed Z-up",
        "bounds_m": bounds,
        "geometry_family": family,
        "objects": objects,
        "components": components,
        "vents": vents,
        "sensors": [],
        "source_position_m": components[0]["position_m"],
        "provenance": "Original simplified ISS-inspired compartment; not actual ISS plans or NASA observations",
    }
    return scene, cell


def build_design(source_hashes: dict) -> dict:
    layouts, runs = [], []
    for variant, split in enumerate(SPLITS):
        grid = CONDITIONS[split]
        for fi, family in enumerate(FAMILIES):
            scene, cell = compartment(family, variant)
            layout = {
                "layout_id": scene["id"],
                "scene_id": scene["id"],
                "scene": scene,
                "split": split,
                "structural_family": family,
                "scene_sha256": canonical_sha(scene),
                "mesh_cell_m": cell,
                "normalized_geometry_sha256": normalized_geometry(scene),
            }
            layouts.append(layout)
            key = variant + fi
            power = grid["power"][key % len(grid["power"])]
            pulse = grid["duration"][key % len(grid["duration"])]
            air = grid["air"][key % len(grid["air"])]
            secondary = grid["power"][(key + 1) % len(grid["power"])]
            delay = (0, 2, 4)[key % 3]
            profiles = [
                ("flame", "flaming", key % 3, power, pulse, air, delay, 0.0001),
                (
                    "flame-alt",
                    "flaming",
                    (key + 1) % 3,
                    secondary,
                    grid["duration"][(key + 1) % 3],
                    grid["air"][(key + 1) % len(grid["air"])],
                    0,
                    0.0001,
                ),
                ("battery", "battery", (key + 2) % 3, power, min(26, pulse + 4), air, delay, 0.0001),
                ("smolder", "smoldering", key % 3, power / 3, min(28, pulse + 4), air, 0, 0.0001),
                ("thermal", "overheating", (key + 1) % 3, power, pulse, air, delay, 0.0001),
                ("arc", "arc", (key + 2) % 3, secondary, (2, 4, 6)[key % 3], air, 0, 0.0001),
                ("control", "overheating", key % 3, 0, 0, air, 0, 0.0001),
                ("flame-earth", "flaming", key % 3, power, pulse, air, delay, 1.0),
            ]
            for ci, (label, incident, source, watts, duration, airflow, ignition_delay, gravity) in enumerate(
                profiles
            ):
                config = {
                    "scene_id": scene["id"],
                    "source_model": "coupled_combustion",
                    "ignition_kind": "thermal",
                    "incident_type": incident,
                    "component_id": scene["components"][source]["id"],
                    "gravity_g": gravity,
                    "airflow_m_s": airflow,
                    "oxygen_percent": 21.0,
                    "ignition_power_w": watts,
                    "ignition_duration_s": duration,
                    "duration_s": 30,
                    "seed": SEED + variant * 100 + fi * 10,
                    "material_id": "cellulose",
                    "mesh_cell_m": cell,
                    "sample_shape": list(SAMPLE_SHAPE),
                    "sample_interval_s": 1,
                    "ambient_temperature_c": 20,
                    "pressure_pa": 101325,
                    "ignition_delay_s": ignition_delay,
                }
                identifier = f"{scene['id']}-{label}"
                runs.append(
                    {
                        "id": identifier,
                        "layout_id": scene["id"],
                        "scene_id": scene["id"],
                        "split": split,
                        "structural_family": family,
                        "condition_id": ci,
                        "condition_group": f"{split}-grid",
                        "scene_sha256": layout["scene_sha256"],
                        "config": config,
                        "relative_path": f"runs/{identifier}",
                        "fingerprint": canonical_sha(
                            {"scene": scene, "config": config, "compiler": original.COMPILER_VERSION}
                        ),
                        "evaluation_role": "zero-input control"
                        if label == "control"
                        else "diverse ISS-inspired POC",
                    }
                )
    return {
        "dataset_id": DATASET_ID,
        "design_version": DESIGN_VERSION,
        "seed": SEED,
        "compiler_version": original.COMPILER_VERSION,
        "material_model_version": original.MODEL_VERSION,
        "compiler_source_hashes": dict(source_hashes),
        "expected_runs": len(runs),
        "layouts": layouts,
        "runs": runs,
        "partition": "Whole new layouts: 30 train, 6 validation, 12 test; 240/48/96 cases; exact condition grids held out",
        "partition_policy": "disjoint_physical_layouts_and_exact_condition_grids_shared_targeted_families",
        "parameter_design": "48 original compartments in six ISS/habitat families, eight incidents/controls each; 336 microgravity and 48 matched Earth flames",
        "condition_grids": copy.deepcopy(CONDITIONS),
        "limitations": [
            "Synthetic original compartments, not actual ISS plans or NASA experimental data",
            "Shared structural families: targeted geometry/condition interpolation, not a generalist vehicle model",
            "Only upper-face electrical source equivalents; coating physics is upper-face only",
            "Coarse FDS with assumed material/soot parameters; no fault probability or validated battery kinetics",
            "Actual FDS timestamps govern; short arcs can remain temporally unresolved",
        ],
    }


def preflight(design: dict, cache_dir=None) -> dict:
    report = previous.preflight(design, cache_dir=cache_dir)
    signatures = [normalized_geometry(layout["scene"]) for layout in design["layouts"]]
    old = {normalized_geometry(layout["scene"]) for layout in previous.build_design({})["layouts"]}
    if len(set(signatures)) != len(signatures) or set(signatures) & old:
        raise ValueError("V2 normalized geometry repeats itself or a v1 layout")
    report["unique_normalized_layouts"] = len(signatures)
    report["v1_normalized_geometry_overlap"] = 0
    return report


def scheduled_runs(design: dict, *, pilot=False) -> list[dict]:
    by_id = {run["id"]: run for run in design["runs"]}
    # Predeclared diagnostic pilot: inspect train/validation activity, never test.
    ids = [
        "iss-laboratory-v2-00-flame",
        "iss-laboratory-v2-00-control",
        "iss-node-v2-00-battery",
        "iss-service-v2-00-smolder",
        "habitat-cargo-v2-00-flame",
        "habitat-capsule-v2-00-arc",
        "habitat-central-racks-v2-00-thermal",
        "habitat-central-racks-v2-00-flame-earth",
        "habitat-cargo-v2-05-flame",
        "habitat-capsule-v2-05-battery",
        "iss-service-v2-05-smolder",
        "iss-node-v2-05-control",
    ]
    first = [by_id[identifier] for identifier in ids]
    return first if pilot else first + [r for r in design["runs"] if r["id"] not in ids]
