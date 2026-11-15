"""Integrity and pairing audit; test labels remain unopened for selection."""
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("E:/IGNIS-Valley-dev")
sys.path[:0] = [str(ROOT / "app/backend"), str(ROOT / "app/tools/remote")]
from generate_iss_poc_vent import label_profile
from generate_spatial_corpus import verify_completed
from ignis.ml.spatial_dataset import file_sha, read_spatial_index
from ignis.provenance import canonical_sha
from iss_poc_vent_design import normalized_geometry, scene_for_run

dataset = ROOT / "datasets/iss-poc-20261115-vent"
plan = json.loads((dataset / "plan.json").read_bytes())
index = read_spatial_index(dataset)
progress = json.loads((dataset / "progress.json").read_bytes())
assert progress["state"] == "completed" and progress["ready_for_training"]
assert len(index["runs"]) == index["expected_runs"] == plan["expected_runs"] == 216
assert file_sha(dataset / "index.json") == index["frozen_index_sha256"]
assert file_sha(dataset / "plan.json") == index["plan_sha256"]
assert plan["design_sha256"] == canonical_sha({k: v for k, v in plan.items() if k not in {"preflight", "design_sha256"}})
preserved = {}
new = {normalized_geometry(lay["scene"]) for lay in plan["layouts"]}
assert len(new) == 24
old_hashes = {
    "iss-poc-20261115-v1": {
        "manifest.json": "b119a200985e936ec3d0ff36d878850165bb345c42df5d6be97da653954592fb",
        "plan.json": "12d0b5b88d206627c38217d5f6cf985b989bc3c7b111d91ce793b1ca04c94139",
        "index.json": "f4648d1466804a180065e35375edb79027115877ea46371fbea682823b96a670",
    },
    "iss-poc-20261115-v2": {
        "manifest.json": "6004eb0f27862106230e6f043fd5963b4da3ce28414b0559b94ca35724757a6f",
        "plan.json": "97f77e5111e53f79b2a1392587de2075438ea3ba2e86a6b0b4ef4b09fa3254bd",
        "index.json": "a2444f2141f858103dd9497726abc0c4540931775871e3b3a48f79f027a27644",
    },
}
for name, expected in old_hashes.items():
    folder = ROOT / "datasets" / name
    preserved[name] = {n: file_sha(folder / n) for n in expected}
    assert preserved[name] == expected
    old_plan = json.loads((folder / "plan.json").read_bytes())
    assert not new & {normalized_geometry(lay["scene"]) for lay in old_plan["layouts"]}
planned = {r["id"]: r for r in plan["runs"]}
scenes = {lay["layout_id"]: lay["scene"] for lay in plan["layouts"]}
assert set(planned) == {r["id"] for r in index["runs"]}
assert Counter(r["split"] for r in index["runs"]) == {"train": 108, "validation": 54, "test": 54}
groups = defaultdict(list)
activity, controls = {}, {}
for row in index["runs"]:
    assert row["status"] == "completed"
    verify_completed(dataset, row, planned[row["id"]])
    folder = dataset / row["relative_path"]
    scene = json.loads((folder / "scene.json").read_bytes())
    assert canonical_sha(scene) == row["scene_sha256"]
    assert scene == scene_for_run(scenes[row["layout_id"]], row)
    if row["ventilation_group_id"]:
        groups[row["ventilation_group_id"]].append(row)
    split = row["split"]
    if split == "test":
        assert "label_profile" not in row
        continue
    profile = label_profile(folder)
    assert profile == row["label_profile"]
    aggregate = activity.setdefault(split, dict(heat_observed=0, heat_positive=0,
                                               smoke_observed=0, smoke_positive=0,
                                               hot_cases=0, smoky_cases=0))
    for key in ("heat_observed", "heat_positive", "smoke_observed", "smoke_positive"):
        aggregate[key] += profile[key]
    aggregate["hot_cases"] += int(profile["heat_positive"] > 0)
    aggregate["smoky_cases"] += int(profile["smoke_positive"] > 0)
    if row["config"]["ignition_power_w"] == 0:
        controls[row["id"]] = {k: profile[k] for k in ("heat_positive", "smoke_positive")}
assert len(controls) == 18 and all(not any(values.values()) for values in controls.values())
assert len(groups) == 48
for members in groups.values():
    assert {r["ventilation_state"] for r in members} == {"still", "slow", "fast", "reverse"}
    configs = [{k: v for k, v in r["config"].items() if k != "airflow_m_s"} for r in members]
    assert all(c == configs[0] for c in configs)
    manifests = [json.loads((dataset / r["relative_path"] / "manifest.json").read_bytes()) for r in members]
    for manifest in manifests[1:]:
        assert all(manifest[k] == manifests[0][k] for k in ("sampling", "objects", "source"))
    assert len({r["split"] for r in members}) == 1
report = {
    "verified_at": datetime.now(timezone.utc).isoformat(), "status": "passed",
    "dataset_id": index["dataset_id"], "complete_cases": len(index["runs"]), "layouts": 24,
    "paired_quartets": 48, "split_counts": dict(Counter(r["split"] for r in index["runs"])),
    "gravity_counts": dict(Counter(r["config"]["gravity_g"] for r in index["runs"])),
    "train_validation_activity": activity, "train_validation_zero_power_controls": controls,
    "test_label_summary": None, "v1_v2_normalized_geometry_overlap": 0,
    "preserved_previous_dataset_hashes": preserved,
    "manifest_sha256": file_sha(dataset / "manifest.json"), "plan_sha256": file_sha(dataset / "plan.json"),
    "frozen_index_sha256": file_sha(dataset / "index.json"),
    "stored_bytes": sum(r["stored_bytes"] for r in index["runs"]),
    "campaign_wall_time_s": progress["elapsed_s"],
    "sum_case_solver_parse_seconds": sum(r["wall_time_s"] for r in index["runs"]),
    "checks": ["all seven artifact hashes of every case", "real effective reversed scenes",
               "quartet source, solids, sampling and non-airflow conditions held fixed",
               "24 normalized new layouts, no v1/v2 overlap", "train/validation controls zero",
               "test label summary remains absent"],
}
(dataset / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report))
