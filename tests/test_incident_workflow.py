import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ignis.api import create_app
from ignis.config import Settings
from ignis.incidents import consequences, incident_scene
from ignis.provenance import physical_scene_sha
from ignis.schema import RunConfig

ROOT = Path(__file__).resolve().parents[1]


def test_incident_annotations_do_not_change_legacy_model_identity():
    catalog = json.loads((ROOT / "scenes/catalog.json").read_text())
    for scene in catalog["scenes"]:
        original = copy.deepcopy(scene)
        prepared = incident_scene(scene)
        assert scene == original
        assert prepared["components"]
        assert any(o.get("combustible_material_id") for o in prepared["objects"])
        original.pop("incident_annotations")
        assert physical_scene_sha(scene) == physical_scene_sha(original)
    assert "incident_type" not in RunConfig(scene_id="soyuz").physical_config()


@pytest.mark.parametrize("extra", [
    {"incident_type": "arc"}, {"component_id": "one"},
    {"incident_type": "arc", "component_id": "one", "source_model": "prescribed_source"},
])
def test_incident_config_requires_consistent_source_contract(extra):
    with pytest.raises(ValueError):
        RunConfig(scene_id="soyuz", **extra)


def test_untrained_prediction_returns_explicit_error_and_no_run(tmp_path):
    with TestClient(create_app(Settings(ROOT, tmp_path, None))) as client:
        catalog = client.get("/api/incidents/catalog").json()
        assert len(catalog["incidents"]) == 5
        assert catalog["model"]["available"] is False
        component = next(c for c in catalog["components"] if c["scene_id"] == "soyuz")
        config = {**catalog["defaults"], "incident_type": "flaming", "component_id": component["id"]}
        assert client.post("/api/incidents/predict", json=config).status_code == 422
        assert client.post("/api/incidents/predict", json={**config, "component_id": "unknown"}).status_code == 422
        assert client.get("/api/runs").json()["runs"] == []


def test_bulk_pause_only_changes_marker_and_preserves_progress(tmp_path):
    runtime = tmp_path / "runtime"
    with TestClient(create_app(Settings(ROOT, runtime, None))) as client:
        assert client.get("/api/incidents/campaign").json()["progress"] is None
        assert client.post("/api/incidents/campaign/pause?paused=true").status_code == 404
        dataset = tmp_path / "datasets/spatial-corpus-v1"
        dataset.mkdir(parents=True)
        progress = {"state": "running", "completed_runs": 3, "total_runs": 20000}
        (dataset / "progress.json").write_text(json.dumps(progress))
        assert client.post("/api/incidents/campaign/pause?paused=true").json()["pause_requested"]
        assert (dataset / "PAUSE").exists()
        assert client.get("/api/incidents/campaign").json()["progress"] == progress
        assert not client.post("/api/incidents/campaign/pause?paused=false").json()["pause_requested"]
        assert not (dataset / "PAUSE").exists()


def example():
    scene = {"bounds_m": [2, 2, 2], "components": [{"id": "source", "object_id": "origin"}],
             "objects": [{"id": name, "role": "obstacle", "center_m": [x, .5, .25],
                          "size_m": [.2, .2, .5], "critical": True}
                         for name, x in [("origin", .5), ("neighbour", 1.5)]], "sensors": []}
    points = [[x, y, z] for x in [.5, 1.5] for y in [.5, 1.5] for z in [.5, 1.5]]
    frame = {"time_s": 2, "bounds_m": [2, 2, 2], "sample_positions_m": points,
             "temperature_c": [100]*8, "smoke_kg_m3": [20e-6]*8, "valid_mask": [True]*8}
    return scene, {"component_id": "source"}, {"frames": [frame]}


def test_consequences_are_conditional_exposure_with_units_and_source_excluded():
    scene, config, result = example()
    values = consequences(scene, config, result)
    assert values["heat_peak_c"] == 100
    assert values["smoke_peak_mg_m3"] == 20
    assert values["hot_volume_peak_m3"] == 8
    assert values["exposed_equipment_ids"] == ["neighbour"]
    assert values["critical_exposed_count"] == 1
    assert values["passages_exposed_count"] is None


def test_missing_fields_or_distant_samples_do_not_mean_safe_equipment():
    scene, config, result = example()
    result["frames"][0]["temperature_c"] = [20]*8
    del result["frames"][0]["smoke_kg_m3"]
    values = consequences(scene, config, result)
    assert values["heat_peak_c"] == 20
    assert values["smoke_peak_mg_m3"] is None
    assert values["exposed_equipment_count"] is None
    # A distant valid gas sample must not be assigned across a room.
    result["frames"][0]["valid_mask"] = [True] + [False]*7
    result["frames"][0]["smoke_kg_m3"] = [20e-6]*8
    values = consequences(scene, config, result)
    assert values["exposed_equipment_count"] is None
    assert values["unobserved_equipment_ids"] == ["neighbour"]


def test_invalid_cells_cannot_create_heat_or_smoke():
    scene, config, result = example()
    result["frames"][0]["valid_mask"] = [False]*8
    values = consequences(scene, config, result)
    assert values["heat_peak_c"] is None
    assert values["smoke_peak_mg_m3"] is None
    assert values["exposed_equipment_count"] is None


def test_missing_later_frame_cannot_make_initially_cold_equipment_safe():
    scene, config, result = example()
    result["frames"][0]["temperature_c"] = [20]*8
    result["frames"][0]["smoke_kg_m3"] = [0]*8
    later = copy.deepcopy(result["frames"][0])
    later.update(time_s=3, temperature_c=[None]*8, smoke_kg_m3=[None]*8)
    result["frames"].append(later)
    values = consequences(scene, config, result)
    assert values["exposed_equipment_count"] is None
    assert values["critical_exposed_count"] is None
    assert values["unobserved_equipment_ids"] == ["neighbour"]
