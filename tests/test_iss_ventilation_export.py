"""Comparison audits reject changed scores, identities and archive sources."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def checker(monkeypatch):
    path = Path(__file__).parents[1] / "tools/remote"
    monkeypatch.syspath_prepend(str(path))
    spec = importlib.util.spec_from_file_location("vent_export_check", path / "verify_iss_ventilation_export.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    case = {
        "record": {"id": "example"}, "time_s": np.array([0.0, 5.0]),
        "field_mask": np.ones((2, 2, 2), dtype=bool),
        "temperature_c": np.array([[20, 20], [30, 30]], dtype=float),
        "smoke_kg_m3": np.array([[0, 0], [0, 2e-6]], dtype=float),
        "config": {"ambient_temperature_c": 20},
    }
    scores = np.array([[[0.9, 0.9], [0.1, 0.1]], [[0.9, 0.9], [0.1, 0.1]]])
    expected = {}
    for name, counts in (("heat", dict(tp=1, fp=0, fn=1, tn=0)), ("smoke", dict(tp=0, fp=1, fn=1, tn=0))):
        value = module.metric(counts)
        expected[name] = {**value, "case_count": 1, "cases": [{"id": "example", **value}]}
    entries = {"example": {"gravity_g": 0.0001, "module_id": "cargo", "incident_type": "flaming"}}
    return module, case, scores, expected, entries


def test_absolute_comparison_recomputes_both_channels_at_nonzero_times(checker):
    module, case, scores, expected, entries = checker
    result = module.absolute_metrics([case], [scores], {"heat": 0.5, "smoke": 0.5}, expected, entries)
    assert result["heat"]["f1"] == pytest.approx(2 / 3)
    assert result["smoke"]["f1"] == 0
    assert result["heat"]["n_valid"] == 2


def test_changed_scores_cannot_reuse_old_report(checker):
    module, case, scores, expected, entries = checker
    scores[1, 1, 0] = 0.9
    with pytest.raises(ValueError, match="recomputed"):
        module.absolute_metrics([case], [scores], {"heat": 0.5, "smoke": 0.5}, expected, entries)


def test_per_case_identity_cannot_be_silently_renamed(checker):
    module, case, scores, expected, entries = checker
    expected["heat"]["cases"][0]["id"] = "wrong-case"
    with pytest.raises(ValueError, match="population"):
        module.absolute_metrics([case], [scores], {"heat": 0.5, "smoke": 0.5}, expected, entries)


def test_comparison_archive_must_match_recorded_hash(checker, tmp_path):
    module = checker[0]
    path = tmp_path / "scores.npz"
    path.write_bytes(b"original")
    record = {"relative_path": path.name, "sha256": module.file_sha(path)}
    assert module.archive_path(tmp_path, record) == path
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        module.archive_path(tmp_path, record)


def test_comparison_archive_cannot_escape_model_directory(checker, tmp_path):
    module = checker[0]
    child = tmp_path / "model"
    child.mkdir()
    path = tmp_path / "scores.npz"
    path.write_bytes(b"elsewhere")
    with pytest.raises(ValueError, match="path"):
        module.archive_path(child, {"relative_path": "../scores.npz", "sha256": module.file_sha(path)})
