"""Plumbing-only paired metric check: artificial scores derived from TRAIN labels."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

root = Path("E:/IGNIS-Valley-dev")
sys.path[:0] = [str(root / "app/backend"), str(root / "app/tools/remote")]
from evaluate_iss_ventilation import digest, paired_metrics
from ignis.ml.spatial_dataset import read_spatial_index

dataset = root / "datasets/iss-poc-20261115-vent"
index = read_spatial_index(dataset)
group = "iss-laboratory-vent-00-flaming"
members = [r for r in index["runs"] if r.get("ventilation_group_id") == group]
assert len(members) == 4 and all(r["split"] == "train" and r["status"] == "completed" for r in members)
cases, scores, timing, hashes = [], [], {}, {}
for row in members:
    folder = dataset / row["relative_path"]
    for name in ("fields.npz", "manifest.json"):
        assert digest(folder / name) == row["file_hashes"][name]
    manifest = json.loads((folder / "manifest.json").read_bytes())
    with np.load(folder / "fields.npz", allow_pickle=False) as arrays:
        case = {key: arrays[key].copy() for key in
                ("time_s", "positions_m", "field_mask", "temperature_c", "smoke_kg_m3")}
    case.update(record=row, manifest=manifest, config=manifest["config"])
    truth = np.stack([case["temperature_c"].astype(np.float64) >= case["config"]["ambient_temperature_c"] + 5,
                      case["smoke_kg_m3"].astype(np.float64) >= 1e-6], axis=-1)
    scores.append(truth * 0.8 + 0.1)
    cases.append(case)
    timing[row["id"]] = {"frames": len(case["time_s"]), "last_time_s": float(case["time_s"][-1]),
                         "maximum_gap_s": float(np.diff(case["time_s"]).max()),
                         "integer_timestamps_only": bool(np.equal(np.floor(case["time_s"]), case["time_s"]).all())}
    hashes[row["id"]] = {name: row["file_hashes"][name] for name in ("fields.npz", "manifest.json")}
result = paired_metrics(cases, scores, {"heat": 0.5, "smoke": 0.5})
result.update(checked_at=datetime.now(timezone.utc).isoformat(), split="train",
              score_origin="ARTIFICIAL plumbing check only: 0.8 * thresholded FDS TRAIN truth + 0.1",
              is_model_evaluation=False, no_training=True, gpu_used=False, test_observations_read=False,
              original_observation_timing=timing, source_hashes=hashes,
              helper_sha256=digest(root / "app/tools/remote/evaluate_iss_ventilation.py"))
target = root / "runtime/iss-poc-vent/paired-preflight.json"
with target.open("x", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2, allow_nan=False)
print(json.dumps({"helper_sha256": result["helper_sha256"], "group_count": result["group_count"],
                  "requested_time_s": result["requested_time_s"], "timing": timing,
                  "alignment": result["alignment"], "reference_change_count": {
                      name: row["reference_change_count"] for name, row in result["metrics"].items()},
                  "is_model_evaluation": False}))
