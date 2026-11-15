"""V2 design contracts: new geometry, genuine boundary conditions, sealed test."""

from __future__ import annotations

from collections import Counter

import pytest
from ignis.provenance import canonical_sha
from test_iss_poc_design import script


@pytest.fixture(scope="module")
def module():
    return script("iss_poc_v2_design.py")


@pytest.fixture(scope="module")
def design(module):
    return module.build_design({})


def test_reproducible_population_and_disjoint_layouts(module, design):
    assert len(design["layouts"]) == 48
    assert len(design["runs"]) == design["expected_runs"] == 384
    assert canonical_sha(module.build_design({})) == canonical_sha(design)
    assert Counter(r["split"] for r in design["runs"]) == {"train": 240, "validation": 48, "test": 96}
    assert len({r["fingerprint"] for r in design["runs"]}) == 384
    splits = {}
    for run in design["runs"]:
        splits.setdefault(run["layout_id"], set()).add(run["split"])
    assert all(len(group) == 1 for group in splits.values())
    new = {module.normalized_geometry(layout["scene"]) for layout in design["layouts"]}
    old = {
        module.normalized_geometry(layout["scene"]) for layout in module.previous.build_design({})["layouts"]
    }
    assert len(new) == 48 and not new & old


def test_conditions_are_not_renamed_training_inputs(module, design):
    grids = design["condition_grids"]
    for name in ("air", "power", "duration"):
        groups = [set(grids[split][name]) for split in ("train", "validation", "test")]
        assert all(not a & b for i, a in enumerate(groups) for b in groups[i + 1 :])
    configs = [r["config"] for r in design["runs"]]
    assert Counter(c["gravity_g"] for c in configs) == {0.0001: 336, 1.0: 48}
    assert sum(c["ignition_power_w"] == 0 for c in configs) == 48
    assert {c["incident_type"] for c in configs} == {"flaming", "smoldering", "battery", "arc", "overheating"}
    assert all(c["ignition_duration_s"] >= 2 for c in configs if c["incident_type"] == "arc")
    by_id = {r["id"]: r for r in design["runs"]}
    for layout in design["layouts"]:
        a = by_id[layout["layout_id"] + "-flame"]["config"]
        b = by_id[layout["layout_id"] + "-flame-earth"]["config"]
        assert {k: v for k, v in a.items() if k != "gravity_g"} == {
            k: v for k, v in b.items() if k != "gravity_g"
        }
        assert a["sample_shape"] == [12, 16, 8] and a["duration_s"] == 30


def test_pilot_covers_new_families_but_never_test(module, design):
    selected = module.scheduled_runs(design, pilot=True)
    assert len(selected) == 12
    assert {r["split"] for r in selected} == {"train", "validation"}
    assert {r["structural_family"] for r in selected} == set(module.FAMILIES)
    assert any(r["config"]["ignition_power_w"] == 0 for r in selected)
    full = module.scheduled_runs(design)
    assert len(full) == len({r["id"] for r in full}) == 384
    assert full[:12] == selected


def test_actual_compiler_accepts_geometries_materials_and_sources(module, design):
    report = module.preflight(design)
    assert report["unique_physical_layouts"] == report["unique_normalized_layouts"] == 48
    assert report["unique_source_geometries"] == 144
    assert report["v1_normalized_geometry_overlap"] == 0
    assert all(12000 <= r["cell_count"] <= 19000 for r in report["layouts"].values())
    old = module.previous.preflight(module.previous.build_design({}))
    assert not {r["geometry_sha256"] for r in report["layouts"].values()} & {
        r["geometry_sha256"] for r in old["layouts"].values()
    }
    scenes = [layout["scene"] for layout in design["layouts"]]
    assert {tuple(s["vents"][0]["normal"]) for s in scenes} == {(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)}
    assert len({o["thermal_thickness_m"] for s in scenes for o in s["objects"]}) >= 5
    assert {o.get("combustible_material_id") for s in scenes for o in s["objects"]} == {
        None,
        "pmma",
        "cellulose",
    }


def test_generator_is_independent_and_refuses_cross_dataset_resume(tmp_path, design):
    runner = script("generate_iss_poc_v2.py")
    assert runner.DATASET_ID == "iss-poc-20261115-v2"
    plan, index = runner.prepare_dataset(tmp_path / "v2", design)
    assert plan["dataset_id"] == index["dataset_id"] == runner.DATASET_ID
    changed = {**design, "seed": design["seed"] + 1}
    with pytest.raises(ValueError, match="differs"):
        runner.prepare_dataset(tmp_path / "v2", changed)
