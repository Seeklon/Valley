"""Tiny CPU contract checks only; these are not training/accuracy experiments."""
# ruff: noqa: E402 -- optional torch must be checked before importing its consumers.

from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from ignis.ml.incidents import COMPILER_VERSION, INCIDENT_TYPES, file_sha
from ignis.ml.spatial_network import (
    CHANNELS,
    FEATURE_VERSION,
    STATIC_CHANNELS,
    SpatialSurrogate,
    SpatialUNet,
    architecture,
    checkpoint,
    geometry_channels,
    input_tensor,
    masked_loss,
    sampling_grid,
)
from ignis.physics import compile_case
from ignis.physics.materials import MODEL_VERSION
from ignis.physics.verification import verification_scene
from ignis.provenance import canonical_sha


@pytest.fixture(scope="module", autouse=True)
def limit_test_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def training():
    path = Path(__file__).parents[1] / "tools/remote/train_spatial.py"
    spec = importlib.util.spec_from_file_location("train_spatial_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_case(directory, *, family="overheating", thickness=0.005, shape=(8, 10, 4)):
    directory.mkdir(parents=True)
    scene = verification_scene()
    scene["objects"][0]["thermal_thickness_m"] = thickness
    scene["components"] = [{"id": "heater", "object_id": "sample", "position_m": [1.0, 1.0, 0.4], "face": 3}]
    config = {
        "source_model": "coupled_combustion",
        "ignition_kind": "thermal",
        "incident_type": family,
        "component_id": "heater",
        "gravity_g": 0.0001,
        "ignition_power_w": 1000,
        "ignition_duration_s": 1 if family == "arc" else 10,
        "duration_s": 30,
        "airflow_m_s": 0.2,
        "oxygen_percent": 21,
        "mesh_cell_m": 0.2,
        "sample_shape": list(shape),
        "material_id": "cellulose",
    }
    manifest = compile_case(scene, config, directory)
    config = manifest["config"]
    frames, metrics = [], []
    sample = manifest["sampling"]
    for t in (0.0, 0.7, 30.0):
        frames.append(
            {
                "time_s": t,
                "shape": sample["shape"],
                "bounds_m": sample["bounds_m"],
                "sample_positions_m": sample["positions_m"],
                "valid_mask": sample["valid_mask"],
                "temperature_c": [20 + 2 * t if valid else None for valid in sample["valid_mask"]],
                "smoke_kg_m3": [t * 1e-7 if valid else None for valid in sample["valid_mask"]],
            }
        )
        metrics.append(
            {
                "time_s": t,
                "temperature_max_c": 20 + 3 * t,
                "temperature_mean_c": 20 + t,
                "smoke_mean_kg_m3": t * 1e-8,
                "heat_release_w": t * 10,
            }
        )
    result = {
        "frames": frames,
        "metrics": metrics,
        "provenance": {
            "origin": "simulation",
            "compiler_version": COMPILER_VERSION,
            "material_model_version": MODEL_VERSION,
            "scene_sha256": canonical_sha(scene),
            "config_sha256": canonical_sha(config),
            "input_sha256": manifest["deck_sha256"],
        },
    }
    for filename, value in (("scene.json", scene), ("config.json", config), ("result.json", result)):
        (directory / filename).write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    return scene, config, manifest, result


@pytest.fixture
def case(tmp_path):
    return make_case(tmp_path / "case")


@pytest.fixture
def dataset(tmp_path):
    directory = tmp_path / "dataset"
    records = []
    for layout, split in enumerate(("train", "train", "validation", "test")):
        for family in INCIDENT_TYPES:
            name = f"layout-{layout}-{family}"
            folder = directory / "runs" / name
            scene, config, _, _ = make_case(folder, family=family, thickness=0.004 + layout * 0.001)
            records.append(
                {
                    "id": name,
                    "layout_id": f"layout-{layout}",
                    "scene_id": "fixture",
                    "relative_path": "runs/" + name,
                    "split": split,
                    "status": "completed",
                    "scene_sha256": canonical_sha(scene),
                    "config": config,
                    "result_sha256": file_sha(folder / "result.json"),
                    "fingerprint": canonical_sha(
                        {"scene": scene, "config": config, "compiler": COMPILER_VERSION}
                    ),
                }
            )
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": "synthetic-contract-fixture",
                "compiler_version": COMPILER_VERSION,
                "expected_runs": len(records),
                "runs": records,
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_exact_coordinates_materials_source_and_airflow_channels(case):
    _, config, manifest, _ = case
    static = geometry_channels(manifest)
    assert static.shape == (len(STATIC_CHANNELS), 8, 10, 4)
    assert static[STATIC_CHANNELS.index("source_patch_fraction")].sum() > 0
    assert static[STATIC_CHANNELS.index("solid_volume_fraction")].sum() > 0
    modified = copy.deepcopy(manifest)
    modified["objects"][0]["thermal_thickness_m"] *= 2
    assert not np.array_equal(static, geometry_channels(modified))
    original = input_tensor(static, config, manifest, 0.7)
    assert original.shape == (len(CHANNELS), 8, 10, 4)
    assert not np.array_equal(original, input_tensor(static, config, manifest, 5))
    permuted = copy.deepcopy(manifest)
    permuted["sampling"]["positions_m"][0:2] = reversed(permuted["sampling"]["positions_m"][0:2])
    with pytest.raises(ValueError, match="Cartesian"):
        sampling_grid(permuted)


def test_fds_boundary_flow_sign_uses_plane_not_annotation_normal(case):
    _, _, manifest, _ = case
    manifest = copy.deepcopy(manifest)
    manifest["vents"] = [
        {
            "bounds_m": [0.4, 1.6, 0.0, 0.0, 0.4, 1.6],
            "normal": [0, -1, 0],
            "role": "inlet",
            "area_m2": 1.44,
            "volume_flow_m3_s": -0.288,
        },
        {
            "bounds_m": [0.4, 1.6, 2.0, 2.0, 0.4, 1.6],
            "normal": [0, -1, 0],
            "role": "outlet",
            "area_m2": 1.44,
            "volume_flow_m3_s": 0.288,
        },
    ]
    channels = geometry_channels(manifest)
    vy = channels[STATIC_CHANNELS.index("boundary_v_scaled")]
    assert vy[:, 0, :].max() > 0 and vy[:, -1, :].max() > 0
    assert vy.min() == 0
    assert not channels[STATIC_CHANNELS.index("boundary_u_scaled")].any()


@pytest.mark.parametrize("shape", [(8, 10, 4), (12, 16, 8)])
def test_network_preserves_grid_shape_and_initial_ambient_head(shape):
    network = SpatialUNet()
    fields, globals_ = network(torch.zeros(2, len(CHANNELS), *shape))
    assert fields.shape == (2, 2, *shape) and globals_.shape == (2, 4)
    assert torch.count_nonzero(fields) == 0 and torch.count_nonzero(globals_) == 0
    assert 500000 < sum(p.numel() for p in network.parameters()) < 2000000


def test_masked_loss_excludes_nan_and_gives_active_cells_bounded_weight():
    predictions = torch.tensor([[0.0, 0.0, 0.0]], requires_grad=True)
    target = torch.tensor([[1.0, 5.0, float("nan")]])
    mask = torch.tensor([[True, True, False]])
    weights = torch.tensor([[1.0, 5.0, 5.0]])
    loss = masked_loss(predictions, target, mask, weights)
    assert loss.item() == pytest.approx((0.5 + 5 * 4.5) / 6)
    loss.backward()
    assert torch.isfinite(predictions.grad).all() and predictions.grad[0, 2] == 0
    with pytest.raises(ValueError, match="observed"):
        masked_loss(predictions, target, torch.zeros_like(mask))


def test_lazy_store_verifies_splits_and_bounds_memory(training, dataset):
    store = training.CaseStore(dataset)
    store.verify()
    assert store.shape == (8, 10, 4) and len(store.records) == 20
    for i in range(10):
        store.get(i)
        assert len(store.cache) <= 2
    assert store.snapshot_sha == canonical_sha(store.snapshot)
    plan = training.frame_plan(store, np.random.default_rng(4), 100)
    assert len(plan) == 20 and all(frame > 0 for _, frame, _ in plan)
    batch = training.training_batch(store, plan[:2], "cpu")
    assert batch[0].shape == (2, len(CHANNELS), 8, 10, 4)
    assert batch[2].dtype == torch.bool
    network = SpatialUNet(16)
    optimizer = torch.optim.AdamW(network.parameters(), lr=1e-4)
    # One tiny synthetic optimizer step verifies the training tensor/mask contract.
    x, y, mask, g, gm, weights, active = batch
    f, gp = network(x)
    loss = ((masked_loss(f, y, mask, active) + 0.25 * masked_loss(gp, g, gm)) * weights).mean()
    loss.backward()
    optimizer.step()
    assert torch.isfinite(loss)


def test_store_rejects_layout_leak_and_tampered_targets(training, dataset):
    path = dataset / "manifest.json"
    content = json.loads(path.read_text())
    changed = copy.deepcopy(content)
    changed["runs"][-1]["layout_id"] = changed["runs"][0]["layout_id"]
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="leaked"):
        training.CaseStore(dataset)
    path.write_text(json.dumps(content))
    store = training.CaseStore(dataset)
    target = store.folder(0) / "result.json"
    target.write_text(target.read_text() + " ")
    with pytest.raises(ValueError, match="checksum"):
        store.verify()


def test_partial_snapshot_merges_checkpoints_and_freezes_known_ids(training, dataset):
    path = dataset / "manifest.json"
    original = json.loads(path.read_text())
    records = dataset / "records"
    records.mkdir()
    for record in original["runs"]:
        (records / (record["id"] + ".json")).write_text(json.dumps(record))
    path.write_text(json.dumps({**original, "runs": [], "record_directory": "records", "expected_runs": 25}))
    with pytest.raises(ValueError, match="incomplete"):
        training.CaseStore(dataset)
    store = training.CaseStore(dataset, allow_incomplete=True)
    assert len(store.records) == 20 and store.snapshot["partial"]
    assert store.snapshot["source_merged_index_sha256"]
    # Subsequent campaign checkpoints cannot mutate this in-memory snapshot.
    later = {**original["runs"][0], "id": "later-case"}
    (records / "later-case.json").write_text(json.dumps(later))
    assert "later-case" not in {record["id"] for record in store.records}
    first = {**original["runs"][0], "structural_family": "shared-structure"}
    last = {**original["runs"][-1], "structural_family": "shared-structure"}
    for record in (first, last):
        (records / (record["id"] + ".json")).write_text(json.dumps(record))
    with pytest.raises(ValueError, match="Structural-family leakage"):
        training.CaseStore(dataset, allow_incomplete=True)


def test_evaluation_reports_active_and_peak_errors_against_ambient(training, dataset):
    store = training.CaseStore(dataset)
    store.verify()
    metrics = training.evaluate(store, "validation")
    values = metrics["layout_balanced"]
    assert values["temperature_peak_error_c"] == pytest.approx(60)
    assert values["hot_temperature_mae_c"] == pytest.approx(60)
    assert values["temperature_mae_c"] < values["hot_temperature_mae_c"]
    assert values["smoky_smoke_mae_kg_m3"] > 0
    assert metrics["runs"] == 5 and len(metrics["per_incident_type"]) == 5


@pytest.mark.parametrize("missing_channel", [0, 1])
def test_metrics_keep_fully_missing_channel_unavailable(training, dataset, missing_channel):
    store = training.CaseStore(dataset)
    case = store.get(store.by_split["validation"][0])
    field_key = ("temperature_c", "smoke_kg_m3")[missing_channel]
    case[field_key][:] = np.nan
    case["field_mask"][..., missing_channel] = False
    # Missing FDS globals are independently masked, not inferred from field absence.
    case["globals"][:, 2] = np.nan
    case["global_mask"][:, 2] = False
    fields, globals_ = training.predict_case(None, case, device="cpu", batch_size=4)
    row = training.run_metrics(case, fields, globals_)
    unavailable = (
        ("temperature_mae_c", "temperature_peak_error_c", "hot_temperature_mae_c")
        if missing_channel == 0
        else ("smoke_mae_kg_m3", "smoke_peak_error_kg_m3", "smoky_smoke_mae_kg_m3")
    )
    assert all(row[key] is None for key in unavailable)
    assert row["fds_global_smoke_mean_kg_m3_mae"] is None
    assert np.isfinite(row["encoded_selection_error"])
    # Predictions at absent targets cannot change model selection.
    fields[..., missing_channel] = 1e10
    globals_[:, 2] = 1e10
    other = training.run_metrics(case, fields, globals_)
    assert other["encoded_selection_error"] == row["encoded_selection_error"]
    summary = training.summarize([row])
    assert all(summary["layout_balanced"][key] is None for key in unavailable)
    json.dumps({"run": row, "summary": summary}, allow_nan=False)


@pytest.mark.parametrize(
    "model_id,dataset_id,shape",
    [
        ("spatial-pilot-v1", "spatial-corpus-v1", (8, 10, 4)),
        ("spatial-corpus-v1", "incidents-v1", (12, 16, 8)),
        ("spatial-pilot-v1", "incidents-v1", (12, 16, 8)),
        ("spatial-corpus-v1", "spatial-corpus-v1", (8, 10, 4)),
    ],
)
def test_model_identity_guard_precedes_network_or_training(
    training, tmp_path, monkeypatch, model_id, dataset_id, shape
):
    store = SimpleNamespace(snapshot={"dataset_id": dataset_id}, shape=shape, verify=lambda log: None)
    monkeypatch.setattr(training, "CaseStore", lambda *a, **k: store)
    monkeypatch.setattr(training, "require_cuda", lambda: {"device": "cpu"})
    monkeypatch.setattr(
        training, "SpatialUNet", lambda *a, **k: pytest.fail("must reject before network creation")
    )
    monkeypatch.setattr(training, "fit_epoch", lambda *a, **k: pytest.fail("must reject before training"))
    with pytest.raises(ValueError, match="requires"):
        training.train(tmp_path, tmp_path / "fixture", model_id=model_id)
    assert not (tmp_path / "runtime/models").exists()


@pytest.mark.parametrize(
    "model_id,dataset_id,shape",
    [
        ("spatial-pilot-v1", "incidents-v1", (8, 10, 4)),
        ("spatial-corpus-v1", "spatial-corpus-v1", (12, 16, 8)),
    ],
)
def test_cli_defaults_match_model_dataset_identity(training, tmp_path, model_id, dataset_id, shape):
    args = training.parse_args(["--home", str(tmp_path), "--model-id", model_id])
    assert args.dataset == tmp_path / "datasets" / dataset_id
    training.validate_dataset_identity(model_id, dataset_id, shape)
    custom = tmp_path / "custom"
    args = training.parse_args(["--model-id", model_id, "--dataset", str(custom)])
    assert args.dataset == custom


def model_metadata(shape=(8, 10, 4)):
    return {
        "id": "spatial-pilot-v1",
        "kind": "incident_3d_unet",
        "feature_version": FEATURE_VERSION,
        "compiler_version": COMPILER_VERSION,
        "material_model_version": MODEL_VERSION,
        "architecture": architecture(),
        "sample_shape": list(shape),
    }


def test_recovery_loader_accepts_only_declared_trained_grids(training, case, tmp_path):
    _, config, manifest, _ = case
    metadata = model_metadata((12, 16, 8))
    metadata.update(id="spatial-recovery-v1", supported_sample_shapes=[[8, 10, 4], [12, 16, 8]])
    output = tmp_path / "recovery-model"
    training.publish(output, metadata, checkpoint(SpatialUNet(), metadata["id"]), {}, {})
    loaded = SpatialSurrogate(output)
    fields, _ = loaded.predict_arrays(config, manifest, [0.0, 1.0])
    assert fields.shape == (2, 320, 2)
    loaded.metadata["supported_sample_shapes"] = [[12, 16, 8]]
    with pytest.raises(ValueError, match="Sampling shape"):
        loaded.predict_arrays(config, manifest, [0.0, 1.0])
    # Extra metadata must not silently broaden an old model's grid contract.
    loaded.metadata.update(id="spatial-pilot-v1", supported_sample_shapes=[[8, 10, 4]])
    with pytest.raises(ValueError, match="Sampling shape"):
        loaded.predict_arrays(config, manifest, [0.0, 1.0])


def test_original_trainer_refuses_recovery_entrypoint(training):
    with pytest.raises(SystemExit):
        training.parse_args(["--model-id", "spatial-recovery-v1"])


def test_atomic_publication_safe_roundtrip_cpu_and_hash(training, case, tmp_path, monkeypatch):
    output = tmp_path / "model"
    metadata = model_metadata()
    training.publish(output, metadata, checkpoint(SpatialUNet(), metadata["id"]), {}, {})
    model = SpatialSurrogate(output)
    assert str(model.device) == "cpu"
    _, config, manifest, _ = case
    fields, globals_ = model.predict_arrays(config, manifest, [0.0, 0.7, 30.0])
    valid = np.asarray(manifest["sampling"]["valid_mask"])
    assert np.isnan(fields[:, ~valid]).all()
    np.testing.assert_array_equal(fields[:, valid, 0], 20)
    np.testing.assert_array_equal(fields[:, valid, 1], 0)
    np.testing.assert_array_equal(globals_[:, 0], 20)
    with pytest.raises(FileExistsError):
        training.publish(output, metadata, {}, {}, {})
    with (output / "weights.pt").open("ab") as stream:
        stream.write(b"tampered")
    monkeypatch.setattr(torch, "load", lambda *a, **k: pytest.fail("must reject before deserialization"))
    with pytest.raises(ValueError, match="checksum"):
        SpatialSurrogate(output)


def test_cpu_training_refused_before_dataset_access(training, tmp_path, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(training, "CaseStore", lambda *a, **k: pytest.fail("dataset must not be loaded"))
    with pytest.raises(RuntimeError, match="CUDA"):
        training.train(tmp_path, tmp_path / "missing")
    assert not (tmp_path / "runtime").exists()
    (tmp_path / "runtime/models/spatial-pilot-v1").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        training.train(tmp_path, tmp_path / "missing")


def test_source_hashes_follow_loaded_checkout_and_capture_real_cli(training, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hashes = training.source_hashes()
    assert set(hashes) == {
        "tools/remote/train_spatial.py",
        "backend/ignis/ml/spatial_network.py",
        "backend/ignis/ml/spatial_dataset.py",
        "backend/ignis/physics/compiler.py",
        "backend/ignis/physics/incidents.py",
        "backend/ignis/physics/materials.py",
    }
    root = Path(training.__file__).resolve().parents[2]
    for path, digest in hashes.items():
        assert (root / path).is_file()
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert digest == file_sha(root / path)
    command = [str(Path(training.__file__).resolve()), "--model-id", "spatial-corpus-v1", "--epochs", "20"]
    monkeypatch.setattr(training.sys, "argv", command)
    execution = training.execution_metadata(home=tmp_path, model_id="spatial-corpus-v1", epochs=20)
    assert execution["command_argv"] == [training.sys.executable, *command]
    assert execution["arguments"] == {
        "home": str(tmp_path.resolve()),
        "model_id": "spatial-corpus-v1",
        "epochs": 20,
    }
    monkeypatch.setattr(training.sys, "argv", ["orchestrator.py"])
    assert training.execution_metadata()["command_argv"] is None


def test_validation_selection_precedes_single_test_evaluation(training, tmp_path, monkeypatch):
    events = []
    store = SimpleNamespace(
        records=[{}],
        shape=(8, 10, 4),
        source_sha="source",
        snapshot_sha="snapshot",
        by_split={"train": [0], "validation": [1], "test": [2]},
        snapshot={"dataset_id": "incidents-v1"},
        verify=lambda log: None,
    )
    monkeypatch.setattr(training, "CaseStore", lambda *a, **k: store)
    monkeypatch.setattr(training, "require_cuda", lambda: {"device": "cpu", "device_name": "CPU test double"})
    for name in ("manual_seed_all", "synchronize"):
        monkeypatch.setattr(torch.cuda, name, lambda *a: None)
    for name in ("memory_allocated", "memory_reserved", "max_memory_allocated", "max_memory_reserved"):
        monkeypatch.setattr(torch.cuda, name, lambda *a: 0)
    epoch = [0]

    def fit(*args, **kwargs):
        epoch[0] += 1
        events.append("train")
        if kwargs.get("first_step"):
            kwargs["first_step"]()
        return 1.0, 1

    def evaluate(store, split, network=None, **kwargs):
        events.append((split, network is not None))
        return {"layout_balanced": {"encoded_selection_error": 10 - epoch[0] if network is not None else 20}}

    monkeypatch.setattr(training, "fit_epoch", fit)
    monkeypatch.setattr(training, "evaluate", evaluate)
    result = training.train(tmp_path, tmp_path / "fake", epochs=5)
    assert result["source_sha256"] == training.source_hashes()
    assert result["execution"]["arguments"]["epochs"] == 5
    assert result["training"]["best_epoch"] == 5
    assert events[-2:] == [("test", True), ("test", False)]
    assert events.count(("test", True)) == 1
    assert events.count(("validation", True)) == 5
    log_path = next((tmp_path / "runtime/training").glob("*.jsonl"))
    log = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert all(row["timestamp_utc"].endswith("+00:00") for row in log)
    assert sum(row["stage"] == "cuda_training_started" for row in log) == 1
