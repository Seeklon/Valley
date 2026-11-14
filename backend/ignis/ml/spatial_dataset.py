"""Per-case spatial FDS storage and lazy loading, including the legacy pilot.

Coordinates and timestamps come from the solver's sampling contract. Missing
values remain NaN with explicit masks; no flame, velocity or oxygen target is
constructed here. Compression preserves the complete original solver result.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import numpy as np

from ignis.physics.compiler import _validate_config
from ignis.physics.materials import MODEL_VERSION
from ignis.provenance import canonical_sha

SCHEMA_VERSION = "ignis-spatial-npz-1"
FIELD_KEYS = ("temperature_c", "smoke_kg_m3")
GLOBAL_KEYS = ("temperature_max_c", "temperature_mean_c", "smoke_mean_kg_m3", "heat_release_w")
ARRAY_KEYS = (
    "time_s",
    *FIELD_KEYS,
    "valid_mask",
    "field_mask",
    "positions_m",
    "bounds_m",
    "shape",
    "globals",
    "global_mask",
    "global_keys",
    "metadata_json",
)


def validate_provenance(provenance: dict, manifest: dict) -> None:
    expected = {
        "origin": "simulation",
        "compiler_version": manifest["compiler_version"],
        "material_model_version": manifest["material_model_version"],
        "scene_sha256": manifest["scene_sha256"],
        "config_sha256": manifest["config_sha256"],
        "input_sha256": manifest["deck_sha256"],
    }
    if (
        manifest["compiler_version"] not in {"ignis-fds-2", "ignis-incidents-1"}
        or manifest["material_model_version"] != MODEL_VERSION
        or any(provenance.get(key) != value for key, value in expected.items())
    ):
        raise ValueError("Only traceable FDS simulation observations may supply spatial targets")


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def position_grid_indices(positions_m, shape) -> np.ndarray:
    """Map authoritative coordinates to a grid, without assuming point ordering."""
    positions = np.asarray(positions_m, dtype=float)
    if len(shape) != 3 or any(
        isinstance(value, (bool, np.bool_)) or int(value) != value or value <= 0 for value in shape
    ):
        raise ValueError("Invalid sampling shape")
    shape = tuple(int(value) for value in shape)
    if positions.shape != (int(np.prod(shape)), 3) or not np.isfinite(positions).all():
        raise ValueError("Invalid sampling positions")
    indices = np.empty(positions.shape, dtype=np.int32)
    for axis, count in enumerate(shape):
        values, inverse = np.unique(positions[:, axis], return_inverse=True)
        if len(values) != count:
            raise ValueError("Sampling coordinates do not form the declared structured grid")
        indices[:, axis] = inverse
    if len(np.unique(indices, axis=0)) != len(positions):
        raise ValueError("Duplicate sampling grid positions")
    return indices


def extract_spatial_arrays(result: dict, manifest: dict) -> dict[str, np.ndarray]:
    validate_provenance(result.get("provenance", {}), manifest)
    sample = manifest["sampling"]
    shape = np.asarray(sample["shape"], dtype=np.int32)
    positions = np.asarray(sample["positions_m"], dtype=np.float64)
    bounds = np.asarray(sample["bounds_m"], dtype=np.float64)
    position_grid_indices(positions, shape)
    points = int(np.prod(shape))
    if bounds.shape != (3,) or not np.isfinite(bounds).all() or np.any(bounds <= 0):
        raise ValueError("Invalid compartment bounds")
    frames, metrics = result["frames"], result["metrics"]
    if not frames or len(frames) != len(metrics):
        raise ValueError("Spatial and global observations must be synchronous")
    times, masks, fields, globals_ = [], [], {key: [] for key in FIELD_KEYS}, []
    expected_mask = np.asarray(sample["valid_mask"], dtype=bool)
    for frame, metric in zip(frames, metrics):
        t = float(frame["time_s"])
        metric_time = float(metric["time_s"])
        if (
            not np.isfinite(t)
            or not np.isfinite(metric_time)
            or t < 0
            or (times and t <= times[-1])
            or abs(t - metric_time) > 1e-7
        ):
            raise ValueError("Invalid or asynchronous timestamps")
        mask = np.asarray(frame["valid_mask"], dtype=bool)
        if (
            mask.shape != (points,)
            or not np.array_equal(mask, expected_mask)
            or not np.array_equal(frame["shape"], shape)
            or not np.allclose(frame["sample_positions_m"], positions, rtol=0, atol=1e-9)
            or not np.allclose(frame["bounds_m"], bounds, rtol=0, atol=1e-9)
        ):
            raise ValueError("Frame coordinates or masks differ from compiled sampling")
        for key in FIELD_KEYS:
            values = np.asarray(frame[key], dtype=np.float32)
            if values.shape != (points,) or np.isinf(values).any():
                raise ValueError(f"Invalid {key} measurements")
            # A solid has no gas observation, even if a producer used a placeholder.
            values[~mask] = np.nan
            fields[key].append(values)
        times.append(t)
        masks.append(mask)
        globals_.append([metric.get(key) for key in GLOBAL_KEYS])
    if times[0] != 0 or abs(times[-1] - manifest["config"]["duration_s"]) > 0.01:
        raise ValueError("Incomplete spatial trajectory")
    mask = np.asarray(masks, dtype=bool)
    values = {key: np.asarray(rows, dtype=np.float32) for key, rows in fields.items()}
    scalar = np.asarray(globals_, dtype=np.float32)
    if np.isinf(scalar).any():
        raise ValueError("Infinite FDS global observation")
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "provenance": result.get("provenance", {}),
        "sample_order": sample.get("order", "authoritative positions_m order"),
        "global_basis": "independent FDS full-domain statistics, not summaries of sampled gas",
        "field_order": list(FIELD_KEYS),
        "global_order": list(GLOBAL_KEYS),
        "scene_sha256": manifest.get("scene_sha256"),
        "config_sha256": manifest.get("config_sha256"),
    }
    arrays = {
        "time_s": np.asarray(times, dtype=np.float64),
        **values,
        "valid_mask": mask,
        "field_mask": mask[:, :, None] & np.isfinite(np.stack([values[key] for key in FIELD_KEYS], axis=-1)),
        "positions_m": positions,
        "bounds_m": bounds,
        "shape": shape,
        "globals": scalar,
        "global_mask": np.isfinite(scalar),
        "global_keys": np.asarray(GLOBAL_KEYS, dtype="U32"),
        "metadata_json": np.asarray(json.dumps(metadata, ensure_ascii=False, allow_nan=False)),
    }
    return {key: np.ascontiguousarray(value) if value.ndim else value for key, value in arrays.items()}


def write_spatial_npz(path: Path, result: dict, manifest: dict) -> dict:
    arrays = extract_spatial_arrays(result, manifest)
    with Path(path).open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    return {
        "path": Path(path).name,
        "sha256": file_sha(path),
        "schema_version": SCHEMA_VERSION,
        "frames": len(arrays["time_s"]),
        "points": len(arrays["positions_m"]),
    }


def compress_completed_run(directory: Path, result: dict) -> dict:
    """Verify compressed copies before removing only their original raw files."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    destinations = [directory / name for name in ("fields.npz", "result.json.gz", "raw-fds.zip")]
    if any(path.exists() for path in destinations):
        raise FileExistsError("Compressed case artifacts already exist; preserve the attempt")
    if canonical_sha(result) != canonical_sha(_read_result(directory / "result.json")):
        raise ValueError("In-memory result differs from the saved solver result")
    npz = write_spatial_npz(destinations[0], result, manifest)
    original_sha = file_sha(directory / "result.json")
    with destinations[1].open("xb") as target, (directory / "result.json").open("rb") as source:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
            shutil.copyfileobj(source, compressed)
    digest = hashlib.sha256()
    with gzip.open(destinations[1], "rb") as restored:
        for block in iter(lambda: restored.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != original_sha:
        raise ValueError("Compressed result failed lossless verification")
    retained = {
        "scene.json",
        "config.json",
        "manifest.json",
        "ignis.fds",
        "result.json",
        "fields.npz",
        "result.json.gz",
        "raw-fds.zip",
    }
    raw = sorted(path for path in directory.iterdir() if path.name not in retained)
    if any(not path.is_file() or path.is_symlink() for path in raw):
        raise ValueError("Unexpected raw FDS directory/symlink; preserve case for inspection")
    raw_hashes = {path.name: file_sha(path) for path in raw}
    with zipfile.ZipFile(destinations[2], "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in raw:
            archive.write(path, arcname=path.name)
    with zipfile.ZipFile(destinations[2]) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != set(raw_hashes):
            raise ValueError("Raw FDS archive failed verification")
        for name, expected in raw_hashes.items():
            digest = hashlib.sha256()
            with archive.open(name) as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError("Archived FDS output checksum mismatch")
    with np.load(destinations[0], allow_pickle=False) as packed:
        for key in ARRAY_KEYS:
            packed[key]  # Read each member so ZIP CRC checks actually run.
    # Every original below has a verified complete compressed copy at this point.
    for path in raw:
        path.unlink()
    (directory / "result.json").unlink()
    names = (
        "scene.json",
        "config.json",
        "manifest.json",
        "ignis.fds",
        "fields.npz",
        "result.json.gz",
        "raw-fds.zip",
    )
    return {
        "npz_file": "fields.npz",
        "npz_sha256": npz["sha256"],
        "result_file": "result.json.gz",
        "result_sha256": file_sha(destinations[1]),
        "result_uncompressed_sha256": original_sha,
        "raw_archive_file": "raw-fds.zip",
        "raw_members_sha256": raw_hashes,
        "file_hashes": {name: file_sha(directory / name) for name in names},
        "stored_bytes": sum((directory / name).stat().st_size for name in names),
        "spatial_schema": SCHEMA_VERSION,
    }


def _read_result(path: Path) -> dict:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def load_spatial_case(directory: Path, record: dict | None = None) -> dict:
    """Load one case only. A supplied index record makes hash checks mandatory."""
    directory = Path(directory)
    record = record or {}
    for name, expected in record.get("file_hashes", {}).items():
        if Path(name).name != name or file_sha(directory / name) != expected:
            raise ValueError("Spatial case artifact checksum mismatch")
    scene = json.loads((directory / "scene.json").read_text(encoding="utf-8"))
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if record.get("scene_sha256", canonical_sha(scene)) != canonical_sha(scene):
        raise ValueError("Spatial scene checksum mismatch")
    if "config" in record and canonical_sha(record["config"]) != canonical_sha(config):
        raise ValueError("Spatial config differs from index")
    if (
        canonical_sha(_validate_config(scene, config)) != manifest["config_sha256"]
        or canonical_sha(manifest["config"]) != manifest["config_sha256"]
    ):
        raise ValueError("Spatial compiled configuration differs from saved inputs")
    npz_name = record.get("npz_file", "fields.npz")
    if Path(npz_name).name != npz_name:
        raise ValueError("Invalid NPZ artifact path")
    npz_path = directory / npz_name
    if npz_path.exists():
        expected_npz = record.get("npz_sha256") or record.get("file_hashes", {}).get(npz_name)
        if record and not expected_npz:
            raise ValueError("Indexed spatial NPZ is missing its checksum")
        if expected_npz and file_sha(npz_path) != expected_npz:
            raise ValueError("Spatial NPZ checksum mismatch")
        with np.load(npz_path, allow_pickle=False) as packed:
            arrays = {key: packed[key] for key in ARRAY_KEYS}
    else:
        result_name = record.get("result_file", "result.json")
        if Path(result_name).name != result_name:
            raise ValueError("Invalid result artifact path")
        path = directory / result_name
        expected_result = record.get("result_sha256") or record.get("file_hashes", {}).get(result_name)
        if record and not expected_result:
            raise ValueError("Indexed spatial result is missing its checksum")
        if expected_result and file_sha(path) != expected_result:
            raise ValueError("Spatial result checksum mismatch")
        arrays = extract_spatial_arrays(_read_result(path), manifest)
    for name_key, hash_key in (("npz_file", "npz_sha256"), ("result_file", "result_sha256")):
        name = record.get(name_key)
        if name and (
            Path(name).name != name
            or (
                hash_key in record
                and name in record.get("file_hashes", {})
                and record[hash_key] != record["file_hashes"][name]
            )
        ):
            raise ValueError("Inconsistent spatial artifact references")
    metadata = json.loads(str(arrays["metadata_json"]))
    if metadata.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Incompatible spatial NPZ schema")
    if metadata.get("scene_sha256") != manifest["scene_sha256"] or manifest["scene_sha256"] != canonical_sha(
        scene
    ):
        raise ValueError("Spatial provenance scene mismatch")
    if metadata.get("config_sha256") != canonical_sha(manifest["config"]):
        raise ValueError("Spatial provenance config mismatch")
    validate_provenance(metadata.get("provenance", {}), manifest)
    deck = directory / "ignis.fds"
    if file_sha(deck) != manifest["deck_sha256"]:
        raise ValueError("Spatial FDS input checksum mismatch")
    if not np.array_equal(arrays["positions_m"], manifest["sampling"]["positions_m"]):
        raise ValueError("NPZ positions differ from authoritative compiled sampling")
    grids = position_grid_indices(arrays["positions_m"], arrays["shape"])
    frames, points = len(arrays["time_s"]), len(grids)
    dtypes = {
        "time_s": np.float64,
        "positions_m": np.float64,
        "bounds_m": np.float64,
        "shape": np.int32,
        "valid_mask": np.bool_,
        "field_mask": np.bool_,
        "global_mask": np.bool_,
        "globals": np.float32,
        **{key: np.float32 for key in FIELD_KEYS},
    }
    if any(arrays[key].dtype != dtype for key, dtype in dtypes.items()):
        raise ValueError("Invalid spatial array dtypes")
    if (
        arrays["time_s"].shape != (frames,)
        or any(arrays[key].shape != (frames, points) for key in (*FIELD_KEYS, "valid_mask"))
        or arrays["field_mask"].shape != (frames, points, 2)
        or arrays["globals"].shape != (frames, 4)
        or arrays["global_mask"].shape != (frames, 4)
        or tuple(arrays["global_keys"]) != GLOBAL_KEYS
    ):
        raise ValueError("Invalid spatial array dimensions")
    times = arrays["time_s"]
    if (
        not frames
        or not np.isfinite(times).all()
        or times[0] != 0
        or np.any(np.diff(times) <= 0)
        or abs(times[-1] - manifest["config"]["duration_s"]) > 0.01
    ):
        raise ValueError("Incomplete or unordered spatial trajectory")
    geometry_mask = np.broadcast_to(
        np.asarray(manifest["sampling"]["valid_mask"], dtype=bool), (frames, points)
    )
    if (
        not np.array_equal(arrays["valid_mask"], geometry_mask)
        or not np.array_equal(arrays["shape"], manifest["sampling"]["shape"])
        or not np.array_equal(arrays["bounds_m"], manifest["sampling"]["bounds_m"])
        or any(np.isinf(arrays[key]).any() for key in (*FIELD_KEYS, "globals"))
    ):
        raise ValueError("Spatial NPZ geometry or finite-value contract mismatch")
    if any(np.isfinite(arrays[key][~geometry_mask]).any() for key in FIELD_KEYS):
        raise ValueError("Solid sampling cells cannot carry gas targets")
    expected = arrays["valid_mask"][:, :, None] & np.isfinite(
        np.stack([arrays[key] for key in FIELD_KEYS], axis=-1)
    )
    if not np.array_equal(expected, arrays["field_mask"]) or not np.array_equal(
        np.isfinite(arrays["globals"]), arrays["global_mask"]
    ):
        raise ValueError("Spatial observation masks do not match finite measurements")
    return {
        **arrays,
        "grid_indices": grids,
        "scene": scene,
        "config": config,
        "manifest": manifest,
        "metadata": metadata,
        "provenance": metadata.get("provenance", {}),
        "record": record,
    }


def read_spatial_index(dataset: Path) -> dict:
    """Merge small atomic per-run checkpoints into an in-memory metadata snapshot."""
    dataset = Path(dataset).resolve()
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    records = {record["id"]: record for record in manifest["runs"]}
    if len(records) != len(manifest["runs"]):
        raise ValueError("Duplicate spatial run in index")
    directory_name = manifest.get("record_directory")
    if directory_name:
        if Path(directory_name).name != directory_name:
            raise ValueError("Invalid record directory")
        for path in sorted((dataset / directory_name).glob("*.json")):
            if not path.resolve().is_relative_to(dataset):
                raise ValueError("Spatial record path leaves dataset")
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["id"] != path.stem:
                raise ValueError("Spatial checkpoint identity mismatch")
            records[record["id"]] = record
    manifest["runs"] = list(records.values())
    if manifest.get("frozen_index_sha256"):
        path = dataset / "index.json"
        if file_sha(path) != manifest["frozen_index_sha256"]:
            raise ValueError("Frozen spatial index checksum mismatch")
        frozen = json.loads(path.read_text(encoding="utf-8"))
        for key in (
            "dataset_id",
            "schema_version",
            "expected_runs",
            "compiler_version",
            "material_model_version",
            "plan_sha256",
            "design_sha256",
        ):
            if frozen.get(key) != manifest.get(key):
                raise ValueError("Frozen spatial index identity mismatch")
        if canonical_sha(sorted(frozen["runs"], key=lambda row: row["id"])) != canonical_sha(
            sorted(manifest["runs"], key=lambda row: row["id"])
        ):
            raise ValueError("Spatial checkpoints differ from frozen index")
    return manifest


def iter_spatial_cases(dataset: Path, split: str | None = None, *, allow_incomplete: bool = False):
    """Yield one case at a time from a fixed index snapshot; never concatenate labels."""
    dataset = Path(dataset).resolve()
    manifest = read_spatial_index(dataset)
    records = manifest["runs"]
    if not allow_incomplete and (
        len(records) != manifest.get("expected_runs", len(records))
        or any(record.get("status", "completed") != "completed" for record in records)
    ):
        raise ValueError("Spatial campaign incomplete; opt in explicitly to a partial training snapshot")
    groups, structures = {}, {}
    for record in records:
        group = record.get("layout_id", record.get("family_id"))
        if not group or record["split"] not in {"train", "validation", "test"}:
            raise ValueError("Every spatial case requires a grouping key and an explicit split")
        if group in groups and groups[group] != record["split"]:
            raise ValueError("Spatial layout leakage across partitions")
        groups[group] = record["split"]
        structure = record.get("structural_family")
        if structure:
            if structure in structures and structures[structure] != record["split"]:
                raise ValueError("Structural-family leakage across partitions")
            structures[structure] = record["split"]
    for record in records:
        if record.get("status", "completed") != "completed" or (
            split is not None and record["split"] != split
        ):
            continue
        folder = (dataset / record["relative_path"]).resolve()
        if not folder.is_relative_to(dataset):
            raise ValueError("Spatial case path leaves dataset")
        yield load_spatial_case(folder, record)
