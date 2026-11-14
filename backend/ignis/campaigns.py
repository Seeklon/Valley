from __future__ import annotations

import json
import random
import threading
import uuid
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .schema import RunConfig


class CampaignConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    count: int = Field(default=12, ge=2, le=100)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    scene_ids: list[str] = Field(min_length=1, max_length=12)
    base_config: RunConfig
    ranges: dict[str, tuple[float, float]] = Field(default_factory=dict)


class Campaigns:
    def __init__(self, directory: Path, store, scenes: list[dict], max_runs=2000):
        self.directory, self.store = directory, store
        self.directory.mkdir(parents=True, exist_ok=True)
        self.scene_ids = {s["id"] for s in scenes}
        self.max_runs = max_runs
        self.lock = threading.Lock()

    def create(self, spec: CampaignConfig) -> dict:
        if spec.base_config.mode != "physics":
            raise ValueError("Les campagnes de référence utilisent le moteur physique.")
        if not set(spec.scene_ids) <= self.scene_ids:
            raise ValueError("Une scène de la campagne est inconnue.")
        permitted = {"airflow_m_s", "oxygen_percent", "ignition_power_w", "gravity_g"}
        if not set(spec.ranges) <= permitted:
            raise ValueError("La campagne contient une variable non prise en charge.")
        if spec.base_config.ignition_kind == "resistive" and "ignition_power_w" in spec.ranges:
            raise ValueError("En résistif, I²R fixe la puissance ; ne pas varier une HRR indépendante.")
        rng = random.Random(spec.seed)
        samples = {}
        for key, (lower, upper) in spec.ranges.items():
            if lower > upper:
                raise ValueError(f"Plage inversée : {key}")
            values = [lower + (upper - lower) * (i + rng.random()) / spec.count for i in range(spec.count)]
            rng.shuffle(values)
            samples[key] = values
        configs = []
        for i in range(spec.count):
            data = spec.base_config.model_dump(mode="json")
            data.update(scene_id=spec.scene_ids[i % len(spec.scene_ids)], seed=(spec.seed + i) % (2**31))
            data.update({key: values[i] for key, values in samples.items()})
            configs.append(RunConfig.model_validate(data).model_dump(mode="json"))
        with self.lock:
            if any(r["status"] in {"queued", "running"} for r in self.store.list(200)):
                raise ValueError("Attendre la fin des calculs en cours avant une nouvelle campagne.")
            identifier = uuid.uuid4().hex
            run_ids = [uuid.uuid4().hex for _ in configs]
            record = {"id": identifier, "spec": spec.model_dump(mode="json"), "run_ids": run_ids,
                      "sampling": "stratified Latin hypercube, deterministic seed", "cancel_requested": False}
            # One transaction makes the campaign visible with all its members.
            import time
            with self.store.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]:
                    raise ValueError("Attendre la fin des calculs en cours avant une nouvelle campagne.")
                if conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] + len(configs) > self.max_runs:
                    raise ValueError(f"Quota de {self.max_runs} calculs atteint ; archiver le runtime.")
                for run_id, config in zip(run_ids, configs):
                    now = time.time()
                    conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                                 (run_id, now, now, "queued", 0, "Campagne en attente.", json.dumps(config), None, 0))
                conn.execute("INSERT INTO campaigns VALUES (?,?)", (identifier, json.dumps(record)))
            return self.get(identifier)

    def get(self, identifier: str) -> dict | None:
        if len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
            return None
        with self.store.connection() as conn:
            row = conn.execute("SELECT data FROM campaigns WHERE id=?", (identifier,)).fetchone()
        if row:
            record = json.loads(row["data"])
        else:
            path = self.directory / f"{identifier}.json"
            if not path.exists():
                return None
            record = json.loads(path.read_text(encoding="utf-8"))
        runs = [self.store.get(run_id) for run_id in record["run_ids"]]
        completed = sum(r is not None and r["status"] == "completed" for r in runs)
        failed = sum(r is None or r["status"] == "failed" for r in runs)
        cancelled = sum(r is not None and r["status"] == "cancelled" for r in runs)
        finished = completed + failed + cancelled
        if finished < len(runs):
            status = "running" if any(r and r["status"] in {"running", "completed"} for r in runs) else "queued"
        else:
            status = "cancelled" if cancelled else "failed" if failed else "completed"
        return {**record, "status": status, "completed_runs": completed, "failed_runs": failed,
                "cancelled_runs": cancelled, "total_runs": len(runs), "progress": finished / len(runs),
                "message": f"{completed}/{len(runs)} calculs valides · {failed} échecs · {cancelled} annulations"}

    def cancel(self, identifier: str):
        record = self.get(identifier)
        if record is None:
            return None
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for run_id in record["run_ids"]:
                conn.execute("""UPDATE runs SET cancel_requested=1,
                    status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END
                    WHERE id=? AND status IN ('queued','running')""", (run_id,))
            row = conn.execute("SELECT data FROM campaigns WHERE id=?", (identifier,)).fetchone()
            if row:
                saved = json.loads(row["data"])
                saved["cancel_requested"] = True
                conn.execute("UPDATE campaigns SET data=? WHERE id=?", (json.dumps(saved), identifier))
        return self.get(identifier)
