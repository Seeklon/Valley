"""Generate fresh similar/OOD FDS cases and evaluate a frozen pilot checkpoint.

Four independent CPU solvers share a bounded pool; inference uses CUDA. The
existing corpus must be paused. No model fitting or automatic promotion occurs.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from generate_spatial_corpus import compiler_hashes, procedural_scene, write_new_json
from ignis.config import Settings
from ignis.engine import FDSRunner, write_json
from ignis.locking import ProcessLock
from ignis.ml.incidents import COMPILER_VERSION, INCIDENT_TYPES, file_sha
from ignis.ml.spatial_dataset import compress_completed_run, load_spatial_case
from ignis.ml.spatial_network import SpatialSurrogate
from ignis.physics import compile_case
from ignis.provenance import canonical_sha
from train_spatial import physical_signature, run_metrics, summarize
from verify_spatial import classification, compare_metrics, physical_metrics, plot_case, state_sha


def make_plan(home):
    dataset = home / "datasets/incidents-v1"
    index = json.loads((dataset / "manifest.json").read_text())
    geometries, signatures = [], set()
    for scene_id in ("soyuz", "habitat", "cargo"):
        record = next(r for r in index["runs"] if r["layout_id"] == scene_id + "-layout-0")
        folder = dataset / record["relative_path"]
        scene = json.loads((folder / "scene.json").read_text())
        config = json.loads((folder / "config.json").read_text())
        geometries.append(("similar", scene_id, scene, config["mesh_cell_m"]))
    for i, family in enumerate(("perimeter", "baffled", "double-island")):
        scene, cell = procedural_scene(1100 + i, family)
        geometries.append(("novel_geometry", family, scene, cell))
    runs = []
    for layout_number, (group, label, scene, cell) in enumerate(geometries):
        for incident_number, kind in enumerate(INCIDENT_TYPES):
            component = scene["components"][(incident_number + layout_number + 1) % len(scene["components"])]
            for gravity in (0.0001, 1.0):
                identifier = f"{group}-{label}-{kind}-{'microg' if gravity < 1 else 'earth'}"
                config = {
                    "scene_id": scene["id"],
                    "source_model": "coupled_combustion",
                    "ignition_kind": "thermal",
                    "incident_type": kind,
                    "component_id": component["id"],
                    "gravity_g": gravity,
                    "airflow_m_s": [0.08, 0.17, 0.29, 0.36, 0.12][(incident_number + layout_number) % 5],
                    "oxygen_percent": [19.5, 22.5, 23.5][layout_number % 3],
                    "ignition_power_w": [1700, 2300, 2900, 1200, 2600][incident_number],
                    "ignition_duration_s": 1 if kind == "arc" else 10,
                    "duration_s": 30,
                    "seed": 812000 + layout_number * 10 + incident_number,
                    "material_id": "cellulose",
                    "mesh_cell_m": cell,
                    "sample_shape": [8, 10, 4],
                    "sample_interval_s": 1,
                    "ambient_temperature_c": 20,
                    "pressure_pa": 101325,
                    "ignition_delay_s": 0,
                }
                fingerprint = canonical_sha({"scene": scene, "config": config, "compiler": COMPILER_VERSION})
                if fingerprint in signatures or any(
                    r.get("fingerprint") == fingerprint for r in index["runs"]
                ):
                    raise ValueError("Repeated evaluation case")
                signatures.add(fingerprint)
                runs.append(
                    {
                        "id": identifier,
                        "layout_id": label,
                        "group": group,
                        "split": "test",
                        "scene": scene,
                        "config": config,
                        "fingerprint": fingerprint,
                    }
                )
    return runs


def execute(home, output, fds, *, workers=4, budget_s=3000):
    started = time.perf_counter()
    output.mkdir(parents=True, exist_ok=False)
    original = home / "datasets/spatial-corpus-v1"
    if not (original / "PAUSE").exists():
        raise RuntimeError("Pause the long campaign between solves before this bounded audit")
    plan = make_plan(home)
    model_dir = home / "runtime/models/spatial-pilot-v1"
    weights_sha = file_sha(model_dir / "weights.pt")
    snapshot = json.loads((model_dir / "dataset-snapshot.json").read_text())
    seen_signatures = {r["geometry_signature"] for r in snapshot["runs"]}
    sources = {
        **compiler_hashes(home / "app"),
        "fds_executable": file_sha(fds),
        "evaluation_script": file_sha(Path(__file__)),
    }
    write_new_json(
        output / "plan.json",
        {
            "runs": plan,
            "sources": sources,
            "workers": workers,
            "threads_per_solver": 1,
            "budget_s": budget_s,
            "model_weights_sha256": weights_sha,
        },
    )
    # Check admissibility before consuming compute; preflight directories are retained.
    for item in plan:
        folder = output / "runs" / item["id"]
        folder.mkdir(parents=True)
        write_new_json(folder / "scene.json", item["scene"])
        write_new_json(folder / "config.json", item["config"])
        preflight = output / "preflight" / item["id"]
        preflight.mkdir(parents=True)
        manifest = compile_case(item["scene"], item["config"], preflight)
        signature = physical_signature(manifest)
        if (signature in seen_signatures) != (item["group"] == "similar"):
            raise ValueError("Evaluation geometry group does not match training provenance")
    print(json.dumps({"stage": "preflight_complete", "runs": len(plan), "workers": workers}), flush=True)
    model = SpatialSurrogate(model_dir, device="cuda:0")
    before = state_sha(model.network)
    rows, references, detection_rows, plots, failures = [], [], [], [], []
    timings = []

    def solve(item):
        folder = output / "runs" / item["id"]
        settings = Settings(
            root=home / "app",
            runtime=folder / "worker-runtime",
            fds_executable=fds,
            omp_threads=1,
            disk_reserve_gb=20,
        )
        # The pool owns the real compute lock; each solver has its own distinct
        # lock. Solvers never compete for the pool lock or each other's outputs.
        start = time.perf_counter()
        result = FDSRunner(settings).run(
            item["scene"], item["config"], folder, cancel=lambda: time.perf_counter() - started > budget_s
        )
        if result["summary"].get("nonfinite_spatial_measurements") != 0:
            raise ValueError("Nonfinite FDS measurements")
        return item, result, time.perf_counter() - start

    with ProcessLock(home / "runtime/compute.lock"):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending, remaining = {}, iter(plan)
            for _ in range(workers):
                item = next(remaining)
                pending[pool.submit(solve, item)] = item
            while pending:
                completed, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                for future in completed:
                    planned = pending.pop(future)
                    try:
                        item, result, solve_seconds = future.result()
                        folder = output / "runs" / item["id"]
                        # Remove only this worker's released lock before archiving raw files.
                        (folder / "worker-runtime/compute.lock").unlink()
                        (folder / "worker-runtime").rmdir()
                        storage = compress_completed_run(folder, result)
                        record = {key: value for key, value in item.items() if key != "scene"}
                        record.update(storage)
                        case = load_spatial_case(folder, record)
                        case["config"] = case["manifest"]["config"]
                        torch.cuda.synchronize()
                        inference_start = time.perf_counter()
                        predicted, globals_ = model.predict_arrays(
                            case["config"], case["manifest"], case["time_s"]
                        )
                        torch.cuda.synchronize()
                        inference_seconds = time.perf_counter() - inference_start
                        row = run_metrics(case, predicted, globals_)
                        compare_metrics(physical_metrics(case, predicted, globals_), row)
                        measured = {**row, "group": item["group"]}
                        ambient = case["config"]["ambient_temperature_c"]
                        baseline = run_metrics(
                            case,
                            np.broadcast_to([ambient, 0.0], predicted.shape),
                            np.tile([ambient, ambient, 0.0, 0.0], (len(predicted), 1)),
                        )
                        reference = {**baseline, "group": item["group"]}
                        detection = {
                            "run_id": item["id"],
                            "group": item["group"],
                            **classification(case, predicted),
                        }
                        plot = {**plot_case(case, predicted), "group": item["group"]}
                        timing = {
                            "run_id": item["id"],
                            "solver_and_parse_s": solve_seconds,
                            "inference_s": inference_seconds,
                            "fds_full_max_c": float(np.nanmax(case["globals"][:, 0])),
                            "sampled_max_c": float(np.nanmax(case["temperature_c"])),
                        }
                        write_new_json(
                            folder / "audit.json",
                            {
                                "metrics": measured,
                                "baseline": baseline,
                                "diagnostics": detection,
                                "record": record,
                            },
                        )
                        rows.append(measured)
                        references.append(reference)
                        detection_rows.append(detection)
                        plots.append(plot)
                        timings.append(timing)
                    except Exception as exc:
                        failures.append({"run_id": planned["id"], "error": f"{type(exc).__name__}: {exc}"})
                    progress = {
                        "stage": "running",
                        "completed": len(rows),
                        "failed": len(failures),
                        "total": len(plan),
                        "elapsed_s": time.perf_counter() - started,
                    }
                    write_json(output / "progress.json", progress)
                    print(json.dumps(progress), flush=True)
                    if time.perf_counter() - started < budget_s:
                        item = next(remaining, None)
                        if item is not None:
                            pending[pool.submit(solve, item)] = item
    if file_sha(model_dir / "weights.pt") != weights_sha or state_sha(model.network) != before:
        raise ValueError("Frozen model changed during evaluation")
    groups = {}
    for group in ("similar", "novel_geometry"):
        selected = [{k: v for k, v in row.items() if k != "group"} for row in rows if row["group"] == group]
        base = [{k: v for k, v in row.items() if k != "group"} for row in references if row["group"] == group]
        if not selected:
            continue
        diagnostics = {}
        for kind in ("hot", "smoky"):
            counts = {
                key: sum(row[kind][key] for row in detection_rows if row["group"] == group)
                for key in ("tp", "fn", "fp", "tn")
            }
            diagnostics[kind] = {
                **counts,
                "recall": counts["tp"] / (counts["tp"] + counts["fn"])
                if counts["tp"] + counts["fn"]
                else None,
                "precision": counts["tp"] / (counts["tp"] + counts["fp"])
                if counts["tp"] + counts["fp"]
                else None,
                "iou": counts["tp"] / (counts["tp"] + counts["fn"] + counts["fp"])
                if counts["tp"] + counts["fn"] + counts["fp"]
                else None,
            }
        groups[group] = {
            "model": summarize(selected),
            "baseline": summarize(base),
            "diagnostics": diagnostics,
        }
    report = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "planned_runs": len(plan),
        "completed_runs": len(rows),
        "failures": failures,
        "groups": groups,
        "elapsed_s": time.perf_counter() - started,
        "workers": workers,
        "threads_per_solver": 1,
        "device_name": torch.cuda.get_device_name(),
        "model_weights_sha256": weights_sha,
        "plan_sha256": file_sha(output / "plan.json"),
        "per_run": rows,
        "baseline_per_run": references,
        "per_run_diagnostics": detection_rows,
        "timings": timings,
        "scope": "New FDS simulations; no fitting or parameter selection; not experimental validation",
        "thresholds": {"temperature_above_ambient_c": 5, "soot_kg_m3": 1e-7},
        "diagnostic_basis": "Observed gas point/time pairs at t>0, not independent cases; micro counts",
        "physical_error_basis": "Run/layout macro means include imposed t=0; 8x10x4 gas samples",
        "frame_selection": "Spatial illustrations use each reference channel's maximum over time",
    }
    write_new_json(output / "report.json", report)
    write_new_json(output / "plot-data.json", plots)
    write_json(
        output / "progress.json",
        {
            "stage": "completed" if len(rows) == len(plan) and not failures else "incomplete",
            "completed": len(rows),
            "failed": len(failures),
            "total": len(plan),
        },
    )
    print(
        json.dumps(
            {
                "stage": "finished",
                "completed": len(rows),
                "failures": failures,
                "elapsed_s": report["elapsed_s"],
                "groups": groups,
            }
        ),
        flush=True,
    )
    if len(rows) != len(plan) or failures:
        raise RuntimeError("Expanded evaluation incomplete; inspect the saved report")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fds", type=Path, required=True)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required for persisted-model inference")
    torch.set_num_threads(2)
    torch.cuda.set_per_process_memory_fraction(0.25, 0)
    execute(args.home, args.output, args.fds)
