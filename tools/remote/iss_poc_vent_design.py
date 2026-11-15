"""Paired microgravity ventilation experiment on new physical compartments.

Each quartet holds geometry, material, source, ambient and solver seed fixed.
Only imposed airflow and, for the last member, inlet/outlet roles differ.
"""

from __future__ import annotations

import copy
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
from ignis.physics import compile_case
from ignis.provenance import canonical_sha

if __package__:
    from . import iss_poc_v2_design as previous
else:
    import iss_poc_v2_design as previous

original = previous.original
DATASET_ID = "iss-poc-20261115-vent"
DESIGN_VERSION = "iss-paired-ventilation-1"
SEED = 2026111503
SAMPLE_SHAPE = [12, 16, 8]
FAMILIES = previous.FAMILIES
SPLITS = ("train", "train", "validation", "test")
VENTILATION_STATES = (
    ("still", 0.0, False),
    ("slow", 0.12, False),
    ("fast", 0.36, False),
    ("reverse", 0.36, True),
)
normalized_geometry = previous.normalized_geometry


def scene_for_run(scene: dict, run: dict) -> dict:
    result = copy.deepcopy(scene)
    if run.get("reverse_ventilation"):
        for vent in result["vents"]:
            vent["role"] = "outlet" if vent["role"] == "inlet" else "inlet"
    return result


def compartment(family: str, variant: int) -> tuple[dict, float]:
    if family not in FAMILIES or variant not in range(len(SPLITS)):
        raise ValueError("Unknown ventilation compartment")
    scene, cell = previous.compartment(family, variant)
    fi = FAMILIES.index(family)
    shape = np.rint(np.asarray(scene["bounds_m"]) / cell).astype(int)
    observed_z = [int((j + 0.5) * shape[2] / SAMPLE_SHAPE[2]) for j in range(SAMPLE_SHAPE[2])]
    heights = [z for z in observed_z if 6 <= z <= 13]
    for i, obj in enumerate(scene["objects"]):
        box = np.rint(
            np.array([[c - s / 2, c + s / 2] for c, s in zip(obj["center_m"], obj["size_m"])]) / cell
        ).astype(int)
        if obj["kind"] == "equipment":
            # Genuine mesh-aligned equipment size/height changes, not new IDs
            # or global scaling of a previously held-out scene.
            box[1, (i + variant) % 2] += 1 if (i + variant) % 2 == 0 else -1
            candidates = [z for z in heights if z != box[2, 1]]
            box[2, 1] = candidates[(i + variant + fi) % len(candidates)]
        else:
            box[2, 1] += 1
        obj["center_m"] = (box.mean(axis=1) * cell).tolist()
        obj["size_m"] = ((box[:, 1] - box[:, 0]) * cell).tolist()
    for i, component in enumerate(scene["components"]):
        obj = next(o for o in scene["objects"] if o["id"] == component["object_id"])
        box = np.rint(
            np.array([[c - s / 2, c + s / 2] for c, s in zip(obj["center_m"], obj["size_m"])]) / cell
        ).astype(int)
        point = []
        for axis in range(2):
            samples = [int((j + 0.5) * shape[axis] / SAMPLE_SHAPE[axis]) for j in range(SAMPLE_SHAPE[axis])]
            inside = [n for n in samples if box[axis, 0] <= n < box[axis, 1]]
            point.append(round((inside[(i + variant) % len(inside)] + 0.5) * cell, 6))
        point.append(round(box[2, 1] * cell, 6))
        component["position_m"] = point
        # Ensure the two active source hosts have an actual combustible coating.
        if i < 2:
            obj["combustible_material_id"] = ("pmma", "cellulose")[(i + fi + variant) % 2]
            obj["thermal_thickness_m"] = (0.001, 0.0018, 0.003)[(fi + variant) % 3]
    axis = (fi + variant) % 2
    tangent = 1 - axis
    vents = []
    # Identical opposed vent apertures: reversing roles preserves both area
    # and absolute volume flow. Both sources remain below/near their lower edge.
    for wall in range(2):
        center = [scene["bounds_m"][0] / 2, scene["bounds_m"][1] / 2, 12 * cell]
        center[axis] = scene["bounds_m"][axis] * wall
        size = [0.0, 0.0, 8 * cell]
        size[tangent] = 12 * cell
        normal = [0, 0, 0]
        normal[axis] = 1 if wall == 0 else -1
        vents.append(
            {
                "id": f"wall-{wall}",
                "role": "inlet" if wall == 0 else "outlet",
                "center_m": center,
                "size_m": size,
                "normal": normal,
            }
        )
    scene.update(
        id=f"{family}-vent-{variant:02d}",
        name=f"{family} · ventilation {variant + 1}",
        vents=vents,
        source_position_m=scene["components"][0]["position_m"],
        provenance="Original ventilation-test compartment; synthetic, not measured ISS geometry",
    )
    return scene, cell


def build_design(source_hashes: dict) -> dict:
    layouts, runs = [], []
    for variant, split in enumerate(SPLITS):
        for fi, family in enumerate(FAMILIES):
            scene, cell = compartment(family, variant)
            layout_id = scene["id"]
            layouts.append(
                {
                    "layout_id": layout_id,
                    "scene_id": layout_id,
                    "scene": scene,
                    "split": split,
                    "structural_family": family,
                    "scene_sha256": canonical_sha(scene),
                    "mesh_cell_m": cell,
                    "normalized_geometry_sha256": normalized_geometry(scene),
                }
            )
            key = variant + fi
            alternative = ("battery", "smoldering", "overheating", "arc")[key % 4]
            profiles = [
                ("flaming", 0, (2200, 3000, 3800)[key % 3], 24),
                (
                    alternative,
                    1,
                    900 if alternative == "smoldering" else 3200,
                    8 if alternative == "arc" else 26,
                ),
            ]
            for incident, source, power, duration in profiles:
                for state, airflow, reverse in VENTILATION_STATES:
                    config = {
                        "scene_id": layout_id,
                        "source_model": "coupled_combustion",
                        "ignition_kind": "thermal",
                        "incident_type": incident,
                        "component_id": scene["components"][source]["id"],
                        "gravity_g": 0.0001,
                        "airflow_m_s": airflow,
                        "oxygen_percent": 21.0,
                        "ignition_power_w": power,
                        "ignition_duration_s": duration,
                        "duration_s": 30,
                        "seed": SEED + variant * 100 + fi * 10 + source,
                        "material_id": "cellulose",
                        "mesh_cell_m": cell,
                        "sample_shape": list(SAMPLE_SHAPE),
                        "sample_interval_s": 1,
                        "ambient_temperature_c": 20,
                        "pressure_pa": 101325,
                        "ignition_delay_s": 0,
                    }
                    identifier = f"{layout_id}-{incident}-{state}"
                    item = {
                        "id": identifier,
                        "layout_id": layout_id,
                        "scene_id": layout_id,
                        "split": split,
                        "structural_family": family,
                        "condition_id": len(runs),
                        "condition_group": "paired-ventilation",
                        "ventilation_group_id": f"{layout_id}-{incident}",
                        "ventilation_state": state,
                        "ventilation_axis": "xy"[(fi + variant) % 2],
                        "reverse_ventilation": reverse,
                        "config": config,
                        "relative_path": f"runs/{identifier}",
                        "evaluation_role": "microgravity paired airflow intervention",
                    }
                    effective = scene_for_run(scene, item)
                    item["scene_sha256"] = canonical_sha(effective)
                    item["fingerprint"] = canonical_sha(
                        {"scene": effective, "config": config, "compiler": original.COMPILER_VERSION}
                    )
                    runs.append(item)
            control = copy.deepcopy(runs[-4])
            identifier = f"{layout_id}-control"
            control.update(
                id=identifier,
                condition_id=len(runs),
                ventilation_group_id=None,
                ventilation_state="control",
                relative_path=f"runs/{identifier}",
                evaluation_role="zero-power control",
            )
            control["config"].update(
                incident_type="overheating", ignition_power_w=0, ignition_duration_s=0, airflow_m_s=0.36
            )
            control["fingerprint"] = canonical_sha(
                {"scene": scene, "config": control["config"], "compiler": original.COMPILER_VERSION}
            )
            runs.append(control)
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
        "partition": "24 whole layouts: 12 train, 6 validation, 6 fresh test; 108/54/54 cases",
        "partition_policy": "whole_new_layouts_disjoint_from_v1_v2_and_across_ventilation_splits",
        "parameter_design": "48 fixed-source quartets with 0, 0.12, 0.36 and reversed 0.36 m/s; 24 controls",
        "paired_evaluation": {
            "group_key": "ventilation_group_id",
            "state_key": "ventilation_state",
            "comparisons": [["still", "slow"], ["still", "fast"], ["fast", "reverse"]],
            "varying": ["airflow_m_s", "vent roles only on reverse"],
            "time_policy": "actual FDS timestamps; align explicitly, never index-only",
        },
        "limitations": [
            "Synthetic FDS compartments, not NASA experimental validation",
            "Prescribed incidents, no ignition probability or fault prediction",
            "Only boundary ventilation is prescribed/encoded; internal airflow is solved by FDS",
            "Sources and combustible coatings use upper faces only",
            "Shared families across splits; this tests new layouts, not unseen vehicle families",
        ],
    }


def preflight(design: dict, cache_dir=None) -> dict:
    report = previous.previous.preflight(design, cache_dir=cache_dir)
    signatures = [normalized_geometry(layout["scene"]) for layout in design["layouts"]]
    old = {
        normalized_geometry(layout["scene"])
        for module in (previous, previous.previous)
        for layout in module.build_design({})["layouts"]
    }
    if len(set(signatures)) != len(signatures) or set(signatures) & old:
        raise ValueError("Ventilation geometry repeats itself or a v1/v2 layout")
    groups = {}
    scene_by_id = {layout["layout_id"]: layout["scene"] for layout in design["layouts"]}
    for run in design["runs"]:
        if run["ventilation_group_id"]:
            groups.setdefault(run["ventilation_group_id"], []).append(run)
    for group in groups.values():
        if Counter(run["ventilation_state"] for run in group) != Counter(s[0] for s in VENTILATION_STATES):
            raise ValueError("Incomplete ventilation quartet")
        configs = [{k: v for k, v in run["config"].items() if k != "airflow_m_s"} for run in group]
        if any(config != configs[0] for config in configs[1:]):
            raise ValueError("Quartet changes a non-ventilation condition")
    flows = []
    # Compile all four states per layout, including the reversed role deck.
    for layout in design["layouts"]:
        members = [
            r
            for r in design["runs"]
            if r["layout_id"] == layout["layout_id"] and r["config"]["incident_type"] == "flaming"
        ]
        compiled = []
        for run in members:
            with tempfile.TemporaryDirectory(prefix="ignis-vent-preflight-") as directory:
                manifest = compile_case(
                    scene_for_run(scene_by_id[run["layout_id"]], run), run["config"], Path(directory)
                )
            compiled.append(manifest)
            inlet = [v for v in manifest["vents"] if v["role"] == "inlet"][0]
            outlet = [v for v in manifest["vents"] if v["role"] == "outlet"][0]
            if not np.isclose(inlet["area_m2"], outlet["area_m2"], rtol=0, atol=1e-10):
                raise ValueError("Paired inversion must retain equal aperture areas")
            q = run["config"]["airflow_m_s"] * inlet["area_m2"]
            if not np.isclose(inlet["volume_flow_m3_s"], -q) or not np.isclose(outlet["volume_flow_m3_s"], q):
                raise ValueError("FDS inlet/outlet signs or magnitudes disagree")
            flows.append(
                {
                    "id": run["id"],
                    "state": run["ventilation_state"],
                    "inlet_m3_s": -q,
                    "outlet_m3_s": q,
                    "deck_sha256": manifest["deck_sha256"],
                }
            )
        for manifest in compiled[1:]:
            if any(manifest[k] != compiled[0][k] for k in ("sampling", "objects", "source")):
                raise ValueError("Ventilation quartet changed geometry, material, sample mask or source")
    report.update(
        unique_normalized_layouts=len(signatures),
        v1_v2_normalized_geometry_overlap=0,
        paired_groups=len(groups),
        compiled_ventilation_states=len(flows),
        ventilation_decks=flows,
    )
    return report


def scheduled_runs(design: dict, *, pilot=False) -> list[dict]:
    # Two complete train quartets plus a validation quartet; no test outputs
    # are inspected before model selection has frozen.
    groups = (
        "iss-laboratory-vent-00-flaming",
        "iss-service-vent-00-overheating",
        "habitat-central-racks-vent-02-flaming",
    )
    first = [r for group in groups for r in design["runs"] if r["ventilation_group_id"] == group]
    if len(first) != 12:
        raise ValueError("Pilot must contain exactly three complete non-test quartets")
    ids = {r["id"] for r in first}
    return first if pilot else first + [r for r in design["runs"] if r["id"] not in ids]
