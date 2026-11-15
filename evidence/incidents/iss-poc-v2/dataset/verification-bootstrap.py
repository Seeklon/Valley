import json,os,runpy,sys,time,traceback
from pathlib import Path
from datetime import datetime,timezone
base=Path("E:/IGNIS-Valley-dev/runtime/iss-poc-v2")
log=open(base/"verification.log","x",encoding="utf-8",buffering=1)
sys.stdout=sys.stderr=log
os.dup2(log.fileno(),1);os.dup2(log.fileno(),2)
code=0
try:
 deadline=time.monotonic()+1900
 while not (base/"full-exit.json").is_file():
  if time.monotonic()>deadline: raise TimeoutError("Campaign did not exit before verification deadline")
  time.sleep(5)
 result=json.loads((base/"full-exit.json").read_text())
 if result["exit_code"]!=0: raise RuntimeError("Campaign failed; preserve all outputs")
 runpy.run_path(str(base/"verify_remote.py"),run_name="__main__")
except BaseException:
 code=1;traceback.print_exc()
finally:
 (base/"verification-exit.json").write_text(json.dumps({"pid":os.getpid(),"exit_code":code,"utc":datetime.now(timezone.utc).isoformat()}),encoding="utf-8")
sys.exit(code)
