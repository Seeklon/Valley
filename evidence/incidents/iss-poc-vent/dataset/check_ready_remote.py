"""Assert finished/audited inputs and probe the OS compute lock without training."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path("E:/IGNIS-Valley-dev")
sys.path.insert(0, str(root / "app/backend"))
from ignis.locking import ProcessLock

dataset = root / "datasets/iss-poc-20261115-vent"
base = root / "runtime/iss-poc-vent"
exit_record = json.loads((base / "full-exit.json").read_bytes())
audit = json.loads((dataset / "verification.json").read_bytes())
assert exit_record["exit_code"] == 0
assert audit["status"] == "passed" and audit["complete_cases"] == 216
assert exit_record["elapsed_generation_and_audit_s"] <= 1200
assert (root / "datasets/spatial-corpus-v1/PAUSE").is_file()
with ProcessLock(root / "runtime/compute.lock"):
    ready = {"checked_at": datetime.now(timezone.utc).isoformat(), "ready": True,
             "complete_cases": 216, "audit": "passed", "compute_lock_available": True,
             "no_training_launched": True, "manifest_sha256": audit["manifest_sha256"],
             "frozen_index_sha256": audit["frozen_index_sha256"]}
with (base / "ready-for-training.json").open("x", encoding="utf-8") as stream:
    json.dump(ready, stream, indent=2)
print(json.dumps(ready))
