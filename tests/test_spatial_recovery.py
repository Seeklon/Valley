"""Meaningful loss contracts; tiny CPU tensors, no FDS or accuracy claims."""

# ruff: noqa: E402
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

torch = pytest.importorskip("torch")
from ignis.ml.spatial_training import region_balanced_loss, support_loss


def test_hot_gradient_is_not_diluted_by_unburned_room_cells():
    gradients = []
    for size in (10, 10000):
        prediction = torch.zeros(1, 1, size, requires_grad=True)
        target = torch.zeros_like(prediction)
        target[0, 0, 0] = 3
        loss = region_balanced_loss(prediction, target, torch.ones_like(target, dtype=torch.bool), target > 0)
        loss.sum().backward()
        gradients.append(prediction.grad[0, 0, 0].item())
    assert gradients == pytest.approx([-0.5, -0.5])


def test_missing_channels_and_nan_targets_do_not_dilute_or_poison_gradients():
    target = torch.tensor([[[2.0, float("nan")], [float("nan"), float("nan")]]])
    prediction = torch.zeros_like(target, requires_grad=True)
    observed = torch.isfinite(target)
    loss = region_balanced_loss(prediction, target, observed, observed)
    assert loss.item() == pytest.approx(1.5)
    loss.sum().backward()
    assert torch.isfinite(prediction.grad).all()
    assert prediction.grad[0, 0, 0] == -1
    assert prediction.grad[~observed].count_nonzero() == 0


def test_false_smoke_is_penalized_in_a_completely_clear_room():
    prediction = torch.ones(1, 2, 20, requires_grad=True)
    target = torch.zeros_like(prediction)
    observed = torch.ones_like(target, dtype=torch.bool)
    loss = region_balanced_loss(prediction, target, observed, target > 0)
    assert loss.item() == pytest.approx(0.5)
    loss.sum().backward()
    assert (prediction.grad > 0).all()


def test_both_fields_count_equally_and_perfect_prediction_has_zero_loss():
    target = torch.tensor([[[3.0, 0.0], [1.0, 1.0]]])
    observed = torch.ones_like(target, dtype=torch.bool)
    active = target > 0
    value = region_balanced_loss(torch.zeros_like(target), target, observed, active)
    assert value.item() == pytest.approx((2.5 / 2 + 0.5) / 2)
    assert region_balanced_loss(target, target, observed, active).item() == 0


def test_unobserved_frame_is_refused():
    target = torch.zeros(2, 2, 3)
    mask = torch.zeros_like(target, dtype=torch.bool)
    with pytest.raises(ValueError, match="observed"):
        region_balanced_loss(target, target, mask, mask)


def test_support_objective_penalizes_false_alerts_with_same_recall():
    target = torch.zeros(1, 2, 20)
    target[:, :, 0] = 1
    mask = torch.ones_like(target, dtype=torch.bool)
    accurate = target.clone()
    spread = target.clone()
    spread[:, :, 1:10] = 1
    assert support_loss(spread, mask, target > 0) > support_loss(accurate, mask, target > 0)


def test_clear_frame_support_has_finite_background_gradients_and_ignores_missing_cells():
    prediction = torch.ones(1, 2, 10, requires_grad=True)
    mask = torch.ones_like(prediction, dtype=torch.bool)
    mask[:, :, 5:] = False
    loss = support_loss(prediction, mask, torch.zeros_like(mask))
    assert torch.isfinite(loss).all() and loss.item() > 0
    loss.sum().backward()
    assert (prediction.grad[:, :, :5] > 0).all()
    assert prediction.grad[:, :, 5:].count_nonzero() == 0


@pytest.fixture
def recovery(monkeypatch):
    scripts = Path(__file__).parents[1] / "tools/remote"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("recovery_test", scripts / "recover_spatial.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "prepared", lambda case: dict(case))
    return module


def fake_store(entries):
    cases = [{"record": record, "manifest": {"deck_sha256": deck}} for record, deck in entries]
    return SimpleNamespace(records=[c["record"] for c in cases], get=lambda i: cases[i], cache={})


def record(name, split, geometry, family=None):
    return {"id": name, "split": split, "geometry_signature": geometry, "structural_family": family}


def test_recovery_reuses_only_original_train_and_deduplicates_exact_cases(recovery):
    compact_train = record("compact-train", "train", "a", "train-family")
    sources = {
        "spatial-compact-v1": fake_store(
            [
                (compact_train, "deck-a"),
                (record("fresh-validation", "validation", "b", "validation-family"), "deck-b"),
                (record("fresh-test", "test", "c", "test-family"), "deck-c"),
            ]
        ),
        "incidents-v1": fake_store(
            [
                (record("old-train", "train", "d"), "deck-d"),
                (record("old-validation", "validation", "e"), "deck-e"),
                (record("old-test", "test", "f"), "deck-f"),
            ]
        ),
        "spatial-corpus-v1": fake_store([(compact_train, "deck-a")]),
    }
    actual = recovery.select_cases(sources, compact=True)
    assert [c["record"]["id"] for c in actual["train"]] == ["compact-train", "old-train"]
    assert [c["record"]["id"] for c in actual["validation"]] == ["fresh-validation"]
    assert [c["record"]["id"] for c in actual["test"]] == ["fresh-test"]


@pytest.mark.parametrize("same_geometry", [True, False])
def test_recovery_refuses_geometry_or_family_leaking_into_test(recovery, same_geometry):
    sources = {
        "spatial-compact-v1": fake_store(
            [
                (record("fresh-test", "test", "shared", "held-out-family"), "deck1"),
            ]
        ),
        "incidents-v1": fake_store([]),
        "spatial-corpus-v1": fake_store(
            [
                (
                    record(
                        "old-train", "train", "shared" if same_geometry else "different", "held-out-family"
                    ),
                    "deck2",
                ),
            ]
        ),
    }
    with pytest.raises(ValueError, match="leaked"):
        recovery.select_cases(sources, compact=True)


def test_smoke_arrival_separates_timing_from_misses_false_alerts_and_censoring(recovery):
    # Point 0: arrives at 2 s, predicted at 5 s. Other points: miss, false
    # alarm, neither, and an incomplete observation that must be excluded.
    truth = np.array([[0, 0, 0, 0, 0], [2, 2, 0, 0, np.nan], [2, 2, 0, 0, 2]]) * 1e-7
    forecast = np.array([[0, 0, 0, 0, 0], [0, 0, 2, 0, 2], [2, 0, 2, 0, 2]]) * 1e-7
    fields = np.stack([np.zeros_like(forecast), forecast], axis=-1)
    case = {
        "time_s": np.array([0, 2, 5]),
        "smoke_kg_m3": truth,
        "field_mask": np.stack([np.isfinite(truth)] * 2, axis=-1),
    }
    result = recovery.smoke_arrival(case, fields)
    assert result["eligible_points"] == 4
    assert result["excluded_incomplete_points"] == 1
    for key in (
        "both_arrive",
        "missed_arrivals",
        "false_arrivals_within_window",
        "neither_arrives_within_window",
    ):
        assert result[key] == 1
    assert result["conditional_mae_s"] == 3
    assert result["conditional_bias_s"] == 3
    fields[..., 1] = 0
    result = recovery.smoke_arrival(case, fields)
    assert result["conditional_mae_s"] is None
    assert result["conditional_bias_s"] is None
    assert result["missed_arrivals"] == 2


def test_existing_recovery_model_is_refused_before_any_compute(recovery, tmp_path, monkeypatch):
    existing = tmp_path / "runtime/models" / recovery.MODEL_ID
    existing.mkdir(parents=True)

    def no_cuda():
        pytest.fail("An existing model must be detected before initializing compute")

    monkeypatch.setattr(recovery, "require_cuda", no_cuda)
    output = tmp_path / "training"
    with pytest.raises(FileExistsError, match="no compute"):
        recovery.train(tmp_path, output, 900, 120)
    assert not output.exists()
