import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ignis.api import create_app
from ignis.config import Settings
from ignis.schema import RunConfig
from ignis.store import RunStore

ROOT = Path(__file__).resolve().parents[1]


def test_missing_engines_are_explicit_and_never_return_fake_data(tmp_path):
    settings = Settings(root=ROOT, runtime=tmp_path, fds_executable=None)
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/health").json()
        assert health["worker_available"]
        assert health["capabilities"]["physics"] is False
        assert health["capabilities"]["prediction"] is False
        assert health["capabilities"]["source_models"] == []
        assert client.get("/api/models").json() == {"models": []}
        assert client.post("/api/runs", json={"scene_id": "habitat"}).status_code == 503
        assert client.post("/api/runs", json={"scene_id": "habitat", "mode": "prediction"}).status_code == 422
        assert client.get("/api/runs").json()["runs"] == []


def test_electrical_heating_cannot_be_mislabelled_as_chemical_heat_release():
    with pytest.raises(ValueError, match="I²R"):
        RunConfig(scene_id="habitat", ignition_kind="resistive")
    config = RunConfig(scene_id="habitat", source_model="coupled_combustion", ignition_kind="resistive",
                       current_a=5, resistance_ohm=4)
    assert config.physical_config()["ignition_power_w"] == 100
    with pytest.raises(ValueError):
        RunConfig(scene_id="habitat", oxygen_percent=float("nan"))


def test_interrupted_run_fails_without_silent_reexecution_and_queue_survives(tmp_path):
    store = RunStore(tmp_path)
    store.create("a" * 32, {"scene_id": "habitat"})
    store.create("b" * 32, {"scene_id": "cargo"})
    assert store.claim_next()["id"] == "a" * 32
    recovered = RunStore(tmp_path)
    assert recovered.get("a" * 32)["status"] == "running"
    recovered.recover_interrupted()
    assert recovered.get("a" * 32)["status"] == "failed"
    assert recovered.get("b" * 32)["status"] == "queued"
    recovered.cancel("b" * 32)
    assert recovered.claim_next() is None
    assert recovered.get("b" * 32)["status"] == "cancelled"


def test_nasa_inventory_is_not_a_fabricated_training_label():
    catalog = json.loads((ROOT / "data/sources/catalog.json").read_text(encoding="utf-8"))
    saffire = next(s for s in catalog["sources"] if s["id"] == "PSI-98")
    assert saffire["quality"]["table_rows"] == 4
    assert saffire["quality"]["combustion_inventory_rows"] == 2
    assert all(s["used_as_training_labels"] is False for s in catalog["sources"])
