"""Small, reproducible ISS-inspired compartments, without claiming ISS fidelity.

The fixed split separates complete physical layouts. Structural families recur
in all splits deliberately: this experiment measures a targeted POC, not transfer
to a new vehicle family. Only this module's generated inputs define the scenes.
"""

from __future__ import annotations

import copy

from ignis.provenance import canonical_sha

if __package__:
    from . import generate_spatial_corpus as original
else:
    import generate_spatial_corpus as original

DATASET_ID = "iss-poc-20261115-v1"
DESIGN_VERSION = "iss-inspired-poc-design-1"
SEED = 2026111501
SAMPLE_SHAPE = [12, 16, 8]
FAMILIES = ("iss-laboratory", "iss-node", "iss-service")
SPLITS = ("train", "train", "train", "train", "validation", "test")


def compartment(family: str, variant: int) -> tuple[dict, float]:
    if family not in FAMILIES or variant not in range(len(SPLITS)):
        raise ValueError("Unknown ISS-inspired family or layout variant")
    # Every coordinate is an exact multiple of a cell. Scale differences remain
    # in the physical geometry signature and therefore cannot cross partitions.
    scale = (0.94, 1.02, 0.98, 1.06, 1.00, 1.04)[variant]
    cell = round(0.15 * scale, 6)
    if family == "iss-laboratory":
        shape = [24, 32, 20]
        boxes = [
            ("rack-port-front", [1, 5, 3, 11, 0, 11], "aluminium", "pmma"),
            ("rack-starboard-front", [19, 23, 3, 11, 0, 11], "aluminium", "cellulose"),
            ("rack-port-aft", [1, 5, 19, 27, 0, 11], "steel", "cellulose"),
            ("rack-starboard-aft", [19, 23, 19, 27, 0, 11], "aluminium", "pmma"),
        ]
        component_objects = [0, 1, 2]
    elif family == "iss-node":
        shape = [24, 24, 24]
        boxes = [
            ("avionics-port", [1, 7, 3, 9, 0, 11], "aluminium", "pmma"),
            ("avionics-starboard", [17, 23, 15, 21, 0, 11], "aluminium", "cellulose"),
            ("utility-bay", [1, 7, 15, 21, 0, 11], "steel", "cellulose"),
            ("hatch-baffle", [10, 12, 19, 23, 0, 8], "steel", None),
        ]
        component_objects = [0, 1, 2]
    else:
        shape = [20, 36, 24]
        boxes = [
            ("power-cabinet", [1, 5, 3, 11, 0, 11], "aluminium", "pmma"),
            ("battery-cabinet", [15, 19, 13, 21, 0, 11], "steel", "pmma"),
            ("cable-bay", [1, 5, 25, 33, 0, 11], "insulation", "cellulose"),
            ("service-baffle", [8, 10, 21, 25, 0, 7], "aluminium", None),
        ]
        component_objects = [0, 1, 2]
    # Variants change normalized layouts as well as physical dimensions: shift
    # and resize racks, and alter a baffle height. All edits remain mesh-aligned.
    adjusted = []
    shift = (0, 1, -1, 2, -2, 1)[variant]
    width_change = (0, 1, -1, 0, 1, -1)[variant]
    for number, (name, original_box, material, combustible) in enumerate(boxes):
        box = list(original_box)
        dy = shift if number % 2 == 0 else -shift
        dy = max(-box[2], min(shape[1] - box[3], dy))
        box[2] += dy
        box[3] += dy
        if combustible:
            if box[0] < shape[0] / 2:
                box[1] += width_change
            else:
                box[0] -= width_change
        else:
            box[5] += (0, 1, -1, 2, 1, -1)[variant]
        adjusted.append((name, box, material, combustible))
    boxes = adjusted
    bounds = [round(n * cell, 6) for n in shape]
    objects = []
    for name, box, material, combustible in boxes:
        physical = [round(n * cell, 6) for n in box]
        obj = {
            "id": name,
            "name": name.replace("-", " ").title(),
            "role": "obstacle",
            "kind": "equipment" if combustible else "baffle",
            "material_id": material,
            "center_m": [(physical[2 * a] + physical[2 * a + 1]) / 2 for a in range(3)],
            "size_m": [physical[2 * a + 1] - physical[2 * a] for a in range(3)],
            "thermal_thickness_m": 0.002 if combustible == "pmma" else 0.001,
        }
        if combustible:
            obj["combustible_material_id"] = combustible
        objects.append(obj)
    components = []
    for n, object_index in enumerate(component_objects):
        obj = objects[object_index]
        # Source lies on a measured horizontal sample column, inside its proxy.
        box = boxes[object_index][1]
        sample_indices = [
            [int((i + 0.5) * shape[a] / SAMPLE_SHAPE[a]) for i in range(SAMPLE_SHAPE[a])] for a in range(2)
        ]
        source_indices = [
            min(
                (i for i in sample_indices[a] if box[2 * a] <= i < box[2 * a + 1]),
                key=lambda i: abs(i - (box[2 * a] + box[2 * a + 1] - 1) / 2),
            )
            for a in range(2)
        ]
        components.append(
            {
                "id": f"electrical-{n:02d}",
                "object_id": obj["id"],
                "kind": "electrical",
                "face": 3,
                "critical": n == 0,
                "position_m": [
                    round((source_indices[0] + 0.5) * cell, 6),
                    round((source_indices[1] + 0.5) * cell, 6),
                    round(box[5] * cell, 6),
                ],
                "provenance": "synthetic annotated electrical site; no actual ISS equipment specification",
            }
        )
    vents = []
    # Broad opposed openings produce a resolvable imposed ventilation flow.
    for i, role in enumerate(("inlet", "outlet")):
        vents.append(
            {
                "id": role,
                "role": role,
                "center_m": [bounds[0] / 2, bounds[1] * i, 13 * cell],
                "size_m": [8 * cell, 0, 6 * cell],
                "normal": [0, 1 if i == 0 else -1, 0],
            }
        )
    scene = {
        "id": f"{family}-v{variant:02d}",
        "name": f"{family.replace('iss-', '').title()} · disposition {variant + 1}",
        "units": "m",
        "coordinate_system": "right-handed Z-up",
        "bounds_m": bounds,
        "geometry_family": family,
        "objects": objects,
        "components": components,
        "vents": vents,
        "sensors": [],
        "source_position_m": components[0]["position_m"],
        "provenance": "Original simplified ISS-inspired compartment; not an ISS digital twin or NASA dataset",
    }
    return scene, cell


def build_design(source_hashes: dict) -> dict:
    layouts, runs = [], []
    for variant, split in enumerate(SPLITS):
        for family_index, family in enumerate(FAMILIES):
            scene, cell = compartment(family, variant)
            layout = {
                "layout_id": scene["id"],
                "scene_id": scene["id"],
                "scene": scene,
                "split": split,
                "structural_family": family,
                "scene_sha256": canonical_sha(scene),
                "mesh_cell_m": cell,
            }
            layouts.append(layout)
            power = 1500 + 180 * ((variant + family_index) % 6)
            ventilation = [0.08, 0.16, 0.24][(variant + family_index) % 3]
            transient = "overheating" if (variant + family_index) % 2 == 0 else "arc"
            profiles = [
                ("flame", "flaming", 0, power, 15, ventilation, 0.0001),
                ("battery", "battery", 1, power + 300, 20, ventilation, 0.0001),
                ("smolder", "smoldering", 2, 450 + 90 * variant, 20, ventilation, 0.0001),
                (
                    "thermal",
                    transient,
                    variant % 3,
                    power + 700,
                    10 if transient == "overheating" else 1,
                    ventilation,
                    0.0001,
                ),
                ("control", "overheating", variant % 3, 0, 0, ventilation, 0.0001),
                ("flame-earth", "flaming", 0, power, 15, ventilation, 1.0),
            ]
            for condition, (label, incident, source, watts, pulse, airflow, gravity) in enumerate(profiles):
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
                    "ignition_duration_s": pulse,
                    "duration_s": 30,
                    "seed": SEED + variant * 100 + family_index * 10,
                    "material_id": "cellulose",
                    "mesh_cell_m": cell,
                    "sample_shape": list(SAMPLE_SHAPE),
                    "sample_interval_s": 1,
                    "ambient_temperature_c": 20,
                    "pressure_pa": 101325,
                    "ignition_delay_s": 0,
                }
                identifier = f"{scene['id']}-{label}"
                runs.append(
                    {
                        "id": identifier,
                        "layout_id": scene["id"],
                        "scene_id": scene["id"],
                        "split": split,
                        "structural_family": family,
                        "condition_id": condition,
                        "scene_sha256": layout["scene_sha256"],
                        "config": config,
                        "relative_path": f"runs/{identifier}",
                        "fingerprint": canonical_sha(
                            {"scene": scene, "config": config, "compiler": original.COMPILER_VERSION}
                        ),
                        "evaluation_role": "zero-input control"
                        if label == "control"
                        else "targeted ISS-inspired POC",
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
        "partition": "Whole physical layouts: 12 train, 3 validation, 3 test; three ISS-inspired families recur in all splits",
        "partition_policy": "disjoint_physical_layouts_shared_targeted_families",
        "parameter_design": "18 deterministic compartments, six incidents/controls per layout; 90 microgravity and 18 matched Earth flames",
        "limitations": [
            "Synthetic original simplified compartments, not measured ISS geometry",
            "Prescribed electrical incident equivalents, not electrical fault or ignition probability",
            "Coarse FDS and assumed material/soot parameters, not NASA validation",
        ],
    }


def preflight(design: dict, cache_dir=None) -> dict:
    """Reuse the original compiler/geometry check with explicit layout groups."""
    splits = {}
    for run in design["runs"]:
        previous = splits.setdefault(run["layout_id"], run["split"])
        if previous != run["split"]:
            raise ValueError("Physical layout crosses dataset partitions")
    grouped = copy.deepcopy(design)
    for run in grouped["runs"]:
        run["structural_family"] = run["layout_id"]
    report = original.preflight(grouped, cache_dir=cache_dir)
    families = {layout["layout_id"]: layout["structural_family"] for layout in design["layouts"]}
    for identifier, row in report["layouts"].items():
        row["structural_family"] = families[identifier]
    report["partition_policy"] = design["partition_policy"]
    return report


def scheduled_runs(design: dict, *, pilot=False) -> list[dict]:
    by_id = {run["id"]: run for run in design["runs"]}
    ids = [
        "iss-laboratory-v00-flame",
        "iss-laboratory-v00-battery",
        "iss-node-v00-flame",
        "iss-node-v00-thermal",
        "iss-service-v00-smolder",
        "iss-service-v00-control",
    ]
    first = [by_id[identifier] for identifier in ids]
    return first if pilot else first + [run for run in design["runs"] if run["id"] not in ids]
