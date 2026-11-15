"""Read actual FDS boundary/velocity observations of the predeclared pilot only."""
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

root = Path("E:/IGNIS-Valley-dev")
sys.path[:0] = [str(root / "app/backend"), str(root / "app/tools/remote")]
from ignis.ml.spatial_dataset import file_sha, read_spatial_index
from iss_poc_vent_design import scheduled_runs

dataset = root / "datasets/iss-poc-20261115-vent"
plan = json.loads((dataset / "plan.json").read_bytes())
index = read_spatial_index(dataset)
records = {r["id"]: r for r in index["runs"]}
rows = []
for planned in scheduled_runs(plan, pilot=True):
    assert planned["split"] in {"train", "validation"}
    row = records[planned["id"]]
    assert row["status"] == "completed"
    folder = dataset / row["relative_path"]
    path = folder / "result.json.gz"
    assert file_sha(path) == row["file_hashes"]["result.json.gz"]
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        result = json.load(stream)
    manifest = json.loads((folder / "manifest.json").read_bytes())
    samples = [m for m in result["metrics"] if m["time_s"] >= 5]
    vents = {}
    for vent in manifest["vents"]:
        measured = np.asarray([m["vent_volume_flows_m3_s"][vent["id"]] for m in samples], dtype=float)
        assert np.isfinite(measured).all()
        vents[vent["id"]] = {"role": vent["role"], "prescribed_volume_flow_m3_s": vent["volume_flow_m3_s"],
                              "observed_normal_velocity_integral_mean_m3_s": float(measured.mean()),
                              "observed_min_m3_s": float(measured.min()),
                              "observed_max_m3_s": float(measured.max())}
    vectors = []
    for frame in result["frames"]:
        if frame["time_s"] < 20:
            continue
        values = np.asarray(frame["velocity_m_s"], dtype=float).reshape(-1, 3)
        mask = np.asarray(frame["valid_mask"], dtype=bool) & np.isfinite(values).all(axis=1)
        vectors.append(values[mask].mean(axis=0))
    rows.append({"id": row["id"], "split": row["split"], "state": row["ventilation_state"],
                 "axis": row["ventilation_axis"], "frames": len(result["frames"]),
                 "max_observation_gap_s": float(np.diff([f["time_s"] for f in result["frames"]]).max()),
                 "sampled_gas_mean_velocity_20_30_s": np.mean(vectors, axis=0).tolist(),
                 "vents": vents, "result_sha256": row["file_hashes"]["result.json.gz"]})
report = {"checked_at": datetime.now(timezone.utc).isoformat(), "cases": rows,
          "test_observations_read": False,
          "semantics": "Boundary statistics are FDS NORMAL VELOCITY surface integrals; velocity vectors are sampled gas means, not full-volume means"}
target = root / "runtime/iss-poc-vent/pilot-flow-observations.json"
with target.open("x", encoding="utf-8") as stream:
    json.dump(report, stream, indent=2)
print(json.dumps(report))
