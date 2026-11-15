"""Read-only final integrity check; no summary or fitting of test labels."""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path[:0] = ["E:/IGNIS-Valley-dev/app/backend", "E:/IGNIS-Valley-dev/app/tools/remote"]
from generate_iss_poc_v2 import label_profile  # noqa: E402 — standalone Windows verification bootstrap
from generate_spatial_corpus import (  # noqa: E402 — standalone Windows verification bootstrap
    now,
    verify_completed,
)
from ignis.ml.spatial_dataset import (  # noqa: E402 — standalone Windows verification bootstrap
    file_sha,
    read_spatial_index,
)
from ignis.provenance import canonical_sha  # noqa: E402 — standalone Windows verification bootstrap
from iss_poc_v2_design import normalized_geometry  # noqa: E402

root = Path("E:/IGNIS-Valley-dev/datasets/iss-poc-20261115-v2")
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
assert len(index["runs"]) == index["expected_runs"] == len(planned) == 384
assert len(plan["preflight"]["layouts"]) == 48
assert len({v["geometry_sha256"] for v in plan["preflight"]["layouts"].values()}) == 48
old_root = root.with_name("iss-poc-20261115-v1")
old_hashes = {
    "manifest.json": "b119a200985e936ec3d0ff36d878850165bb345c42df5d6be97da653954592fb",
    "plan.json": "12d0b5b88d206627c38217d5f6cf985b989bc3c7b111d91ce793b1ca04c94139",
    "index.json": "f4648d1466804a180065e35375edb79027115877ea46371fbea682823b96a670",
}
assert all(file_sha(old_root / name) == digest for name, digest in old_hashes.items())
old_plan = json.loads((old_root / "plan.json").read_text(encoding="utf-8"))
old_physical = {v["geometry_sha256"] for v in old_plan["preflight"]["layouts"].values()}
new_physical = {v["geometry_sha256"] for v in plan["preflight"]["layouts"].values()}
assert not new_physical & old_physical
old_normalized = {normalized_geometry(lay["scene"]) for lay in old_plan["layouts"]}
new_normalized = {normalized_geometry(lay["scene"]) for lay in plan["layouts"]}
assert len(new_normalized) == 48 and not new_normalized & old_normalized
assert Counter(r["split"] for r in index["runs"]) == {"train": 240, "validation": 48, "test": 96}
assert {r["id"] for r in index["runs"]} == set(planned)
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
assert len(controls) == 36 and all(not any(values.values()) for values in controls.values())
report = {
    "verified_at": now(),
    "dataset_id": index["dataset_id"],
    "status": "passed",
    "complete_cases": len(index["runs"]),
    "layouts": 48,
    "split_counts": dict(Counter(r["split"] for r in index["runs"])),
    "gravity_counts": dict(Counter(r["config"]["gravity_g"] for r in index["runs"])),
    "planned_zero_power_controls": sum(r["config"]["ignition_power_w"] == 0 for r in index["runs"]),
    "train_validation_activity": activity,
    "train_validation_zero_power_controls": controls,
    "test_label_summary": None,
    "v1_physical_geometry_overlap": 0,
    "v1_normalized_geometry_overlap": 0,
    "preserved_v1_hashes": old_hashes,
    "normalized_layouts": len(new_normalized),
    "checks": [
        "immutable plan and frozen index hashes",
        "all seven artifact hashes of every case",
        "FDS provenance, coordinates, timestamps and masked observations",
        "48 unique physical and normalized geometry hashes; no v1 overlap",
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
