from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path

from .config import Settings
from .locking import ProcessLock
from .schema import RunConfig
from .store import RunStore


class Cancelled(Exception):
    pass


def write_json(path: Path, value: dict):
    temp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class FDSRunner:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def available(self) -> bool:
        p = self.settings.fds_executable
        return p is not None and p.is_file()

    def run(self, scene: dict, config: dict, directory: Path, *, progress=None, cancel=None) -> dict:
        lock = ProcessLock(self.settings.runtime / "compute.lock")
        waiting = time.monotonic()
        while True:
            if cancel and cancel():
                raise Cancelled()
            try:
                lock.acquire()
                break
            except RuntimeError:
                if time.monotonic() - waiting > 3600:
                    raise TimeoutError("Le poste de calcul est occupé depuis plus d’une heure.")
                if progress:
                    progress(0, "En attente du poste de calcul IGNIS.")
                time.sleep(0.5)
        try:
            return self._run(scene, config, directory, progress=progress, cancel=cancel)
        finally:
            lock.release()

    def _run(self, scene: dict, config: dict, directory: Path, *, progress=None, cancel=None) -> dict:
        from .physics import compile_case, parse_result

        if not self.available:
            raise RuntimeError("Le moteur FDS n’est pas configuré sur cette machine.")
        if shutil.disk_usage(directory.parent).free < self.settings.disk_reserve_gb * 1024**3:
            raise RuntimeError("Réserve disque atteinte : libérer de l’espace avant de lancer un calcul.")
        directory.mkdir(parents=True, exist_ok=True)
        compile_case(scene, config, directory)
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(self.settings.omp_threads)
        env["OMP_STACKSIZE"] = "64M"
        binary_dir = self.settings.fds_executable.parent
        env["PATH"] = os.pathsep.join([str(binary_dir), str(binary_dir / "mpi"), env.get("PATH", "")])
        if (binary_dir / "mpi").exists():
            env["I_MPI_ROOT"] = str(binary_dir / "mpi")
        # No shell: executable and deck are separate arguments, both project-controlled.
        deck = directory / "ignis.fds"
        started = time.monotonic()
        with (directory / "engine.log").open("w", encoding="utf-8") as log:
            command = [str(self.settings.fds_executable), deck.name]
            job = None
            if os.name == "nt":
                from .windows_process import spawn_in_job
                process, job = spawn_in_job(command, cwd=directory, env=env, stdout=log,
                                           stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                process = subprocess.Popen(command, cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                while process.poll() is None:
                    if cancel and cancel():
                        raise Cancelled()
                    if time.monotonic() - started > 3600:
                        raise TimeoutError("FDS a dépassé la limite de calcul d’une heure.")
                    if progress:
                        simulated = 0.0
                        outputs = list(directory.glob("*.out"))
                        if outputs:
                            with outputs[0].open("rb") as out:
                                out.seek(max(0, outputs[0].stat().st_size - 16384))
                                tail = out.read().decode(errors="replace")
                            times = re.findall(r"Total Time:\s*([\d.Ee+\-]+)", tail)
                            if times:
                                simulated = float(times[-1])
                        progress(min(0.94, 0.03 + 0.9 * simulated / config["duration_s"]),
                                 f"FDS · {simulated:.1f} / {config['duration_s']:g} s physiques")
                    time.sleep(0.5)
            finally:
                try:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                finally:
                    if job is not None:
                        job.close()
        if cancel and cancel():
            raise Cancelled()
        if process.returncode != 0:
            tail = (directory / "engine.log").read_text(errors="replace")[-3000:]
            raise RuntimeError(f"FDS s’est arrêté (code {process.returncode}). {tail}")
        if progress:
            progress(0.97, "Lecture des mesures et contrôle du résultat.")
        result = parse_result(directory)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("incident"):
            result["provenance"]["incident"] = manifest["incident"]
        result.setdefault("provenance", {}).update({
            "wall_time_s": round(time.monotonic() - started, 3),
            "threads": self.settings.omp_threads,
            "origin": "simulation",
            "ignition_kind": config.get("ignition_kind", "thermal"),
            "electrical_model": "I²R as imposed thermal power; no arc/plasma model"
                if config.get("ignition_kind") == "resistive" else None,
        })
        write_json(directory / "result.json", result)
        return result


class Worker:
    def __init__(self, settings: Settings, store: RunStore, catalog: dict, models, incidents=None):
        self.settings, self.store, self.catalog, self.models = settings, store, catalog, models
        self.runner = FDSRunner(settings)
        self.incidents = incidents
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.loop, name="ignis-worker", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.thread.join()

    def loop(self):
        while not self.stopping.is_set():
            try:
                run = self.store.claim_next()
            except Exception:
                logging.exception("Cannot claim the next IGNIS job; retrying")
                self.stopping.wait(2)
                continue
            if not run:
                self.stopping.wait(0.5)
                continue
            identifier = run["id"]
            directory = self.settings.runtime / "runs" / identifier
            try:
                directory.mkdir(parents=True, exist_ok=True)
                config = RunConfig.model_validate(run["config"])
                scene = next(s for s in self.catalog["scenes"] if s["id"] == config.scene_id)
                if config.incident_type:
                    if self.incidents is None:
                        raise ValueError("Le service des incidents n'est pas disponible.")
                    scene = self.incidents.scene(config)
                def cancel():
                    return self.stopping.is_set() or self.store.get(identifier)["cancel_requested"]

                def progress(p, msg):
                    self.store.update(identifier, progress=p, message=msg)
                write_json(directory / "config.json", config.physical_config())
                write_json(directory / "scene.json", scene)
                if cancel():
                    raise Cancelled()
                if config.mode == "physics":
                    result = self.runner.run(scene, config.physical_config(), directory,
                                             progress=progress, cancel=cancel)
                else:
                    progress(0.25, "Prédiction avec les poids chargés.")
                    result = (self.incidents.predict(config) if config.incident_type
                              else self.models.predict(scene, config))
                    if cancel():
                        raise Cancelled()
                    write_json(directory / "result.json", result)
                if config.incident_type:
                    self.incidents.complete(scene, config.physical_config(), result)
                    if config.mode == "physics":
                        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                        result["provenance"]["incident"] = manifest.get("incident")
                    write_json(directory / "result.json", result)
                self.store.update(identifier, status="completed", progress=1,
                                  result_path=str(directory / "result.json"), message="Résultat disponible.")
            except Cancelled:
                self.store.update(identifier, status="cancelled", message="Calcul annulé ; fichiers conservés.")
            except Exception as exc:
                logging.exception("IGNIS job %s failed", identifier)
                try:
                    (directory / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                except OSError:
                    pass
                try:
                    self.store.update(identifier, status="failed", message=str(exc)[:3000])
                except Exception:
                    logging.exception("Cannot persist job failure; recovery will mark it interrupted")
