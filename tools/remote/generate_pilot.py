"""Windows-only, resumable FDS campaign with family-level holdouts and bounded storage."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from ignis.config import Settings
from ignis.engine import FDSRunner, write_json
from ignis.locking import ProcessLock
from ignis.schema import RunConfig


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def designs():
    rng = random.Random(20261114)
    params = {}
    for key, lower, upper in [("airflow_m_s", 0.05, 0.4), ("oxygen_percent", 18, 24),
                             ("ignition_power_w", 500, 3000), ("ignition_duration_s", 8, 25)]:
        values = [lower + (upper-lower)*(i+rng.random())/12 for i in range(12)]
        rng.shuffle(values)
        params[key] = values
    # Include ordinary UI defaults explicitly; the remaining runs span the domain.
    for key, value in {"airflow_m_s": 0.2, "oxygen_percent": 21, "ignition_power_w": 500,
                       "ignition_duration_s": 15}.items():
        params[key][1] = value
    return [{key: values[i] for key, values in params.items()} for i in range(12)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", action="append", help="Append or resume only these scene IDs")
    args = parser.parse_args()
    root = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    settings = Settings(root=root / "app", runtime=root / "runtime",
                        fds_executable=root / "tools/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe")
    dataset = root / "datasets/pilot-v2"
    dataset.mkdir(parents=True, exist_ok=True)
    runner = FDSRunner(settings)
    catalog = json.loads(settings.catalog_path.read_text(encoding="utf-8"))
    selected = [scene for scene in catalog["scenes"] if not args.scene or scene["id"] in args.scene]
    if args.scene and set(args.scene) != {scene["id"] for scene in selected}:
        raise ValueError("Unknown requested scene")
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "schema_version": 1, "dataset_id": "pilot-v2", "created_at": datetime.now(timezone.utc).isoformat(),
        "engine": "FDS", "engine_version": "6.11.1", "compiler_version": "ignis-fds-2",
        "material_model_version": "ignis-fds-materials-2", "origin": "simulation",
        "nasa_experimental_labels": False, "mesh_cell_m": 0.2,
        "design": "12 stratified parameter families × 2 gravity regimes × each scene",
        "partition": {"geometry_holdout": ["crossflow"], "test_family_indices": [10, 11],
                      "validation_family_indices": [0, 5], "unit": "entire run, never individual frames"},
        "runs": []}
    by_id = {r["id"]: r for r in manifest["runs"]}
    total = len(catalog["scenes"]) * 24
    started = time.monotonic()
    for scene in selected:
        for family, parameters in enumerate(designs()):
            for regime, gravity in [("microg", 0.0001), ("earth", 1.0)]:
                identifier = f"{scene['id']}-f{family:02d}-{regime}"
                cfg = RunConfig(scene_id=scene["id"], gravity_g=gravity, duration_s=60,
                                mesh_cell_m=0.2, material_id="pmma" if family % 2 else "cellulose",
                                seed=1729 + family*2 + (regime == "earth"), **parameters).physical_config()
                split = "test" if scene["id"] == "crossflow" or family >= 10 else "validation" if family in {0, 5} else "train"
                fingerprint = sha({"scene": scene, "config": cfg, "compiler": manifest["compiler_version"],
                                   "material_model": manifest["material_model_version"]})
                directory = dataset / "runs" / identifier
                directory.parent.mkdir(exist_ok=True)
                old = by_id.get(identifier)
                if old:
                    if old["fingerprint"] != fingerprint:
                        raise RuntimeError(f"Inputs changed for {identifier}; use a new dataset version")
                    if old["status"] == "completed" and (directory / "result.json").exists():
                        if hashlib.sha256((directory / "result.json").read_bytes()).hexdigest() != old["result_sha256"]:
                            raise RuntimeError("A saved result was altered: " + identifier)
                        continue
                    raise RuntimeError(f"Existing incomplete run {identifier} preserved; inspect before retry")
                if (dataset / "STOP").exists():
                    print("Campaign stopped cooperatively", flush=True)
                    return
                entry = {"id": identifier, "family_id": f"{scene['id']}-f{family:02d}",
                         "parameter_family": family, "scene_id": scene["id"], "split": split,
                         "geometry_holdout": scene["id"] == "crossflow", "status": "running",
                         "fingerprint": fingerprint, "config": cfg, "relative_path": f"runs/{identifier}"}
                manifest["runs"].append(entry)
                by_id[identifier] = entry
                write_json(manifest_path, manifest)
                directory.mkdir(exist_ok=True)
                write_json(directory / "config.json", cfg)
                write_json(directory / "scene.json", scene)
                try:
                    result = runner.run(scene, cfg, directory, cancel=lambda: (dataset / "STOP").exists())
                    if result["summary"]["nonfinite_spatial_measurements"]:
                        raise ValueError("Non-finite spatial observations")
                    if result["provenance"]["compiler_version"] != manifest["compiler_version"]:
                        raise ValueError("Compiler version differs from dataset")
                    entry.update(status="completed", summary=result["summary"],
                                 wall_time_s=result["provenance"]["wall_time_s"],
                                 result_sha256=hashlib.sha256((directory / "result.json").read_bytes()).hexdigest())
                except Exception as exc:
                    entry.update(status="failed", error=str(exc))
                    write_json(manifest_path, manifest)
                    raise
                manifest["completed_runs"] = sum(r["status"] == "completed" for r in manifest["runs"])
                manifest["expected_runs_current_catalog"] = total
                manifest["elapsed_s_this_session"] = round(time.monotonic() - started, 2)
                write_json(manifest_path, manifest)
                print(json.dumps({"id": identifier, "completed": manifest["completed_runs"], "total": total,
                                  "seconds": entry["wall_time_s"], "Tmax": result["summary"]["temperature_peak_c"]}), flush=True)
    print("PILOT_COMPLETE", manifest["completed_runs"], flush=True)


if __name__ == "__main__":
    project_root = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    with ProcessLock(project_root / "datasets/pilot-v2/generation.lock"):
        main()
