"""Targeted ISS POC contracts: no simulator run or accuracy claim in these tests."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(scope="module")
def modules():
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    import sys

    directory = str(Path(__file__).parents[1] / "tools/remote")
    sys.path.insert(0, directory)
    yield importlib.import_module("train_iss_poc"), importlib.import_module("iss_poc_model")
    sys.path.remove(directory)
    torch.set_num_threads(previous)


def case(split="validation", module="lab", gravity=0.0001):
    return {
        "record": {
            "id": module + "-case",
            "layout_id": module + "-layout",
            "split": split,
            "structural_family": module,
        },
        "config": {
            "ambient_temperature_c": 20.0,
            "gravity_g": gravity,
            "incident_type": "flaming",
            "airflow_m_s": 0.1,
            "oxygen_percent": 21,
            "duration_s": 2,
            "ignition_power_w": 1000,
            "ignition_duration_s": 1,
        },
        "time_s": np.array([0, 1, 2]),
        "temperature_c": np.array([[25, 25, 25], [25, 24.999, 100], [26, 20, 20]]),
        "smoke_kg_m3": np.array([[1e-6, 1e-6, 1e-6], [1e-6, 0.999e-6, 1e-5], [2e-6, 0, 0]]),
        "field_mask": np.array([[[1, 1], [1, 1], [0, 0]]] * 3, dtype=bool),
        "positions_m": np.array([[0.1, 0.1, 0.1], [0.2, 0.1, 0.1], [0.3, 0.1, 0.1]]),
        "bounds_m": np.array([1, 1, 1]),
        "shape": np.array([3, 1, 1]),
        "scene": {"id": "fixture", "name": "Fixture"},
        "manifest": {
            "objects": [],
            "vents": [],
            "incident": {
                "source": {
                    "bounds_m": [0, 0.1, 0, 0.1, 0.1, 0.1],
                    "position_m": [0.05, 0.05, 0.1],
                }
            },
        },
    }


def scores():
    return np.repeat(
        np.array([[1, 1, 1], [0.8, 0.2, 1], [0.8, 0.2, 1]], dtype=np.float32)[..., None], 2, axis=-1
    )


def test_dual_targets_include_thresholds_and_ignore_missing_or_initial_frames(modules):
    train, _ = modules
    truth, observed = train.targets(case())
    assert truth[1].tolist() == [[True, True], [False, False], [False, False]]
    assert observed.shape == (3, 3, 2)
    for channel in (0, 1):
        metric = train.assess_field([case()], [scores()], 0.5, channel)
        assert (metric["tp"], metric["fp"], metric["fn"], metric["tn"]) == (2, 0, 0, 2)
        assert metric["n_valid"] == 4


def test_masks_are_separate_for_heat_and_smoke(modules):
    train, _ = modules
    value = case()
    value["field_mask"][1, 0, 1] = False
    value["smoke_kg_m3"][1, 0] = np.nan
    heat = train.assess_field([value], [scores()], 0.5, 0)
    smoke = train.assess_field([value], [scores()], 0.5, 1)
    assert heat["tp"] == 2 and smoke["tp"] == 1
    assert heat["n_valid"] == 4 and smoke["n_valid"] == 3


def test_physical_smoke_threshold_is_exact_not_rounded_to_float32(modules):
    train, _ = modules
    value = case()
    value["smoke_kg_m3"] = value["smoke_kg_m3"].astype(np.float32)
    assert float(value["smoke_kg_m3"][1, 0]) < 1e-6
    truth, _ = train.targets(value)
    assert not truth[1, 0, 1]
    value["smoke_kg_m3"][1, 0] = np.nextafter(np.float32(1e-6), np.float32(np.inf))
    assert train.targets(value)[0][1, 0, 1]


@pytest.mark.parametrize("split", ["train", "test"])
def test_threshold_selection_rejects_training_and_test(modules, split):
    with pytest.raises(ValueError, match="validation cases only"):
        modules[0].select_thresholds([case(split)], [scores()])


def test_validation_thresholds_are_independent_and_earth_does_not_choose_them(modules):
    train, _ = modules
    first, second = case(), case(module="node")
    values = scores()
    values[..., 1] *= 0.5
    micro = train.select_thresholds([first, second], [values, values])
    assert micro["value"] == 1
    assert 0.2 < micro["score_thresholds"]["heat"] <= 0.8
    assert 0.1 < micro["score_thresholds"]["smoke"] <= 0.4
    earth = case(module="earth", gravity=1)
    with_earth = train.select_thresholds([first, second, earth], [values, values, 1 - values])
    assert with_earth["score_thresholds"] == micro["score_thresholds"]
    assert with_earth["value"] == micro["value"]


def test_no_positive_smoke_selects_all_cold_and_reports_null_recall(modules):
    train, _ = modules
    value = case()
    value["smoke_kg_m3"][:] = 0
    result = train.select_field_threshold([value], [scores()], 1)
    assert result["threshold"] > 1
    assert result["metrics"]["recall"] is None
    assert result["metrics"]["false_positive_rate"] == 0
    assert result["positive_modules"] == 0


def test_loss_penalizes_both_fields_and_ignores_missing(modules):
    import torch

    train, _ = modules
    logits = torch.tensor([[[[[-4.0, 4.0, 99.0]]], [[[-4.0, 4.0, 99.0]]]]], requires_grad=True)
    target = torch.tensor([[[[[1, 0, 1]]], [[[1, 0, 1]]]]], dtype=torch.bool)
    observed = torch.tensor([[[[[1, 1, 0]]], [[[1, 1, 0]]]]], dtype=torch.bool)
    train.dual_balanced_bce(logits, target, observed).mean().backward()
    assert (logits.grad[..., 0] < 0).all()
    assert (logits.grad[..., 1] > 0).all()
    assert (logits.grad[..., 2] == 0).all()
    cold_logits = torch.full((1, 2, 1, 1, 1), 4.0, requires_grad=True)
    train.dual_balanced_bce(
        cold_logits, torch.zeros_like(cold_logits), torch.ones_like(cold_logits)
    ).mean().backward()
    assert (cold_logits.grad > 0).all()


def test_missing_channel_does_not_dilute_the_observed_channel_loss(modules):
    import torch

    train, _ = modules
    logits = torch.zeros((1, 2, 1, 1, 1))
    observed = torch.tensor([[[[[1]]], [[[0]]]]], dtype=torch.bool)
    result = train.dual_balanced_bce(logits, torch.zeros_like(logits), observed)
    assert result.item() == pytest.approx(np.log(2))


def test_training_cache_rejects_validation_before_allocation(modules):
    with pytest.raises(ValueError, match="training cases only"):
        modules[0].TrainingCache([case()])


def test_run_holds_shared_runtime_lock_for_entire_fit(modules, tmp_path, monkeypatch):
    train, _ = modules
    args = SimpleNamespace(runtime=tmp_path / "runtime", dataset=tmp_path / "datasets/iss")
    visited = []

    def locked_body(arguments):
        with pytest.raises(RuntimeError, match="autre instance"):
            with train.ProcessLock(arguments.compute_lock_path):
                pytest.fail("Shared compute lock unexpectedly available during the fit")
        visited.append(True)

    monkeypatch.setattr(train, "_run_locked", locked_body)
    train.run(args)
    assert visited == [True]
    with train.ProcessLock(args.runtime / "compute.lock"):
        pass


def write_index(tmp_path, **updates):
    records = []
    for split in ("train", "validation", "test"):
        for module in ("lab", "node", "service"):
            identifier = split + "-" + module
            records.append(
                {
                    "id": identifier,
                    "layout_id": identifier,
                    "structural_family": module,
                    "split": split,
                    "status": "completed",
                    "relative_path": "runs/" + identifier,
                }
            )
    value = {"dataset_id": "iss-poc-20261115-v1", "expected_runs": 9, "runs": records, **updates}
    (tmp_path / "manifest.json").write_text(json.dumps(value), encoding="utf-8")
    return value


def test_dedicated_store_allows_known_modules_but_keeps_inherited_physical_checks(modules, tmp_path):
    train, _ = modules
    write_index(tmp_path)
    store = train.ISSCaseStore(tmp_path)
    assert [len(store.by_split[key]) for key in ("train", "validation", "test")] == [3, 3, 3]
    assert train.ISSCaseStore.verify is train.CaseStore.verify
    assert train.ISSCaseStore.get is train.CaseStore.get


def test_dedicated_store_rejects_shared_layouts(modules, tmp_path):
    value = write_index(tmp_path)
    value["runs"][3]["layout_id"] = value["runs"][0]["layout_id"]
    write_index(tmp_path, runs=value["runs"])
    with pytest.raises(ValueError, match="layout leakage"):
        modules[0].ISSCaseStore(tmp_path)


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"dataset_id": "spatial-compact-v1"}, "exact ISS dataset ID"),
        ({"expected_runs": 10}, "complete before fitting"),
    ],
)
def test_dedicated_store_does_not_relax_other_datasets_or_partial_runs(modules, tmp_path, updates, message):
    write_index(tmp_path, **updates)
    with pytest.raises(ValueError, match=message):
        modules[0].ISSCaseStore(tmp_path)


def test_export_preserves_exact_float_scores_truth_and_separate_masks(modules, tmp_path):
    train, _ = modules
    value, predicted = case(), scores()
    predicted[1, 0, 0] = np.float32(0.50000006)
    value["field_mask"][1, 0, 1] = False
    threshold = {"heat": 0.50000001, "smoke": 0.5}
    metric = {
        name: train.assess_field([value], [predicted], threshold[name], i)
        for i, name in enumerate(train.OUTPUTS)
    }
    path = tmp_path / "case.json"
    train.export_case(path, value, predicted, threshold, metric)
    exported = json.loads(path.read_text())
    frame = exported["frames"][1]
    assert frame["heat_score"][0] == float(predicted[1, 0, 0])
    assert frame["predicted_hot_mask"][0] is True
    assert frame["heat_valid_mask"][0] is True
    assert frame["smoke_valid_mask"][0] is False
    assert frame["soot_kg_m3"][0] is None and frame["smoke_score"][0] is None
    assert frame["smoke_truth"][0] is None and frame["predicted_smoke_mask"][0] is None
    assert exported["scene"]["geometry_semantics"] == "compiled FDS axis-aligned boxes"


def test_cpu_predictor_uses_geometry_conditions_and_time_without_labels(modules, tmp_path):
    import torch
    from ignis.physics import compile_case
    from ignis.physics.verification import verification_scene

    _, model = modules
    scene = verification_scene()
    scene["components"] = [{"id": "heater", "object_id": "sample", "position_m": [1, 1, 0.4], "face": 3}]
    config = {
        "source_model": "coupled_combustion",
        "ignition_kind": "thermal",
        "incident_type": "flaming",
        "component_id": "heater",
        "gravity_g": 0.0001,
        "ignition_power_w": 1000,
        "ignition_duration_s": 10,
        "duration_s": 30,
        "airflow_m_s": 0.2,
        "oxygen_percent": 21,
        "mesh_cell_m": 0.2,
        "sample_shape": [4, 4, 4],
        "material_id": "cellulose",
    }
    manifest = compile_case(scene, config, tmp_path / "compiled")
    network = model.ISSClassifier(16)
    weights = tmp_path / "weights.pt"
    torch.save(
        {
            "id": model.MODEL_ID,
            "schema_version": model.SCHEMA_VERSION,
            "architecture": model.architecture(16),
            "sample_shape": [4, 4, 4],
            "score_thresholds": {"heat": 0.1, "smoke": 0.2},
            "state_dict": network.state_dict(),
        },
        weights,
    )
    predictor = model.ISSPredictor(weights)
    prediction = predictor.predict_arrays(manifest["config"], manifest, [1, 10, 30])
    assert prediction["scores"].shape == (3, 64, 2)
    assert prediction["predicted_mask"].dtype == bool
    assert np.isfinite(prediction["scores"][prediction["valid_mask"]]).all()
    assert np.isnan(prediction["scores"][~prediction["valid_mask"]]).all()
    assert prediction["output_channels"] == ("heat", "smoke")
    altered = copy.deepcopy(manifest["config"])
    altered["airflow_m_s"] = 0.3
    with pytest.raises(ValueError, match="effective config"):
        predictor.predict_arrays(altered, manifest, [10])
    with pytest.raises(ValueError, match="checksum"):
        model.ISSPredictor(weights, expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="ordered finite times"):
        predictor.predict_arrays(manifest["config"], manifest, [10, 1])

    # Genuine disabled FDS sources have an empty ramp. They must remain in the
    # training data, rather than being replaced by artificially heated controls.
    config["ignition_power_w"] = 0
    cold = compile_case(scene, config, tmp_path / "cold")
    original = copy.deepcopy(cold)
    assert cold["source"]["ramp"] == []
    cold_prediction = predictor.predict_arrays(cold["config"], cold, [1, 10, 30])
    assert cold_prediction["scores"].shape == (3, 64, 2)
    static = model.geometry_channels(cold)
    for t in (0, 10, 30):
        features = model.input_tensor(static, cold["config"], cold, t)
        assert np.all(features[model.CHANNELS.index("source_ramp_fraction")] == 0)
        assert np.all(features[model.CHANNELS.index("power_scaled")] == 0)
    assert cold == original
    invalid_config = {**cold["config"], "ignition_power_w": 100}
    with pytest.raises(ValueError, match="energized ISS source"):
        model.input_tensor(static, invalid_config, cold, 10)


def test_network_output_channels_are_distinct_from_regression_outputs(modules):
    import torch

    _, model = modules
    network = model.ISSClassifier(16)
    values = torch.zeros((1, len(model.CHANNELS), 4, 4, 4))
    with torch.inference_mode():
        logits = network(values)
    assert logits.shape == (1, 2, 4, 4, 4)
    assert torch.all(logits == -2)
    assert model.architecture()["output_channels"] == ["heat", "smoke"]
    assert all(not parameter.requires_grad for parameter in network.global_head.parameters())
