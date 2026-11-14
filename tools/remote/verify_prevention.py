"""Verify frozen training artifacts and the actual Windows prevention service."""
from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pyarrow.parquet as pq
from ignis.engine import write_json
from ignis.preignition.learning import THERMAL_FEATURES, THERMAL_MODEL_ID, ThermalHistoryModel


def main():
    home = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "host": "Windows", "checks": [], "analyses": []}

    def check(name, **details):
        report["checks"].append({"name": name, "passed": True, **details})
        print("PASS", name, flush=True)

    folder = home / "runtime/prevention/datasets/thermal-families-v1"
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    for name, expected in metadata["hashes"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))["scenarios"]
    assert len(plan) == 384
    families = {r["family_id"] for r in plan}
    assert len(families) == 96
    assert all(len({r["split"] for r in plan if r["family_id"] == family}) == 1 for family in families)
    check("frozen_dataset_hashes_and_family_partitions", trajectories=384, families=96)
    model = ThermalHistoryModel(home / "runtime/prevention/models" / THERMAL_MODEL_ID)
    rows = [r for r in pq.read_table(folder / "windows.parquet").to_pylist() if r["split"] == "test"]
    x = np.asarray([[r[f] for f in THERMAL_FEATURES] for r in rows])
    prediction = model.model.predict(x)
    errors = np.abs(prediction - np.asarray([r["target_temperature_c"] for r in rows]))
    weights = np.asarray([1/sum(other["family_id"] == r["family_id"] for other in rows) for r in rows])
    mae = float(np.average(errors, weights=weights))
    assert abs(mae-model.metadata["metrics"]["test"]["mae_c"]) < 1e-9
    assert abs(float(errors.max())-model.metadata["metrics"]["test"]["max_absolute_error_c"]) < 1e-9
    check("saved_thermal_weights_reproduce_frozen_test_metrics", mae_c=mae, max_error_c=float(errors.max()), windows=len(rows))

    with httpx.Client(base_url="http://127.0.0.1:8765", timeout=90) as client:
        catalog = client.get("/api/prevention/catalog").json()
        assert len(catalog["models"]) == 2
        assert client.get("/api/health").json()["capabilities"]["ignition_delay_prediction"]
        assert len([m for m in client.get("/api/models").json()["models"] if m["loaded"]]) == 2
        check("four_models_preloaded_across_prevention_and_laboratory")

        def analyze(change):
            response = client.post("/api/prevention/analyze", json=change)
            response.raise_for_status()
            result = response.json()
            report["analyses"].append({"id": result["id"], "config": result["config"],
                "components": [{"id": c["component_id"], "status": c["status"], "estimate": c["estimate"],
                                "learned_points": len(c["learned_forecast"])} for c in result["components"]]})
            assert all(c["ignition_probability"] is None and c["interval"] is None for c in result["components"])
            assert all(c["estimate"] is None for c in result["components"][2:])
            for c in result["components"]:
                assert all(p["time_s"] <= result["observation_cutoff_s"]+1e-9 for p in c["observations"])
                assert all(p["time_s"] > result["observation_cutoff_s"] for p in c["learned_forecast"])
            return result

        default = analyze({})
        assert all(c["estimate"] and c["learned_forecast"] for c in default["components"][:2])
        check("real_empirical_and_history_inference_before_ignition", analysis_id=default["id"])
        for scene in ["habitat", "cargo", "crossflow"]:
            result = analyze({"scene_id": scene})
            assert result["components"][0]["estimate"]["ignition_delay_s"] == default["components"][0]["estimate"]["ignition_delay_s"]
        check("scene_markers_do_not_invent_a_geometry_effect_on_uncoupled_wire_model")
        cutoff = analyze({"cutoff_s": .25})["components"][0]
        assert cutoff["estimate"] is None and cutoff["learned_forecast"]
        assert cutoff["forecast"][-1]["current_a"] == 0
        assert cutoff["forecast"][-1]["surface_temperature_c"] < cutoff["observations"][-1]["surface_temperature_c"]
        check("cutoff_continues_cooling_and_refuses_unsupported_ignition_delay")
        for change in [{"airflow_m_s": .1}, {"gravity_g": 1}, {"pressure_pa": 80000}]:
            c = analyze(change)["components"][0]
            assert c["status"] == "out_of_domain" and c["estimate"] is None
            if "pressure_pa" in change:
                assert c["learned_forecast"] == []
                assert any("Pression" in line for line in c["thermal"]["limitations"])
            else:
                assert c["learned_forecast"]
        check("empirical_and_thermal_domains_are_independently_enforced")
        late = analyze({"current_a": 2, "observation_cutoff_s": 11, "duration_s": 40})["components"][0]
        assert late["learned_forecast"] == []
        assert any("elapsed_s" in line for line in late["thermal"]["limitations"])
        check("future_temperature_does_not_extrapolate_beyond_trained_elapsed_domain")
        archive = client.get(default["export_url"])
        archive.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            original = json.loads(z.read("analysis.json"))
            snapshot = json.loads(z.read("evidence_findings.json"))
            assert original == default and snapshot == default["evidence_snapshot"]
            assert hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest() == default["provenance"]["evidence_snapshot_sha256"]
            assert len([f for f in snapshot["findings"] if f["is_nasa_source"]]) == 22
        check("export_preserves_analysis_and_hashed_experimental_evidence")
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(home / "runtime/prevention/application-verification.json", report)
    print(json.dumps({"verified_checks": len(report["checks"])}), flush=True)


if __name__ == "__main__":
    main()
