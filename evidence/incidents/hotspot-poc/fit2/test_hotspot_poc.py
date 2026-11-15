"""Heat-only classification, validation isolation, and exact demo contracts."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture
def poc(monkeypatch):
    pytest.importorskip("torch")
    scripts = Path(__file__).parents[1] / "tools/remote"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("hotspot_poc_test", scripts / "train_hotspot_poc.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def case(split="validation", gravity=0.0001):
    return {
        "record": {"id": "fixture", "layout_id": "layout-fixture", "split": split},
        "config": {
            "ambient_temperature_c": 20,
            "gravity_g": gravity,
            "incident_type": "overheating",
            "airflow_m_s": 0.1,
            "oxygen_percent": 21,
            "duration_s": 2,
            "ignition_power_w": 100,
            "ignition_duration_s": 1,
        },
        "time_s": np.array([0, 1, 2]),
        "temperature_c": np.array([[25, 25, 25], [25, 24.9999, 100], [26, 20, 20]]),
        "field_mask": np.array([[[1, 1], [1, 1], [0, 0]]] * 3, dtype=bool),
        "positions_m": np.array([[0.1, 0.1, 0.1], [0.2, 0.1, 0.1], [0.3, 0.1, 0.1]]),
        "bounds_m": np.array([1, 1, 1]),
        "shape": np.array([3, 1, 1]),
        "scene": {"id": "fixture", "name": "Fixture"},
        "manifest": {
            "objects": [
                {
                    "id": "object",
                    "role": "equipment",
                    "material_id": "aluminium",
                    "bounds_m": [0, 0.1, 0, 0.1, 0, 0.1],
                }
            ],
            "vents": [],
            "incident": {"source": {"bounds_m": [0, 0.1, 0, 0.1, 0.1, 0.1], "position_m": [0.05, 0.05, 0.1]}},
        },
    }


def test_heat_target_is_inclusive_and_missing_never_cold(poc):
    truth, observed = poc.heat_target(case())
    assert truth[1].tolist() == [True, False, False]
    assert observed[1].tolist() == [True, True, False]
    score = np.array([[1, 1, 1], [1, 0, 1], [1, 0, 1]], dtype=np.float32)
    metric = poc.classification(truth, score, poc.evaluation_mask(case()), 0.5)
    assert (metric["tp"], metric["fp"], metric["fn"], metric["tn"]) == (2, 0, 0, 2)
    assert metric["n_valid"] == 4


def test_empty_positive_metrics_are_null_not_perfect(poc):
    metric = poc.metric_from_counts(0, 0, 0, 100)
    assert metric["f1"] is None
    assert metric["precision"] is None
    assert metric["recall"] is None
    assert metric["false_positive_rate"] == 0


@pytest.mark.parametrize("split", ["train", "test"])
def test_threshold_selection_refuses_other_partitions(poc, split):
    with pytest.raises(ValueError, match="validation cases only"):
        poc.select_threshold([case(split)], [np.ones((3, 3), dtype=np.float32)])


def test_common_threshold_balances_gravities_and_preserves_all_points(poc):
    micro, earth = case(), case(gravity=1)
    a = np.array([[0, 0, 0], [0.8, 0.2, 0.9], [0.8, 0.2, 0.9]], dtype=np.float32)
    b = np.array([[0, 0, 0], [0.7, 0.1, 0.9], [0.7, 0.1, 0.9]], dtype=np.float32)
    selection = poc.select_threshold([micro, earth], [a, b])
    assert selection["value"] == 1
    assert selection["metrics"]["n_valid"] == 8
    assert 0.2 < selection["threshold"] <= 0.7
    assert selection["metrics"]["groups"]["microgravity"]["f1"] == 1


def test_loss_penalizes_missing_hotspots_and_cold_false_alarms(poc):
    import torch

    logits = torch.tensor([[[[[-4.0, 4.0, 100.0]]]]], requires_grad=True)
    target = torch.tensor([[[[[1, 0, 1]]]]], dtype=torch.bool)
    mask = torch.tensor([[[[[1, 1, 0]]]]], dtype=torch.bool)
    loss = poc.balanced_bce(logits, target, mask).mean()
    loss.backward()
    assert logits.grad.flatten()[0] < 0
    assert logits.grad.flatten()[1] > 0
    assert logits.grad.flatten()[2] == 0
    cold = torch.tensor([[[[[4.0]]]]], requires_grad=True)
    poc.balanced_bce(cold, torch.zeros_like(cold), torch.ones_like(cold)).mean().backward()
    assert cold.grad.item() > 0


def test_fit_loads_only_train_and_validation(poc, monkeypatch):
    store = SimpleNamespace(
        snapshot={"dataset_id": "spatial-compact-v1"},
        shape=(12, 16, 8),
        by_split={"train": list(range(120)), "validation": list(range(40)), "test": list(range(40))},
    )
    seen = []
    monkeypatch.setattr(poc, "load_partition", lambda _, split: seen.append(split) or [])
    poc.fit_cases(store)
    assert seen == ["train", "validation"]


def test_dice_focuses_overlap_and_preserves_cold_control_loss(poc):
    import torch

    observed = torch.ones((1, 1, 1, 1, 2), dtype=torch.bool)
    target = torch.tensor([[[[[1, 0]]]]], dtype=torch.bool)
    good = torch.tensor([[[[[5.0, -5.0]]]]], requires_grad=True)
    bad = -good.detach().clone().requires_grad_(True)
    good_dice = poc.heat_loss(good, target, observed, "dice_reflections") - poc.balanced_bce(
        good, target, observed
    )
    bad_dice = poc.heat_loss(bad, target, observed, "dice_reflections") - poc.balanced_bce(
        bad, target, observed
    )
    assert good_dice.item() < bad_dice.item()
    cold = torch.zeros_like(target)
    assert torch.equal(
        poc.heat_loss(good, cold, observed, "dice_reflections"), poc.balanced_bce(good, cold, observed)
    )


@pytest.mark.parametrize("axis", [0, 1])
def test_reflection_transforms_coordinates_source_flow_and_labels_together(poc, axis):
    import torch

    shape = (1, len(poc.CHANNELS), 4, 4, 4)
    x = torch.zeros(shape)
    coord_name = "x_over_width" if axis == 0 else "y_over_depth"
    source_name = "source_x_scaled" if axis == 0 else "source_y_scaled"
    delta_name = "source_dx" if axis == 0 else "source_dy"
    flow_name = "boundary_u_scaled" if axis == 0 else "boundary_v_scaled"
    coordinate = torch.tensor([0.125, 0.375, 0.625, 0.875])
    coordinate = (
        coordinate[:, None, None].expand(4, 4, 4) if axis == 0 else coordinate[None, :, None].expand(4, 4, 4)
    )
    x[:, poc.CHANNELS.index(coord_name)] = coordinate
    x[:, poc.CHANNELS.index(source_name)] = 0.25
    x[:, poc.CHANNELS.index(delta_name)] = coordinate - 0.25
    x[:, poc.CHANNELS.index(flow_name)] = 0.5
    target = torch.zeros((1, 1, 4, 4, 4), dtype=torch.bool)
    target[0, 0, 1, 1, 2] = True
    observed = torch.ones_like(target)
    original = x.clone()
    result, reflected_target, reflected_mask = poc.reflect_horizontal(x, target, observed, axis)
    assert torch.equal(x, original)
    assert torch.equal(result[:, poc.CHANNELS.index(coord_name)], x[:, poc.CHANNELS.index(coord_name)])
    assert torch.all(result[:, poc.CHANNELS.index(source_name)] == 0.75)
    assert torch.allclose(result[:, poc.CHANNELS.index(delta_name)], coordinate - 0.75)
    assert torch.all(result[:, poc.CHANNELS.index(flow_name)] == -0.5)
    assert torch.equal(reflected_target, torch.flip(target, (axis + 2,)))
    restored = poc.reflect_horizontal(result, reflected_target, reflected_mask, axis)
    assert all(torch.equal(a, b) for a, b in zip(restored, (x, target, observed)))
    with pytest.raises(ValueError, match="horizontal"):
        poc.reflect_horizontal(x, target, observed, 2)


def test_training_cache_refuses_validation_before_allocation(poc):
    with pytest.raises(ValueError, match="training cases only"):
        poc.TrainingCache([case()])


def test_export_keeps_exact_threshold_truth_and_masks(poc, tmp_path):
    example = case()
    threshold = float(np.float32(0.61234567))
    score = np.full((3, 3), np.float32(threshold), dtype=np.float32)
    score[1, 1] = np.nextafter(np.float32(threshold), np.float32(0))
    metric = poc.assess_scores([example], [score], threshold)["cases"][0]
    path = tmp_path / "case.json"
    poc.export_case(path, example, score, threshold, metric)
    saved = json.loads(path.read_text())
    assert saved["frames"][1]["hotspot_score"][0] == threshold
    assert saved["frames"][1]["predicted_hot_mask"] == [True, False, None]
    assert saved["frames"][1]["hotspot_truth"] == [True, False, None]
    assert saved["frames"][1]["temperature_c"][2] is None
    assert saved["metrics"]["n_valid"] == 4
    assert saved["scene"]["geometry_semantics"] == "compiled FDS axis-aligned boxes"
    with pytest.raises(FileExistsError):
        poc.export_case(path, example, score, threshold, metric)


def test_saved_classifier_reload_preserves_exact_state_and_task(poc, tmp_path):
    import torch

    network = poc.HotspotClassifier(16)
    path = tmp_path / "weights.pt"
    poc.save_weights(path, network, 16, 500, 0.5)
    loaded = torch.load(path, map_location="cpu", weights_only=True)
    restored = poc.HotspotClassifier(16)
    restored.load_state_dict(loaded["state_dict"], strict=True)
    assert poc.state_sha(network) == poc.state_sha(restored)
    assert loaded["architecture"]["output"] == "one heat-class logit per sample"
    assert network.field_head.out_channels == 1
    with pytest.raises(FileExistsError):
        poc.save_weights(path, network, 16, 500, 0.5)


def test_demo_chooses_median_and_failure_never_best(poc):
    rows = []
    for i, iou in enumerate([0.9, 0.5, 0.1]):
        rows.append(
            {
                "id": str(i),
                "split": "validation",
                "gravity_g": 0.0001,
                "metrics": {"tp": 1, "fn": 1, "iou": iou},
            }
        )
    rows.append(
        {
            "id": "control",
            "split": "validation",
            "gravity_g": 0.0001,
            "metrics": {"tp": 0, "fn": 0, "iou": None},
        }
    )
    assert poc.selected_examples(rows) == {"representative": "1", "failure": "2", "cold_control": "control"}


@pytest.mark.parametrize("seconds", [0, 239, 1201])
def test_cli_refuses_out_of_budget_jobs(poc, seconds):
    with pytest.raises(SystemExit):
        poc.parse_args(["--dataset", "source", "--output", "destination", "--seconds", str(seconds)])
