"""Compiler/storage/lifecycle checks only; fixtures are never real FDS labels."""

from __future__ import annotations

import copy
import gzip
import importlib.util
import json
import zipfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from ignis.config import Settings
from ignis.engine import write_json
from ignis.locking import ProcessLock
from ignis.ml.spatial_dataset import (
    ARRAY_KEYS,
    GLOBAL_KEYS,
    compress_completed_run,
    extract_spatial_arrays,
    file_sha,
    iter_spatial_cases,
    load_spatial_case,
    position_grid_indices,
    read_spatial_index,
    write_spatial_npz,
)
from ignis.physics import compile_case
from ignis.provenance import canonical_sha


@pytest.fixture(scope="module")
def corpus():
    path = Path(__file__).resolve().parents[1] / "tools/remote/generate_spatial_corpus.py"
    spec = importlib.util.spec_from_file_location("spatial_corpus_contract_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def design(corpus):
    root = Path(__file__).resolve().parents[1]
    return corpus.build_design(corpus.compiler_hashes(root))


def test_design_is_reproducible_and_holds_out_whole_structural_families(corpus, design):
    assert len(design["layouts"]) == 1000 and len(design["runs"]) == 20000
    assert len({run["fingerprint"] for run in design["runs"]}) == 20000
    assert len({run["id"] for run in design["runs"]}) == 20000
    assert Counter(run["split"] for run in design["runs"]) == {
        "train": 12000,
        "validation": 4000,
        "test": 4000,
    }
    assert Counter(run["config"]["incident_type"] for run in design["runs"]) == dict.fromkeys(
        corpus.INCIDENT_TYPES, 4000
    )
    assert {run["split"] for run in design["runs"][:60]} == {"train", "validation", "test"}
    families = {}
    for layout in design["layouts"]:
        families.setdefault(layout["structural_family"], set()).add(layout["split"])
    assert len(families) == 10 and all(len(values) == 1 for values in families.values())
    assert canonical_sha(design) == canonical_sha(corpus.build_design(design["compiler_source_hashes"]))


def test_rooms_have_distinct_geometry_nonoverlapping_solids_vents_and_covered_sources(design):
    signatures, usage = set(), {}
    for run in design["runs"]:
        usage.setdefault(run["layout_id"], set()).add(run["config"]["component_id"])
    for layout in design["layouts"]:
        scene, objects = layout["scene"], layout["scene"]["objects"]
        assert 6 <= len(objects) <= 18 and 3 <= len(scene["components"]) <= 6
        assert usage[layout["layout_id"]] == {component["id"] for component in scene["components"]}
        boxes = [
            (
                np.asarray(obj["center_m"]) - np.asarray(obj["size_m"]) / 2,
                np.asarray(obj["center_m"]) + np.asarray(obj["size_m"]) / 2,
            )
            for obj in objects
        ]
        for index, (lo, hi) in enumerate(boxes):
            assert np.all(lo >= -1e-10) and np.all(hi <= scene["bounds_m"])
            for other_lo, other_hi in boxes[index + 1 :]:
                assert not np.all(np.minimum(hi, other_hi) - np.maximum(lo, other_lo) > 1e-8)
        assert {vent["role"] for vent in scene["vents"]} == {"inlet", "outlet"}
        assert all(sum(size == 0 for size in vent["size_m"]) == 1 for vent in scene["vents"])
        assert all(0.0008 <= obj["thermal_thickness_m"] <= 0.008 for obj in objects)
        assert all(obj["material_id"] in {"aluminium", "steel", "insulation"} for obj in objects)
        signatures.add(
            canonical_sha(
                {
                    "bounds": scene["bounds_m"],
                    "boxes": [{"center": obj["center_m"], "size": obj["size_m"]} for obj in objects],
                    "vents": scene["vents"],
                }
            )
        )
    assert len(signatures) == 1000


def test_twenty_scenarios_per_room_cover_conditions_and_paired_gravity(design):
    assert set(Counter(run["layout_id"] for run in design["runs"]).values()) == {20}
    for microg, earth in zip(design["runs"][::2], design["runs"][1::2]):
        config = microg["config"]
        assert config["gravity_g"] == 0.0001 and earth["config"]["gravity_g"] == 1
        assert {key: value for key, value in config.items() if key != "gravity_g"} == {
            key: value for key, value in earth["config"].items() if key != "gravity_g"
        }
        assert 500 <= config["ignition_power_w"] <= 3000 and 0.05 <= config["airflow_m_s"] <= 0.4
        assert 18 <= config["oxygen_percent"] <= 24 and config["duration_s"] == 30
        assert config["ignition_duration_s"] == (1 if config["incident_type"] == "arc" else 10)
        assert config["sample_shape"] == [12, 16, 8]


def test_preflight_compiles_every_room_once_and_checks_all_sources(corpus, design, tmp_path, monkeypatch):
    report = corpus.preflight(design, cache_dir=tmp_path / "preflight")
    assert report["unique_physical_layouts"] == 1000
    assert report["unique_source_geometries"] == sum(
        len(layout["scene"]["components"]) for layout in design["layouts"]
    )
    assert len({row["geometry_sha256"] for row in report["layouts"].values()}) == 1000
    assert all(12000 <= row["cell_count"] <= 60000 for row in report["layouts"].values())
    assert all(row["combustible_material_id"] in {"cellulose", "pmma"} for row in report["sources"])
    assert report["max_estimated_device_csv_bytes"] > 0

    def fail_compile(*args, **kwargs):
        pytest.fail("Validated geometry must reuse its checksum-protected preflight cache")

    monkeypatch.setattr(corpus, "compile_case", fail_compile)
    assert corpus.preflight(design, cache_dir=tmp_path / "preflight") == report


def small_design(design, count=2):
    return {
        **design,
        "layouts": copy.deepcopy(design["layouts"][:1]),
        "runs": copy.deepcopy(design["runs"][:count]),
        "expected_runs": count,
    }


def test_duplicate_physics_and_structural_leakage_are_rejected(corpus, design):
    duplicate = small_design(design, 1)
    duplicate["layouts"].append(
        {
            **copy.deepcopy(duplicate["layouts"][0]),
            "layout_id": "other",
            "split": "test",
            "structural_family": "held-out",
        }
    )
    duplicate["runs"].append(
        {
            **copy.deepcopy(duplicate["runs"][0]),
            "id": "other",
            "layout_id": "other",
            "split": "test",
            "structural_family": "held-out",
        }
    )
    with pytest.raises(ValueError, match="Physical layout duplicate"):
        corpus.preflight(duplicate)
    duplicate["runs"][-1]["structural_family"] = duplicate["runs"][0]["structural_family"]
    with pytest.raises(ValueError, match="Structural family crosses"):
        corpus.preflight(duplicate)


def fixture_result(manifest):
    sample = manifest["sampling"]
    mask = sample["valid_mask"]
    frames, metrics = [], []
    for t in [0.0, manifest["config"]["duration_s"]]:
        frames.append(
            {
                "time_s": t,
                "shape": sample["shape"],
                "bounds_m": sample["bounds_m"],
                "sample_positions_m": sample["positions_m"],
                "valid_mask": mask,
                "temperature_c": [20.0 + t / 10 if valid else None for valid in mask],
                "smoke_kg_m3": [t * 1e-9 if valid else None for valid in mask],
                "oxygen_percent": [21.0 - t / 100 if valid else None for valid in mask],
                "velocity_m_s": [value if valid else None for valid in mask for value in [0.1, 0.2, 0.3]],
            }
        )
        metrics.append(
            {
                "time_s": t,
                "temperature_max_c": 20.0 + t,
                "temperature_mean_c": 20.0 + t / 20,
                "smoke_mean_kg_m3": t * 1e-10,
                "heat_release_w": t * 10,
            }
        )
    return {
        "frames": frames,
        "metrics": metrics,
        "summary": {"nonfinite_spatial_measurements": 0},
        "provenance": {
            "origin": "simulation",
            "wall_time_s": 1.5,
            "compiler_version": manifest["compiler_version"],
            "material_model_version": manifest["material_model_version"],
            "scene_sha256": manifest["scene_sha256"],
            "config_sha256": manifest["config_sha256"],
            "input_sha256": manifest["deck_sha256"],
        },
    }


@pytest.fixture
def case(design, tmp_path):
    directory = tmp_path / "case"
    directory.mkdir()
    scene, config = copy.deepcopy(design["layouts"][0]["scene"]), copy.deepcopy(design["runs"][0]["config"])
    write_json(directory / "scene.json", scene)
    write_json(directory / "config.json", config)
    manifest = compile_case(scene, config, directory)
    result = fixture_result(manifest)
    write_json(directory / "result.json", result)
    (directory / "engine.log").write_bytes(b"fixture solver log\r\n")
    (directory / "ignis_devc.csv").write_bytes(b"fixture raw,0,1\r\n")
    return directory, manifest, result


def test_npz_preserves_nulls_time_positions_and_independent_globals(case):
    directory, manifest, result = case
    valid = manifest["sampling"]["valid_mask"]
    point = valid.index(True)
    result["frames"][1]["temperature_c"][point] = None
    write_spatial_npz(directory / "fields.npz", result, manifest)
    loaded = load_spatial_case(directory)
    assert set(ARRAY_KEYS) <= set(loaded)
    assert loaded["temperature_c"].shape == (2, 1536) and loaded["temperature_c"].dtype == np.float32
    assert np.isnan(loaded["temperature_c"][1, point]) and not loaded["field_mask"][1, point, 0]
    assert loaded["field_mask"][1, point, 1] and loaded["valid_mask"][1, point]
    assert np.isnan(loaded["temperature_c"][:, ~np.array(valid)]).all()
    assert np.array_equal(loaded["positions_m"], manifest["sampling"]["positions_m"])
    assert np.array_equal(loaded["time_s"], [0, 30]) and loaded["time_s"].dtype == np.float64
    assert tuple(loaded["global_keys"]) == GLOBAL_KEYS
    assert loaded["globals"][-1, 0] != np.nanmax(loaded["temperature_c"][-1])
    assert loaded["metadata"]["field_order"] == ["temperature_c", "smoke_kg_m3"]


def test_coordinate_mapping_preserves_nonuniform_and_shuffled_sampling_order():
    positions = np.stack(np.meshgrid([0.1, 0.3], [0.2, 0.7], [0.2, 0.9], indexing="ij"), axis=-1).reshape(
        -1, 3
    )
    order = [5, 2, 1, 7, 0, 3, 6, 4]
    mapped = position_grid_indices(positions[order], [2, 2, 2])
    assert np.array_equal(mapped, np.array(list(np.ndindex(2, 2, 2)))[order])
    with pytest.raises(ValueError, match="Duplicate"):
        position_grid_indices(np.vstack([positions[:-1], positions[0]]), [2, 2, 2])


@pytest.mark.parametrize(
    "key,value",
    [
        ("origin", "prediction"),
        ("compiler_version", "other"),
        ("material_model_version", "other"),
        ("scene_sha256", "other"),
        ("config_sha256", "other"),
        ("input_sha256", "other"),
    ],
)
def test_prediction_or_untraceable_values_cannot_become_training_labels(case, key, value):
    _, manifest, result = case
    result["provenance"][key] = value
    with pytest.raises(ValueError, match="traceable FDS"):
        extract_spatial_arrays(result, manifest)


@pytest.mark.parametrize(
    "field", ["timestamp", "asynchronous", "mask", "positions", "infinity", "incomplete"]
)
def test_extraction_rejects_invalid_observations(case, field):
    _, manifest, result = case
    result = copy.deepcopy(result)
    if field == "timestamp":
        result["frames"][0]["time_s"] = 1
    elif field == "asynchronous":
        result["metrics"][1]["time_s"] = float("nan")
    elif field == "mask":
        result["frames"][0]["valid_mask"][0] = not result["frames"][0]["valid_mask"][0]
    elif field == "positions":
        result["frames"][0]["sample_positions_m"][0][0] += 0.1
    elif field == "infinity":
        result["frames"][0]["temperature_c"][0] = float("inf")
    elif field == "incomplete":
        result["frames"][1]["time_s"] = result["metrics"][1]["time_s"] = 29
    with pytest.raises(ValueError):
        extract_spatial_arrays(result, manifest)


@pytest.mark.parametrize(
    "field", ["timestamps", "geometry_mask", "field_mask", "global_mask", "dtype", "solid_value"]
)
def test_npz_loader_revalidates_masks_timestamps_and_numeric_contract(case, field):
    directory, manifest, result = case
    arrays = extract_spatial_arrays(result, manifest)
    if field == "timestamps":
        arrays["time_s"][-1] = 29
    elif field == "geometry_mask":
        arrays["valid_mask"][0, 0] = ~arrays["valid_mask"][0, 0]
    elif field == "field_mask":
        arrays["field_mask"][0, 0, 0] = ~arrays["field_mask"][0, 0, 0]
    elif field == "global_mask":
        arrays["global_mask"][0, 0] = False
    elif field == "dtype":
        arrays["temperature_c"] = arrays["temperature_c"].astype(np.float64)
    elif field == "solid_value":
        point = manifest["sampling"]["valid_mask"].index(False)
        arrays["temperature_c"][0, point] = 20
    np.savez_compressed(directory / "fields.npz", **arrays)
    with pytest.raises(ValueError):
        load_spatial_case(directory)


def test_legacy_loader_checks_actual_input_config(case):
    directory, _, _ = case
    record = {"result_sha256": file_sha(directory / "result.json")}
    assert load_spatial_case(directory, record)["temperature_c"].shape == (2, 1536)
    config = json.loads((directory / "config.json").read_text())
    config["airflow_m_s"] += 0.01
    write_json(directory / "config.json", config)
    with pytest.raises(ValueError, match="configuration"):
        load_spatial_case(directory, record)


def test_indexed_npz_requires_a_matching_hash(case):
    directory, manifest, result = case
    write_spatial_npz(directory / "fields.npz", result, manifest)
    with pytest.raises(ValueError, match="missing its checksum"):
        load_spatial_case(directory, {"id": "case"})
    with pytest.raises(ValueError, match="NPZ checksum"):
        load_spatial_case(directory, {"npz_sha256": "wrong"})
    load_spatial_case(directory, {"npz_sha256": file_sha(directory / "fields.npz")})


def test_compression_preserves_all_six_channels_and_raw_bytes(case):
    directory, _, result = case
    original = (directory / "result.json").read_bytes()
    raw = {name: (directory / name).read_bytes() for name in ("engine.log", "ignis_devc.csv")}
    record = compress_completed_run(directory, result)
    assert gzip.decompress((directory / "result.json.gz").read_bytes()) == original
    with zipfile.ZipFile(directory / "raw-fds.zip") as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == raw
    assert not (directory / "result.json").exists()
    assert not any((directory / name).exists() for name in raw)
    assert len(record["file_hashes"]) == 7
    assert set(json.loads(original)["frames"][0]) >= {
        "temperature_c",
        "smoke_kg_m3",
        "oxygen_percent",
        "velocity_m_s",
    }
    assert record["stored_bytes"] == sum(path.stat().st_size for path in directory.iterdir())
    assert load_spatial_case(directory, record)["provenance"]["origin"] == "simulation"
    with pytest.raises(FileExistsError):
        compress_completed_run(directory, result)


def test_compression_failure_keeps_every_original(case, monkeypatch):
    directory, _, result = case
    originals = {path.name: path.read_bytes() for path in directory.iterdir()}
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: "engine.log")
    with pytest.raises(ValueError, match="archive failed"):
        compress_completed_run(directory, result)
    assert all((directory / name).read_bytes() == content for name, content in originals.items())


@pytest.fixture
def campaign(corpus, design, tmp_path):
    small = small_design(design)
    dataset = tmp_path / "datasets" / corpus.DATASET_ID
    dataset.mkdir(parents=True)
    plan, manifest = corpus.prepare_campaign(dataset, small)
    settings = Settings(
        root=tmp_path / "app",
        runtime=tmp_path / "runtime",
        fds_executable=None,
        omp_threads=4,
        disk_reserve_gb=20,
    )
    return settings, dataset, plan, manifest, small


class FakeRunner:
    """Temporary fixtures; never campaign labels or proof of FDS physics."""

    calls = []
    after_run = None
    fail = False

    def __init__(self, settings):
        self.settings = settings

    def run(self, scene, config, directory, **kwargs):
        assert "cancel" not in kwargs
        assert self.settings.omp_threads == 4 and self.settings.disk_reserve_gb == 20
        type(self).calls.append(directory.name)
        manifest = compile_case(scene, config, directory)
        (directory / "engine.log").write_text("fixture solver log retained", encoding="utf-8")
        if type(self).fail:
            raise RuntimeError("fixture interrupted attempt")
        result = fixture_result(manifest)
        write_json(directory / "result.json", result)
        if type(self).after_run:
            type(self).after_run(directory)
        return result


@pytest.fixture(autouse=True)
def reset_runner():
    FakeRunner.calls, FakeRunner.after_run, FakeRunner.fail = [], None, False


def test_limit_resume_and_frozen_index_reuse_verified_artifacts(corpus, campaign):
    settings, dataset, plan, manifest, design = campaign
    first = corpus.execute_campaign(settings, dataset, plan, manifest, limit=1, runner_factory=FakeRunner)
    assert first["state"] == "limited" and first["completed_runs"] == 1 and first["completed_layouts"] == 0
    completed = dataset / plan["runs"][0]["relative_path"] / "result.json.gz"
    digest, modified = file_sha(completed), completed.stat().st_mtime_ns
    plan, manifest = corpus.prepare_campaign(dataset, design)
    final = corpus.execute_campaign(settings, dataset, plan, manifest, runner_factory=FakeRunner)
    assert final["state"] == "completed" and final["completed_runs"] == 2 and final["completed_layouts"] == 1
    assert (
        len(FakeRunner.calls) == 2
        and file_sha(completed) == digest
        and completed.stat().st_mtime_ns == modified
    )
    assert final["mean_completed_run_s"] == 1.5 and final["estimated_remaining_s"] == 0
    assert final["by_split"]["train"] == {"planned": 2, "completed": 2, "failed": 0}
    assert file_sha(dataset / "index.json") == read_spatial_index(dataset)["frozen_index_sha256"]
    assert len(list(iter_spatial_cases(dataset))) == 2
    plan, manifest = corpus.prepare_campaign(dataset, design)
    assert (
        corpus.execute_campaign(settings, dataset, plan, manifest, runner_factory=FakeRunner)["state"]
        == "completed"
    )
    assert len(FakeRunner.calls) == 2


def test_partial_training_requires_opt_in_and_recovers_small_checkpoints(corpus, campaign):
    settings, dataset, plan, manifest, design = campaign
    initial = (dataset / "manifest.json").read_bytes()
    corpus.execute_campaign(settings, dataset, plan, manifest, limit=1, runner_factory=FakeRunner)
    (dataset / "manifest.json").write_bytes(initial)
    assert read_spatial_index(dataset)["runs"][0]["status"] == "completed"
    with pytest.raises(ValueError, match="incomplete"):
        list(iter_spatial_cases(dataset))
    assert len(list(iter_spatial_cases(dataset, allow_incomplete=True))) == 1
    assert not (dataset / "index.json").exists()
    _, recovered = corpus.prepare_campaign(dataset, design)
    assert recovered["active_elapsed_s"] >= json.loads((dataset / "progress.json").read_text())["elapsed_s"]


@pytest.mark.parametrize("status", ["running", "failed"])
def test_failed_or_interrupted_attempts_are_preserved_before_restart(corpus, campaign, status):
    settings, dataset, plan, manifest, design = campaign
    FakeRunner.fail = True
    with pytest.raises(RuntimeError, match="interrupted"):
        corpus.execute_campaign(settings, dataset, plan, manifest, runner_factory=FakeRunner)
    record = manifest["runs"][0]
    record["status"] = status
    write_json(dataset / "records" / (record["id"] + ".json"), record)
    FakeRunner.fail = False
    plan, manifest = corpus.prepare_campaign(dataset, design)
    result = corpus.execute_campaign(settings, dataset, plan, manifest, limit=1, runner_factory=FakeRunner)
    archive = dataset / "attempts" / record["id"] / "001"
    assert result["state"] == "limited"
    assert (archive / "engine.log").read_text() == "fixture solver log retained"
    assert json.loads((archive / "attempt-record.json").read_text())["status"] == status
    assert manifest["runs"][0]["attempts"] == [f"attempts/{record['id']}/001"]


def test_checksum_failure_prevents_new_solve_or_archive(corpus, campaign):
    settings, dataset, plan, manifest, _ = campaign
    corpus.execute_campaign(settings, dataset, plan, manifest, limit=1, runner_factory=FakeRunner)
    path = dataset / plan["runs"][0]["relative_path"] / "fields.npz"
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        corpus.execute_campaign(settings, dataset, plan, manifest, runner_factory=FakeRunner)
    assert len(FakeRunner.calls) == 1 and not (dataset / "attempts").exists()
    assert json.loads((dataset / "progress.json").read_text())["state"] == "failed"


def test_frozen_index_detects_tampered_per_run_record(corpus, campaign):
    settings, dataset, plan, manifest, _ = campaign
    corpus.execute_campaign(settings, dataset, plan, manifest, runner_factory=FakeRunner)
    path = dataset / "records" / (plan["runs"][0]["id"] + ".json")
    record = json.loads(path.read_text())
    record["split"] = "test"
    write_json(path, record)
    with pytest.raises(ValueError, match="frozen index"):
        read_spatial_index(dataset)


def test_stop_finishes_current_case_then_restart_continues(corpus, campaign):
    settings, dataset, plan, manifest, design = campaign
    FakeRunner.after_run = lambda directory: (dataset / "STOP").touch()
    result = corpus.execute_campaign(settings, dataset, plan, manifest, runner_factory=FakeRunner)
    assert result["state"] == "stopped" and result["completed_runs"] == 1
    assert manifest["runs"][0]["status"] == "completed"
    FakeRunner.after_run = None
    (dataset / "STOP").unlink()
    plan, manifest = corpus.prepare_campaign(dataset, design)
    assert (
        corpus.execute_campaign(settings, dataset, plan, manifest, runner_factory=FakeRunner)["state"]
        == "completed"
    )


def test_pause_waits_between_runs_and_releases_compute(corpus, campaign, monkeypatch):
    settings, dataset, plan, manifest, _ = campaign
    FakeRunner.after_run = lambda directory: (dataset / "PAUSE").touch()
    waits = []

    def unpause(seconds):
        assert seconds == 2
        assert json.loads((dataset / "progress.json").read_text())["state"] == "paused"
        with ProcessLock(settings.runtime / "compute.lock"):
            waits.append(seconds)
        (dataset / "PAUSE").unlink()

    monkeypatch.setattr(corpus.time, "sleep", unpause)
    result = corpus.execute_campaign(settings, dataset, plan, manifest, runner_factory=FakeRunner)
    assert waits == [2] and result["completed_runs"] == 2


def test_stop_can_end_pause_without_starting_solver(corpus, campaign, monkeypatch):
    settings, dataset, plan, manifest, _ = campaign
    (dataset / "PAUSE").touch()
    monkeypatch.setattr(corpus.time, "sleep", lambda seconds: (dataset / "STOP").touch())
    result = corpus.execute_campaign(settings, dataset, plan, manifest, runner_factory=FakeRunner)
    assert result["state"] == "stopped" and not FakeRunner.calls


def test_disk_reserve_protects_twenty_gib_before_next_solve(corpus, campaign, monkeypatch):
    settings, dataset, plan, manifest, _ = campaign
    monkeypatch.setattr(corpus.shutil, "disk_usage", lambda path: SimpleNamespace(free=19 * 1024**3))
    result = corpus.execute_campaign(settings, dataset, plan, manifest, runner_factory=FakeRunner)
    assert result["state"] == "disk_reserve" and result["disk_reserve_gb"] == 20 and not FakeRunner.calls


def test_zero_limit_verifies_without_running(corpus, campaign):
    settings, dataset, plan, manifest, _ = campaign
    result = corpus.execute_campaign(settings, dataset, plan, manifest, limit=0, runner_factory=FakeRunner)
    assert result["state"] == "limited" and result["completed_runs"] == 0 and not FakeRunner.calls


def test_changed_plan_or_unknown_artifacts_are_not_overwritten(corpus, campaign, tmp_path):
    _, dataset, _, _, design = campaign
    original = (dataset / "plan.json").read_bytes()
    design["runs"][0]["config"]["ignition_power_w"] += 1
    with pytest.raises(ValueError, match="differs"):
        corpus.prepare_campaign(dataset, design)
    assert (dataset / "plan.json").read_bytes() == original
    unknown = tmp_path / "unknown"
    unknown.mkdir()
    (unknown / "precious.txt").write_text("preserve")
    with pytest.raises(FileExistsError, match="overwritten"):
        corpus.prepare_campaign(unknown, design)
    assert (unknown / "precious.txt").read_text() == "preserve"


def test_immutable_json_is_atomically_published_and_never_replaced(corpus, tmp_path, monkeypatch):
    path = tmp_path / "plan.json"

    def interrupted(*args):
        raise OSError("fixture publication interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(corpus.os, "rename" if corpus.os.name == "nt" else "link", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            corpus.write_new_json(path, {"complete": True})
    assert not path.exists()
    leftovers = list(tmp_path.glob(".plan.json.*.tmp"))
    assert len(leftovers) == 1 and json.loads(leftovers[0].read_text()) == {"complete": True}
    corpus.write_new_json(path, {"complete": True})
    with pytest.raises(FileExistsError):
        corpus.write_new_json(path, {"complete": False})
    assert json.loads(path.read_text()) == {"complete": True}


def test_interrupted_temporary_plan_does_not_block_preflight_restart(corpus, design, tmp_path):
    (tmp_path / ".plan.json.interrupted.tmp").write_text('{"truncated":')
    plan, _ = corpus.prepare_campaign(tmp_path, small_design(design))
    assert plan["expected_runs"] == 2
    assert (tmp_path / ".plan.json.interrupted.tmp").read_text() == '{"truncated":'


def test_corrupted_preflight_cache_is_rejected(corpus, design, tmp_path):
    small = small_design(design)
    corpus.preflight(small, cache_dir=tmp_path)
    path = tmp_path / (small["layouts"][0]["layout_id"] + ".json")
    entry = json.loads(path.read_text())
    entry["cell_count"] = 1
    write_json(path, entry)
    with pytest.raises(ValueError, match="output checksum"):
        corpus.preflight(small, cache_dir=tmp_path)


def test_checkpointing_does_not_rewrite_the_whole_manifest_each_run(corpus, campaign, monkeypatch):
    settings, dataset, plan, manifest, _ = campaign
    writes = []
    original = corpus.write_json

    def observe(path, data):
        writes.append(path)
        original(path, data)

    monkeypatch.setattr(corpus, "write_json", observe)
    corpus.execute_campaign(settings, dataset, plan, manifest, runner_factory=FakeRunner)
    assert writes.count(dataset / "manifest.json") == 1  # Final snapshot; periodic snapshot every 100.
    assert len([path for path in writes if path.parent == dataset / "records"]) == 4


def test_actual_deck_tampering_is_rejected_even_without_index_record(case):
    directory, _, _ = case
    with (directory / "ignis.fds").open("a") as stream:
        stream.write("\nchanged")
    with pytest.raises(ValueError, match="FDS input checksum"):
        load_spatial_case(directory)


def test_disk_and_in_memory_result_must_match_before_compression(case):
    directory, _, result = case
    result["metrics"][-1]["temperature_max_c"] += 1
    with pytest.raises(ValueError, match="differs from the saved"):
        compress_completed_run(directory, result)
    assert (directory / "result.json").exists() and (directory / "engine.log").exists()
    assert not (directory / "fields.npz").exists()


@pytest.mark.parametrize("key", ["layout_id", "structural_family"])
def test_loader_rejects_partition_leakage_before_loading_targets(corpus, campaign, key):
    settings, dataset, plan, manifest, _ = campaign
    corpus.execute_campaign(settings, dataset, plan, manifest, limit=1, runner_factory=FakeRunner)
    record = copy.deepcopy(manifest["runs"][0])
    record.update(id="other", split="test")
    if key == "structural_family":
        record["layout_id"] = "other-layout"
    write_json(dataset / "records" / "other.json", record)
    with pytest.raises(ValueError, match="leakage"):
        list(iter_spatial_cases(dataset, allow_incomplete=True))
