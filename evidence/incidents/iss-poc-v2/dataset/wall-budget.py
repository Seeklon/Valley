import json,time
from pathlib import Path
from datetime import datetime,timezone
base=Path("E:/IGNIS-Valley-dev/runtime/iss-poc-v2")
dataset=Path("E:/IGNIS-Valley-dev/datasets/iss-poc-20261115-v2")
deadline=datetime.fromisoformat('2026-11-15T14:10:19.064072+00:00')
state="campaign_exited"
while not (base/"full-exit.json").is_file():
 if datetime.now(timezone.utc)>=deadline:
  state="wall_budget_stop_requested"
  try:
   with (dataset/"STOP").open("x",encoding="utf-8") as stream: stream.write("30-minute wall budget reached; preserve all outputs\n")
  except FileExistsError: pass
  break
 time.sleep(2)
(base/"wall-budget-exit.json").write_text(json.dumps({"state":state,"deadline_utc":deadline.isoformat(),"exited_utc":datetime.now(timezone.utc).isoformat()}),encoding="utf-8")
