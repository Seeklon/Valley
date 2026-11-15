"""Sampling and measured-peak contracts; tiny CPU tensors, no accuracy claims."""

# ruff: noqa: E402
import importlib.util
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")


@pytest.fixture
def hotspot(monkeypatch):
    scripts = Path(__file__).parents[1] / "tools/remote"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("hotspot_test", scripts / "hotspot_spatial.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample(temperatures, split="train"):
    temperatures = np.asarray(temperatures, dtype=np.float32)
    return {
        "record": {"split": split, "id": "case", "layout_id": "geometry"},
        "config": {"ambient_temperature_c": 20, "gravity_g": 0, "incident_type": "overheating"},
        "time_s": np.arange(len(temperatures)),
        "temperature_c": temperatures,
        "field_mask": np.ones((*temperatures.shape, 2), dtype=bool),
        "positions_m": np.arange(temperatures.shape[1] * 3).reshape(-1, 3).astype(float),
    }


def test_hot_times_gain_mass_without_losing_cold_times_or_equal_case_weight(hotspot):
    cases = [sample([[20], [20], [30], [80], [400]]), sample([[20], [20], [20]])]
    uniform, addresses = hotspot.frame_probabilities(cases, "uniform")
    hot, other = hotspot.frame_probabilities(cases, "hot")
    assert addresses == other
    assert all(frame > 0 for _, frame in addresses)
    assert (hot > 0).all() and hot.sum() == pytest.approx(1)
    for case in (0, 1):
        assert sum(hot[i] for i, (c, _) in enumerate(addresses) if c == case) == pytest.approx(0.5)
    peak = addresses.index((0, 4))
    assert hot[peak] > uniform[peak]


@pytest.mark.parametrize("split", ["validation", "test"])
def test_sampler_cannot_use_heldout_targets(hotspot, split):
    with pytest.raises(ValueError, match="training only"):
        hotspot.frame_probabilities([sample([[20], [100]], split)], "hot")


def test_peak_anchor_uses_true_coordinate_not_largest_prediction(hotspot):
    target = torch.tensor([[[0.0, 5.0, 0.0], [0.0, 0.0, 0.0]]])
    wrong = torch.tensor([[[5.0, 0.0, 0.0], [0.0, 0.0, 0.0]]], requires_grad=True)
    mask = torch.ones_like(target, dtype=torch.bool)
    loss = hotspot.amplitude_anchor(wrong, target, mask, target > 0)
    assert loss.item() == pytest.approx(4.5)
    loss.sum().backward()
    assert wrong.grad[0, 0, 1] < 0
    assert hotspot.amplitude_anchor(target, target, mask, target > 0).item() == 0


def test_missing_and_inactive_peaks_have_no_gradient(hotspot):
    target = torch.tensor([[[float("nan"), 3.0], [float("nan"), float("nan")]]])
    mask = torch.isfinite(target)
    prediction = torch.zeros_like(target, requires_grad=True)
    loss = hotspot.amplitude_anchor(prediction, target, mask, mask & (target > 0))
    loss.sum().backward()
    assert torch.isfinite(prediction.grad).all()
    assert prediction.grad[~mask].count_nonzero() == 0
    assert prediction.grad[0, 0, 1] < 0
    assert hotspot.amplitude_anchor(prediction, target, mask, torch.zeros_like(mask)).item() == 0


def test_peak_alignment_rejects_peak_at_wrong_place_time_and_missing_cell(hotspot):
    case = sample([[20, 20, 999], [100, 20, 999], [30, 20, 999]])
    case["field_mask"][:, 2] = False
    fields = np.stack([[[20, 20, 5000], [20, 90, 5000], [30, 110, 5000]], np.zeros((3, 3))], axis=-1)
    result = hotspot.peak_alignment(case, fields)
    assert result["sampled_peak_c"] == 100
    assert result["prediction_at_true_peak_c"] == 20
    assert result["peak_location_amplitude_error_c"] == 80
    assert result["predicted_peak_c"] == 110
    assert result["peak_time_error_s"] == 1
    assert result["peak_displacement_at_true_time_m"] == pytest.approx(np.sqrt(27))
