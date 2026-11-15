"""Bounded FDS generation for the diverse ISS-inspired v2; no model training."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import numpy as np
from ignis.config import Settings
from ignis.engine import Cancelled, FDSRunner, write_json
from ignis.locking import ProcessLock
from ignis.ml.spatial_dataset import compress_completed_run, file_sha, read_spatial_index
from ignis.provenance import canonical_sha

if __package__:
    from . import iss_poc_v2_design as design_module
else:
    import iss_poc_v2_design as design_module

original = design_module.original
DATASET_ID = design_module.DATASET_ID


def prepare_dataset(dataset: Path, design: dict) -> tuple[dict, dict]:
    dataset.mkdir(parents=True, exist_ok=True)
    plan_path, index_path = dataset / "plan.json", dataset / "manifest.json"
    design_sha = canonical_sha(design)
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        stored = {k: v for k, v in plan.items() if k not in {"design_sha256", "preflight"}}
        if plan.get("design_sha256") != design_sha or canonical_sha(stored) != design_sha:
            raise ValueError("Existing ISS plan differs; preserve it and choose a new dataset")
    else:
        allowed = {"generation.lock", "progress.json", "preflight", "PAUSE", "STOP"}
        if any(p.name not in allowed for p in dataset.iterdir()):
            raise FileExistsError("Unrecognized ISS artifacts; nothing will be overwritten")
        plan = {
            **design,
            "design_sha256": design_sha,
            "preflight": design_module.preflight(design, cache_dir=dataset / "preflight"),
        }
        original.write_new_json(plan_path, plan)
    if index_path.exists():
        index = read_spatial_index(dataset)
        if (
            index.get("dataset_id") != DATASET_ID
            or index.get("plan_sha256") != file_sha(plan_path)
            or index.get("design_sha256") != design_sha
            or index.get("expected_runs") != len(plan["runs"])
        ):
            raise ValueError("ISS manifest identity or immutable plan checksum mismatch")
    else:
        if any((dataset / name).exists() for name in ("runs", "records", "attempts")):
            raise FileExistsError("ISS case artifacts exist without their manifest")
        index = {
            "dataset_id": DATASET_ID,
            "schema_version": 1,
            "compiler_version": plan["compiler_version"],
            "material_model_version": plan["material_model_version"],
            "created_at": original.now(),
            "origin": "FDS simulations",
            "nasa_experimental_labels": False,
            "expected_runs": len(plan["runs"]),
            "partition": plan["partition"],
            "partition_policy": plan["partition_policy"],
            "plan_sha256": file_sha(plan_path),
            "design_sha256": design_sha,
            "record_directory": "records",
            "runs": [],
        }
        original.write_new_json(index_path, index)
    return plan, index


def label_profile(folder: Path) -> dict:
    """Observed label prevalence only; missing/solid observations never count."""
    with np.load(folder / "fields.npz", allow_pickle=False) as arrays:
        later = arrays["time_s"] > 0
        heat = arrays["temperature_c"][later].astype(np.float64)
        smoke = arrays["smoke_kg_m3"][later].astype(np.float64)
        masks = arrays["field_mask"][later]
        ambient = json.loads((folder / "config.json").read_text(encoding="utf-8"))["ambient_temperature_c"]
        hot = masks[..., 0] & (heat >= ambient + 5)
        smoky = masks[..., 1] & (smoke >= 1e-6)
        return {
            "heat_observed": int(masks[..., 0].sum()),
            "heat_positive": int(hot.sum()),
            "smoke_observed": int(masks[..., 1].sum()),
            "smoke_positive": int(smoky.sum()),
            "maximum_temperature_c": float(heat[masks[..., 0]].max()),
            "maximum_smoke_kg_m3": float(smoke[masks[..., 1]].max()),
            "heat_threshold": "ambient + 5 C",
            "smoke_threshold_kg_m3": 1e-6,
            "excluded": "t=0 and all unobserved gas/solid values",
        }


def execute_campaign(
    settings: Settings,
    dataset: Path,
    plan: dict,
    index: dict,
    *,
    source: Path,
    pilot=False,
    workers=4,
    budget_s=600,
    runner_factory=FDSRunner,
    started_at=None,
) -> dict:
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 4:
        raise ValueError("workers must be an integer in 1..4")
    if isinstance(budget_s, bool) or not math.isfinite(budget_s) or budget_s <= 0:
        raise ValueError("budget_s must be positive and finite")
    if settings.omp_threads != 1 or settings.disk_reserve_gb < 20:
        raise ValueError("ISS pool requires one thread per FDS process and 20 GiB reserve")
    if dataset.resolve().is_relative_to(source.resolve()) or source.resolve().is_relative_to(
        dataset.resolve()
    ):
        raise ValueError("Output and original corpus must be independent")
    if source.exists() and not (source / "PAUSE").is_file():
        raise ValueError("Original corpus must remain paused")
    started = time.monotonic() if started_at is None else started_at
    deadline = started + budget_s
    planned = {r["id"]: r for r in plan["runs"]}
    records = {r["id"]: r for r in index["runs"]}
    scenes = {layout["layout_id"]: layout["scene"] for layout in plan["layouts"]}
    if len(records) != len(index["runs"]) or set(records) - set(planned):
        raise ValueError("Unknown or duplicate ISS case record")
    for record in records.values():
        expected = planned[record["id"]]
        if any(record.get(k) != v for k, v in expected.items()):
            raise ValueError("ISS checkpoint input differs from immutable plan")
        if record.get("status") == "completed":
            original.verify_completed(dataset, record, expected)
    checkpoint_dir = dataset / "records"
    checkpoint_dir.mkdir(exist_ok=True)
    cancelled = threading.Event()
    newly_completed = 0
    selected = design_module.scheduled_runs(plan, pilot=pilot)

    def save(state):
        index["runs"] = list(records.values())
        elapsed = time.monotonic() - started
        index["active_elapsed_s"] = elapsed
        index["completed_runs"] = sum(r["status"] == "completed" for r in records.values())
        summary = original.progress_summary(
            plan,
            index,
            state,
            elapsed_s=elapsed,
            completed_this_session=newly_completed,
            disk_free_gb=shutil.disk_usage(dataset).free / 1024**3,
        )
        summary.update(
            dataset_id=DATASET_ID,
            pilot=pilot,
            workers=workers,
            threads_per_solver=1,
            budget_s=budget_s,
            budget_overrun_s=max(0, elapsed - budget_s),
            ready_for_training=index["completed_runs"] == len(planned),
            estimated_remaining_s=None,
            elapsed_basis="This invocation including verification, FDS, parsing, archival",
            budget_basis="Cancel live FDS at deadline; finish in-flight archival safely",
        )
        write_json(dataset / "manifest.json", index)
        write_json(dataset / "progress.json", summary)
        print(json.dumps(summary), flush=True)
        return summary

    def checkpoint(record):
        records[record["id"]] = record
        write_json(checkpoint_dir / (record["id"] + ".json"), record)

    def interruption():
        if cancelled.is_set() or (dataset / "STOP").exists():
            return "stopped"
        if (dataset / "PAUSE").exists():
            return "paused"
        if time.monotonic() >= deadline:
            return "budget_exhausted"
        if source.exists() and not (source / "PAUSE").is_file():
            return "source_resumed"
        if shutil.disk_usage(dataset).free < settings.disk_reserve_gb * 1024**3:
            return "disk_reserve"
        return None

    def solve(item):
        folder = dataset / item["relative_path"]
        folder.mkdir(parents=True, exist_ok=False)
        original.write_new_json(folder / "scene.json", scenes[item["layout_id"]])
        original.write_new_json(folder / "config.json", item["config"])
        worker_settings = Settings(
            settings.root, dataset / "workers" / item["id"], settings.fds_executable, 1, disk_reserve_gb=20
        )
        began = time.monotonic()
        result = runner_factory(worker_settings).run(
            scenes[item["layout_id"]], item["config"], folder, cancel=lambda: interruption() is not None
        )
        solve_seconds = time.monotonic() - began
        if result["summary"].get("nonfinite_spatial_measurements") != 0:
            raise ValueError("Nonfinite gas observations require review")
        if abs(result["metrics"][-1]["time_s"] - item["config"]["duration_s"]) > 0.01:
            raise ValueError("Incomplete FDS trajectory")
        storage = compress_completed_run(folder, result)
        record = {
            **item,
            **storage,
            "status": "completed",
            "completed_at": original.now(),
            "wall_time_s": result["provenance"]["wall_time_s"],
            "solver_and_parse_s": solve_seconds,
            "solve_parse_archive_s": time.monotonic() - began,
        }
        # Test labels remain sealed for first final evaluation; no activity report.
        if item["split"] != "test":
            record["label_profile"] = label_profile(folder)
        original.verify_completed(dataset, record, item)
        return record

    with ProcessLock(settings.runtime / "compute.lock"):
        for item in selected:
            record = records.get(item["id"])
            if record and record["status"] != "completed":
                original.archive_incomplete(dataset, record, item)
                checkpoint(record)
        todo = iter(r for r in selected if records.get(r["id"], {}).get("status") != "completed")
        save("running")
        stop_reason = None
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {}
            try:
                while True:
                    stop_reason = interruption() or stop_reason
                    while not stop_reason and len(pending) < workers:
                        item = next(todo, None)
                        if item is None:
                            break
                        if (dataset / item["relative_path"]).exists():
                            raise FileExistsError("Untracked ISS case folder; preserve for review")
                        checkpoint({**item, "status": "running", "started_at": original.now()})
                        pending[pool.submit(solve, item)] = item
                    if not pending:
                        break
                    done, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                    for future in done:
                        item = pending.pop(future)
                        try:
                            checkpoint(future.result())
                            newly_completed += 1
                        except Exception as exc:
                            checkpoint(
                                {
                                    **item,
                                    "status": "cancelled" if isinstance(exc, Cancelled) else "failed",
                                    "error": f"{type(exc).__name__}: {exc}",
                                    "failed_at": original.now(),
                                }
                            )
                        save(stop_reason or "running")
            except BaseException:
                cancelled.set()
                raise
        complete = len(records) == len(planned) and all(r["status"] == "completed" for r in records.values())
        if complete:
            index["runs"] = list(records.values())
            original.freeze_index(dataset, index)
        selected_complete = all(records.get(r["id"], {}).get("status") == "completed" for r in selected)
        state = (
            "completed"
            if complete
            else "pilot_completed"
            if pilot and selected_complete
            else stop_reason or "incomplete"
        )
        return save(state)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    parser.add_argument("--dataset", type=Path)
    parser.add_argument(
        "--pilot", action="store_true", help="Twelve predeclared train/validation cases; no test"
    )
    parser.add_argument("--budget-s", type=float, default=1800)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--fds",
        type=Path,
        default=Path("E:/IGNIS-Valley/tools/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe"),
    )
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("Real FDS must run on the authorized Windows workstation")
    if not args.fds.is_file():
        parser.error("FDS executable missing")
    started = time.monotonic()
    settings = Settings(args.home / "app", args.home / "runtime", args.fds, 1, disk_reserve_gb=20)
    dataset = args.dataset or args.home / "datasets" / DATASET_ID
    source = args.home / "datasets" / original.DATASET_ID
    inputs = {
        **original.compiler_hashes(settings.root),
        "fds_executable_sha256": file_sha(args.fds),
        "tools/remote/iss_poc_v2_design.py": file_sha(Path(design_module.__file__)),
        "tools/remote/generate_iss_poc_v2.py": file_sha(Path(__file__)),
        "tools/remote/iss_poc_design.py": file_sha(Path(design_module.previous.__file__)),
    }
    design = design_module.build_design(inputs)
    dataset.mkdir(parents=True, exist_ok=True)
    with ProcessLock(dataset / "generation.lock"):
        plan, index = prepare_dataset(dataset, design)
        execute_campaign(
            settings,
            dataset,
            plan,
            index,
            source=source,
            pilot=args.pilot,
            workers=args.workers,
            budget_s=args.budget_s,
            started_at=started,
        )


if __name__ == "__main__":
    main()
