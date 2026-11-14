"""Generate 1,000 procedural compartments and 20,000 real FDS scenarios on Windows."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from ignis.config import Settings
from ignis.engine import FDSRunner, write_json
from ignis.locking import ProcessLock
from ignis.ml.incidents import (
    COMPILER_VERSION,
    INCIDENT_TYPES,
)
from ignis.ml.spatial_dataset import compress_completed_run, file_sha, load_spatial_case, read_spatial_index
from ignis.physics import compile_case
from ignis.physics.compiler import _smooth_count, _validate_config
from ignis.physics.incidents import locate_incident
from ignis.physics.materials import MODEL_VERSION
from ignis.provenance import canonical_sha

DATASET_ID = "spatial-corpus-v1"
DESIGN_VERSION = "procedural-spatial-design-1"
SEED = 2026111401
RESERVE_GB = 20
SAMPLE_SHAPE = [12, 16, 8]
EXPECTED_RUNS = 20000
# Interleave partitions from the first three geometries onward.
STRUCTURES = (
    ("perimeter", "train"),
    ("cross-aisle", "validation"),
    ("baffled", "test"),
    ("central-island", "train"),
    ("split-bays", "validation"),
    ("double-island", "test"),
    ("parallel-aisles", "train"),
    ("staggered", "train"),
    ("corner-banks", "train"),
    ("radial-clusters", "train"),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_new_json(path: Path, value) -> None:
    """Publish a complete immutable file, never replace an existing artifact.

    An interrupted write leaves only a hidden temporary file, kept for review.
    POSIX link and Windows rename both fail atomically when the target exists.
    """
    if path.exists():
        raise FileExistsError(path)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False, encoding="utf-8"
    ) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == "nt":
        os.rename(temporary, path)
    else:
        os.link(temporary, path)
        temporary.unlink()


def compiler_hashes(root: Path) -> dict:
    paths = [
        "backend/ignis/schema.py",
        "backend/ignis/physics/compiler.py",
        "backend/ignis/physics/incidents.py",
        "backend/ignis/physics/materials.py",
    ]
    return {path: file_sha(root / path) for path in paths}


def _tiles(family, nx, ny):
    all_tiles = [(x, y) for x in range(nx) for y in range(ny)]
    cx, cy = (nx - 1) / 2, (ny - 1) / 2
    selectors = {
        "perimeter": lambda x, y: x in (0, nx - 1) or y in (0, ny - 1),
        "central-island": lambda x, y: 0 < x < nx - 1 and 0 < y < ny - 1,
        "parallel-aisles": lambda x, y: x % 2 == 0,
        "staggered": lambda x, y: (x + y) % 2 == 0,
        "corner-banks": lambda x, y: abs(x - cx) >= 0.5 and abs(y - cy) >= 0.5,
        "cross-aisle": lambda x, y: x != nx // 2 and y != ny // 2,
        "split-bays": lambda x, y: y != ny // 2,
        "baffled": lambda x, y: (x % 2 == 0) if y % 2 == 0 else (x % 2 == 1),
        "double-island": lambda x, y: x in (1, nx - 2) and 0 < y < ny - 1,
        "radial-clusters": lambda x, y: (abs(x - cx) < 1 or abs(y - cy) < 1) and (x, y) != (nx // 2, ny // 2),
    }
    selected = [tile for tile in all_tiles if selectors[family](*tile)]
    if len(selected) < 6:
        remainder = sorted(
            (tile for tile in all_tiles if tile not in selected),
            key=lambda tile: (tile[0] - cx) ** 2 + (tile[1] - cy) ** 2,
        )
        selected.extend(remainder[: 6 - len(selected)])
    return selected


def procedural_scene(index: int, family: str) -> tuple[dict, float]:
    rng = np.random.default_rng(SEED + index * 101)
    bounds = np.round(rng.uniform([2.4, 3.2, 2.6], [6.0, 6.0, 4.8]), 4)
    cell = round(float((np.prod(bounds) / 24000) ** (1 / 3)), 6)
    ijk = np.asarray([_smooth_count(math.ceil(float(value / cell) - 1e-9)) for value in bounds])
    if not 12000 <= int(np.prod(ijk)) <= 60000:
        raise ValueError("Procedural mesh outside 12k–60k cells")
    spacing = bounds / ijk
    nx, ny = [max(3, min(6, (int(count) - 4) // 4)) for count in ijk[:2]]
    choices = _tiles(family, nx, ny)
    count = int(rng.integers(6, min(18, len(choices)) + 1))
    chosen = [choices[int(i)] for i in rng.choice(len(choices), count, replace=False)]
    edges = [np.linspace(2, int(ijk[a]) - 2, n + 1).astype(int) for a, n in enumerate((nx, ny))]
    objects = []
    for number, (x, y) in enumerate(chosen):
        lower, upper = [], []
        for axis, tile in enumerate((x, y)):
            lo, hi = int(edges[axis][tile]), int(edges[axis][tile + 1])
            width = int(rng.integers(2, max(3, hi - lo - 1)))
            if family == "baffled" and number % 3 == 0 and axis == 0:
                width = 1
            lower.append((lo + 1) * spacing[axis])
            upper.append((lo + 1 + width) * spacing[axis])
        lower.append(0.0)
        upper.append(int(rng.integers(3, max(4, int(ijk[2] * 0.65)))) * spacing[2])
        lo, hi = np.asarray(lower), np.asarray(upper)
        obj = {
            "id": f"equipment-{number:02d}",
            "name": f"Equipment {number + 1}",
            "role": "obstacle",
            "kind": "baffle" if family == "baffled" and number % 3 == 0 else "equipment",
            "material_id": str(rng.choice(["aluminium", "steel", "insulation"])),
            "center_m": ((lo + hi) / 2).tolist(),
            "size_m": (hi - lo).tolist(),
            "thermal_thickness_m": round(float(rng.uniform(0.0008, 0.008)), 6),
        }
        if rng.random() < 0.7:
            obj["combustible_material_id"] = str(rng.choice(["pmma", "cellulose"]))
        objects.append(obj)
    source_count = int(rng.integers(3, min(6, count) + 1))
    components = []
    for number, obj in enumerate(objects[:source_count]):
        obj.setdefault("combustible_material_id", "pmma" if number % 2 else "cellulose")
        point = [*obj["center_m"][:2], obj["center_m"][2] + obj["size_m"][2] / 2]
        components.append(
            {
                "id": f"electrical-{number:02d}",
                "object_id": obj["id"],
                "position_m": point,
                "face": 3,
                "kind": "electrical",
                "critical": number == 0,
            }
        )
    vents = []
    axis = int(rng.integers(0, 2))
    for number, role in enumerate(("inlet", "outlet")):
        center, size = [], []
        for a in range(3):
            if a == axis:
                center.append(0.0 if number == 0 else float(bounds[a]))
                size.append(0.0)
            else:
                width = int(rng.integers(2, max(3, min(7, int(ijk[a]) // 3))))
                first = int(rng.integers(1, int(ijk[a]) - width))
                center.append((first + width / 2) * float(spacing[a]))
                size.append(width * float(spacing[a]))
        normal = [0, 0, 0]
        normal[axis] = 1 if number == 0 else -1
        vents.append({"id": role, "role": role, "center_m": center, "size_m": size, "normal": normal})
    sensors = []
    for vent in vents:
        point = list(vent["center_m"])
        point[axis] += spacing[axis] / 2 * (1 if vent["role"] == "inlet" else -1)
        sensors.append({"id": "monitor-" + vent["id"], "position_m": point, "kind": "gas"})
    scene = {
        "id": f"procedural-{index:04d}",
        "name": f"{family} / {index:04d}",
        "units": "m",
        "coordinate_system": "right-handed Z-up",
        "bounds_m": bounds.tolist(),
        "geometry_family": family,
        "objects": objects,
        "components": components,
        "vents": vents,
        "sensors": sensors,
        "source_position_m": components[0]["position_m"],
        "provenance": "seeded procedural physical proxies; not a measured vehicle interior",
    }
    return scene, cell


def build_design(source_hashes: dict) -> dict:
    """One hundred rounds interleave all ten structural families and splits."""
    rng = np.random.default_rng(SEED)
    physical_layouts, runs = [], []
    pair_index = 0
    for index in range(1000):
        structural_family, split = STRUCTURES[index % len(STRUCTURES)]
        scene, mesh_cell = procedural_scene(index, structural_family)
        layout = {
            "layout_id": scene["id"],
            "scene_id": scene["id"],
            "scene": scene,
            "split": split,
            "structural_family": structural_family,
            "scene_sha256": canonical_sha(scene),
            "mesh_cell_m": mesh_cell,
        }
        physical_layouts.append(layout)
        for family_index, family in enumerate(INCIDENT_TYPES):
            # Each SI variable occupies both halves of its range. The same
            # conditions and turbulent seed are reused across gravity pairs.
            unit = np.column_stack([(rng.permutation(2) + rng.random(2)) / 2 for _ in range(3)])
            for condition in range(2):
                component = scene["components"][
                    (2 * family_index + condition + index) % len(scene["components"])
                ]
                power, air, oxygen = [
                    round(value, 6) for value in np.array([500, 0.05, 18]) + unit[condition] * [2500, 0.35, 6]
                ]
                for gravity_label, gravity in (("microg", 0.0001), ("earth", 1.0)):
                    config = {
                        "scene_id": scene["id"],
                        "source_model": "coupled_combustion",
                        "ignition_kind": "thermal",
                        "incident_type": family,
                        "component_id": component["id"],
                        "gravity_g": gravity,
                        "airflow_m_s": air,
                        "oxygen_percent": oxygen,
                        "ignition_power_w": power,
                        "ignition_duration_s": 1 if family == "arc" else 10,
                        "duration_s": 30,
                        "seed": 710000 + pair_index,
                        "material_id": "cellulose",
                        "mesh_cell_m": mesh_cell,
                        "sample_shape": list(SAMPLE_SHAPE),
                        "sample_interval_s": 1,
                        "ambient_temperature_c": 20,
                        "pressure_pa": 101325,
                        "ignition_delay_s": 0,
                    }
                    identifier = (
                        f"{layout['layout_id']}-{component['id']}-{family}-{gravity_label}-c{condition}"
                    )
                    runs.append(
                        {
                            "id": identifier,
                            "layout_id": layout["layout_id"],
                            "scene_id": scene["id"],
                            "split": layout["split"],
                            "condition_id": condition,
                            "config": config,
                            "structural_family": structural_family,
                            "scene_sha256": layout["scene_sha256"],
                            "relative_path": f"runs/{identifier}",
                            "fingerprint": canonical_sha(
                                {"scene": scene, "config": config, "compiler": COMPILER_VERSION}
                            ),
                        }
                    )
                pair_index += 1
    if len(runs) != EXPECTED_RUNS:
        raise ValueError(f"Campaign must contain exactly {EXPECTED_RUNS} distinct planned runs")
    physical_keys = []
    for run in runs:
        config = {
            key: value
            for key, value in run["config"].items()
            if key not in {"seed", "scene_id", "mode", "model_id"}
        }
        physical_keys.append(canonical_sha({"scene": run["scene_sha256"], "config": config}))
    if len(set(physical_keys)) != len(runs):
        raise ValueError("Duplicate physical cases: changing only a random seed does not make a new scenario")
    return {
        "dataset_id": DATASET_ID,
        "design_version": DESIGN_VERSION,
        "seed": SEED,
        "compiler_version": COMPILER_VERSION,
        "material_model_version": MODEL_VERSION,
        "compiler_source_hashes": source_hashes,
        "expected_runs": len(runs),
        "layouts": physical_layouts,
        "runs": runs,
        "partition": "Whole structural families: six train, two validation, two test; all 20 scenarios of every room remain together",
        "parameter_design": "Seeded 2-stratum Latin hypercube per layout/incident, paired across gravities, cycling 3–6 component origins",
    }


def preflight(design: dict, on_progress=None, cache_dir: Path | None = None) -> dict:
    """Compile each room once and validate every source against its snapped solids."""
    scene_by_layout = {item["layout_id"]: item["scene"] for item in design["layouts"]}
    checked_layouts, signatures, geometries, family_splits = set(), {}, {}, {}
    source_records, largest_csv = [], 0
    for run in design["runs"]:
        scene = scene_by_layout[run["layout_id"]]
        _validate_config(scene, run["config"])
        structural_family = run["structural_family"]
        if structural_family in family_splits and family_splits[structural_family] != run["split"]:
            raise ValueError("Structural family crosses dataset partitions")
        family_splits[structural_family] = run["split"]
        if run["layout_id"] in checked_layouts:
            continue
        checked_layouts.add(run["layout_id"])
        cache_key = canonical_sha(
            {"scene": scene, "config": run["config"], "sources": design["compiler_source_hashes"]}
        )
        cache = cache_dir / (run["layout_id"] + ".json") if cache_dir else None
        if cache and cache.exists():
            entry = json.loads(cache.read_text(encoding="utf-8"))
            if entry.get("input_sha256") != cache_key:
                raise ValueError("Cached preflight input differs; preserve the existing campaign")
            if entry.get("output_sha256") != canonical_sha(
                {key: value for key, value in entry.items() if key != "output_sha256"}
            ):
                raise ValueError("Cached preflight output checksum mismatch")
        else:
            with tempfile.TemporaryDirectory(prefix="ignis-spatial-preflight-") as folder:
                manifest = compile_case(scene, run["config"], Path(folder))
            if not 12000 <= manifest["mesh"]["cell_count"] <= 60000:
                raise ValueError("Compiled mesh exceeds procedural resource envelope")
            physical = {
                "bounds_m": manifest["mesh"]["bounds_m"],
                "objects": sorted(
                    [
                        {
                            key: obj.get(key)
                            for key in (
                                "bounds_m",
                                "material_id",
                                "combustible_material_id",
                                "thermal_thickness_m",
                            )
                        }
                        for obj in manifest["objects"]
                    ],
                    key=lambda obj: obj["bounds_m"],
                ),
                "vents": sorted(
                    [
                        {key: vent[key] for key in ("bounds_m", "normal", "role")}
                        for vent in manifest["vents"]
                    ],
                    key=lambda vent: vent["bounds_m"],
                ),
            }
            sources = []
            for component in scene["components"]:
                source = locate_incident(
                    scene,
                    {**manifest["config"], "component_id": component["id"]},
                    manifest["objects"],
                    manifest["mesh"]["cell_size_m"],
                    scene["bounds_m"],
                )
                sources.append({"layout_id": run["layout_id"], **source})
            entry = {
                "input_sha256": cache_key,
                "geometry_sha256": canonical_sha(physical),
                "cell_count": manifest["mesh"]["cell_count"],
                "mesh_cell_m": manifest["config"]["mesh_cell_m"],
                "cell_size_m": manifest["mesh"]["cell_size_m"],
                "mesh_shape": manifest["mesh"]["shape"],
                "sources": sources,
                "csv_bytes": manifest["estimates"]["csv_bytes_uncompressed"],
            }
            entry["output_sha256"] = canonical_sha(entry)
            if cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                write_new_json(cache, entry)
        signature = entry["geometry_sha256"]
        if signature in signatures and signatures[signature] != run["layout_id"]:
            raise ValueError(f"Physical layout duplicate across IDs/splits: {run['layout_id']}")
        signatures[signature] = run["layout_id"]
        geometries[run["layout_id"]] = {
            "geometry_sha256": signature,
            "split": run["split"],
            "structural_family": structural_family,
            "cell_count": entry["cell_count"],
            "mesh_cell_m": entry["mesh_cell_m"],
            "cell_size_m": entry["cell_size_m"],
            "mesh_shape": entry["mesh_shape"],
        }
        largest_csv = max(largest_csv, entry["csv_bytes"])
        source_records.extend(entry["sources"])
        if on_progress and len(checked_layouts) % 10 == 0:
            on_progress(len(checked_layouts))
    if len(geometries) != len(design["layouts"]):
        raise ValueError("Preflight did not cover every layout")
    return {
        "unique_source_geometries": len(source_records),
        "unique_physical_layouts": len(geometries),
        "layouts": geometries,
        "sources": source_records,
        "max_estimated_device_csv_bytes": largest_csv,
        "scope": "compiler admissibility and split isolation, not solver success or physical validation",
    }


def prepare_campaign(dataset: Path, design: dict) -> tuple[dict, dict]:
    plan_path, manifest_path = dataset / "plan.json", dataset / "manifest.json"
    design_sha = canonical_sha(design)
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan.get("design_sha256") != design_sha:
            raise ValueError(
                "Existing campaign design/compiler differs; preserve it and use a new dataset version"
            )
        # Validate the stored immutable content itself, not only its claimed hash.
        saved_design = {
            key: value for key, value in plan.items() if key not in {"design_sha256", "preflight"}
        }
        if canonical_sha(saved_design) != design_sha:
            raise ValueError("Stored campaign plan integrity mismatch")
    else:
        controls = {"generation.lock", "progress.json", "preflight", "PAUSE", "STOP"}
        if manifest_path.exists() or any(
            path.name not in controls
            and not (path.name.startswith(".plan.json.") and path.name.endswith(".tmp"))
            for path in dataset.iterdir()
        ):
            raise FileExistsError("Unrecognized existing campaign artifacts; nothing will be overwritten")
        started = time.monotonic()

        def report_preflight(count):
            progress = progress_summary(
                design,
                {"runs": []},
                "preflight",
                elapsed_s=time.monotonic() - started,
                completed_this_session=0,
                disk_free_gb=shutil.disk_usage(dataset).free / 1024**3,
            )
            progress["preflight_checked_layouts"] = count
            write_json(dataset / "progress.json", progress)

        report_preflight(0)
        try:
            report = preflight(design, report_preflight, dataset / "preflight")
        except Exception as exc:
            progress = json.loads((dataset / "progress.json").read_text(encoding="utf-8"))
            progress.update(
                state="failed", updated_at=now(), last_error=f"Preflight: {type(exc).__name__}: {exc}"
            )
            write_json(dataset / "progress.json", progress)
            raise
        plan = {**design, "design_sha256": design_sha, "preflight": report}
        write_new_json(plan_path, plan)
    if manifest_path.exists():
        manifest = read_spatial_index(dataset)
        if manifest.get("plan_sha256") != file_sha(plan_path):
            raise ValueError("Campaign plan checksum mismatch")
        if manifest.get("dataset_id") != DATASET_ID or manifest.get("compiler_version") != COMPILER_VERSION:
            raise ValueError("Campaign identity mismatch")
        if manifest.get("expected_runs") != len(plan["runs"]) or manifest.get("design_sha256") != design_sha:
            raise ValueError("Campaign checkpoint design mismatch")
        try:
            progress = json.loads((dataset / "progress.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            progress = {}
        elapsed = progress.get("elapsed_s")
        if (
            progress.get("plan_sha256") == manifest["plan_sha256"]
            and isinstance(elapsed, (int, float))
            and math.isfinite(elapsed)
        ):
            # Per-case progress can be newer than the periodic aggregate after
            # an interrupted launcher. Downtime is never added to active time.
            manifest["active_elapsed_s"] = max(manifest.get("active_elapsed_s", 0), elapsed)
    else:
        if (dataset / "runs").exists() or (dataset / "attempts").exists():
            raise FileExistsError("A campaign manifest is missing but run artifacts exist")
        manifest = {
            "dataset_id": DATASET_ID,
            "schema_version": 1,
            "compiler_version": COMPILER_VERSION,
            "material_model_version": MODEL_VERSION,
            "created_at": now(),
            "origin": "FDS simulations",
            "nasa_experimental_labels": False,
            "expected_runs": len(plan["runs"]),
            "partition": plan["partition"],
            "plan_sha256": file_sha(plan_path),
            "design_sha256": design_sha,
            "active_elapsed_s": 0,
            "completed_runs": 0,
            "record_directory": "records",
            "runs": [],
        }
        write_new_json(manifest_path, manifest)
    return plan, manifest


def verify_completed(dataset: Path, record: dict, planned: dict) -> None:
    if any(record.get(key) != planned[key] for key in planned):
        raise ValueError(f"Saved campaign inputs differ: {record['id']}")
    folder = dataset / planned["relative_path"]
    hashes = record.get("file_hashes", {})
    required = {
        "scene.json",
        "config.json",
        "manifest.json",
        "ignis.fds",
        "fields.npz",
        "result.json.gz",
        "raw-fds.zip",
    }
    if set(hashes) != required or any(file_sha(folder / name) != digest for name, digest in hashes.items()):
        raise ValueError(f"Completed run artifact checksum mismatch: {record['id']}")
    case = load_spatial_case(folder, record)
    if (
        record.get("result_sha256") != hashes["result.json.gz"]
        or case["manifest"]["deck_sha256"] != hashes["ignis.fds"]
    ):
        raise ValueError(f"Completed run provenance mismatch: {record['id']}")


def archive_incomplete(dataset: Path, record: dict, planned: dict) -> None:
    folder = dataset / planned["relative_path"]
    archive_root = dataset / "attempts" / planned["id"]
    if folder.exists():
        archive_root.mkdir(parents=True, exist_ok=True)
        indices = [int(path.name) for path in archive_root.iterdir() if path.is_dir() and path.name.isdigit()]
        target = archive_root / f"{max(indices, default=0) + 1:03d}"
        folder.rename(target)
        write_new_json(target / "attempt-record.json", {**record, "archived_at": now()})
    archived = (
        [
            str(path.relative_to(dataset)).replace("\\", "/")
            for path in sorted(archive_root.iterdir())
            if path.is_dir()
        ]
        if archive_root.exists()
        else []
    )
    record.clear()
    record.update({**planned, "status": "pending", "attempts": archived})


def progress_summary(
    plan: dict,
    manifest: dict,
    state: str,
    *,
    elapsed_s: float,
    completed_this_session: int,
    disk_free_gb: float,
    current=None,
    error=None,
) -> dict:
    completed = [run for run in manifest["runs"] if run["status"] == "completed"]
    statuses = {run["id"]: run["status"] for run in manifest["runs"]}
    by_split, by_type, by_structure, layout_status = {}, {}, {}, {}
    for run in plan["runs"]:
        layout_status.setdefault(run["layout_id"], []).append(statuses.get(run["id"]) == "completed")
        for container, key in (
            (by_split, run["split"]),
            (by_type, run["config"]["incident_type"]),
            (by_structure, run["structural_family"]),
        ):
            row = container.setdefault(key, {"planned": 0, "completed": 0, "failed": 0})
            row["planned"] += 1
            if statuses.get(run["id"]) in {"completed", "failed"}:
                row[statuses[run["id"]]] += 1
    for layout in plan["layouts"]:
        row = by_structure[layout["structural_family"]]
        row["planned_layouts"] = row.get("planned_layouts", 0) + 1
        row["completed_layouts"] = row.get("completed_layouts", 0) + int(
            all(layout_status[layout["layout_id"]])
        )
    mean = sum(run["wall_time_s"] for run in completed) / len(completed) if completed else None
    count = len(completed)
    return {
        "dataset_id": DATASET_ID,
        "plan_sha256": manifest.get("plan_sha256"),
        "state": state,
        "updated_at": now(),
        "total_runs": len(plan["runs"]),
        "completed_runs": count,
        "pending_runs": len(plan["runs"]) - count,
        "failed_runs": sum(status == "failed" for status in statuses.values()),
        "total_layouts": len(layout_status),
        "completed_layouts": sum(all(value) for value in layout_status.values()),
        "total_structural_families": len(by_structure),
        "completed_structural_families": sum(
            row["planned"] == row["completed"] for row in by_structure.values()
        ),
        "by_structural_family": by_structure,
        "current_run_id": current["id"] if current else None,
        "current_run": {
            "scene_id": current["scene_id"],
            "layout_id": current["layout_id"],
            **{key: current["config"][key] for key in ("component_id", "incident_type", "gravity_g")},
        }
        if current
        else None,
        "by_split": by_split,
        "by_incident_type": by_type,
        "elapsed_s": round(elapsed_s, 3),
        "elapsed_basis": "persisted launcher time including pauses and compute-lock waits; excludes time while launcher stopped",
        "estimated_remaining_s": round(mean * (len(plan["runs"]) - count), 1) if mean is not None else None,
        "estimate_basis": "completed FDS wall-time mean; excludes future pauses, failures and verification",
        "mean_completed_run_s": mean,
        "completed_this_session": completed_this_session,
        "disk_free_gb": round(disk_free_gb, 3),
        "disk_reserve_gb": RESERVE_GB,
        "last_error": error,
    }


def freeze_index(dataset: Path, manifest: dict) -> None:
    """A final immutable metadata index; case bytes stay in their own directories."""
    keys = (
        "dataset_id",
        "schema_version",
        "expected_runs",
        "compiler_version",
        "material_model_version",
        "plan_sha256",
        "design_sha256",
    )
    frozen = {key: manifest[key] for key in keys}
    frozen["runs"] = sorted(manifest["runs"], key=lambda row: row["id"])
    if len(frozen["runs"]) != frozen["expected_runs"] or any(
        row["status"] != "completed" for row in frozen["runs"]
    ):
        raise ValueError("Only a complete campaign can receive a frozen spatial index")
    path = dataset / "index.json"
    if path.exists():
        if canonical_sha(json.loads(path.read_text(encoding="utf-8"))) != canonical_sha(frozen):
            raise ValueError("Existing frozen spatial index differs; preserve it for inspection")
    else:
        write_new_json(path, frozen)
    manifest["frozen_index_sha256"] = file_sha(path)


def execute_campaign(
    settings: Settings, dataset: Path, plan: dict, manifest: dict, *, limit=None, runner_factory=FDSRunner
) -> dict:
    """Sequential solves. PAUSE and STOP are checked only between complete solves."""
    if settings.omp_threads != 4 or settings.disk_reserve_gb < RESERVE_GB:
        raise ValueError(
            "Spatial campaign requires exactly four FDS threads and at least 20 GiB disk reserve"
        )
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise ValueError("limit must be a nonnegative integer")
    started, previous_elapsed = time.monotonic(), manifest.get("active_elapsed_s", 0)
    completed_this_session = 0
    planned = {run["id"]: run for run in plan["runs"]}
    scenes = {layout["layout_id"]: layout["scene"] for layout in plan["layouts"]}

    checkpoint_dir = dataset / manifest["record_directory"]
    checkpoint_dir.mkdir(exist_ok=True)

    def checkpoint(record):
        write_json(checkpoint_dir / (record["id"] + ".json"), record)

    def save(state, current=None, error=None, persist_manifest=False):
        elapsed = previous_elapsed + time.monotonic() - started
        manifest["active_elapsed_s"] = elapsed
        manifest["completed_runs"] = sum(run["status"] == "completed" for run in manifest["runs"])
        if persist_manifest:
            write_json(dataset / "manifest.json", manifest)
        summary = progress_summary(
            plan,
            manifest,
            state,
            elapsed_s=elapsed,
            completed_this_session=completed_this_session,
            disk_free_gb=shutil.disk_usage(dataset).free / 1024**3,
            current=current,
            error=error,
        )
        write_json(dataset / "progress.json", summary)
        return summary

    current = None
    try:
        previous = {run["id"]: run for run in manifest["runs"]}
        if len(previous) != len(manifest["runs"]) or set(previous) - set(planned):
            raise ValueError("Unknown or duplicate run in campaign manifest")
        # Verify every completed run before modifying or archiving any artifact.
        for record in manifest["runs"]:
            expected = planned[record["id"]]
            if record["status"] not in {"pending", "running", "failed", "completed"}:
                raise ValueError(f"Unknown run checkpoint state: {record['id']}")
            if any(record.get(key) != expected[key] for key in expected):
                raise ValueError(f"Existing run plan mismatch: {record['id']}")
            if record["status"] == "completed":
                verify_completed(dataset, record, expected)
        if (dataset / "STOP").exists():
            return save("stopped", persist_manifest=True)
        for record in manifest["runs"]:
            if record["status"] != "completed":
                archive_incomplete(dataset, record, planned[record["id"]])
                checkpoint(record)
        runner = runner_factory(settings)
        for expected in plan["runs"]:
            if expected["id"] in previous and previous[expected["id"]]["status"] == "completed":
                continue
            if (dataset / "STOP").exists():
                return save("stopped", persist_manifest=True)
            if limit is not None and completed_this_session >= limit:
                return save("limited", persist_manifest=True)
            if (dataset / "PAUSE").exists():
                save("paused", persist_manifest=True)
                while (dataset / "PAUSE").exists():
                    if (dataset / "STOP").exists():
                        return save("stopped", persist_manifest=True)
                    time.sleep(2)
                    save("paused")
            if (dataset / "STOP").exists():
                return save("stopped", persist_manifest=True)
            if shutil.disk_usage(dataset).free < settings.disk_reserve_gb * 1024**3:
                return save("disk_reserve", persist_manifest=True)
            current = previous.get(expected["id"])
            if current is None:
                current = {**expected, "status": "pending", "attempts": []}
                manifest["runs"].append(current)
                previous[current["id"]] = current
            directory = dataset / expected["relative_path"]
            if directory.exists():
                raise FileExistsError(f"Untracked run folder already exists: {directory}")
            current.update(status="running", started_at=now())
            checkpoint(current)
            save("running", current)
            directory.mkdir(parents=True, exist_ok=False)
            scene = scenes[current["layout_id"]]
            write_new_json(directory / "scene.json", scene)
            write_new_json(directory / "config.json", current["config"])
            # Intentionally omit cancel: STOP/PAUSE must never abort current FDS.
            result = runner.run(scene, current["config"], directory)
            if result["summary"].get("nonfinite_spatial_measurements") != 0:
                raise ValueError("Nonfinite gas observations require review before campaign inclusion")
            if abs(result["metrics"][-1]["time_s"] - current["config"]["duration_s"]) > 0.01:
                raise ValueError("Incomplete FDS trajectory")
            storage = compress_completed_run(directory, result)
            current.update(
                status="completed",
                completed_at=now(),
                **storage,
                wall_time_s=result["provenance"]["wall_time_s"],
            )
            verify_completed(dataset, current, expected)
            checkpoint(current)
            completed_this_session += 1
            summary = save("running", persist_manifest=completed_this_session % 100 == 0)
            print(
                json.dumps(
                    {
                        "id": current["id"],
                        "completed": summary["completed_runs"],
                        "total": summary["total_runs"],
                        "estimated_remaining_s": summary["estimated_remaining_s"],
                    }
                ),
                flush=True,
            )
            current = None
        freeze_index(dataset, manifest)
        return save("completed", persist_manifest=True)
    except (Exception, KeyboardInterrupt) as exc:
        if current is not None:
            current.update(status="failed", error=f"{type(exc).__name__}: {exc}", failed_at=now())
            checkpoint(current)
        save("failed", current, error=f"{type(exc).__name__}: {exc}", persist_manifest=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    parser.add_argument(
        "--fds",
        type=Path,
        default=Path("E:/IGNIS-Valley/tools/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe"),
    )
    parser.add_argument(
        "--limit",
        "--max-runs",
        dest="limit",
        type=int,
        help="Maximum NEW successful runs this invocation; full plan remains 20,000",
    )
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("The real spatial campaign must run on the authorized Windows compute workstation.")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be nonnegative")
    if not args.fds.is_file():
        parser.error("The configured FDS executable is missing.")
    settings = Settings(
        root=args.home / "app",
        runtime=args.home / "runtime",
        fds_executable=args.fds,
        omp_threads=4,
        disk_reserve_gb=RESERVE_GB,
    )
    dataset = args.home / "datasets" / DATASET_ID
    dataset.mkdir(parents=True, exist_ok=True)
    with ProcessLock(dataset / "generation.lock"):
        try:
            sources = {**compiler_hashes(settings.root), "fds_executable_sha256": file_sha(args.fds)}
            design = build_design(sources)
            plan, manifest = prepare_campaign(dataset, design)
        except (Exception, KeyboardInterrupt) as exc:
            # The plan/checkpoints remain untouched even when startup validation
            # fails. Only the mutable status advertises this invocation's error.
            path = dataset / "progress.json"
            try:
                progress = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                progress = {"dataset_id": DATASET_ID}
            progress.update(
                state="failed", updated_at=now(), last_error=f"Startup: {type(exc).__name__}: {exc}"
            )
            write_json(path, progress)
            raise
        summary = execute_campaign(settings, dataset, plan, manifest, limit=args.limit)
        print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
