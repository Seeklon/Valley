"""Bounded, resumable Windows FDS pilot for geometry-conditioned incident prediction."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ignis.config import Settings
from ignis.engine import FDSRunner, write_json
from ignis.incidents import INCIDENTS, incident_scene
from ignis.locking import ProcessLock
from ignis.provenance import canonical_sha
from ignis.schema import RunConfig


def layouts(catalog):
    by_id = {s["id"]: s for s in catalog["scenes"]}
    for scene_id in ["soyuz", "habitat", "cargo", "crossflow"]:
        for variant in range(3):
            scene = incident_scene(by_id[scene_id])
            if variant:
                displacement = .2 if variant == 1 else -.2
                for obj in scene["objects"]:
                    if obj["id"] in {"experiment_base", "fuel_sample"} and scene_id != "soyuz":
                        obj["center_m"][0] += displacement
                    if obj["id"].startswith("soyuz_seat_"):
                        obj["center_m"][1] += displacement
                    if obj["id"].startswith("cargo_crate_"):
                        obj["center_m"][1] += displacement
                    if obj.get("combustible_material_id"):
                        obj["combustible_material_id"] = "cellulose" if variant == 1 else "pmma"
                        obj["thermal_thickness_m"] = .004 if variant == 1 else .001
            split = "test" if scene_id == "crossflow" else "validation" if variant == 2 else "train"
            yield f"{scene_id}-layout-{variant}", scene, split


def design(catalog):
    for layout_index, (layout_id, scene, split) in enumerate(layouts(catalog)):
        for family_index, family in enumerate(INCIDENTS):
            component = scene["components"][(family_index + layout_index) % len(scene["components"])]
            config = RunConfig(scene_id=scene["id"], source_model="coupled_combustion",
                incident_type=family["id"], component_id=component["id"],
                gravity_g=1.0 if (layout_index + family_index) % 2 else .0001,
                airflow_m_s=[.05, .2, .4][(layout_index + family_index) % 3],
                oxygen_percent=[18, 21, 24][(layout_index + family_index * 2) % 3],
                ignition_power_w=[500, 1000, 1500, 2000, 3000][(layout_index + family_index) % 5],
                ignition_duration_s=1 if family["id"] == "arc" else 10,
                duration_s=30, seed=42100 + layout_index * 5 + family_index).physical_config()
            yield {"id": f"{layout_id}-{family['id']}", "layout_id": layout_id,
                   "scene_id": scene["id"], "split": split, "config": config}, copy.deepcopy(scene)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    parser.add_argument("--fds", type=Path,
                        default=Path("E:/IGNIS-Valley/tools/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe"))
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("The incident pilot must run on the Windows compute workstation")
    settings = Settings(root=args.home/"app", runtime=args.home/"runtime", fds_executable=args.fds)
    dataset = args.home/"datasets/incidents-v1"
    dataset.mkdir(parents=True, exist_ok=True)
    (settings.runtime).mkdir(parents=True, exist_ok=True)
    catalog = json.loads(settings.catalog_path.read_text(encoding="utf-8"))
    path = dataset/"manifest.json"
    with ProcessLock(dataset/"generation.lock"):
        manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "dataset_id": "incidents-v1", "schema_version": 1, "compiler_version": "ignis-incidents-1",
            "created_at": datetime.now(timezone.utc).isoformat(), "origin": "FDS simulations",
            "nasa_experimental_labels": False, "expected_runs": 60,
            "partition": "Entire layouts; all crossflow layouts reserved for test; variant2 of other scenes for validation",
            "runs": []}
        previous = {r["id"]: r for r in manifest["runs"]}
        runner = FDSRunner(settings)
        for index, (record, scene) in enumerate(design(catalog)):
            if index >= args.limit or (dataset/"STOP").exists():
                break
            record["scene_sha256"] = canonical_sha(scene)
            record["fingerprint"] = canonical_sha({"scene": scene, "config": record["config"],
                                                   "compiler": manifest["compiler_version"]})
            record["relative_path"] = "runs/" + record["id"]
            directory = dataset/record["relative_path"]
            if old := previous.get(record["id"]):
                if old["fingerprint"] != record["fingerprint"] or old["status"] != "completed":
                    raise RuntimeError("Existing inputs differ or run incomplete; preserve and inspect " + record["id"])
                if hashlib.sha256((directory/"result.json").read_bytes()).hexdigest() != old["result_sha256"]:
                    raise RuntimeError("Result integrity mismatch: " + record["id"])
                continue
            directory.mkdir(parents=True)
            write_json(directory/"scene.json", scene)
            write_json(directory/"config.json", record["config"])
            record["status"] = "running"
            manifest["runs"].append(record)
            write_json(path, manifest)
            try:
                result = runner.run(scene, record["config"], directory,
                                    cancel=lambda: (dataset/"STOP").exists())
                if result["summary"]["nonfinite_spatial_measurements"]:
                    raise RuntimeError("Nonfinite gas samples must be reviewed before training")
                record.update(status="completed", wall_time_s=result["provenance"]["wall_time_s"],
                              result_sha256=hashlib.sha256((directory/"result.json").read_bytes()).hexdigest())
            except Exception as exc:
                record.update(status="failed", error=str(exc))
                write_json(path, manifest)
                raise
            manifest["completed_runs"] = sum(r["status"] == "completed" for r in manifest["runs"])
            write_json(path, manifest)
            print(json.dumps({"id": record["id"], "completed": manifest["completed_runs"],
                              "seconds": record["wall_time_s"], "peak_c": result["summary"]["temperature_peak_c"]}), flush=True)
        print("INCIDENT_PILOT_COMPLETE", manifest.get("completed_runs", 0), flush=True)


if __name__ == "__main__":
    main()
