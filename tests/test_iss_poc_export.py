"""Independent replay checks catch cross-channel, geometry and report errors."""

import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def export(tmp_path):
    path = Path(__file__).parents[1] / "tools/remote/verify_iss_poc_export.py"
    spec = importlib.util.spec_from_file_location("iss_export_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    metric = module.metric(dict(tp=1, fp=1, fn=1, tn=0))
    model = dict(id="test-model", weights_sha256="a" * 64, state_sha256="b" * 64,
                 dataset_sha256="c" * 64, score_thresholds=dict(heat=0.5, smoke=0.5),
                 heat_delta_c=5, smoke_threshold_kg_m3=1e-6)
    entry = dict(id="example", split="validation", layout_id="room-a", module_id="laboratory", family="laboratory",
                 url="./cases/example.json", ambient_temperature_c=20, gravity_g=0.0001,
                 airflow_m_s=0.1, incident_type="flaming", metrics=dict(heat=metric, smoke=metric))
    index = dict(schema_version="iss-poc-1", model=model, cases=[entry],
                 metrics={"validation": {"heat": metric, "smoke": metric}}, default_case_id="example")
    heat_valid = [True, True, True, False, False, False, False, False]
    smoke_valid = [False, True, False, True, True, False, False, False]
    frame = dict(time_s=1,
                 temperature_c=[25, 20, 25, None, None, None, None, None],
                 heat_score=[0.9, 0.9, 0.1, None, None, None, None, None],
                 heat_valid_mask=heat_valid,
                 hotspot_truth=[True, False, True, None, None, None, None, None],
                 predicted_hot_mask=[True, True, False, None, None, None, None, None],
                 soot_kg_m3=[None, 2e-6, None, 0, 2e-6, None, None, None],
                 smoke_score=[None, 0.9, None, 0.9, 0.1, None, None, None],
                 smoke_valid_mask=smoke_valid,
                 smoke_truth=[None, True, None, False, True, None, None, None],
                 predicted_smoke_mask=[None, True, None, True, False, None, None, None])
    initial = copy.deepcopy(frame)
    initial["time_s"] = 0
    case = dict(schema_version="iss-poc-1", id="example", split="validation", layout_id="room-a", module_id="laboratory",
                scene=dict(bounds_m=[2, 2, 2], objects=[], vents=[],
                           source={"bounds_m": [0.1, 0.3, 0.1, 0.3, 0.2, 0.2]}),
                shape=[2, 2, 2], sample_positions_m=[[x, y, z] for x in (0.2, 1.2) for y in (0.2, 1.2) for z in (0.2, 1.2)],
                conditions=dict(ambient_temperature_c=20, gravity_g=0.0001, airflow_m_s=0.1,
                                incident_type="flaming", source_position_m=[0.2, 0.2, 0.2]),
                score_thresholds=model["score_thresholds"], heat_delta_c=5, smoke_threshold_kg_m3=1e-6,
                metrics=dict(heat=metric, smoke=metric), frames=[initial, frame])
    (tmp_path / "cases").mkdir()

    def write():
        (tmp_path / "index.json").write_text(json.dumps(index))
        (tmp_path / "cases/example.json").write_text(json.dumps(case))

    write()
    return module, tmp_path, index, case, write


def test_channels_use_independent_masks_and_exclude_initial_time(export):
    module, path, _, _, _ = export
    result = module.verify(path)
    assert result["verified"] and result["no_inference_or_training"]
    assert not result["fds_observations_verified"]
    for channel in ("heat", "smoke"):
        assert result["metrics"]["validation"][channel]["n_valid"] == 3
        assert result["metrics"]["validation"][channel]["f1"] == 0.5


def test_smoke_predictions_cannot_silently_reuse_heat_mask(export):
    module, path, _, case, write = export
    case["frames"][1]["smoke_valid_mask"] = case["frames"][1]["heat_valid_mask"]
    write()
    with pytest.raises(ValueError, match="Missing or invalid"):
        module.verify(path)


def test_false_positive_change_requires_new_metrics(export):
    module, path, _, case, write = export
    case["frames"][1]["smoke_score"][3] = 0.1
    case["frames"][1]["predicted_smoke_mask"][3] = False
    write()
    with pytest.raises(ValueError, match="recomputed"):
        module.verify(path)


def test_rendered_truth_cannot_disagree_with_measurement(export):
    module, path, _, case, write = export
    case["frames"][1]["hotspot_truth"][0] = False
    write()
    with pytest.raises(ValueError, match="hotspot_truth disagrees"):
        module.verify(path)


def test_renamed_geometry_cannot_cross_partitions(export):
    module, path, index, case, write = export
    other = copy.deepcopy(case)
    other.update(id="renamed", split="test", layout_id="renamed-layout")
    index["cases"].append({**index["cases"][0], "id": "renamed", "split": "test",
                           "layout_id": "renamed-layout", "url": "./cases/renamed.json"})
    (path / "cases/renamed.json").write_text(json.dumps(other))
    write()
    with pytest.raises(ValueError, match="geometry crosses"):
        module.verify(path)


def test_coordinate_reordering_is_not_silent(export):
    module, path, _, case, write = export
    case["sample_positions_m"].reverse()
    write()
    with pytest.raises(ValueError, match="sample order"):
        module.verify(path)


def test_export_url_cannot_escape_directory(export):
    module, path, index, _, write = export
    index["cases"][0]["url"] = "../../unrelated.json"
    write()
    with pytest.raises(ValueError, match="escapes"):
        module.verify(path)


def test_score_cannot_be_a_concentration_or_temperature(export):
    module, path, _, case, write = export
    case["frames"][1]["heat_score"][0] = 25
    write()
    with pytest.raises(ValueError, match="invalid observed"):
        module.verify(path)


def test_soot_threshold_uses_exact_documented_value(export):
    module, path, index, case, write = export
    # This is the exact JSON value of float32(1e-6), below the physical threshold.
    case["frames"][1]["soot_kg_m3"][1] = 9.999999974752427e-7
    case["frames"][1]["smoke_truth"][1] = False
    expected = module.metric(dict(tp=0, fp=2, fn=1, tn=0))
    case["metrics"]["smoke"] = expected
    index["cases"][0]["metrics"]["smoke"] = expected
    index["metrics"]["validation"]["smoke"] = expected
    write()
    assert module.verify(path)["verified"]


@pytest.fixture
def source_dataset(export):
    module, path, index, case, write = export
    dataset = path / "source"
    folder = dataset / "runs/example"
    folder.mkdir(parents=True)
    case["conditions"].update(oxygen_percent=21, duration_s=1, power_w=100, source_duration_s=1)
    source = {**case["scene"]["source"], "position_m": case["conditions"]["source_position_m"]}
    case["scene"]["source"] = source
    case["scene"]["vents"] = [dict(id="inlet", role="inlet", center_m=[1, 0, 1], size_m=[1, 0, 1], normal=[0, 1, 0])]
    manifest = dict(config={**case["conditions"], "ignition_power_w": 100, "ignition_duration_s": 1},
                    incident={"source": source}, objects=[],
                    vents=[dict(id="inlet", role="inlet", normal=[0, 1, 0], bounds_m=[0.5, 1.5, 0, 0, 0.5, 1.5])])
    arrays = {}
    for exported, stored in (("temperature_c", "temperature_c"), ("soot_kg_m3", "smoke_kg_m3")):
        values = np.asarray([f[exported] for f in case["frames"]], dtype=np.float32)
        arrays[stored] = values
        for i, frame in enumerate(case["frames"]):
            frame[exported] = [float(v) if np.isfinite(v) else None for v in values[i]]
    arrays.update(time_s=[0, 1], shape=case["shape"], bounds_m=case["scene"]["bounds_m"],
                  positions_m=case["sample_positions_m"],
                  field_mask=np.stack([[f["heat_valid_mask"] for f in case["frames"]],
                                       [f["smoke_valid_mask"] for f in case["frames"]]], axis=-1))
    np.savez_compressed(folder / "fields.npz", **arrays)
    (folder / "manifest.json").write_text(json.dumps(manifest))
    (folder / "config.json").write_text(json.dumps(manifest["config"]))
    (folder / "scene.json").write_text(json.dumps(case["scene"]))
    (folder / "ignis.fds").write_text("test-only source bytes")
    (dataset / "plan.json").write_text("{}")
    record = dict(id="example", split="validation", layout_id="room-a", structural_family="laboratory",
                  relative_path="runs/example", status="completed",
                  file_hashes={p.name: module.file_sha(p) for p in folder.iterdir()})
    frozen = dict(dataset_id="fixture", expected_runs=1, schema_version=1, compiler_version="fixture",
                  material_model_version="fixture", plan_sha256=module.file_sha(dataset / "plan.json"),
                  design_sha256="d" * 64, runs=[record])
    (dataset / "index.json").write_text(json.dumps(frozen))
    merged = {**frozen, "frozen_index_sha256": module.file_sha(dataset / "index.json")}
    (dataset / "manifest.json").write_text(json.dumps(merged))
    model_directory = path / "model"
    model_directory.mkdir()
    (model_directory / "weights.pt").write_bytes(b"fixture, not a PyTorch model")
    snapshot = dict(source_manifest_sha256=module.file_sha(dataset / "manifest.json"),
                    source_merged_index_sha256=module.canonical_sha(merged), runs=[record])
    (model_directory / "dataset-snapshot.json").write_text(json.dumps(snapshot))
    index["model"].update(selected_step=2, weights_sha256=module.file_sha(model_directory / "weights.pt"),
                          dataset_sha256=module.canonical_sha(snapshot))
    (model_directory / "frozen-selection.json").write_text(json.dumps(dict(
        step=2, state_sha256=index["model"]["state_sha256"], score_thresholds=index["model"]["score_thresholds"],
        test_labels_used_for_selection=False)))
    write()
    return (*export, dataset, model_directory)


def test_npz_observations_and_model_files_are_bound_to_export(source_dataset):
    module, path, _, _, _, dataset, model_directory = source_dataset
    result = module.verify(path, dataset, model_directory)
    assert result["fds_observations_verified"] and result["model_files_verified"]
    assert result["prediction_recomputed"] is False


def test_export_cannot_relabel_a_dataset_partition(source_dataset):
    module, path, index, case, write, dataset, _ = source_dataset
    index["cases"][0]["split"] = case["split"] = "test"
    write()
    with pytest.raises(ValueError, match="partition or layout"):
        module.verify(path, dataset)


def test_export_must_cover_complete_source_population(source_dataset):
    module, path, index, _, write, dataset, _ = source_dataset
    index["cases"] = []
    write()
    with pytest.raises(ValueError, match="population"):
        module.verify(path, dataset)


def test_case_layout_must_match_index(source_dataset):
    module, path, _, case, write, dataset, _ = source_dataset
    case["layout_id"] = "another-layout"
    write()
    with pytest.raises(ValueError, match="identity differs"):
        module.verify(path, dataset)


def test_vent_direction_must_match_compiled_source(source_dataset):
    module, path, _, case, write, dataset, _ = source_dataset
    case["scene"]["vents"][0]["normal"] = [0, -1, 0]
    write()
    with pytest.raises(ValueError, match="normal differs"):
        module.verify(path, dataset)


def test_changed_npz_is_rejected_before_comparing_values(source_dataset):
    module, path, _, _, _, dataset, _ = source_dataset
    with (dataset / "runs/example/fields.npz").open("ab") as stream:
        stream.write(b"unexpected change")
    with pytest.raises(ValueError, match="checksum mismatch"):
        module.verify(path, dataset)


def test_model_weights_must_match_frozen_index(source_dataset):
    module, path, _, _, _, dataset, model_directory = source_dataset
    (model_directory / "weights.pt").write_bytes(b"another model")
    with pytest.raises(ValueError, match="weights checksum"):
        module.verify(path, dataset, model_directory)


@pytest.fixture
def paired_comparison(source_dataset):
    module, path, index, case, write, dataset, model_directory = source_dataset
    previous = path / "previous"
    previous.mkdir()
    (previous / "weights.pt").write_bytes(b"previous fixture weights")
    thresholds = dict(heat=0.5, smoke=0.5)
    old_model = dict(weights_sha256=module.file_sha(previous / "weights.pt"),
                     score_thresholds=thresholds, architecture={"version": "same-network"})
    (previous / "report.json").write_text(json.dumps({"model": old_model}))
    (previous / "frozen-selection.json").write_text(json.dumps({"score_thresholds": thresholds}))
    selection = json.loads((model_directory / "frozen-selection.json").read_bytes())
    selection["v1_recalibrated_thresholds"] = thresholds
    (model_directory / "frozen-selection.json").write_text(json.dumps(selection))
    index["model"].update(warm_start={"weights_sha256": old_model["weights_sha256"]},
                          architecture=old_model["architecture"])
    scores = np.stack([np.asarray([[f["heat_score"][i], f["smoke_score"][i]]
                                 for i in range(8)], dtype=np.float32) for f in case["frames"]])
    archive = model_directory / "old-scores.npz"
    np.savez_compressed(archive, example=scores)
    index["comparison_thresholds"] = {"v1_frozen": thresholds, "v1_recalibrated": thresholds}
    index["comparisons"] = {"validation": {
        "same_cases_as_retrained_model": True,
        "v1_score_archive": {"relative_path": archive.name, "sha256": module.file_sha(archive)},
        "v1_frozen": copy.deepcopy(index["metrics"]["validation"]),
        "v1_recalibrated": copy.deepcopy(index["metrics"]["validation"]),
    }}
    write()
    return (*source_dataset, previous, archive, scores)


def test_paired_comparison_uses_actual_channel_masks_and_frozen_thresholds(paired_comparison):
    module, path, _, _, _, dataset, model_directory, previous, _, _ = paired_comparison
    module.verify(path, dataset, model_directory)
    result = module.verify_retraining_comparison(path, dataset, model_directory, previous)
    assert result["verified"] and result["architecture_unchanged"]
    assert result["metrics"]["validation"]["v1_frozen"]["smoke"]["n_valid"] == 3


def test_comparison_cannot_silently_drop_a_case(paired_comparison):
    module, path, index, _, write, dataset, model_directory, previous, archive, _ = paired_comparison
    np.savez_compressed(archive)
    index["comparisons"]["validation"]["v1_score_archive"]["sha256"] = module.file_sha(archive)
    write()
    with pytest.raises(ValueError, match="population"):
        module.verify_retraining_comparison(path, dataset, model_directory, previous)


def test_comparison_metrics_recomputed_even_when_archive_hash_is_updated(paired_comparison):
    module, path, index, _, write, dataset, model_directory, previous, archive, scores = paired_comparison
    scores[1, 3, 1] = 0.1  # Remove a smoke false positive, leaving the reported metric stale.
    np.savez_compressed(archive, example=scores)
    index["comparisons"]["validation"]["v1_score_archive"]["sha256"] = module.file_sha(archive)
    write()
    with pytest.raises(ValueError, match="recomputed"):
        module.verify_retraining_comparison(path, dataset, model_directory, previous)


def test_comparison_cannot_retune_old_frozen_threshold(paired_comparison):
    module, path, index, _, write, dataset, model_directory, previous, _, _ = paired_comparison
    index["comparison_thresholds"]["v1_frozen"] = dict(heat=0.8, smoke=0.8)
    write()
    with pytest.raises(ValueError, match="frozen selection"):
        module.verify_retraining_comparison(path, dataset, model_directory, previous)
