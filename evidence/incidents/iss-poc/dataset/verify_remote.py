"""Read-only final integrity check; no summary or fitting of test labels."""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path[:0] = ["E:/IGNIS-Valley-dev/app/backend", "E:/IGNIS-Valley-dev/app/tools/remote"]
from generate_iss_poc import label_profile  # noqa: E402 — standalone Windows verification bootstrap
from generate_spatial_corpus import (  # noqa: E402 — standalone Windows verification bootstrap
    now,
    verify_completed,
)
from ignis.ml.spatial_dataset import (  # noqa: E402 — standalone Windows verification bootstrap
    file_sha,
    read_spatial_index,
)
from ignis.provenance import canonical_sha  # noqa: E402 — standalone Windows verification bootstrap

root = Path("E:/IGNIS-Valley-dev/datasets/iss-poc-20261115-v1")
plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
index = read_spatial_index(root)
progress = json.loads((root / "progress.json").read_text(encoding="utf-8"))
assert progress["state"] == "completed" and progress["ready_for_training"]
assert index["frozen_index_sha256"] == file_sha(root / "index.json")
assert index["plan_sha256"] == file_sha(root / "plan.json")
assert plan["design_sha256"] == canonical_sha(
    {k: v for k, v in plan.items() if k not in {"preflight", "design_sha256"}}
)
planned = {r["id"]: r for r in plan["runs"]}
assert len(index["runs"]) == index["expected_runs"] == len(planned) == 108
assert len(plan["preflight"]["layouts"]) == 18
assert len({v["geometry_sha256"] for v in plan["preflight"]["layouts"].values()}) == 18
activity = {}
controls = {}
for row in index["runs"]:
    assert row["status"] == "completed"
    verify_completed(root, row, planned[row["id"]])
    split = row["split"]
    if split == "test":
        assert "label_profile" not in row
        continue
    profile = label_profile(root / row["relative_path"])
    assert profile == row["label_profile"]
    aggregate = activity.setdefault(
        split,
        dict(
            heat_observed=0, heat_positive=0, smoke_observed=0, smoke_positive=0, hot_cases=0, smoky_cases=0
        ),
    )
    for key in ("heat_observed", "heat_positive", "smoke_observed", "smoke_positive"):
        aggregate[key] += profile[key]
    aggregate["hot_cases"] += int(profile["heat_positive"] > 0)
    aggregate["smoky_cases"] += int(profile["smoke_positive"] > 0)
    if row["config"]["ignition_power_w"] == 0:
        controls[row["id"]] = {k: profile[k] for k in ("heat_positive", "smoke_positive")}
report = {
    "verified_at": now(),
    "dataset_id": index["dataset_id"],
    "status": "passed",
    "complete_cases": len(index["runs"]),
    "layouts": 18,
    "split_counts": dict(Counter(r["split"] for r in index["runs"])),
    "gravity_counts": dict(Counter(r["config"]["gravity_g"] for r in index["runs"])),
    "planned_zero_power_controls": sum(r["config"]["ignition_power_w"] == 0 for r in index["runs"]),
    "train_validation_activity": activity,
    "train_validation_zero_power_controls": controls,
    "test_label_summary": None,
    "checks": [
        "immutable plan and frozen index hashes",
        "all seven artifact hashes of every case",
        "FDS provenance, coordinates, timestamps and masked observations",
        "18 unique physical geometry hashes",
        "train/validation profile recomputation with float64 thresholds",
        "test label summaries remain absent",
    ],
    "manifest_sha256": file_sha(root / "manifest.json"),
    "plan_sha256": file_sha(root / "plan.json"),
    "frozen_index_sha256": file_sha(root / "index.json"),
    "stored_bytes": sum(r["stored_bytes"] for r in index["runs"]),
    "campaign_wall_time_s": progress["elapsed_s"],
    "sum_case_solver_parse_seconds": sum(r["wall_time_s"] for r in index["runs"]),
}
(root / "verification.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(report, ensure_ascii=False))
