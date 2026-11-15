"""Physical pairing, genuinely new layouts, and signed boundary interventions."""

from collections import Counter, defaultdict

import numpy as np
import pytest
from ignis.physics import compile_case
from ignis.provenance import canonical_sha
from test_iss_poc_design import script


@pytest.fixture(scope="module")
def module():
    return script("iss_poc_vent_design.py")


@pytest.fixture(scope="module")
def design(module):
    return module.build_design({})


def test_new_geometries_and_whole_layout_partitions(module, design):
    assert len(design["layouts"]) == 24
    assert len(design["runs"]) == design["expected_runs"] == 216
    assert Counter(r["split"] for r in design["runs"]) == {"train": 108, "validation": 54, "test": 54}
    assert canonical_sha(module.build_design({})) == canonical_sha(design)
    groups = defaultdict(set)
    for row in design["runs"]:
        groups[row["layout_id"]].add(row["split"])
    assert all(len(splits) == 1 for splits in groups.values())
    assert len({r["fingerprint"] for r in design["runs"]}) == 216
    new = {module.normalized_geometry(layout["scene"]) for layout in design["layouts"]}
    old = {
        module.normalized_geometry(layout["scene"])
        for previous in (module.previous, module.previous.previous)
        for layout in previous.build_design({})["layouts"]
    }
    assert len(new) == 24 and not new & old


def test_quartets_only_intervene_on_airflow(module, design):
    scenes = {layout["layout_id"]: layout["scene"] for layout in design["layouts"]}
    groups = defaultdict(list)
    for row in design["runs"]:
        if row["ventilation_group_id"]:
            groups[row["ventilation_group_id"]].append(row)
    assert len(groups) == 48
    for members in groups.values():
        assert {r["ventilation_state"] for r in members} == {"still", "slow", "fast", "reverse"}
        assert [r["config"]["airflow_m_s"] for r in members] == [0, 0.12, 0.36, 0.36]
        configs = [{k: v for k, v in r["config"].items() if k != "airflow_m_s"} for r in members]
        assert all(c == configs[0] for c in configs)
        for row in members:
            scene = module.scene_for_run(scenes[row["layout_id"]], row)
            assert canonical_sha(scene) == row["scene_sha256"]
            if row["reverse_ventilation"]:
                for i, vent in enumerate(scene["vents"]):
                    original = scenes[row["layout_id"]]["vents"][i]
                    assert vent["role"] != original["role"]
                    assert {k: v for k, v in vent.items() if k != "role"} == {
                        k: v for k, v in original.items() if k != "role"
                    }
                scene["vents"] = scenes[row["layout_id"]]["vents"]
            assert scene == scenes[row["layout_id"]]
    controls = [r for r in design["runs"] if r["ventilation_group_id"] is None]
    assert len(controls) == 24 and all(r["config"]["ignition_power_w"] == 0 for r in controls)
    assert {r["config"]["incident_type"] for r in design["runs"]} == {
        "flaming",
        "battery",
        "smoldering",
        "overheating",
        "arc",
    }
    assert all(r["config"]["gravity_g"] == 0.0001 for r in design["runs"])


def test_compiled_flows_masks_sources_and_signs(module, design):
    report = module.preflight(design)
    assert report["unique_normalized_layouts"] == report["unique_physical_layouts"] == 24
    assert report["paired_groups"] == 48 and report["compiled_ventilation_states"] == 96
    assert report["v1_v2_normalized_geometry_overlap"] == 0
    assert all(12000 <= layout["cell_count"] <= 19000 for layout in report["layouts"].values())
    for deck in report["ventilation_decks"]:
        assert deck["inlet_m3_s"] <= 0 and deck["outlet_m3_s"] >= 0
        assert deck["inlet_m3_s"] == -deck["outlet_m3_s"]


def test_schedule_and_generator_keep_paired_scene(module, design):
    pilot = module.scheduled_runs(design, pilot=True)
    assert len(pilot) == 12 and all(r["split"] != "test" for r in pilot)
    assert len({r["ventilation_group_id"] for r in pilot}) == 3
    full = module.scheduled_runs(design)
    assert len(full) == len({r["id"] for r in full}) == 216
    runner = script("generate_iss_poc_vent.py")
    assert runner.DATASET_ID == design["dataset_id"]
    assert (
        runner.design_module.scene_for_run(design["layouts"][0]["scene"], full[3])["vents"][0]["role"]
        == "outlet"
    )


def test_real_encoder_carries_signed_velocity(module, design, tmp_path):
    pytest.importorskip("torch")
    from ignis.ml.spatial_network import STATIC_CHANNELS, condition_values, geometry_channels

    scene = design["layouts"][0]["scene"]
    members = [r for r in design["runs"] if r["ventilation_group_id"] == scene["id"] + "-flaming"]
    features = {}
    for row in members:
        m = compile_case(module.scene_for_run(scene, row), row["config"], tmp_path / row["ventilation_state"])
        features[row["ventilation_state"]] = geometry_channels(m)
        assert np.isfinite(condition_values(m["config"], m, 15)).all()
    u = STATIC_CHANNELS.index("boundary_u_scaled")
    assert np.count_nonzero(features["still"][u : u + 3]) == 0
    np.testing.assert_allclose(features["fast"][u : u + 3], features["slow"][u : u + 3] * 3, atol=1e-6)
    np.testing.assert_allclose(features["fast"][u : u + 3], -features["reverse"][u : u + 3], atol=1e-6)
    assert np.count_nonzero(features["fast"][u]) > 0
    assert np.count_nonzero(features["fast"][u + 1 : u + 3]) == 0
