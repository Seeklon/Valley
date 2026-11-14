"""Deterministic compact selection from the procedural FDS corpus.

This module designs cases only: it never starts a solver or writes a dataset.
It preserves the original scene, config, ID and fingerprint of every selected
case so a separate runner can verify and reuse already completed artifacts.
"""

from __future__ import annotations

import numpy as np
from ignis.provenance import canonical_sha

if __package__:
    from . import generate_spatial_corpus as original
else:
    import generate_spatial_corpus as original

DATASET_ID = "spatial-compact-v1"
DESIGN_VERSION = "procedural-spatial-compact-design-1"
SOURCE_DESIGN_VERSION = "procedural-spatial-design-1"
DEFAULT_LAYOUT_COUNT = 200
MAX_LAYOUT_COUNT = 1000
SAMPLE_SHAPE = tuple(original.SAMPLE_SHAPE)


def build_design(source_hashes: dict, layout_count: int = DEFAULT_LAYOUT_COUNT) -> dict:
    """Select two gravity-paired original cases per room; keep all ten families.

    Incident changes every ten rooms, independently of the structural family.
    Condition changes every fifty rooms. Replaying only the original numeric
    condition draws preserves exact case inputs without building 20,000 runs.
    """
    if (
        isinstance(layout_count, bool)
        or not isinstance(layout_count, int)
        or not 0 < layout_count <= MAX_LAYOUT_COUNT
        or layout_count % 50
    ):
        raise ValueError("layout_count must be a positive multiple of 50, at most 1000")
    if original.DESIGN_VERSION != SOURCE_DESIGN_VERSION:
        raise ValueError("Original design version changed; verify compact selection before reusing cases")

    rng = np.random.default_rng(original.SEED)
    layouts, runs = [], []
    for index in range(layout_count):
        structural_family, split = original.STRUCTURES[index % len(original.STRUCTURES)]
        scene, mesh_cell = original.procedural_scene(index, structural_family)
        layout = {
            "layout_id": scene["id"],
            "scene_id": scene["id"],
            "scene": scene,
            "split": split,
            "structural_family": structural_family,
            "scene_sha256": canonical_sha(scene),
            "mesh_cell_m": mesh_cell,
        }
        layouts.append(layout)
        selected_incident = (index // 10) % len(original.INCIDENT_TYPES)
        condition = (index // 50) % 2
        selected_unit = None
        for incident_index in range(len(original.INCIDENT_TYPES)):
            # Keep the exact original draw order, including unselected incidents.
            unit = np.column_stack([(rng.permutation(2) + rng.random(2)) / 2 for _ in range(3)])
            if incident_index == selected_incident:
                selected_unit = unit[condition]
        incident = original.INCIDENT_TYPES[selected_incident]
        component = scene["components"][
            (2 * selected_incident + condition + index) % len(scene["components"])
        ]
        power, air, oxygen = [
            round(value, 6) for value in np.array([500, 0.05, 18]) + selected_unit * [2500, 0.35, 6]
        ]
        pair_index = index * len(original.INCIDENT_TYPES) * 2 + selected_incident * 2 + condition
        for gravity_label, gravity in (("microg", 0.0001), ("earth", 1.0)):
            config = {
                "scene_id": scene["id"],
                "source_model": "coupled_combustion",
                "ignition_kind": "thermal",
                "incident_type": incident,
                "component_id": component["id"],
                "gravity_g": gravity,
                "airflow_m_s": air,
                "oxygen_percent": oxygen,
                "ignition_power_w": power,
                "ignition_duration_s": 1 if incident == "arc" else 10,
                "duration_s": 30,
                "seed": 710000 + pair_index,
                "material_id": "cellulose",
                "mesh_cell_m": mesh_cell,
                "sample_shape": list(SAMPLE_SHAPE),
                "sample_interval_s": 1,
                "ambient_temperature_c": 20,
                "pressure_pa": 101325,
                "ignition_delay_s": 0,
            }
            identifier = f"{layout['layout_id']}-{component['id']}-{incident}-{gravity_label}-c{condition}"
            runs.append(
                {
                    "id": identifier,
                    "layout_id": layout["layout_id"],
                    "scene_id": scene["id"],
                    "split": split,
                    "condition_id": condition,
                    "config": config,
                    "structural_family": structural_family,
                    "scene_sha256": layout["scene_sha256"],
                    "relative_path": f"runs/{identifier}",
                    "fingerprint": canonical_sha(
                        {"scene": scene, "config": config, "compiler": original.COMPILER_VERSION}
                    ),
                }
            )

    return {
        "dataset_id": DATASET_ID,
        "design_version": DESIGN_VERSION,
        "seed": original.SEED,
        "compiler_version": original.COMPILER_VERSION,
        "material_model_version": original.MODEL_VERSION,
        "compiler_source_hashes": dict(source_hashes),
        "expected_runs": len(runs),
        "layouts": layouts,
        "runs": runs,
        "source_dataset_id": original.DATASET_ID,
        "source_design_version": SOURCE_DESIGN_VERSION,
        "selection": {
            "layout_count": layout_count,
            "scenarios_per_layout": 2,
            "layout_indices": f"0..{layout_count - 1}",
            "incident_index": "(layout_index // 10) % 5",
            "condition_index": "(layout_index // 50) % 2",
            "reuse": "Exact original scene/config/ID/fingerprint; verify artifacts before copy or hardlink",
        },
        "partition": (
            "Whole structural families: six train, two validation, two test; "
            "both gravity scenarios of every room remain together"
        ),
        "parameter_design": (
            "Deterministic subset of original seeded Latin-hypercube conditions; one incident and "
            "one annotated source per room, paired across gravities; all five incidents balanced "
            "within each structural family in every 50-room block"
        ),
    }
