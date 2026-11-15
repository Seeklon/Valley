"""Detached Windows fit wrapper; outputs remain isolated under the ISS runtime."""

import json
import os
import runpy
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

APP = Path("E:/IGNIS-Valley-dev/app")
OUTPUT = Path("E:/IGNIS-Valley-dev/runtime/iss-poc/20261115")
os.chdir(APP)
sys.path[0:0] = [str(APP / "backend"), str(APP / "tools/remote")]
sys.stdout = (OUTPUT / "fit1-retry.stdout.log").open("x", encoding="utf-8", buffering=1)
sys.stderr = (OUTPUT / "fit1-retry.stderr.log").open("x", encoding="utf-8", buffering=1)
os.dup2(sys.stdout.fileno(), 1)
os.dup2(sys.stderr.fileno(), 2)
sys.argv = [
    "train_iss_poc.py",
    "--dataset", "E:/IGNIS-Valley-dev/datasets/iss-poc-20261115-v1",
    "--output", str(OUTPUT / "fit1-retry"),
    "--runtime", "E:/IGNIS-Valley-dev/runtime",
    "--seconds", "1180",
    "--steps", "20000",
    "--width", "16",
    "--batch-size", "128",
    "--validate-every", "500",
    "--benchmark-batches",
]
started = datetime.now(timezone.utc).isoformat()
print(json.dumps({"stage": "wrapper_started", "pid": os.getpid(), "utc": started, "argv": sys.argv}), flush=True)
status = 0
try:
    runpy.run_path(str(APP / "tools/remote/train_iss_poc.py"), run_name="__main__")
except BaseException:
    status = 1
    traceback.print_exc()
finally:
    (OUTPUT / "fit1-retry-exited.json").write_text(json.dumps({
        "pid": os.getpid(), "started_utc": started,
        "exited_utc": datetime.now(timezone.utc).isoformat(), "exit_code": status,
    }), encoding="utf-8")
sys.exit(status)
