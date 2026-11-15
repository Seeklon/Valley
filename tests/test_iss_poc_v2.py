"""Retraining-only changes: cache parity, holdout isolation and loader compatibility."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(scope="module")
def modules():
    torch = pytest.importorskip("torch")
    import sys

    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    directory = str(Path(__file__).parents[1] / "tools/remote")
    sys.path.insert(0, directory)
    yield importlib.import_module("train_iss_poc_v2"), importlib.import_module("iss_poc_model")
    sys.path.remove(directory)
    torch.set_num_threads(previous)


def compiled_case(tmp_path, model, *, power=1000, incident="flaming", delay=1):
    from ignis.physics import compile_case
    from ignis.physics.verification import verification_scene

    scene = verification_scene()
    scene["components"] = [{"id": "heater", "object_id": "sample", "position_m": [1, 1, 0.4], "face": 3}]
    config = {
        "source_model": "coupled_combustion",
        "ignition_kind": "thermal",
        "incident_type": incident,
        "component_id": "heater",
        "gravity_g": 0.0001,
        "ignition_power_w": power,
        "ignition_duration_s": 2 if power else 0,
        "ignition_delay_s": delay if power else 0,
        "duration_s": 4,
        "airflow_m_s": 0.2,
        "oxygen_percent": 21,
        "mesh_cell_m": 0.2,
        "sample_shape": [4, 4, 4],
        "material_id": "cellulose",
    }
    manifest = compile_case(scene, config, tmp_path)
    _, bounds, positions, gas, _, _ = model.sampling_grid(manifest)
    observed = np.broadcast_to(gas[None, :, None], (5, 64, 2)).copy()
    temperature = np.full((5, 64), 20, dtype=np.float32)
    soot = np.zeros((5, 64), dtype=np.float32)
    if power:
        temperature[2:, gas] = 27
        soot[3:, gas] = 2e-6
    return {
        "record": {
            "id": tmp_path.name,
            "split": "train",
            "layout_id": tmp_path.name,
            "structural_family": "iss-laboratory",
        },
        "manifest": manifest,
        "config": manifest["config"],
        "time_s": np.arange(5, dtype=np.float64),
        "static": model.geometry_channels(manifest),
        "shape": np.array([4, 4, 4]),
        "field_mask": observed,
        "temperature_c": temperature,
        "smoke_kg_m3": soot,
        "positions_m": positions,
        "bounds_m": bounds,
    }


def test_factorized_cache_is_exact_for_delayed_source_arc_and_disabled_control(modules, tmp_path):
    import torch

    train, model = modules
    cases = [
        compiled_case(tmp_path / "delayed", model, delay=1),
        compiled_case(tmp_path / "arc", model, incident="arc", delay=0),
        compiled_case(tmp_path / "control", model, power=0),
    ]
    original_manifests = [copy.deepcopy(case["manifest"]) for case in cases]
    cache = train.FactorizedTrainingCache(cases, device="cpu")
    x, y, mask = cache.gather(torch.arange(cache.frames))
    expected_x, expected_y, expected_mask = [], [], []
    for case in cases:
        truth, observed = train.targets(case)
        for frame in range(1, 5):
            expected_x.append(model.input_tensor(case["static"], case["config"], case["manifest"], frame))
            expected_y.append(truth[frame].T.reshape(2, 4, 4, 4))
            expected_mask.append(observed[frame].T.reshape(2, 4, 4, 4))
    assert np.array_equal(x.numpy(), np.stack(expected_x))
    assert np.array_equal(y.numpy(), np.stack(expected_y))
    assert np.array_equal(mask.numpy(), np.stack(expected_mask))
    assert all(case["manifest"] == original for case, original in zip(cases, original_manifests))
    assert cache.bytes < x.numel() * x.element_size()
    assert cache.static.shape[0] == len(cases)
    assert cache.frames == 12
    assert np.all(cache.probability.numpy() > 0)
    for index in range(len(cases)):
        assert cache.probability[cache.case == index].sum().item() == pytest.approx(1 / 3)
    ramp = model.CHANNELS.index("source_ramp_fraction")
    assert np.all(x.numpy()[8:, ramp] == 0)


def test_factorized_cache_rejects_holdout_before_reading_fields(modules):
    with pytest.raises(ValueError, match="training cases only"):
        modules[0].FactorizedTrainingCache([{"record": {"split": "validation"}}], device="cpu")


def write_index(directory, train, **updates):
    records = []
    for split in ("train", "validation", "test"):
        for family in sorted(train.FAMILIES):
            identifier = split + "-" + family
            records.append(
                {
                    "id": identifier,
                    "layout_id": identifier,
                    "structural_family": family,
                    "split": split,
                    "status": "completed",
                    "relative_path": "runs/" + identifier,
                }
            )
    index = {"dataset_id": train.DATASET_ID, "expected_runs": 18, "runs": records, **updates}
    (directory / "manifest.json").write_text(json.dumps(index), encoding="utf-8")
    return index


def test_store_uses_exact_six_families_and_inherits_all_compiler_checks(modules, tmp_path):
    train, _ = modules
    write_index(tmp_path, train)
    store = train.RetrainingCaseStore(tmp_path)
    assert [len(store.by_split[split]) for split in ("train", "validation", "test")] == [6, 6, 6]
    assert train.RetrainingCaseStore.get is train.CaseStore.get
    assert train.RetrainingCaseStore.verify is train.CaseStore.verify


@pytest.mark.parametrize(
    "problem", ["wrong_dataset", "incomplete", "unknown_family", "shared_layout", "missing_family"]
)
def test_store_rejects_dataset_and_partition_contract_changes(modules, tmp_path, problem):
    train, _ = modules
    index = write_index(tmp_path, train)
    if problem == "wrong_dataset":
        index["dataset_id"] = "iss-poc-20261115-v1"
    elif problem == "incomplete":
        index["expected_runs"] = 19
    elif problem == "unknown_family":
        index["runs"][0]["structural_family"] = "unknown"
    elif problem == "shared_layout":
        index["runs"][6]["layout_id"] = index["runs"][0]["layout_id"]
    else:
        index["runs"][6]["structural_family"] = index["runs"][7]["structural_family"]
    (tmp_path / "manifest.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(ValueError):
        train.RetrainingCaseStore(tmp_path)


def test_normalized_geometry_ignores_names_material_and_overall_scale(modules):
    train, _ = modules
    old = {
        "sampling": {"bounds_m": [2, 3, 4]},
        "objects": [
            {"id": "rack", "bounds_m": [0, 1, 0, 1, 0, 1], "material_id": "steel"},
        ],
    }
    changed = copy.deepcopy(old)
    changed["sampling"]["bounds_m"] = [4, 6, 8]
    changed["objects"][0].update(id="renamed", bounds_m=[0, 2, 0, 2, 0, 2], material_id="aluminium")
    assert train.normalized_geometry(changed) == train.normalized_geometry(old)
    changed["objects"][0]["bounds_m"][1] = 3
    assert train.normalized_geometry(changed) != train.normalized_geometry(old)


def test_disjointness_rejects_v1_overlap_and_new_split_leakage(modules, tmp_path):
    train, _ = modules
    old = {"sampling": {"bounds_m": [2, 3, 4]}, "objects": [{"bounds_m": [0, 1, 0, 1, 0, 1]}]}
    dataset = tmp_path / "old-dataset"
    (dataset / "runs/old").mkdir(parents=True)
    manifest_path = dataset / "runs/old/manifest.json"
    manifest_path.write_text(json.dumps(old), encoding="utf-8")
    snapshot = {
        "dataset_id": "iss-poc-20261115-v1",
        "runs": [
            {
                "layout_id": "old-layout",
                "relative_path": "runs/old",
                "geometry_signature": "old-physical",
                "file_hashes": {"manifest.json": train.file_sha(manifest_path)},
            }
        ],
    }
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    records = [{"layout_id": "new-layout", "geometry_signature": "new-physical", "split": "validation"}]
    store = SimpleNamespace(records=records, get=lambda index: {"manifest": old})
    with pytest.raises(ValueError, match="scaled copy"):
        train.verify_disjointness(store, snapshot_path, dataset, train.canonical_sha(snapshot))
    new = copy.deepcopy(old)
    new["objects"][0]["bounds_m"][1] = 1.5
    store.get = lambda index: {"manifest": new}
    report = train.verify_disjointness(store, snapshot_path, dataset, train.canonical_sha(snapshot))
    assert report["all_v1_partitions_excluded"]
    records.append({"layout_id": "test-layout", "geometry_signature": "different-physical", "split": "test"})
    with pytest.raises(ValueError, match="Normalized geometry leakage"):
        train.verify_disjointness(store, snapshot_path, dataset, train.canonical_sha(snapshot))
    with pytest.raises(ValueError, match="frozen v1"):
        train.verify_disjointness(store, snapshot_path, dataset, "0" * 64)


def test_retrained_checkpoint_remains_compatible_with_unchanged_v1_predictor(modules, tmp_path):
    import torch

    train, model = modules
    case = compiled_case(tmp_path / "case", model, power=0)
    network = model.ISSClassifier(16)
    payload = {
        "id": model.MODEL_ID,
        "schema_version": model.SCHEMA_VERSION,
        "architecture": model.architecture(16),
        "sample_shape": [4, 4, 4],
        "score_thresholds": {"heat": 0.1, "smoke": 0.2},
        "state_dict": network.state_dict(),
        "training_version": train.TRAINING_VERSION,
        "warm_start": {"architecture_unchanged": True},
    }
    weights = tmp_path / "weights.pt"
    torch.save(payload, weights)
    predictor = model.ISSPredictor(weights)
    result = predictor.predict_arrays(case["config"], case["manifest"], [1, 2, 4])
    assert result["scores"].shape == (3, 64, 2)
    assert predictor.metadata["training_version"] == train.TRAINING_VERSION
    assert train.state_sha(predictor.network) == train.state_sha(network)
    assert sum(p.numel() for p in network.parameters()) == 379046


def test_shared_compute_lock_encloses_entire_retraining(modules, tmp_path, monkeypatch):
    train, _ = modules
    args = SimpleNamespace(runtime=tmp_path / "runtime", dataset=tmp_path / "dataset")
    visited = []

    def body(arguments):
        with pytest.raises(RuntimeError):
            with train.ProcessLock(arguments.compute_lock_path):
                pytest.fail("Shared lock was available during retraining")
        visited.append(True)

    monkeypatch.setattr(train, "_run_locked", body)
    train.run(args)
    assert visited == [True]
    with train.ProcessLock(args.runtime / "compute.lock"):
        pass
