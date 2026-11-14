"""Incident ML contracts; tiny estimators test serialization, not scientific accuracy."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import joblib
import numpy as np
import pytest
from ignis.ml.incidents import (
    COMPILER_VERSION,
    FEATURE_VERSION,
    MODEL_ID,
    SHAPE,
    IncidentSurrogate,
    build_features,
    compile_geometry,
    decode_fields,
    decode_globals,
    encode_fields,
    encode_globals,
    encode_result,
    file_sha,
    geometry_signature,
    load_dataset,
    point_features,
    validate_conditions,
    validate_splits,
)
from ignis.physics import compile_case
from ignis.physics.materials import MODEL_VERSION
from ignis.physics.verification import verification_scene
from ignis.provenance import canonical_sha
from sklearn.ensemble import ExtraTreesRegressor


@pytest.fixture
def scene():
    result = verification_scene()
    result["components"] = [
        {"id": "heater", "object_id": "sample", "position_m": [1.0, 1.0, 0.4], "face": 3},
        {"id": "left", "object_id": "sample", "position_m": [0.85, 0.85, 0.4], "face": 3},
    ]
    result["objects"].append({"id": "rack", "role": "obstacle", "material_id": "aluminium",
                              "combustible_material_id": "pmma", "thermal_thickness_m": 0.005,
                              "center_m": [1.6, 1.6, 0.4], "size_m": [0.4, 0.4, 0.8]})
    return result


@pytest.fixture
def config():
    return {"source_model": "coupled_combustion", "ignition_kind": "thermal", "incident_type": "overheating",
            "component_id": "heater", "gravity_g": 0.0001, "ignition_power_w": 1000,
            "ignition_duration_s": 10, "duration_s": 30, "airflow_m_s": 0.2, "oxygen_percent": 21,
            "mesh_cell_m": 0.2, "sample_shape": list(SHAPE), "material_id": "cellulose"}


def synthetic_result(manifest):
    sample = manifest["sampling"]
    frames, metrics = [], []
    for t in [0.0, 0.7, 30.0]:
        temperature = [20 + 2 * t if valid else None for valid in sample["valid_mask"]]
        soot = [t * 1e-7 if valid else None for valid in sample["valid_mask"]]
        frames.append({"time_s": t, "shape": list(SHAPE), "bounds_m": sample["bounds_m"],
                       "sample_positions_m": sample["positions_m"], "valid_mask": sample["valid_mask"],
                       "temperature_c": temperature, "smoke_kg_m3": soot})
        metrics.append({"time_s": t, "temperature_max_c": 20 + 3 * t, "temperature_mean_c": 20 + t,
                        "smoke_mean_kg_m3": t * 1e-8, "heat_release_w": t * 10})
    return {"frames": frames, "metrics": metrics,
            "provenance": {"origin": "simulation", "compiler_version": COMPILER_VERSION,
                           "material_model_version": MODEL_VERSION, "scene_sha256": manifest["scene_sha256"],
                           "config_sha256": manifest["config_sha256"], "input_sha256": manifest["deck_sha256"]}}


def write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


@pytest.fixture
def model_directory(scene, config, tmp_path):
    directory = tmp_path / "model"
    directory.mkdir()
    manifest = compile_geometry(scene, config)
    frame_features = build_features(scene, config, manifest, [0, 5, 20])
    points = np.flatnonzero(manifest["sampling"]["valid_mask"])[:12]
    ti, pi = np.repeat([1, 2], len(points)), np.tile(points, 2)
    inputs = point_features(frame_features, manifest, ti, pi)
    target = encode_fields(np.tile([75, 2e-6], (len(inputs), 1)))
    spatial = ExtraTreesRegressor(n_estimators=2, max_depth=2, n_jobs=1, random_state=1).fit(inputs, target)
    global_model = ExtraTreesRegressor(n_estimators=2, max_depth=2, n_jobs=1, random_state=1).fit(
        frame_features, encode_globals(np.tile([100, 50, 1e-6, 100], (3, 1))))
    joblib.dump({"model_id": MODEL_ID, "feature_version": FEATURE_VERSION,
                 "spatial": spatial, "global": global_model}, directory / "weights.joblib")
    write_json(directory / "metadata.json", {"id": MODEL_ID, "kind": "incident_point_extra_trees",
        "feature_version": FEATURE_VERSION, "compiler_version": COMPILER_VERSION,
        "material_model_version": MODEL_VERSION, "dataset_id": "tiny-contract-fixture",
        "weights_sha256": file_sha(directory / "weights.joblib"), "input_features": frame_features.shape[1],
        "spatial_input_features": inputs.shape[1], "geometry_support": {geometry_signature(manifest): "train_geometry"},
        "domain": {"bounds_m": {"min": [2, 2, 2], "max": [4, 6, 4]}}, "metrics": {}})
    return directory


def test_features_respond_to_physics_and_ignore_names(scene, config):
    original = compile_geometry(scene, config)
    baseline = build_features(scene, config, original, [0, 2.5])
    renamed = copy.deepcopy(scene)
    renamed.update(id="unrelated-id", name="Presentation change")
    renamed["objects"] = list(reversed(renamed["objects"]))
    other = compile_geometry(renamed, config)
    np.testing.assert_array_equal(baseline, build_features(renamed, config, other, [0, 2.5]))
    moved_source = {**config, "component_id": "left"}
    moved = compile_geometry(scene, moved_source)
    assert not np.array_equal(baseline, build_features(scene, moved_source, moved, [0, 2.5]))
    for change in ("coating", "substrate", "thickness", "obstacle", "vent"):
        varied = copy.deepcopy(scene)
        if change == "coating":
            varied["objects"][1]["combustible_material_id"] = "cellulose"
        elif change == "substrate":
            varied["objects"][1]["material_id"] = "steel"
        elif change == "thickness":
            varied["objects"][1]["thermal_thickness_m"] = 0.002
        elif change == "obstacle":
            varied["objects"][1]["center_m"][0] -= 0.2
        else:
            varied["vents"][0]["size_m"][1] += 0.2
        compiled = compile_geometry(varied, config)
        assert not np.array_equal(baseline, build_features(varied, config, compiled, [0, 2.5])), change
        assert geometry_signature(original) != geometry_signature(compiled), change


def test_encoder_preserves_real_timestamps_and_null_observations(scene, config):
    manifest = compile_geometry(scene, config)
    result = synthetic_result(manifest)
    gap = int(np.flatnonzero(manifest["sampling"]["valid_mask"])[0])
    result["frames"][1]["temperature_c"][gap] = None
    times, fields, masks, globals_ = encode_result(result, manifest)
    np.testing.assert_array_equal(times, [0.0, 0.7, 30.0])
    assert not masks[1, gap]
    assert np.isnan(fields[1, gap]).all()
    assert not masks[:, ~np.asarray(manifest["sampling"]["valid_mask"])].any()
    np.testing.assert_allclose(decode_globals(globals_)[2], [110, 50, 3e-7, 300], rtol=1e-6)
    np.testing.assert_allclose(decode_fields(fields)[2, masks[2]][0], [80, 3e-6], rtol=1e-6)
    result["metrics"][1]["time_s"] = 1
    with pytest.raises(ValueError, match="asynchronous"):
        encode_result(result, manifest)


def test_inference_masks_initial_state_and_coherent_field_summaries(model_directory, scene, config):
    model = IncidentSurrogate(model_directory)
    result = model.predict(scene, {**config, "duration_s": 10.5})
    assert result["frames"][-1]["time_s"] == 10.5
    assert result["provenance"]["incident"]["source"]["component_id"] == "heater"
    assert result["provenance"]["geometry_status"] == "train_geometry"
    for index, (frame, metric) in enumerate(zip(result["frames"], result["metrics"])):
        valid = np.asarray(frame["valid_mask"])
        temperature = np.asarray(frame["temperature_c"], dtype=float)
        soot = np.asarray(frame["smoke_kg_m3"], dtype=float)
        assert "velocity_m_s" not in frame and "oxygen_percent" not in frame
        assert np.isnan(temperature[~valid]).all() and np.isnan(soot[~valid]).all()
        assert metric["temperature_max_c"] == temperature[valid].max()
        assert metric["temperature_mean_c"] == temperature[valid].mean()
        assert metric["smoke_mean_kg_m3"] == soot[valid].mean()
        if index == 0:
            np.testing.assert_array_equal(temperature[valid], 20)
            np.testing.assert_array_equal(soot[valid], 0)
        else:
            assert metric["fds_global_prediction"]["temperature_max_c"] != metric["temperature_max_c"]


def test_unseen_geometry_is_exploratory_within_envelope(model_directory, scene, config):
    model = IncidentSurrogate(model_directory)
    scene["objects"][1]["thermal_thickness_m"] = 0.003
    model.validate(scene, config)
    result = model.predict(scene, {**config, "duration_s": 10})
    assert result["provenance"]["geometry_status"] == "unseen_geometry_exploratory"
    assert any("Géométrie inédite" in warning for warning in result["provenance"]["warnings"])
    scene["bounds_m"] = [5, 2, 2]
    scene["vents"][1]["center_m"][0] = 5
    with pytest.raises(ValueError, match="enveloppe"):
        model.validate(scene, config)


@pytest.mark.parametrize("updates", [
    {"source_model": "prescribed_source"}, {"ignition_kind": "resistive"}, {"gravity_g": 0},
    {"duration_s": 31}, {"ignition_power_w": 400}, {"airflow_m_s": 0.5}, {"oxygen_percent": 25},
    {"mesh_cell_m": 0.1}, {"incident_type": "unknown"}, {"incident_type": "arc"},
    {"ambient_temperature_c": 25}, {"pressure_pa": 100000}, {"ignition_delay_s": 1},
    {"sample_shape": [4, 4, 4]}, {"ignition_power_w": float("nan")},
])
def test_outside_training_conditions_rejected(config, updates):
    with pytest.raises(ValueError):
        validate_conditions({**config, **updates})


def test_weight_hash_and_legacy_identity_are_checked_before_loading(model_directory):
    metadata_path = model_directory / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    write_json(metadata_path, {**metadata, "id": "field-mlp-v2"})
    with pytest.raises(ValueError, match="legacy"):
        IncidentSurrogate(model_directory)
    write_json(metadata_path, metadata)
    with (model_directory / "weights.joblib").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        IncidentSurrogate(model_directory)


def test_compiler_version_cannot_be_reused(scene, config):
    manifest = compile_geometry(scene, config)
    manifest["compiler_version"] = "ignis-fds-2"
    with pytest.raises(ValueError, match="Compiler version"):
        build_features(scene, config, manifest, [0])


def test_splits_refuse_shared_layouts_or_crossflow_training():
    runs = [{"id": name, "layout_id": name, "split": name, "scene_id": "scene"}
            for name in ("train", "validation", "test")]
    validate_splits(runs)
    runs[1]["layout_id"] = "train"
    with pytest.raises(ValueError, match="leakage"):
        validate_splits(runs)
    runs[1]["layout_id"] = "validation"
    runs[0]["scene_id"] = "crossflow"
    with pytest.raises(ValueError, match="Crossflow"):
        validate_splits(runs)


@pytest.fixture
def dataset_directory(tmp_path, scene, config):
    root = tmp_path / "dataset"
    runs = []
    for index, split in enumerate(("train", "validation", "test")):
        variant = copy.deepcopy(scene)
        variant["objects"][1]["thermal_thickness_m"] = 0.003 + index * 0.001
        folder = root / split
        manifest = compile_case(variant, config, folder)
        write_json(folder / "scene.json", variant)
        write_json(folder / "config.json", config)
        write_json(folder / "result.json", synthetic_result(manifest))
        runs.append({"id": split, "layout_id": split, "split": split, "scene_id": "scene",
                     "relative_path": split, "config": config, "scene_sha256": canonical_sha(variant),
                     "result_sha256": file_sha(folder / "result.json")})
    write_json(root / "manifest.json", {"dataset_id": "contract-fixture", "compiler_version": COMPILER_VERSION,
                                        "runs": runs})
    return root


def test_dataset_validates_scene_result_and_compiler_integrity(dataset_directory):
    _, records = load_dataset(dataset_directory)
    assert len(records) == 3
    np.testing.assert_array_equal(records[0]["times"], [0, 0.7, 30])
    path = dataset_directory / "train/result.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="Result checksum"):
        load_dataset(dataset_directory)


def test_dataset_scene_tampering_is_not_ignored(dataset_directory):
    path = dataset_directory / "train/scene.json"
    scene = json.loads(path.read_text())
    scene["objects"][1]["combustible_material_id"] = "cellulose"
    write_json(path, scene)
    with pytest.raises(ValueError, match="Scene checksum"):
        load_dataset(dataset_directory)


def test_incomplete_campaign_is_rejected_before_fitting(dataset_directory):
    path = dataset_directory / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["expected_runs"] = 4
    write_json(path, manifest)
    with pytest.raises(ValueError, match="incomplete"):
        load_dataset(dataset_directory)


def trainer_module():
    path = Path(__file__).resolve().parents[1] / "tools/remote/train_incidents.py"
    spec = importlib.util.spec_from_file_location("incident_training_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_trainer_refuses_existing_artifacts_before_reading_dataset(tmp_path):
    trainer = trainer_module()
    (tmp_path / "runtime/models" / MODEL_ID).mkdir(parents=True)
    with pytest.raises(FileExistsError, match="preserved"):
        trainer.train(tmp_path)


def test_evaluation_reports_run_and_layout_balanced_baseline(dataset_directory):
    _, records = load_dataset(dataset_directory)
    report = trainer_module().evaluate(records)
    assert report["runs"] == 3 and report["layouts"] == 3
    assert len(report["per_run"]) == 3
    expected = np.mean([row["temperature_mae_c"] for row in report["per_run"]])
    assert report["layout_balanced"]["temperature_mae_c"] == pytest.approx(expected)
    assert report["per_incident_type"]["overheating"]["runs"] == 3


def test_training_cap_excludes_nulls_initial_frames_and_heldout_targets(dataset_directory):
    _, records = load_dataset(dataset_directory)
    training = []
    for index, family in enumerate(("overheating", "arc", "flaming", "smoldering", "battery")):
        row = copy.deepcopy(records[0])
        row.update(id=f"train-{family}", layout_id="layout-a" if index < 3 else "layout-b")
        row["config"].update(incident_type=family, ignition_duration_s=1 if family == "arc" else 10,
                             gravity_g=1.0 if index % 2 else 0.0001)
        point = int(np.flatnonzero(row["masks"][1])[0])
        row["masks"][1, point], row["fields"][1, point] = False, np.nan
        training.append(row)
    # Poison held-out labels: no sampling or fitting input may consult them.
    for row in records[1:]:
        row["fields"][:] = np.nan
        row["globals"][:] = np.nan
    arrays, counts = trainer_module().training_arrays(training + records[1:], 1000)
    x, y, weights, gx, gy, gweights = arrays
    assert len(x) <= 1000 and len(gx) == 10
    assert x.shape[1] == gx.shape[1] + 11
    assert all(np.isfinite(array).all() for array in arrays)
    assert (x[:, 0] > 0).all() and (gx[:, 0] > 0).all()
    offset, totals = 0, {}
    for row in counts:
        size = row["selected_points"]
        totals[row["layout_id"]] = totals.get(row["layout_id"], 0) + weights[offset:offset + size].sum()
        offset += size
    assert totals["layout-a"] == pytest.approx(totals["layout-b"])
