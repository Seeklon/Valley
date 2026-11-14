import hashlib
import io
import json
import runpy
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from ignis.api import create_app
from ignis.config import Settings
from ignis.preignition.learning import (
    IGNITION_MODEL_ID,
    THERMAL_FEATURES,
    IgnitionDelayModel,
    ThermalHistoryModel,
    thermal_features,
)
from ignis.preignition.schema import PreventionConfig

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "evidence/prevention/models" / IGNITION_MODEL_ID


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("IGNIS_CODEX_EXECUTABLE", raising=False)
    shutil.copytree(ARTIFACT, tmp_path / "prevention/models" / IGNITION_MODEL_ID)
    app = create_app(Settings(root=ROOT, runtime=tmp_path, fds_executable=None))
    with TestClient(app) as http:
        yield http


def test_archived_ignition_points_and_current_group_partitions_are_traceable():
    source = ROOT / "data/prevention/ignition"
    blob = (source / "dataset.json").read_bytes()
    data = json.loads(blob)
    assert hashlib.sha256((source / data["source_file"]).read_bytes()).hexdigest() == data["source_sha256"]
    assert data["is_nasa_dataset"] is False
    points = data["points"]
    assert len(points) == 26
    assert all(p["origin"] == "published_experimental_figure_digitization" for p in points)
    assert all(p["experimental_uncertainty"] is None and p["replicate_count"] is None for p in points)
    groups = [{p["family_id"] for p in points if p["split"] == split} for split in ["train", "validation", "test"]]
    assert not groups[0] & groups[1] and not groups[0] & groups[2] and not groups[1] & groups[2]
    model = IgnitionDelayModel(ARTIFACT)
    assert model.metadata["dataset_sha256"] == hashlib.sha256(blob).hexdigest()
    assert model.metadata["metrics"]["test"]["points"] == 9
    assert model.metadata["metrics"]["test"]["false_alarms_per_hour"] is None
    for record in model.metadata["metrics"]["test"]["predictions"]:
        assert model.delay(record["current_a"]) == pytest.approx(record["predicted_delay_s"])
    assert model.metadata["uncertainty_interval"] is None


@pytest.mark.parametrize("change", [{"gravity_g": 1}, {"airflow_m_s": .05}, {"cutoff_s": 1},
                                   {"oxygen_percent": 25}, {"pressure_pa": 80000}, {"ambient_temperature_c": 30}])
def test_empirical_model_refuses_unlearned_interventions(change):
    model = IgnitionDelayModel(ARTIFACT)
    cfg = PreventionConfig().model_dump() | change
    assert model.reasons(cfg, 5, "nichrome_ldpe_guo2023")


def test_empirical_domain_and_artifact_integrity(tmp_path):
    model = IgnitionDelayModel(ARTIFACT)
    cfg = PreventionConfig().model_dump()
    assert model.reasons(cfg, 5, "nichrome_ldpe_guo2023") == []
    assert model.reasons(cfg, 5, "copper")
    assert model.reasons(cfg, 0, "nichrome_ldpe_guo2023")
    for current in [0, 20, float("nan")]:
        with pytest.raises(ValueError):
            model.delay(current)
    shutil.copytree(ARTIFACT, tmp_path / "model")
    (tmp_path / "model/parameters.json").write_text("{}")
    with pytest.raises(ValueError, match="empreinte"):
        IgnitionDelayModel(tmp_path / "model")


def test_temperature_features_only_use_history_and_declared_commands():
    cfg = PreventionConfig().model_dump()
    history = [{"time_s": t, "surface_temperature_c": 20+10*t, "current_a": 5,
                "hidden_conductor_temperature_c": 1000, "future_ignition_time_s": 0}
               for t in [0, .1, .2, .3, .4, .5]]
    before = thermal_features(history, cfg, 1.5, 5)
    for row in history:
        row["hidden_conductor_temperature_c"] = -1e9
        row["future_ignition_time_s"] = 10000
    np.testing.assert_equal(before, thermal_features(history, cfg, 1.5, 5))
    after = thermal_features(history, cfg | {"cutoff_s": .75}, 1.5, 5)
    assert dict(zip(THERMAL_FEATURES, after))["scheduled_on_time_s"] == .25
    assert before[1] == after[1] == 25
    with pytest.raises(ValueError):
        thermal_features(history[::-1], cfg, 1.5, 5)


def test_thermal_inference_guards_pressure_elapsed_and_forecast_horizon():
    model = ThermalHistoryModel.__new__(ThermalHistoryModel)
    model.metadata = {"domain": {"current_a": [0, 20], "airflow_m_s": [0, .5],
        "ambient_temperature_c": [0, 50], "elapsed_s": [.1, 10], "gravity_g": [.0001, 1],
        "pressure_pa": 101325, "horizon_s": [.1, 20]}}
    cfg = PreventionConfig().model_dump()
    history = [{"time_s": .5, "surface_temperature_c": 25, "current_a": 5}]
    with pytest.raises(ValueError, match="Pression"):
        model.predict(history, cfg | {"pressure_pa": 90000}, [1], 5)
    with pytest.raises(ValueError, match="elapsed"):
        model.predict([history[0] | {"time_s": 11}], cfg, [12], 5)
    with pytest.raises(ValueError, match="Horizon"):
        model.predict(history, cfg, [.51], 5)


def test_thermal_campaign_groups_gravity_and_cutoff_pairs_before_solving():
    module = runpy.run_path(str(ROOT / "tools/remote/train_thermal.py"))
    rows = module["scenarios"]()
    assert len(rows) == 384
    assert len({r["family_id"] for r in rows}) == 96
    for family in {r["family_id"] for r in rows}:
        members = [r for r in rows if r["family_id"] == family]
        assert len(members) == 4
        assert len({r["split"] for r in members}) == 1
        assert {r["config"]["gravity_g"] for r in members} == {.0001, 1}


def test_analysis_has_actual_conditional_delay_and_unknown_components(client):
    response = client.post("/api/prevention/analyze", json={})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["components"]) == 4
    wire = result["components"][0]
    assert wire["status"] == "available"
    assert 7 < wire["estimate"]["ignition_delay_s"] < 9
    assert wire["ignition_probability"] is None and wire["interval"] is None
    assert all(p["time_s"] <= .5+1e-9 for p in wire["observations"])
    assert all(p["time_s"] > .5 for p in wire["forecast"])
    assert wire["thermal"]["ignition_supported"] is False
    assert result["components"][2]["status"] == "unsupported"
    assert result["components"][2]["estimate"] is None
    response = client.get(result["export_url"])
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert {"analysis.json", "config.json", "thermal_series.csv", "evidence_findings.json", "README.txt"} <= set(archive.namelist())
        assert json.loads(archive.read("evidence_findings.json")) == result["evidence_snapshot"]
        assert json.loads(archive.read("analysis.json"))["id"] == result["id"]
        assert "observations" in archive.read("thermal_series.csv").decode()
    answer = client.post("/api/prevention/interpret", json={"analysis_id": result["id"], "component_id": wire["component_id"]})
    assert answer.status_code == 200
    assert answer.json()["method"] == "extractive_evidence"
    assert "[GUO-2023]" in answer.json()["summary"]


def test_cutoff_cannot_turn_temperature_into_a_fire_probability(client):
    result = client.post("/api/prevention/analyze", json={"cutoff_s": .25}).json()
    wire = result["components"][0]
    assert wire["status"] == "out_of_domain" and wire["estimate"] is None
    assert wire["ignition_probability"] is None
    assert wire["forecast"][-1]["current_a"] == 0
    assert wire["thermal"]["summary"]["ignition_time_s"] is None


def test_catalog_evidence_and_request_boundaries(client):
    catalog = client.get("/api/prevention/catalog").json()
    assert catalog["default_scene_id"] == "soyuz"
    assert catalog["models"][0]["id"] == IGNITION_MODEL_ID
    evidence = client.get("/api/prevention/evidence").json()
    assert len([f for f in evidence["findings"] if f["id"].startswith("NASA-")]) == 22
    assert evidence["findings"][-1]["id"] == "GUO-2023"
    for cfg in [{"scene_id": "unknown"}, {"observation_cutoff_s": 19, "horizon_s": 5}, {"cutoff_s": 30}]:
        assert client.post("/api/prevention/analyze", json=cfg).status_code == 422
    assert client.get("/api/prevention/evidence?component_id=missing").status_code == 422
    assert client.get("/api/prevention/analyses/invalid/export").status_code == 404


def test_exports_keep_original_evidence_after_catalog_changes(client, monkeypatch):
    result = client.post("/api/prevention/analyze", json={}).json()
    monkeypatch.setattr(client.app.state.prevention, "evidence", lambda **kw: {"findings": [], "limitations": []})
    with zipfile.ZipFile(io.BytesIO(client.get(result["export_url"]).content)) as archive:
        snapshot = json.loads(archive.read("evidence_findings.json"))
        assert snapshot == result["evidence_snapshot"]
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        assert digest == result["provenance"]["evidence_snapshot_sha256"]


def test_terrestrial_conditions_are_recognized_and_incompatible_air_ranked_lower(client):
    findings = client.get("/api/prevention/evidence?gravity_g=1").json()["findings"]
    terrestrial = next(f for f in findings if f["id"] == "NASA-PRE-019")
    assert "Le régime de gravité choisi est inclus dans la conclusion." in terrestrial["reasons"]
    findings = client.get("/api/prevention/evidence?airflow_m_s=0.08").json()["findings"]
    same = next(f for f in findings if f["id"] == "NASA-PRE-002")
    assert any("Vitesse nominale ou plage" in r for r in same["reasons"])


def test_codex_uses_frozen_applicability_of_the_selected_component(client, tmp_path, monkeypatch):
    result = client.post("/api/prevention/analyze", json={}).json()
    component = result["components"][-1]
    selected_id = component["component_id"]
    executable = tmp_path / "codex.exe"
    executable.touch()
    monkeypatch.setenv("IGNIS_CODEX_EXECUTABLE", str(executable))
    captured = {}

    def summary(_executable, prompt):
        context = json.loads(prompt[prompt.index('{"question"'):])
        captured.update(context)
        return f"Données à confronter au composant [{context['nasa_findings'][0]['id']}].", "test-double"

    monkeypatch.setattr("ignis.preignition.routes.codex_summary", summary)
    response = client.post("/api/prevention/interpret", json={"analysis_id": result["id"], "component_id": selected_id})
    assert response.status_code == 200
    assert response.json()["method"] == "codex_grounded_in_prevention_evidence"
    expected = {f["id"]: f for f in result["evidence_snapshots_by_component"][selected_id]["findings"]}
    assert all(f == expected[f["id"]] for f in captured["nasa_findings"])
    assert captured["status"] == "unsupported"
