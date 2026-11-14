from __future__ import annotations

import csv
import io
import json
import shutil
import uuid
import zipfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .campaigns import CampaignConfig, Campaigns
from .config import Settings
from .engine import Worker
from .incidents import IncidentService
from .knowledge import InsightRequest, interpret
from .locking import ProcessLock
from .ml.registry import ModelRegistry
from .preignition.routes import prevention_router
from .preignition.service import PreventionService
from .schema import RunConfig
from .store import RunStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    catalog = json.loads(settings.catalog_path.read_text(encoding="utf-8"))
    models = ModelRegistry(settings.models_dir)
    store = RunStore(settings.runtime)
    incidents = IncidentService(settings, catalog["scenes"])
    worker = Worker(settings, store, catalog, models, incidents)
    campaigns = Campaigns(settings.runtime / "campaigns", store, catalog["scenes"], settings.max_runs)
    prevention = PreventionService(settings, catalog["scenes"])

    @asynccontextmanager
    async def lifespan(app):
        with ProcessLock(settings.runtime / "service.lock"):
            store.recover_interrupted()
            models.load()
            prevention.load()
            incidents.load()
            worker.start()
            try:
                yield
            finally:
                worker.stop()

    app = FastAPI(title="IGNIS 3D", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.store, app.state.models = settings, store, models
    app.state.prevention = prevention
    app.state.incidents = incidents
    app.include_router(prevention_router(prevention))

    @app.get("/api/health")
    def health():
        source_models = ["prescribed_source", "coupled_combustion"] if worker.runner.available else sorted({
            entry["meta"]["domain"]["source_model"] for entry in models.models.values()
        })
        return {"status": "ok", "worker_available": worker.thread.is_alive(),
                "capabilities": {"physics": worker.runner.available, "prediction": bool(models.models),
                                 "campaigns": worker.runner.available,
                                 "insights": True,
                                 "prevention": True,
                                 "incident_prediction": incidents.model is not None,
                                 "ignition_delay_prediction": prevention.ignition_model is not None,
                                 "source_models": source_models},
                "disk_free_gb": round(shutil.disk_usage(settings.runtime).free / 1024**3, 2),
                "version": "0.1.0"}

    @app.get("/api/scenes")
    def scenes():
        return catalog

    @app.get("/api/materials")
    def materials():
        return {"materials": catalog["materials"]}

    @app.get("/api/models")
    def model_list():
        return {"models": models.list()}

    @app.get("/api/incidents/catalog")
    def incident_catalog():
        return incidents.catalog()

    campaign_directory = settings.runtime.parent / "datasets/spatial-corpus-v1"

    @app.get("/api/incidents/campaign")
    def incident_campaign():
        path = campaign_directory / "progress.json"
        try:
            progress = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Le suivi de campagne est momentanément indisponible.") from exc
        return {"progress": progress, "pause_requested": (campaign_directory / "PAUSE").exists()}

    @app.post("/api/incidents/campaign/pause")
    def pause_incident_campaign(paused: bool):
        if not (campaign_directory / "progress.json").exists():
            raise HTTPException(404, "Aucune campagne de génération n'est disponible.")
        marker = campaign_directory / "PAUSE"
        if paused:
            marker.write_text("Pause demandée depuis IGNIS ; terminer le calcul courant.\n", encoding="utf-8")
        else:
            marker.unlink(missing_ok=True)
        return incident_campaign()

    @app.post("/api/incidents/predict")
    def predict_incidents(config: RunConfig):
        try:
            return incidents.predict_map(config)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/campaigns", status_code=202)
    def create_campaign(spec: CampaignConfig):
        if not worker.runner.available or not worker.thread.is_alive():
            raise HTTPException(503, "Le moteur physique doit être disponible.")
        try:
            return campaigns.create(spec)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/campaigns/{identifier}")
    def get_campaign(identifier: str):
        result = campaigns.get(identifier)
        if result is None:
            raise HTTPException(404, "Campagne inconnue.")
        return result

    @app.post("/api/campaigns/{identifier}/cancel")
    def cancel_campaign(identifier: str):
        get_campaign(identifier)
        return campaigns.cancel(identifier)

    @app.get("/api/campaigns/{identifier}/export")
    def export_campaign(identifier: str):
        campaign = get_campaign(identifier)
        if campaign["status"] in {"queued", "running"}:
            raise HTTPException(409, "La campagne est encore en cours.")
        import pyarrow as pa
        import pyarrow.parquet as pq
        buffer = io.BytesIO()
        observations = []
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(campaign, ensure_ascii=False, indent=2))
            for run_id in campaign["run_ids"]:
                run = store.get(run_id)
                if not run or run["status"] != "completed":
                    continue
                directory = settings.runtime / "runs" / run_id
                result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
                for name in ("config.json", "scene.json", "manifest.json"):
                    if (directory / name).exists():
                        archive.write(directory / name, run_id + "/" + name)
                archive.writestr(run_id + "/provenance.json", json.dumps(result["provenance"]))
                for row in result["metrics"]:
                    numeric = {k: v for k, v in row.items() if isinstance(v, (int, float)) or v is None}
                    observations.append({"run_id": run_id, **run["config"], **numeric})
            if observations:
                table_buffer = io.BytesIO()
                pq.write_table(pa.Table.from_pylist(observations), table_buffer, compression="zstd")
                archive.writestr("metrics.parquet", table_buffer.getvalue())
            archive.writestr("README.txt", "Frames from the same run are not independent samples. Split by scene/family before training.\n"
                              "These labels are generated by FDS, not by NASA experiments. Spatial fields are available in individual run exports.\n")
        buffer.seek(0)
        return StreamingResponse(buffer, media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="ignis-campaign-{identifier}.zip"'})

    @app.get("/api/sources")
    def sources():
        path = settings.root / "data/sources/catalog.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"sources": []}

    @app.post("/api/insights")
    async def insights(request: InsightRequest):
        return await interpret(settings.root, request)

    @app.post("/api/runs", status_code=202)
    def submit(config: RunConfig):
        if not any(s["id"] == config.scene_id for s in catalog["scenes"]):
            raise HTTPException(422, "Scène inconnue.")
        if not worker.thread.is_alive():
            raise HTTPException(503, "Le worker n’est pas disponible.")
        if config.mode == "physics" and not worker.runner.available:
            raise HTTPException(503, "FDS n’est pas installé ou configuré.")
        if config.incident_type:
            try:
                incidents.validate(config)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        elif config.mode == "prediction":
            try:
                models.select(config, next(s for s in catalog["scenes"] if s["id"] == config.scene_id))
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        identifier = uuid.uuid4().hex
        try:
            store.create(identifier, config.model_dump(mode="json"), max_total=settings.max_runs)
        except ValueError as exc:
            raise HTTPException(429, str(exc)) from exc
        return {"id": identifier, "status": "queued"}

    def get_run(identifier):
        if len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
            raise HTTPException(404, "Calcul inconnu.")
        run = store.get(identifier)
        if run is None:
            raise HTTPException(404, "Calcul inconnu.")
        return run

    def public_run(run, include_result=False):
        result_path = run.pop("result_path", None)
        run.pop("cancel_requested", None)
        if include_result and result_path and run["status"] == "completed":
            from pathlib import Path
            run["result"] = json.loads(Path(result_path).read_text(encoding="utf-8"))
        return run

    @app.get("/api/runs")
    def run_list(limit: int = Query(30, ge=1, le=100)):
        return {"runs": [public_run(run) for run in store.list(limit)]}

    @app.get("/api/runs/{identifier}")
    def run_detail(identifier: str):
        return public_run(get_run(identifier), include_result=True)

    @app.post("/api/runs/{identifier}/cancel")
    def cancel(identifier: str):
        get_run(identifier)
        store.cancel(identifier)
        return public_run(get_run(identifier))

    @app.get("/api/runs/{identifier}/export")
    def export(identifier: str):
        run = get_run(identifier)
        if run["status"] != "completed":
            raise HTTPException(409, "Le résultat doit être terminé avant son export.")
        directory = settings.runtime / "runs" / identifier
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in ("config.json", "scene.json", "manifest.json", "ignis.fds", "result.json"):
                if (directory / name).exists():
                    archive.write(directory / name, name)
            rows = result["metrics"]
            table = io.StringIO()
            fields = [key for key in rows[0] if key != "sensors"] if rows else []
            writer = csv.DictWriter(table, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr("metrics.csv", table.getvalue())
            archive.writestr("README.txt", "IGNIS 3D — provenance and numerical limits are in result.json.\n"
                              "Simulation and prediction outputs are not NASA experimental measurements.\n")
        buffer.seek(0)
        return StreamingResponse(buffer, media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="ignis-{identifier}.zip"'})

    assets = settings.root / "scenes/generated"
    assets.mkdir(parents=True, exist_ok=True)
    app.mount("/assets/scenes", StaticFiles(directory=assets), name="scenes")
    dist = settings.root / "web/dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:
        @app.get("/")
        def no_build():
            return {"application": "IGNIS 3D", "message": "Compiler le frontend : npm ci && npm run build dans web."}
    return app
