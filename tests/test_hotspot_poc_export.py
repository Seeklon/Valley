"""Replay verification catches label, partition, and score/report mismatches."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def export(tmp_path):
    script = Path(__file__).parents[1] / "tools/remote/verify_hotspot_poc_export.py"
    spec = importlib.util.spec_from_file_location("poc_export_check", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    metrics = module.metrics({"tp": 1, "fp": 1, "fn": 1, "tn": 0})
    entry = {"id": "example", "split": "validation", "layout_id": "room-a",
             "ambient_temperature_c": 20, "url": "/poc/cases/example.json", "metrics": metrics}
    index = {"schema_version": "hotspot-poc-1", "model": {"id": "example-model", "score_threshold": 0.5, "heat_delta_c": 5},
             "cases": [entry], "metrics": {"validation": metrics}}
    case = {"id": "example", "scene": {"bounds_m": [2, 2, 2]},
            "conditions": {"ambient_temperature_c": 20},
            "sample_positions_m": [[0.2, 0.2, z] for z in (0.2, 0.4, 0.6, 0.8)],
            "frames": [
                {"time_s": 0, "temperature_c": [20, 20, 20, 20], "hotspot_score": [0.9] * 4},
                {"time_s": 1, "temperature_c": [25, 20, 25, None], "hotspot_score": [0.9, 0.9, 0.1, None],
                 "valid_mask": [True, True, True, False]},
            ]}
    (tmp_path / "cases").mkdir()

    def write():
        (tmp_path / "hotspots.json").write_text(json.dumps(index))
        (tmp_path / "cases/example.json").write_text(json.dumps(case))

    write()
    return module, tmp_path, index, case, write


def test_metrics_exclude_initial_state_and_unobserved_points(export):
    module, path, _, _, _ = export
    result = module.verify(path)
    assert result["metrics"]["validation"]["n_valid"] == 3
    assert result["metrics"]["validation"]["f1"] == 0.5
    assert result["no_inference_or_training"]


def test_changed_replay_scores_cannot_keep_old_metrics(export):
    module, path, _, case, write = export
    case["frames"][1]["hotspot_score"][0] = 0.1
    write()
    with pytest.raises(ValueError, match="recomputed"):
        module.verify(path)


def test_missing_prediction_at_observed_temperature_is_rejected(export):
    module, path, _, case, write = export
    case["frames"][1]["hotspot_score"][0] = None
    write()
    with pytest.raises(ValueError, match="Missing or invalid"):
        module.verify(path)


def test_same_layout_cannot_cross_partitions(export):
    module, path, index, _, write = export
    index["cases"].append({**index["cases"][0], "id": "other", "split": "train"})
    write()
    with pytest.raises(ValueError, match="crosses partitions"):
        module.verify(path)


def test_rendered_masks_cannot_disagree_with_verified_scores(export):
    module, path, _, case, write = export
    case["frames"][1]["predicted_hot_mask"] = [False, True, False, None]
    write()
    with pytest.raises(ValueError, match="predicted_hot_mask disagrees"):
        module.verify(path)


def test_case_threshold_cannot_differ_from_index(export):
    module, path, _, case, write = export
    case["score_threshold"] = 0.4
    write()
    with pytest.raises(ValueError, match="score_threshold disagree"):
        module.verify(path)


def test_explicit_all_cold_candidate_is_valid(export):
    module, path, index, case, write = export
    index["model"]["score_threshold"] = 1.000001
    expected = module.metrics({"tp": 0, "fp": 0, "fn": 2, "tn": 1})
    index["metrics"]["validation"] = expected
    index["cases"][0]["metrics"] = expected
    case["frames"][1]["predicted_hot_mask"] = [False, False, False, None]
    write()
    assert module.verify(path)["verified"]


def test_undefined_precision_stays_unknown():
    script = Path(__file__).parents[1] / "tools/remote/verify_hotspot_poc_export.py"
    spec = importlib.util.spec_from_file_location("poc_metrics", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values = module.metrics({"tp": 0, "fp": 0, "fn": 0, "tn": 100})
    assert values["precision"] is None
    assert values["recall"] is None
    assert values["iou"] is None
    assert values["false_positive_rate"] == 0
