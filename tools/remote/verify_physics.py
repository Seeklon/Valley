"""Exercise actual FDS on Windows; persist each result immediately."""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

from ignis.config import Settings
from ignis.engine import FDSRunner, write_json
from ignis.physics.verification import verification_cases

root = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
settings = Settings(root=root / "app", runtime=root / "runtime",
                    fds_executable=root / "tools/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe")
runner = FDSRunner(settings)
stamp = str(int(time.time()))
directory = root / "runtime" / ("verification-" + stamp)
directory.mkdir(parents=True)
cases = verification_cases()
catalog = json.loads((settings.root / "scenes/catalog.json").read_text(encoding="utf-8"))
for mesh in [0.4, 0.2]:
    cases[f"habitat-{mesh}"] = (catalog["scenes"][0], {"source_model": "prescribed_source", "gravity_g": 0.0001,
        "duration_s": 30, "ignition_power_w": 1500, "ignition_duration_s": 15,
        "airflow_m_s": 0.2, "mesh_cell_m": mesh, "sample_shape": [8, 10, 4]})
report = {"directory": str(directory), "cases": []}
for name, (scene, config) in cases.items():
    before = time.monotonic()
    print("Running", name, flush=True)
    try:
        result = runner.run(scene, config, directory / name)
        item = {"case": name, "status": "completed", "wall_time_s": time.monotonic() - before,
                "summary": result["summary"], "provenance": result["provenance"]}
    except Exception as exc:
        item = {"case": name, "status": "failed", "error": str(exc), "traceback": traceback.format_exc()}
    report["cases"].append(item)
    write_json(root / "runtime/verification-latest.json", report)
    print(json.dumps(item, ensure_ascii=False), flush=True)
