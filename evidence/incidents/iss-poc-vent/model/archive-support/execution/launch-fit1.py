"""Detached ventilation adaptation; no deployment."""
import hashlib, json, os, runpy, sys, traceback
from datetime import datetime, timezone
from pathlib import Path
APP=Path("E:/IGNIS-Valley-dev/app")
PARENT=Path("E:/IGNIS-Valley-dev/runtime/iss-poc-vent/20261115")
os.chdir(APP)
sys.path[0:0]=[str(APP/"backend"),str(APP/"tools/remote")]
sys.stdout=(PARENT/"fit1.stdout.log").open("x",encoding="utf-8",buffering=1)
sys.stderr=(PARENT/"fit1.stderr.log").open("x",encoding="utf-8",buffering=1)
os.dup2(sys.stdout.fileno(),1)
os.dup2(sys.stderr.fileno(),2)
sys.argv=["train_iss_poc_vent.py","--dataset","E:/IGNIS-Valley-dev/datasets/iss-poc-20261115-vent","--output",str(PARENT/"fit1"),"--runtime","E:/IGNIS-Valley-dev/runtime","--warm-start","E:/IGNIS-Valley-dev/runtime/iss-poc-v2/20261115/fit1/weights.pt","--previous-snapshot","E:/IGNIS-Valley-dev/runtime/iss-poc-v2/20261115/fit1/dataset-snapshot.json","--previous-dataset","E:/IGNIS-Valley-dev/datasets/iss-poc-20261115-v2","--seconds","600","--training-seconds","300","--steps","15000","--batch-size","128","--validate-every","1000"]
started=datetime.now(timezone.utc).isoformat()
print(json.dumps({"stage":"wrapper_started","pid":os.getpid(),"utc":started,"argv":sys.argv}),flush=True)
status=0
try:
 expected={'tools/remote/train_iss_poc_vent.py': 'ebdcf76451b9a0371dc92a9bef9beca57afe38e251a311a7dbf9f7cec38b6731', 'tools/remote/evaluate_iss_ventilation.py': 'a8b55f57e1b76c3c27285b8d149410ab9cd0c9fda2eac1e0fe00e41b89890b10', 'tests/test_iss_poc_vent.py': '03a70e3d9913dc0b2e157629adaecaa039fd400d15569f88bdc22d68136aa55b'}
 for name,digest in expected.items():
  if hashlib.sha256((APP/name).read_bytes()).hexdigest()!=digest: raise RuntimeError("Reviewed source changed: "+name)
 print(json.dumps({"stage":"reviewed_sources_verified","sources":expected}),flush=True)
 runpy.run_path(str(APP/"tools/remote/train_iss_poc_vent.py"),run_name="__main__")
except BaseException:
 status=1
 traceback.print_exc()
finally:
 (PARENT/"fit1-exited.json").write_text(json.dumps({"pid":os.getpid(),"started_utc":started,"exited_utc":datetime.now(timezone.utc).isoformat(),"exit_code":status}),encoding="utf-8")
sys.exit(status)
