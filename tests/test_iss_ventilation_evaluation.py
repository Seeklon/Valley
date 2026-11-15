"""Paired errors must reflect actual direction, missing plume coverage and masks."""

import copy
import importlib.util
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def quartet():
    path = Path(__file__).parents[1] / "tools/remote/evaluate_iss_ventilation.py"
    spec = importlib.util.spec_from_file_location("paired_ventilation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases, scores = [], []
    for state, air, point in zip(module.STATES, (0, 0.12, 0.36, 0.36), (0, 1, 2, 0)):
        truth = np.zeros((2, 4, 2), dtype=bool)
        truth[1, point] = True
        config = {"ambient_temperature_c": 20, "airflow_m_s": air, "seed": 1, "ignition_power_w": 3200}
        case = {
            "record": {"id": "case-" + state, "split": "validation", "layout_id": "room",
                       "structural_family": "cargo", "ventilation_group_id": "room-fire",
                       "ventilation_state": state},
            "config": config,
            "manifest": {"objects": [], "sampling": {"shape": [4, 1, 1]},
                         "incident": {"source": {"position_m": [0, 0, 0]}}, "vents": []},
            "positions_m": np.array([[p, 0, 0] for p in range(4)], dtype=float),
            "time_s": np.array([0, 5]), "field_mask": np.ones_like(truth),
            "temperature_c": 20 + 10 * truth[..., 0], "smoke_kg_m3": 2e-6 * truth[..., 1],
        }
        cases.append(case)
        scores.append(np.where(truth, 0.9, 0.1))
    return module, cases, scores, {"heat": 0.5, "smoke": 0.5}


def test_perfect_signed_response_and_centroid_displacement(quartet):
    module, cases, scores, thresholds = quartet
    result = module.paired_metrics(cases, scores, thresholds)
    assert result["group_count"] == 1 and result["contrast_count"] == 3
    for name in module.FIELDS:
        metric = result["metrics"][name]
        assert metric["tp"] == 6 and metric["fp"] == 0 and metric["fn"] == 0
        assert metric["f1"] == 1
        assert metric["centroid_prediction_coverage"] == 1
        assert metric["centroid_displacement_error_mean_m"] == 0


def test_unresponsive_model_cannot_pass_by_predicting_same_plume(quartet):
    module, cases, scores, thresholds = quartet
    result = module.paired_metrics(cases, [scores[0]] * 4, thresholds)
    for name in module.FIELDS:
        metric = result["metrics"][name]
        assert metric["f1"] == 0 and metric["fn"] == 6
        assert metric["centroid_displacement_error_mean_m"] == pytest.approx(5 / 3)


def test_missing_plumes_are_reported_in_centroid_coverage(quartet):
    module, cases, scores, thresholds = quartet
    result = module.paired_metrics(cases, [np.zeros_like(s) for s in scores], thresholds)
    metric = result["metrics"]["smoke"]
    assert metric["recall"] == 0 and metric["centroid_prediction_coverage"] == 0
    assert metric["centroid_missing_prediction_frames"] == 3
    assert metric["centroid_displacement_error_mean_m"] is None


def test_wrong_signed_changes_do_not_count_as_correct(quartet):
    module, cases, scores, thresholds = quartet
    scores[0], scores[1] = scores[1], scores[0]
    first = module.paired_metrics(cases, scores, thresholds)["pairs"][0]["metrics"]["heat"]
    assert first["tp"] == 0 and first["fp"] == 2 and first["fn"] == 2


def test_masks_are_channel_specific_and_initial_time_is_excluded(quartet):
    module, cases, scores, thresholds = quartet
    for case, score in zip(cases, scores):
        case["field_mask"][..., 0] = False
        score[..., 0] = np.nan
        score[0, :, 1] = 0.9
    result = module.paired_metrics(cases, scores, thresholds)
    assert result["metrics"]["heat"]["valid_sample_pairs"] == 0
    assert result["metrics"]["heat"]["f1"] is None
    assert result["metrics"]["smoke"]["valid_sample_pairs"] == 12
    assert result["metrics"]["smoke"]["f1"] == 1


@pytest.mark.parametrize("kind", ("power", "source", "geometry", "sampling", "split", "positions", "vents"))
def test_pair_rejects_confounders_and_misalignment(quartet, kind):
    module, cases, scores, thresholds = quartet
    right = cases[1]
    if kind == "power":
        right["config"]["ignition_power_w"] += 1
    elif kind == "source":
        right["manifest"]["incident"]["source"]["position_m"][0] = 1
    elif kind == "geometry":
        right["manifest"]["objects"] = [{"material": "steel"}]
    elif kind == "sampling":
        right["manifest"]["sampling"]["shape"] = [1, 4, 1]
    elif kind == "split":
        right["record"]["split"] = "test"
    elif kind == "positions":
        right["positions_m"] = right["positions_m"][::-1]
    else:
        right["manifest"]["vents"] = [{"bounds_m": [0] * 6, "normal": [1, 0, 0], "area_m2": 1}]
    with pytest.raises(ValueError):
        module.paired_metrics(cases, scores, thresholds)


def test_quartets_must_be_complete_and_unique(quartet):
    module, cases, scores, thresholds = quartet
    with pytest.raises(ValueError, match="Incomplete"):
        module.paired_metrics(cases[:3], scores[:3], thresholds)
    with pytest.raises(ValueError, match="Duplicate"):
        module.paired_metrics(cases + [copy.deepcopy(cases[0])], scores + [scores[0]], thresholds)


def test_physical_label_boundary_matches_float64_fds_comparison(quartet):
    module, cases, scores, thresholds = quartet
    case = cases[0]
    case["smoke_kg_m3"] = np.full((2, 4), 1e-6, dtype=np.float32)
    truth, _, _ = module._arrays(case, scores[0], thresholds)
    assert float(np.float32(1e-6)) < 1e-6
    assert not truth[..., 1].any()


def test_nonfinite_observed_scores_are_rejected(quartet):
    module, cases, scores, thresholds = quartet
    scores[1][1, 1, 1] = np.nan
    with pytest.raises(ValueError, match="Invalid observed"):
        module.paired_metrics(cases, scores, thresholds)


def test_irregular_physical_times_use_linear_values_before_threshold(quartet):
    module, cases, scores, thresholds = quartet
    case = cases[0]
    case["time_s"] = np.array([4.0, 6.0])
    case["temperature_c"] = np.array([[24.0] * 4, [26.0] * 4])
    case["smoke_kg_m3"] = np.array([[0.0] * 4, [2.2e-6] * 4])
    scores[0][:] = np.array([0.3, 0.7])[:, None, None]
    aligned, predicted, _ = module.interpolate_case(case, scores[0], [5.0])
    truth, classified, observed = module._arrays(aligned, predicted, thresholds)
    assert truth.all() and classified.all() and observed.all()
    assert np.all(aligned["temperature_c"] == 25.0)


def test_exact_time_does_not_require_previous_mask_or_short_gap(quartet):
    module, cases, scores, _ = quartet
    cases[0]["field_mask"][0] = False
    aligned, _, coverage = module.interpolate_case(cases[0], scores[0], [5.0])
    assert aligned["field_mask"].all() and coverage["gap_rejected_times_s"] == []


def test_interpolation_requires_both_masks_and_bounded_time_gap(quartet):
    module, cases, scores, _ = quartet
    cases[0]["time_s"] = np.array([4.0, 6.0])
    cases[0]["field_mask"][0, 0, 1] = False
    aligned, _, _ = module.interpolate_case(cases[0], scores[0], [5.0])
    assert not aligned["field_mask"][0, 0, 1]
    assert aligned["field_mask"][0, 0, 0]
    cases[0]["time_s"] = np.array([3.0, 6.0])
    aligned, _, coverage = module.interpolate_case(cases[0], scores[0], [5.0])
    assert not aligned["field_mask"].any() and coverage["gap_rejected_times_s"] == [5.0]


def test_interpolation_cannot_extrapolate_or_hide_missing_horizons(quartet):
    module, cases, scores, thresholds = quartet
    with pytest.raises(ValueError, match="extrapolate"):
        module.interpolate_case(cases[0], scores[0], [6.0])
    result = module.paired_metrics(cases, scores, thresholds)
    assert result["alignment"]["room-fire"]["common_time_s"] == [5.0]
    assert result["alignment"]["room-fire"]["out_of_domain_time_s"] == [10, 15, 20, 25, 30]
