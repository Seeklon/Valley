"""Exercise the real Windows service; no mocked engine, models, or NASA response."""
from __future__ import annotations

import io
import json
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pyarrow.parquet as pq


def main():
    root = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    report = {"base_url": "http://127.0.0.1:8765", "checks": [], "runs": [],
              "started_utc": datetime.now(timezone.utc).isoformat()}
    with httpx.Client(base_url=report["base_url"], timeout=125) as client:
        def check(name, **details):
            report["checks"].append({"name": name, "passed": True, **details})
            print("PASS", name, flush=True)

        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def post(path, data=None):
            response = client.post(path, json=data)
            response.raise_for_status()
            return response.json()

        def await_run(identifier):
            end = time.monotonic() + 180
            while time.monotonic() < end:
                run = get("/api/runs/" + identifier)
                if run["status"] in {"completed", "failed", "cancelled"}:
                    report["runs"].append({"id": identifier, "status": run["status"], "config": run["config"]})
                    return run
                time.sleep(.4)
            raise TimeoutError(identifier)

        health = get("/api/health")
        assert all(health["capabilities"][key] for key in ("physics", "prediction", "campaigns", "insights"))
        models = get("/api/models")["models"]
        assert {m["id"] for m in models if m["loaded"]} == {"field-mlp-v2", "metrics-forest-v2"}
        assert all(m["physical_scene_hash_version"] == 2 for m in models)
        check("models_preloaded_and_all_engines_available")
        cfg = {"scene_id": "soyuz", "duration_s": 30, "ignition_duration_s": 10, "ignition_power_w": 1000,
               "airflow_m_s": .2, "oxygen_percent": 21, "gravity_g": .0001, "material_id": "cellulose"}
        physical = await_run(post("/api/runs", cfg)["id"])
        assert physical["status"] == "completed", physical.get("message")
        result = physical["result"]
        assert result["provenance"]["engine"] == "FDS" and result["provenance"]["origin"] == "simulation"
        assert result["summary"]["nonfinite_spatial_measurements"] == 0
        assert max(m["temperature_max_c"] for m in result["metrics"]) > 20.1
        check("real_soyuz_fds_run", run_id=physical["id"], frames=len(result["frames"]), summary=result["summary"])
        blob = client.get(f"/api/runs/{physical['id']}/export")
        blob.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(blob.content)) as archive:
            assert {"result.json", "config.json", "scene.json", "metrics.csv"} <= set(archive.namelist())
            assert json.loads(archive.read("result.json"))["provenance"]["input_sha256"] == result["provenance"]["input_sha256"]
        check("individual_export_matches_real_result", bytes=len(blob.content))
        for scene_id in ("habitat", "cargo", "crossflow", "soyuz"):
            for identifier, has_fields in [("field-mlp-v2", True), ("metrics-forest-v2", False)]:
                predicted = await_run(post("/api/runs", {**cfg, "scene_id": scene_id, "mode": "prediction", "model_id": identifier})["id"])
                assert predicted["status"] == "completed", predicted.get("message")
                result = predicted["result"]
                assert result["provenance"]["model_id"] == identifier
                assert bool(result["frames"]) is has_fields
                assert len(result["metrics"]) == 31
                if has_fields:
                    assert any("cohérence" in warning for warning in result["provenance"]["warnings"])
                    for frame in result["frames"]:
                        assert len(frame["temperature_c"]) == 320
                        assert all((value is None) == (not valid) for value, valid in zip(frame["temperature_c"], frame["valid_mask"]))
                check("actual_prediction_" + scene_id + "_" + identifier,
                      run_id=predicted["id"], seconds=result["provenance"]["inference_seconds"])
        for changed in ({"gravity_g": .16}, {"mesh_cell_m": .4}, {"airflow_m_s": .8}):
            response = client.post("/api/runs", json={**cfg, "mode": "prediction", **changed})
            assert response.status_code == 422
        check("prediction_domain_rejections")
        cancelled_id = post("/api/runs", {**cfg, "duration_s": 180, "mesh_cell_m": .1})["id"]
        for _ in range(100):
            if get("/api/runs/" + cancelled_id)["status"] == "running":
                break
            time.sleep(.1)
        time.sleep(.5)
        post(f"/api/runs/{cancelled_id}/cancel")
        cancelled = await_run(cancelled_id)
        assert cancelled["status"] == "cancelled"
        check("running_fds_cancellation", run_id=cancelled_id)
        campaign = post("/api/campaigns", {"count": 2, "seed": 721, "scene_ids": ["soyuz", "habitat"],
            "base_config": {**cfg, "duration_s": 10, "ignition_duration_s": 5},
            "ranges": {"airflow_m_s": [.1, .2], "ignition_power_w": [500, 750]}})
        for run_id in campaign["run_ids"]:
            assert await_run(run_id)["status"] == "completed"
        campaign = get("/api/campaigns/" + campaign["id"])
        assert campaign["status"] == "completed" and campaign["completed_runs"] == 2
        exported = client.get(f"/api/campaigns/{campaign['id']}/export")
        exported.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            table = pq.read_table(io.BytesIO(archive.read("metrics.parquet")))
            assert len(set(table.column("run_id").to_pylist())) == 2
            assert table.num_rows > 10
        check("campaign_completion_and_parquet_export", campaign_id=campaign["id"], rows=table.num_rows)
        insight = post("/api/insights", {"config": cfg, "question": "Que permettent de comparer les observations NASA pour cette capsule ?"})
        assert insight["sources"] and insight["facts"] and insight["summary"]
        assert insight["method"] == "codex_grounded_in_nasa_evidence", insight
        check("actual_codex_nasa_interpretation", method=insight["method"], model=insight["model"])
        report["insight"] = insight
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    destination = root / "runtime/application-verification.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("APPLICATION_VERIFIED", len(report["checks"]), flush=True)


if __name__ == "__main__":
    main()
