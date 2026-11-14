from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class RunStore:
    """Durable lifecycle. A server restart never silently reruns an interrupted job."""

    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "jobs.sqlite3"
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL,
                status TEXT NOT NULL, progress REAL NOT NULL, message TEXT NOT NULL,
                config TEXT NOT NULL, result_path TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0
            )""")
            conn.execute("CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    def recover_interrupted(self):
        """Call only after acquiring the runtime's exclusive service lock."""
        with self.connection() as conn:
            conn.execute("UPDATE runs SET status='failed', message=?, updated=? WHERE status='running'",
                         ("Exécution interrompue par un redémarrage ; journaux conservés.", time.time()))

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create(self, identifier: str, config: dict, *, max_active=8, max_total=2000):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0] >= max_active:
                raise ValueError("La file contient déjà huit calculs ; attendre ou annuler un calcul.")
            if conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] >= max_total:
                raise ValueError("Quota de calculs atteint ; archiver le runtime avant de poursuivre.")
            now = time.time()
            conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                         (identifier, now, now, "queued", 0, "En attente du moteur.",
                          json.dumps(config), None, 0))

    def get(self, identifier: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (identifier,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["config"] = json.loads(data["config"])
        return data

    def list(self, limit: int = 50) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute("SELECT id FROM runs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [self.get(row["id"]) for row in rows]

    def claim_next(self) -> dict | None:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM runs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                conn.execute("UPDATE runs SET status='running',updated=?,message=? WHERE id=?",
                             (time.time(), "Initialisation du calcul.", row["id"]))
        return self.get(row["id"]) if row else None

    def update(self, identifier: str, **fields):
        allowed = {"status", "progress", "message", "result_path", "cancel_requested"}
        if not fields.keys() <= allowed:
            raise ValueError("Unsupported run field")
        fields["updated"] = time.time()
        sql = ",".join(f"{key}=?" for key in fields)
        with self.connection() as conn:
            conn.execute(f"UPDATE runs SET {sql} WHERE id=?", (*fields.values(), identifier))

    def cancel(self, identifier: str):
        with self.connection() as conn:
            conn.execute("""UPDATE runs SET cancel_requested=1,
                status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END, updated=?
                WHERE id=? AND status IN ('queued','running')""", (time.time(), identifier))
