import json,os,sys,traceback
from pathlib import Path
from datetime import datetime,timezone
root=Path("E:/IGNIS-Valley-dev")
os.chdir(root/"app")
sys.path[:0]=[str(root/"app/backend"),str(root/"app/tools/remote")]
log=open(root/"runtime/iss-poc-v2/pilot.log","x",encoding="utf-8",buffering=1)
sys.stdout=sys.stderr=log
os.dup2(log.fileno(),1);os.dup2(log.fileno(),2)
code=0
try:
 import generate_iss_poc_v2 as campaign
 campaign.main(["--home",str(root),"--pilot","--budget-s","240","--workers","4"])
except BaseException:
 code=1;traceback.print_exc()
finally:
 (root/"runtime/iss-poc-v2/pilot-exit.json").write_text(json.dumps({"pid":os.getpid(),"exit_code":code,"utc":datetime.now(timezone.utc).isoformat()}),encoding="utf-8")
sys.exit(code)
