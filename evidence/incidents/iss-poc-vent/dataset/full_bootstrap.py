"""Run a bounded new campaign then its audit; preserve exit and timing evidence."""
import json
import os
import runpy
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

root = Path("E:/IGNIS-Valley-dev")
base = root / "runtime/iss-poc-vent"
os.chdir(root / "app")
sys.path[:0] = [str(root / "app/backend"), str(root / "app/tools/remote")]
log = (base / "full.log").open("x", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = log
os.dup2(log.fileno(), 1)
os.dup2(log.fileno(), 2)
started = time.monotonic()
began = datetime.now(timezone.utc).isoformat()
(base / "launch.json").write_text(json.dumps({"pid": os.getpid(), "started_utc": began,
    "generation_budget_s": 1140, "generation_and_audit_budget_s": 1200,
    "workers": 4, "threads_per_solver": 1, "gpu_training": False}), encoding="utf-8")
code = 0
try:
    import generate_iss_poc_vent as campaign
    campaign.main(["--home", str(root), "--budget-s", "1140", "--workers", "4"])
    (base / "generation-exit.json").write_text(json.dumps({"utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": time.monotonic() - started}), encoding="utf-8")
    runpy.run_path(str(base / "verify_remote.py"), run_name="__main__")
except BaseException:
    code = 1
    traceback.print_exc()
finally:
    (base / "full-exit.json").write_text(json.dumps({"pid": os.getpid(), "exit_code": code,
        "started_utc": began, "exited_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_generation_and_audit_s": time.monotonic() - started}), encoding="utf-8")
sys.exit(code)
