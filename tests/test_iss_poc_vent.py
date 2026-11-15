"""Physical reflection parity and validation-only promotion guardrails."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture(scope="module")
def modules():
    torch = pytest.importorskip("torch")
    import sys

    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    directory = str(Path(__file__).parents[1] / "tools/remote")
    sys.path.insert(0, directory)
    yield importlib.import_module("train_iss_poc_vent"), importlib.import_module("iss_poc_model")
    sys.path.remove(directory)
    torch.set_num_threads(previous)


def fixture_scene(vent_axis):
    from ignis.physics.verification import verification_scene

    scene = verification_scene()
    scene["bounds_m"] = [2, 3, 2]
    scene["objects"][0].update(center_m=[0.75, 1.25, 0.25], size_m=[0.5, 0.5, 0.5])
    scene["objects"].append(
        {
            "id": "rack",
            "role": "obstacle",
            "material_id": "steel",
            "combustible_material_id": "pmma",
            "thermal_thickness_m": 0.002,
            "center_m": [1.75, 2.5, 0.5],
            "size_m": [0.5, 0.5, 1],
        }
    )
    scene["source_position_m"] = [0.625, 1.125, 0.5]
    scene["components"] = [
        {"id": "heater", "object_id": "sample", "position_m": [0.625, 1.125, 0.5], "face": 3}
    ]
    if vent_axis == 0:
        scene["vents"][0].update(center_m=[0, 1, 1.5], size_m=[0, 1, 0.5])
        scene["vents"][1].update(center_m=[2, 2, 1.5], size_m=[0, 1, 0.5])
    else:
        scene["vents"][0].update(center_m=[0.5, 0, 1.5], size_m=[0.5, 0, 0.5], normal=[0, 1, 0])
        scene["vents"][1].update(center_m=[1.5, 3, 1], size_m=[0.5, 0, 0.5], normal=[0, -1, 0])
    return scene


def fixture_config(power=1000):
    return {
        "source_model": "coupled_combustion",
        "ignition_kind": "thermal",
        "incident_type": "flaming",
        "component_id": "heater",
        "gravity_g": 0.0001,
        "ignition_power_w": power,
        "ignition_duration_s": 2 if power else 0,
        "ignition_delay_s": 1 if power else 0,
        "duration_s": 4,
        "airflow_m_s": 0.2,
        "oxygen_percent": 21,
        "mesh_cell_m": 0.25,
        "sample_shape": [4, 6, 4],
        "material_id": "cellulose",
    }


def mirrored_scene(scene, axes):
    result = copy.deepcopy(scene)
    for axis in axes:
        bound = scene["bounds_m"][axis]
        result["source_position_m"][axis] = bound - result["source_position_m"][axis]
        for key in ("objects", "vents", "components", "sensors"):
            for item in result[key]:
                position = item.get("center_m", item.get("position_m"))
                position[axis] = bound - position[axis]
                if "normal" in item:
                    item["normal"][axis] *= -1
    return result


@pytest.mark.parametrize("axes", [(0,), (1,), (0, 1)])
@pytest.mark.parametrize("vent_axis", [0, 1])
def test_reflection_matches_recompiled_physics_at_reflected_actual_samples(
    modules, tmp_path, axes, vent_axis
):
    import torch
    from ignis.physics import compile_case

    train, model = modules
    scene, config = fixture_scene(vent_axis), fixture_config()
    original = compile_case(scene, config, tmp_path / "original")
    mirror = compile_case(mirrored_scene(scene, axes), config, tmp_path / "mirror")
    shape = tuple(original["sampling"]["shape"])
    positions = np.array(original["sampling"]["positions_m"]).reshape(*shape, 3)
    positions = np.flip(positions, axes).copy()
    for axis in axes:
        positions[..., axis] = original["sampling"]["bounds_m"][axis] - positions[..., axis]
    gas = np.array(original["sampling"]["valid_mask"]).reshape(shape)
    mirror["sampling"]["positions_m"] = positions.reshape(-1, 3).tolist()
    mirror["sampling"]["valid_mask"] = np.flip(gas, axes).reshape(-1).tolist()
    expected = model.input_tensor(model.geometry_channels(mirror), mirror["config"], mirror, 2)
    values = model.input_tensor(model.geometry_channels(original), original["config"], original, 2)
    original_values = values.copy()
    target = torch.arange(2 * np.prod(shape)).reshape(1, 2, *shape) % 3 == 0
    mask = torch.arange(2 * np.prod(shape)).reshape(1, 2, *shape) % 5 != 0
    actual, mirrored_target, mirrored_mask = train.reflect_xy(
        torch.from_numpy(values[None]), target, mask, axes
    )
    np.testing.assert_allclose(actual.numpy()[0], expected, atol=2e-6, rtol=2e-6)
    assert np.array_equal(values, original_values), "Augmentation must not mutate cached geometry"
    assert torch.equal(mirrored_target, torch.flip(target, tuple(axis + 2 for axis in axes)))
    assert torch.equal(mirrored_mask, torch.flip(mask, tuple(axis + 2 for axis in axes)))
    recovered, labels, observed = train.reflect_xy(actual, mirrored_target, mirrored_mask, axes)
    np.testing.assert_allclose(recovered.numpy()[0], values, atol=1e-7, rtol=1e-7)
    assert torch.equal(labels, target) and torch.equal(observed, mask)
    if 0 in axes:
        # FDS grid snapping yields an asymmetric sampling grid in this fixture.
        assert not np.allclose(actual.numpy()[0, 0], values[0])


def make_case(tmp_path, model, *, power=1000, split="train"):
    from ignis.physics import compile_case

    manifest = compile_case(fixture_scene(0), fixture_config(power), tmp_path)
    shape, bounds, positions, gas, _, _ = model.sampling_grid(manifest)
    mask = np.broadcast_to(gas[None, :, None], (5, len(gas), 2)).copy()
    heat, smoke = np.full((5, len(gas)), 20, dtype=np.float32), np.zeros((5, len(gas)), dtype=np.float32)
    if power:
        heat[2:, gas], smoke[3:, gas] = 27, 2e-6
    return {
        "record": {"id": tmp_path.name, "split": split, "structural_family": "iss-laboratory"},
        "config": manifest["config"],
        "manifest": manifest,
        "static": model.geometry_channels(manifest),
        "shape": np.array(shape),
        "positions_m": positions,
        "bounds_m": bounds,
        "time_s": np.arange(5),
        "field_mask": mask,
        "temperature_c": heat,
        "smoke_kg_m3": smoke,
    }


def test_cache_balances_corpora_without_erasing_controls_or_inactive_times(modules, tmp_path):
    import torch

    train, model = modules
    previous = [make_case(tmp_path / "old", model)]
    fresh = [make_case(tmp_path / "new", model), make_case(tmp_path / "control", model, power=0)]
    cache = train.VentilationTrainingCache(previous, fresh, device="cpu")
    assert cache.probability[cache.case == 0].sum().item() == pytest.approx(0.5)
    assert cache.probability[cache.case == 1].sum().item() == pytest.approx(0.25)
    assert cache.probability[cache.case == 2].sum().item() == pytest.approx(0.25)
    assert torch.all(cache.probability > 0)
    x, y, mask = cache.gather(torch.arange(cache.frames))
    assert x.shape == (12, 54, 4, 6, 4)
    assert not y[8:].any()
    assert mask[8:].any()
    ramp = model.CHANNELS.index("source_ramp_fraction")
    assert torch.all(x[8:, ramp] == 0)
    assert fresh[1]["manifest"]["source"]["ramp"] == []
    for _ in range(4):
        batch = cache.batch(8)
        assert batch[0].shape == (8, 54, 4, 6, 4)


def test_cache_rejects_holdout_and_reflection_rejects_gravity_flip(modules, tmp_path):
    import torch

    train, _ = modules
    with pytest.raises(ValueError, match="training cases only"):
        train.VentilationTrainingCache(
            [{"record": {"split": "train"}}], [{"record": {"split": "validation"}}], device="cpu"
        )
    for axes in ((2,), (0, 0)):
        with pytest.raises(ValueError, match="horizontal"):
            train.reflect_xy(
                torch.zeros(1, 54, 4, 4, 4), torch.zeros(1, 2, 4, 4, 4), torch.zeros(1, 2, 4, 4, 4), axes
            )


def selection_fixture():
    return {
        "value": 0.5,
        "paired_macro_f1": 0.2,
        "old_validation_macro_f1": 0.5,
        "control_false_positives": {"heat": 0, "smoke": 0},
        "combined_metrics": {
            name: {"groups": {"microgravity": {"precision": 0.6, "recall": 0.5}}}
            for name in ("heat", "smoke")
        },
    }


@pytest.mark.parametrize("failure", ["old_f1", "precision", "recall", "control", "composite", "paired"])
def test_promotion_rejects_each_predeclared_failure(modules, failure):
    train, _ = modules
    baseline, candidate = selection_fixture(), selection_fixture()
    candidate.update(value=0.6, paired_macro_f1=0.3)
    assert train.promotion_guard(candidate, baseline)["promotable"]
    if failure == "old_f1":
        candidate["old_validation_macro_f1"] = 0.479
    elif failure in ("precision", "recall"):
        candidate["combined_metrics"]["smoke"]["groups"]["microgravity"][failure] = (
            0.56 if failure == "precision" else 0.499
        )
    elif failure == "control":
        candidate["control_false_positives"]["heat"] = 1
    elif failure == "composite":
        candidate["value"] = baseline["value"]
    else:
        candidate["paired_macro_f1"] = baseline["paired_macro_f1"]
    assert not train.promotion_guard(candidate, baseline)["promotable"]


def test_selection_rejects_test_before_reading_scores(modules):
    train, _ = modules
    with pytest.raises(ValueError, match="validation only"):
        train.validation_selection([{"record": {"split": "test"}}], [], [], [])


def test_geometry_orbit_detects_scale_and_reflected_copy(modules):
    train, _ = modules
    manifest = {"sampling": {"bounds_m": [2, 3, 4]}, "objects": [{"bounds_m": [0, 1, 0.5, 1.5, 0, 1]}]}
    mirrored = {"sampling": {"bounds_m": [4, 6, 8]}, "objects": [{"bounds_m": [2, 4, 3, 5, 0, 2]}]}
    assert train.geometry_orbit(manifest) == train.geometry_orbit(mirrored)
    mirrored["objects"][0]["bounds_m"][0] = 1
    assert train.geometry_orbit(manifest) != train.geometry_orbit(mirrored)


def write_vent_index(directory, train):
    records = []
    for family in sorted(train.FAMILIES):
        for variant in range(4):
            split = "train" if variant < 2 else "validation" if variant == 2 else "test"
            layout = family + str(variant)
            for incident in ("flaming", "arc"):
                for state in ("still", "slow", "fast", "reverse"):
                    identifier = layout + "-" + incident + "-" + state
                    records.append(
                        {
                            "id": identifier,
                            "layout_id": layout,
                            "structural_family": family,
                            "split": split,
                            "status": "completed",
                            "relative_path": "runs/" + identifier,
                            "ventilation_group_id": layout + "-" + incident,
                            "ventilation_state": state,
                        }
                    )
            records.append(
                {
                    "id": layout + "-control",
                    "layout_id": layout,
                    "structural_family": family,
                    "split": split,
                    "status": "completed",
                    "relative_path": "runs/" + layout + "-control",
                }
            )
    index = {"dataset_id": train.DATASET_ID, "expected_runs": 216, "runs": records}
    (directory / "manifest.json").write_text(json.dumps(index), encoding="utf-8")
    return index


def test_store_keeps_compiler_checks_and_whole_quartets(modules, tmp_path):
    train, _ = modules
    write_vent_index(tmp_path, train)
    store = train.VentilationCaseStore(tmp_path)
    assert train.VentilationCaseStore.get is train.CaseStore.get
    assert train.VentilationCaseStore.verify is train.CaseStore.verify
    assert [len(indices) for indices in store.by_split.values()] == [108, 54, 54]


def test_postfreeze_integrity_pass_cannot_mutate_frozen_training_snapshot(modules, tmp_path, monkeypatch):
    train, _ = modules
    write_vent_index(tmp_path, train)
    store = train.VentilationCaseStore(tmp_path)
    before = copy.deepcopy(store.snapshot)

    def enrich(instance, log):
        for record in instance.records:
            record["geometry_signature"] = "enriched"
        instance.snapshot_sha = train.canonical_sha(instance.snapshot)

    monkeypatch.setattr(train.CaseStore, "verify", enrich)
    verified = store.verify_after_selection(None)
    assert store.snapshot == before
    assert train.canonical_sha(store.snapshot) != verified.snapshot_sha
    assert verified.records is verified.snapshot["runs"]
    assert all("geometry_signature" not in record for record in store.records)


@pytest.mark.parametrize("failure", ["wrong_id", "incomplete", "duplicate_state", "layout_leak"])
def test_store_rejects_dataset_contract_changes(modules, tmp_path, failure):
    train, _ = modules
    index = write_vent_index(tmp_path, train)
    if failure == "wrong_id":
        index["dataset_id"] = "iss-poc-20261115-v2"
    elif failure == "incomplete":
        index["runs"].pop()
    elif failure == "duplicate_state":
        index["runs"][1]["ventilation_state"] = "still"
    else:
        index["runs"][18]["layout_id"] = index["runs"][0]["layout_id"]
    (tmp_path / "manifest.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(ValueError):
        train.VentilationCaseStore(tmp_path)
