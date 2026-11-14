"""Generate a finite compact FDS dataset with verified reuse and a wall-time budget.

The original corpus is read only and must remain paused. A dataset's selected
layout count is immutable: request another destination to change it. Four FDS
processes use one OpenMP thread each; a single global lock protects the pool.
An optional completed compact dataset can supply exact cases to a larger plan.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from ignis.config import Settings
from ignis.engine import Cancelled, FDSRunner, write_json
from ignis.locking import ProcessLock
from ignis.ml.spatial_dataset import compress_completed_run, file_sha, read_spatial_index
from ignis.provenance import canonical_sha

if __package__:
    from . import compact_spatial_design as compact
else:
    import compact_spatial_design as compact

original = compact.original
DATASET_ID = compact.DATASET_ID


def balanced_order(plan: dict) -> list[dict]:
    """Interleave incidents and structures inside each complete 50-layout block."""
    layouts = plan["layouts"]
    grouped = {}
    for run in plan["runs"]:
        grouped.setdefault(run["layout_id"], []).append(run)
    order = []
    for block in range(0, len(layouts), 50):
        for family_round in range(10):
            for incident in range(5):
                index = block + incident * 10 + (family_round + incident) % 10
                if index < len(layouts):
                    order.extend(grouped[layouts[index]["layout_id"]])
    if len(order) != len(plan["runs"]) or len({r["id"] for r in order}) != len(order):
        raise ValueError("Scheduling lost or duplicated planned cases")
    return order


def prepare_dataset(dataset: Path, design: dict) -> tuple[dict, dict]:
    """Build or verify one immutable plan; checkpoints remain mutable metadata."""
    dataset.mkdir(parents=True, exist_ok=True)
    plan_path, index_path = dataset / "plan.json", dataset / "manifest.json"
    design_sha = canonical_sha(design)
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        saved_design = {k: v for k, v in plan.items() if k not in {"design_sha256", "preflight"}}
        if plan.get("design_sha256") != design_sha or canonical_sha(saved_design) != design_sha:
            raise ValueError("Existing compact plan differs; select a new dataset directory")
    else:
        allowed = {"generation.lock", "progress.json", "preflight", "PAUSE", "STOP"}
        if any(p.name not in allowed for p in dataset.iterdir()):
            raise FileExistsError("Unrecognized compact artifacts; nothing will be overwritten")
        preflight = original.preflight(design, cache_dir=dataset / "preflight")
        plan = {**design, "design_sha256": design_sha, "preflight": preflight}
        original.write_new_json(plan_path, plan)
    if index_path.exists():
        index = read_spatial_index(dataset)
        if (
            index.get("dataset_id") != DATASET_ID
            or index.get("plan_sha256") != file_sha(plan_path)
            or index.get("design_sha256") != design_sha
            or index.get("expected_runs") != len(plan["runs"])
            or index.get("compiler_version") != plan["compiler_version"]
            or index.get("material_model_version") != plan["material_model_version"]
        ):
            raise ValueError("Compact manifest identity or immutable plan checksum mismatch")
    else:
        if any((dataset / name).exists() for name in ("runs", "records", "attempts")):
            raise FileExistsError("Compact case artifacts exist without their manifest")
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
            "plan_sha256": file_sha(plan_path),
            "design_sha256": design_sha,
            "record_directory": "records",
            "runs": [],
        }
        original.write_new_json(index_path, index)
    return plan, index


def reusable_records(source: Path, plan: dict, *, compact_source: bool = False) -> dict[str, dict]:
    """Only exact cases from a checksum-verified source plan qualify.

    A compact source must have a complete frozen index; the legacy original
    corpus can be partial, but must remain paused throughout the new campaign.
    """
    if not source.exists():
        if compact_source:
            raise ValueError("Requested compact reuse source does not exist")
        return {}
    if not compact_source and not (source / "PAUSE").is_file():
        raise ValueError("The original spatial corpus must remain paused")
    source_index = read_spatial_index(source)
    source_path = source / "plan.json"
    source_plan = json.loads(source_path.read_text(encoding="utf-8"))
    design = {k: v for k, v in source_plan.items() if k not in {"design_sha256", "preflight"}}
    expected_id = DATASET_ID if compact_source else original.DATASET_ID
    expected_version = compact.DESIGN_VERSION if compact_source else compact.SOURCE_DESIGN_VERSION
    if (
        source_index.get("dataset_id") != expected_id
        or source_plan.get("dataset_id") != expected_id
        or source_plan.get("design_version") != expected_version
        or source_index.get("plan_sha256") != file_sha(source_path)
        or source_plan.get("design_sha256") != canonical_sha(design)
        or source_index.get("design_sha256") != source_plan.get("design_sha256")
        or source_plan.get("compiler_source_hashes") != plan["compiler_source_hashes"]
    ):
        raise ValueError("Source dataset provenance differs; cannot reuse its labels")
    if compact_source and (
        not source_index.get("frozen_index_sha256")
        or len(source_index["runs"]) != source_index.get("expected_runs")
        or source_index.get("expected_runs") != len(source_plan["runs"])
        or any(r.get("status") != "completed" for r in source_index["runs"])
    ):
        raise ValueError("Compact reuse source must be complete and have a verified frozen index")
    planned_source = {r["id"]: r for r in source_plan["runs"]}
    completed = {r["id"]: r for r in source_index["runs"] if r.get("status") == "completed"}
    matches = {}
    for planned in plan["runs"]:
        record = completed.get(planned["id"])
        if record is None:
            continue
        if planned_source.get(planned["id"]) != planned:
            raise ValueError("Matched source ID has different inputs, split or fingerprint")
        original.verify_completed(source, record, planned)
        matches[planned["id"]] = record
    return matches


def copy_verified_case(
    source: Path, dataset: Path, record: dict, planned: dict, *, source_dataset_id: str = original.DATASET_ID
) -> dict:
    """Copy verified bytes exclusively; never link mutable files to the source."""
    original.verify_completed(source, record, planned)
    source_folder = source / planned["relative_path"]
    folder = dataset / planned["relative_path"]
    folder.mkdir(parents=True, exist_ok=False)
    for name in sorted(record["file_hashes"]):
        with (source_folder / name).open("rb") as old, (folder / name).open("xb") as new:
            shutil.copyfileobj(old, new)
    copied = copy.deepcopy(record)
    previous_origin = copied.pop("reused_from", None)
    copied["reused_from"] = {
        "dataset_id": source_dataset_id,
        "dataset_path": str(source.resolve()),
        "run_id": record["id"],
        "source_plan_sha256": file_sha(source / "plan.json"),
        "verified_at": original.now(),
    }
    if previous_origin is not None:
        copied["reused_from"]["upstream"] = previous_origin
    original.verify_completed(dataset, copied, planned)
    return copied


def execute_campaign(
    settings: Settings,
    dataset: Path,
    plan: dict,
    index: dict,
    *,
    source: Path,
    reuse_compact: Path | None = None,
    workers: int = 4,
    budget_s: float = 1200,
    runner_factory=FDSRunner,
    started_at: float | None = None,
) -> dict:
    """Budget includes setup/reuse/solve/parse; in-flight archival finishes safely.

    At the deadline live FDS processes are cancelled and no case is submitted.
    Python parsing/compression already in progress may finish after the deadline;
    actual overrun is explicitly reported rather than counted as another budget.
    """
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 4:
        raise ValueError("workers must be an integer in 1..4")
    if isinstance(budget_s, bool) or not math.isfinite(budget_s) or budget_s <= 0:
        raise ValueError("budget_s must be positive and finite")
    if settings.omp_threads != 1 or settings.disk_reserve_gb < original.RESERVE_GB:
        raise ValueError("Compact pool requires one thread per solver and a 20 GiB disk reserve")
    if dataset.resolve() == source.resolve() or dataset.resolve().is_relative_to(source.resolve()):
        raise ValueError("Compact output must be independent of the original corpus")
    if reuse_compact is not None and (
        dataset.resolve().is_relative_to(reuse_compact.resolve())
        or reuse_compact.resolve().is_relative_to(dataset.resolve())
    ):
        raise ValueError("Compact output must be independent of the compact reuse source")
    started = time.monotonic() if started_at is None else started_at
    deadline = started + budget_s
    records = {r["id"]: r for r in index["runs"]}
    planned = {r["id"]: r for r in plan["runs"]}
    scenes = {r["layout_id"]: r["scene"] for r in plan["layouts"]}
    if len(records) != len(index["runs"]) or set(records) - set(planned):
        raise ValueError("Unknown or duplicate compact case record")
    for record in records.values():
        expected = planned[record["id"]]
        if any(record.get(k) != v for k, v in expected.items()):
            raise ValueError("Compact checkpoint inputs differ from immutable plan")
        if record.get("status") == "completed":
            original.verify_completed(dataset, record, expected)
    reuse = {key: (source, original.DATASET_ID, row) for key, row in reusable_records(source, plan).items()}
    if reuse_compact is not None:
        # Exact compact copies take precedence, so overlapping original cases
        # are counted only once and record their immediate source honestly.
        reuse.update(
            {
                key: (reuse_compact, DATASET_ID, row)
                for key, row in reusable_records(reuse_compact, plan, compact_source=True).items()
            }
        )
    checkpoint_dir = dataset / index["record_directory"]
    checkpoint_dir.mkdir(exist_ok=True)
    cancelled = threading.Event()
    new_count = reuse_count = 0
    stop_reason = None

    def save(state):
        index["runs"] = list(records.values())
        completed = [r for r in index["runs"] if r["status"] == "completed"]
        elapsed = time.monotonic() - started
        index["completed_runs"] = len(completed)
        index["active_elapsed_s"] = elapsed
        summary = original.progress_summary(
            plan,
            index,
            state,
            elapsed_s=elapsed,
            completed_this_session=new_count + reuse_count,
            disk_free_gb=shutil.disk_usage(dataset).free / 1024**3,
        )
        summary.update(
            dataset_id=DATASET_ID,
            workers=workers,
            threads_per_solver=1,
            budget_s=budget_s,
            budget_overrun_s=max(0, elapsed - budget_s),
            newly_generated_runs=new_count,
            reused_this_session=reuse_count,
            reused_runs=sum("reused_from" in r for r in completed),
            reused_by_source={
                source_id: sum(r.get("reused_from", {}).get("dataset_id") == source_id for r in completed)
                for source_id in (original.DATASET_ID, DATASET_ID)
            },
            ready_for_training=len(completed) == len(planned),
            estimated_remaining_s=None,
            estimate_basis="No serial wall-time extrapolation for a concurrent pool",
            elapsed_basis="Invocation wall time including setup, verification, solves, parsing and archival",
            budget_basis="Stop dispatch and cancel FDS at deadline; finish in-flight parsing/archival safely",
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
        if source.exists() and not (source / "PAUSE").exists():
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
            root=settings.root,
            runtime=dataset / "workers" / item["id"],
            fds_executable=settings.fds_executable,
            omp_threads=1,
            disk_reserve_gb=settings.disk_reserve_gb,
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
        original.verify_completed(dataset, record, item)
        return record

    with ProcessLock(settings.runtime / "compute.lock"):
        for item in balanced_order(plan):
            record = records.get(item["id"])
            if record and record["status"] == "completed":
                continue
            stop_reason = interruption()
            if stop_reason:
                return save(stop_reason)
            if record:
                original.archive_incomplete(dataset, record, item)
                checkpoint(record)
            if item["id"] in reuse:
                # Record ownership first so an interrupted copy can be archived on resume.
                checkpoint({**item, "status": "running", "started_at": original.now()})
                reuse_path, reuse_id, reuse_record = reuse[item["id"]]
                checkpoint(
                    copy_verified_case(reuse_path, dataset, reuse_record, item, source_dataset_id=reuse_id)
                )
                reuse_count += 1
        todo = iter(r for r in balanced_order(plan) if records.get(r["id"], {}).get("status") != "completed")
        save("running")
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
                            raise FileExistsError("Untracked compact run folder; preserve for inspection")
                        checkpoint({**item, "status": "running", "started_at": original.now()})
                        pending[pool.submit(solve, item)] = item
                    if not pending:
                        break
                    done, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                    for future in done:
                        item = pending.pop(future)
                        try:
                            checkpoint(future.result())
                            new_count += 1
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
        return save("completed" if complete else stop_reason or "incomplete")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    parser.add_argument("--dataset", type=Path, help="Separate output directory, never the original corpus")
    parser.add_argument(
        "--reuse-compact",
        type=Path,
        help="Read exact cases from a completed, frozen compact dataset; never modify it",
    )
    parser.add_argument("--layout-count", type=int, default=50)
    parser.add_argument("--budget-s", type=float, default=1200)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--fds",
        type=Path,
        default=Path("E:/IGNIS-Valley/tools/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe"),
    )
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("Real FDS generation must run on the authorized Windows workstation")
    if not args.fds.is_file():
        parser.error("The FDS executable is missing")
    started = time.monotonic()
    dataset = args.dataset or args.home / "datasets" / DATASET_ID
    source = args.home / "datasets" / original.DATASET_ID
    if dataset.resolve() == source.resolve() or dataset.resolve().is_relative_to(source.resolve()):
        parser.error("Compact output must be independent of the original corpus")
    if args.reuse_compact is not None and (
        dataset.resolve().is_relative_to(args.reuse_compact.resolve())
        or args.reuse_compact.resolve().is_relative_to(dataset.resolve())
    ):
        parser.error("Compact output must be independent of the compact reuse source")
    settings = Settings(args.home / "app", args.home / "runtime", args.fds, 1, disk_reserve_gb=20)
    design = compact.build_design(
        {**original.compiler_hashes(settings.root), "fds_executable_sha256": file_sha(args.fds)},
        layout_count=args.layout_count,
    )
    dataset.mkdir(parents=True, exist_ok=True)
    with ProcessLock(dataset / "generation.lock"):
        plan, index = prepare_dataset(dataset, design)
        execute_campaign(
            settings,
            dataset,
            plan,
            index,
            source=source,
            reuse_compact=args.reuse_compact,
            workers=args.workers,
            budget_s=args.budget_s,
            started_at=started,
        )


if __name__ == "__main__":
    main()
