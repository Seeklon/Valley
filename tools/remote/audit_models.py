"""Audit frozen IGNIS models on Windows; optionally plot saved curves elsewhere.

No fitting, threshold selection, or changes to weights are performed. Ground
truth metrics are read directly from FDS, without the model's target encoding.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

MODEL_IDS = ("field-mlp-v2", "metrics-forest-v2")
SCENES = ("habitat", "cargo", "crossflow", "soyuz")
CURVE_RUNS = ("habitat-f10-microg", "soyuz-f10-microg")
PARAMETERS = ("airflow_m_s", "oxygen_percent", "ignition_power_w", "ignition_duration_s")
CHANNELS = ("temperature_c", "oxygen_percent", "smoke_kg_m3", "u_m_s", "v_m_s", "w_m_s")
METRICS = (
    "temperature_max_c",
    "temperature_mean_c",
    "oxygen_mean_percent",
    "smoke_mean_kg_m3",
    "heat_release_w",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure(condition, message: str) -> None:
    if not condition:
        raise ValueError(message)


def equivalent_number_differences(saved, current, path="") -> list[dict]:
    """Require equal physical inputs; record only exact integer/float equivalents."""
    if type(saved) is not type(current):
        ensure(
            {type(saved), type(current)} == {int, float} and saved == current,
            "Physical scene value/type differs at " + path,
        )
        return [
            {
                "path": path,
                "saved": saved,
                "saved_type": type(saved).__name__,
                "current": current,
                "current_type": type(current).__name__,
            }
        ]
    if isinstance(saved, dict):
        ensure(saved.keys() == current.keys(), "Physical scene keys differ at " + path)
        return [
            difference
            for key in saved
            for difference in equivalent_number_differences(saved[key], current[key], path + "/" + key)
        ]
    if isinstance(saved, list):
        ensure(len(saved) == len(current), "Physical scene array lengths differ at " + path)
        return [
            difference
            for index, (left, right) in enumerate(zip(saved, current))
            for difference in equivalent_number_differences(left, right, path + "/" + str(index))
        ]
    ensure(saved == current, "Physical scene value differs at " + path)
    return []


def verify_scene_equivalence(dataset, runs, scenes, models) -> dict:
    """Recompile both physical representations before permitting metadata migration."""
    from ignis.ml.features import geometry
    from ignis.provenance import (
        PHYSICAL_SCENE_HASH_VERSION,
        PHYSICAL_SCENE_KEYS,
        canonical_sha,
        physical_scene_sha,
    )

    scene_proofs, run_proofs = {}, []
    for index, run in enumerate(runs):
        directory = dataset / run["relative_path"]
        saved, current = read(directory / "scene.json"), scenes[run["scene_id"]]
        before = {key: saved.get(key) for key in PHYSICAL_SCENE_KEYS}
        after = {key: current.get(key) for key in PHYSICAL_SCENE_KEYS}
        differences = equivalent_number_differences(before, after)
        ensure(physical_scene_sha(saved) == physical_scene_sha(current), "Normalized identity differs")
        scene_proof = {
            "saved_legacy_sha256": canonical_sha(before),
            "current_legacy_sha256": canonical_sha(after),
            "normalized_physical_sha256": physical_scene_sha(saved),
            "numeric_representation_differences": differences,
        }
        if run["scene_id"] in scene_proofs:
            ensure(scene_proofs[run["scene_id"]] == scene_proof, "Saved scene versions differ within dataset")
        else:
            scene_proofs[run["scene_id"]] = scene_proof
        for model in models.values():
            version = model.metadata.get("physical_scene_hash_version", 1)
            ensure(version in {1, PHYSICAL_SCENE_HASH_VERSION}, "Unsupported physical scene hash version")
            expected = canonical_sha(before) if version == 1 else physical_scene_sha(saved)
            ensure(
                model.metadata["physical_scene_hashes"][run["scene_id"]] == expected,
                "Model hash does not identify its saved physical scene",
            )
        ensure(read(directory / "config.json") == run["config"], "Run config differs from manifest")
        original = read(directory / "manifest.json")
        saved_compilation = geometry(saved, run["config"])
        current_compilation = geometry(current, run["config"])
        ensure(
            saved_compilation["deck_sha256"]
            == current_compilation["deck_sha256"]
            == original["deck_sha256"]
            == digest(directory / "ignis.fds"),
            "Saved/current compiler inputs produce different FDS decks: " + run["id"],
        )
        sampling_sha = canonical_sha(original["sampling"])
        ensure(
            canonical_sha(saved_compilation["sampling"])
            == canonical_sha(current_compilation["sampling"])
            == sampling_sha,
            "Saved/current compiler inputs produce different sampling: " + run["id"],
        )
        run_proofs.append(
            {
                "run_id": run["id"],
                "deck_sha256": original["deck_sha256"],
                "sampling_sha256": sampling_sha,
                "saved_current_original_identical": True,
            }
        )
        if (index + 1) % 24 == 0:
            print("SCENE_EQUIVALENCE_VERIFIED", index + 1, flush=True)
    return {
        "physical_scene_hash_version": PHYSICAL_SCENE_HASH_VERSION,
        "scope": "Integer-valued JSON floats normalize to integers; canonical FDS provenance is unchanged",
        "all_96_saved_and_current_decks_and_sampling_identical": True,
        "scenes": scene_proofs,
        "runs": run_proofs,
    }


def describe(parts) -> dict | None:
    values = np.concatenate(parts) if parts else np.array([])
    if not values.size:
        return None
    return {"mae": float(values.mean()), "p95_absolute_error": float(np.quantile(values, 0.95))}


def aggregate(rows: list[dict], spatial: bool) -> dict:
    result = {
        "runs": len(rows),
        "frames": sum(r["frames"] for r in rows),
        "metric_errors": {
            name: describe([r["metric_errors"][:, i] for r in rows]) for i, name in enumerate(METRICS)
        },
        "run_temperature_peak_mae_c": float(np.mean([r["peak_error_c"] for r in rows])),
        "metric_mae_run_balanced": {
            name: float(np.mean([r["metric_errors"][:, i].mean() for r in rows]))
            for i, name in enumerate(METRICS)
        },
        "consistency": {
            "mean_above_global_max_frames": sum(
                r["consistency"]["mean_above_global_max_frames"] for r in rows
            ),
            "max_mean_above_global_max_c": max(r["consistency"]["max_mean_above_global_max_c"] for r in rows),
        },
    }
    if spatial:
        result.update(
            {
                "field_errors": {
                    name: describe([r["field_errors"][i] for r in rows]) for i, name in enumerate(CHANNELS)
                },
                "spatial_temperature_peak_mae_c": float(np.mean([r["spatial_peak_error_c"] for r in rows])),
                "temperature_field_mae_run_balanced_c": float(
                    np.mean([r["field_errors"][0].mean() for r in rows])
                ),
                "heated_points_temperature_error_c": describe([r["hot_errors"] for r in rows]),
                "heated_points_count": sum(r["hot_errors"].size for r in rows),
            }
        )
        result["consistency"].update(
            {
                "sample_above_global_max_frames": sum(
                    r["consistency"]["sample_above_global_max_frames"] for r in rows
                ),
                "max_sample_above_global_max_c": max(
                    r["consistency"]["max_sample_above_global_max_c"] for r in rows
                ),
            }
        )
    return result


def validate_frames(result: dict, physical: dict, *, spatial: bool) -> None:
    frames, metrics = result["frames"], result["metrics"]
    ensure(bool(metrics), "No metric observations")
    times = np.array([m["time_s"] for m in metrics])
    ensure(times[0] == 0 and np.all(np.diff(times) > 0), "Non-monotone observation times")
    ensure(np.isfinite([[m[key] for key in METRICS] for m in metrics]).all(), "Invalid scalar output")
    if not spatial:
        ensure(frames == [], "Scalar-only model fabricated spatial fields")
        return
    ensure(len(frames) == len(metrics), "Frame/metric lengths differ")
    sampling = physical["sampling"]
    valid = np.asarray(sampling["valid_mask"], dtype=bool)
    ensure(valid.size == 320 and valid.any(), "Unexpected or empty sampling grid")
    for frame, metric in zip(frames, metrics):
        ensure(frame["time_s"] == metric["time_s"], "Frame/metric timestamps differ")
        ensure(frame["shape"] == [8, 10, 4], "Unexpected frame shape")
        ensure(frame["valid_mask"] == sampling["valid_mask"], "Mask differs from physical geometry")
        ensure(frame["sample_positions_m"] == sampling["positions_m"], "Sampling positions differ")
        ensure(frame["bounds_m"] == sampling["bounds_m"], "Sampling bounds differ")
        for key in ("temperature_c", "oxygen_percent", "smoke_kg_m3", "velocity_m_s"):
            mask = np.repeat(valid, 3) if key == "velocity_m_s" else valid
            values = frame[key]
            ensure(len(values) == len(mask), "Invalid spatial array length")
            ensure(
                all(v is None for v, measured in zip(values, mask) if not measured),
                "Solid observations fabricated",
            )
            ensure(
                np.isfinite([v for v, measured in zip(values, mask) if measured]).all(),
                "Invalid gas observation",
            )


def domain_checks(model, scene, base, run_config) -> list[dict]:
    results = []
    variants = [
        ("mesh_0.1", {"mesh_cell_m": 0.1}),
        ("mesh_0.4", {"mesh_cell_m": 0.4}),
        ("zero_gravity", {"gravity_g": 0}),
        ("lunar_gravity", {"gravity_g": 0.165}),
        ("unknown_scene", {"scene_id": "unknown"}),
        ("coupled_source", {"source_model": "coupled_combustion"}),
        ("resistive_source", {"source_model": "coupled_combustion", "ignition_kind": "resistive"}),
    ]
    for key, (low, high) in model.metadata["domain"]["ranges"].items():
        variants.extend(
            [(key + "_below_domain", {key: low - 0.01}), (key + "_above_domain", {key: high + 0.01})]
        )
    for label, updates in variants:
        try:
            config = run_config.model_validate({**base, **updates})
            model.validate(config, scene)
        except ValueError as exc:
            results.append({"case": label, "rejected": True, "reason": str(exc)[:300]})
        else:
            raise ValueError("Out-of-domain request accepted: " + label)
    altered = copy.deepcopy(scene)
    altered["source_position_m"][0] += 0.01
    try:
        model.validate(run_config.model_validate(base), altered)
    except ValueError as exc:
        results.append({"case": "altered_physical_geometry", "rejected": True, "reason": str(exc)})
    else:
        raise ValueError("Changed geometry accepted under the old scene ID")
    visual = {**scene, "name": "Presentation-only change", "asset_url": "/alternate-visual.glb"}
    model.validate(run_config.model_validate(base), visual)
    results.append({"case": "presentation_only_change", "accepted": True})
    return results


def audit(root: Path, output: Path) -> None:
    ensure(os.name == "nt", "Model inference and dataset audit must execute on the Windows PC")
    from ignis.engine import write_json
    from ignis.ml.features import apply_initial_thermodynamics, decode_outputs, features, geometry
    from ignis.ml.surrogate import Surrogate
    from ignis.physics import parse_result
    from ignis.provenance import PHYSICAL_SCENE_HASH_VERSION, canonical_sha, physical_scene_sha
    from ignis.schema import RunConfig

    started = time.perf_counter()
    output.mkdir(parents=True, exist_ok=True)
    dataset = root / "datasets/pilot-v2"
    manifest_path = dataset / "manifest.json"
    manifest = read(manifest_path)
    ensure(
        {key: manifest[key] for key in ("engine_version", "compiler_version", "material_model_version")}
        == {
            "engine_version": "6.11.1",
            "compiler_version": "ignis-fds-2",
            "material_model_version": "ignis-fds-materials-2",
        },
        "Dataset versions differ from the published model targets",
    )
    runs = manifest["runs"]
    expected = {(s, f, g) for s in SCENES for f in range(12) for g in (0.0001, 1.0)}
    observed = [(r["scene_id"], r["parameter_family"], r["config"]["gravity_g"]) for r in runs]
    ensure(
        len(runs) == 96 and len(set(observed)) == 96 and set(observed) == expected,
        "Missing/duplicate pilot combinations",
    )
    ensure(len({r["id"] for r in runs}) == 96, "Duplicate run IDs")
    ensure(all(r["status"] == "completed" for r in runs), "Unfinished dataset")
    training = [r for r in runs if r["split"] == "train"]
    ensure(len(training) == 48, "Expected 48 training runs")
    observed_ranges = {
        k: [min(r["config"][k] for r in training), max(r["config"][k] for r in training)] for k in PARAMETERS
    }
    families = {
        split: {r["family_id"] for r in runs if r["split"] == split}
        for split in ("train", "validation", "test")
    }
    for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")):
        ensure(not families[left] & families[right], "Family leakage between " + left + " and " + right)
    catalog = read(root / "app/scenes/catalog.json")
    scenes = {s["id"]: s for s in catalog["scenes"]}
    scene_hashes = {s: physical_scene_sha(scenes[s]) for s in SCENES}
    models, model_proofs = {}, {}
    for model_id in MODEL_IDS:
        directory = root / "runtime/models" / model_id
        model = Surrogate.load(directory)
        meta = model.metadata
        ensure(
            meta["dataset_manifest_sha256"] == digest(manifest_path),
            "Model refers to another dataset manifest",
        )
        ensure(meta["mesh_cell_m"] == 0.2, "Wrong learned mesh")
        for split in families:
            ids = {r["id"] for r in runs if r["split"] == split}
            ensure(ids == set(meta["split_run_ids"][split]), "Metadata partition mismatch")
        weight_path = directory / ("weights.pt" if meta["kind"] == "spatial_mlp" else "weights.joblib")
        model_proofs[model_id] = {
            "kind": meta["kind"],
            "weights_sha256": digest(weight_path),
            "weights_bytes": weight_path.stat().st_size,
            "metadata_before_audit_sha256": digest(directory / "metadata.json"),
            "physical_scene_hash_version_before": meta.get("physical_scene_hash_version", 1),
            "physical_scene_hashes_before": copy.deepcopy(meta["physical_scene_hashes"]),
        }
        models[model_id] = model

    scene_equivalence = verify_scene_equivalence(dataset, runs, scenes, models)
    for model in models.values():
        # In-memory changes only, after exact saved/current deck and sampling checks.
        # Persistent metadata is updated only after the entire audit succeeds.
        model.metadata["physical_scene_hashes"] = scene_hashes
        model.metadata["physical_scene_hash_version"] = PHYSICAL_SCENE_HASH_VERSION
        model.metadata["observed_training_ranges"] = observed_ranges

    evaluations = {model_id: [] for model_id in models}
    run_proofs, curves, versions = [], {}, Counter()
    frame_counts = Counter()
    for index, run in enumerate(runs):
        family, scene_id = run["parameter_family"], run["scene_id"]
        expected_split = (
            "test"
            if scene_id == "crossflow" or family >= 10
            else "validation"
            if family in {0, 5}
            else "train"
        )
        ensure(run["split"] == expected_split, "Unexpected partition: " + run["id"])
        ensure(run["family_id"] == f"{scene_id}-f{family:02d}", "Unexpected family ID")
        ensure(run["geometry_holdout"] == (scene_id == "crossflow"), "Geometry holdout mislabeled")
        directory = dataset / run["relative_path"]
        ensure(digest(directory / "result.json") == run["result_sha256"], "Modified result: " + run["id"])
        result = read(directory / "result.json")
        physical, scene = read(directory / "manifest.json"), read(directory / "scene.json")
        config = run["config"]
        ensure(
            config["source_model"] == "prescribed_source" and config["mesh_cell_m"] == 0.2,
            "Run is outside the declared source/mesh domain",
        )
        ensure(read(directory / "config.json") == config, "Stored config differs from dataset entry")
        for key in ("engine_version", "compiler_version", "material_model_version"):
            ensure(result["provenance"][key] == physical[key] == manifest[key], "Mixed version: " + key)
        versions[
            (
                result["provenance"]["engine_version"],
                physical["compiler_version"],
                physical["material_model_version"],
            )
        ] += 1
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "scene": scene,
                    "config": config,
                    "compiler": manifest["compiler_version"],
                    "material_model": manifest["material_model_version"],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        ensure(fingerprint == run["fingerprint"], "Input fingerprint mismatch")
        ensure(
            physical_scene_sha(scene) == scene_hashes[scene_id], "Saved and current physical scenes differ"
        )
        for key, value in {
            "scene_sha256": canonical_sha(scene),
            "config_sha256": canonical_sha(physical["config"]),
            "input_sha256": digest(directory / "ignis.fds"),
        }.items():
            ensure(result["provenance"][key] == value, "Physical provenance mismatch: " + key)
        rebuilt = geometry(scene, config)
        ensure(rebuilt["deck_sha256"] == physical["deck_sha256"], "Compiler cannot reproduce saved deck")
        ensure(rebuilt["sampling"] == physical["sampling"], "Compiler cannot reproduce sampling")
        reparsed = parse_result(directory)
        ensure(
            reparsed["metrics"] == result["metrics"] and reparsed["frames"] == result["frames"],
            "Saved labels differ from raw FDS CSV",
        )
        validate_frames(result, physical, spatial=True)
        ensure(result["metrics"][-1]["time_s"] >= config["duration_s"] - 0.001, "Truncated run")
        times = np.asarray([m["time_s"] for m in result["metrics"]])
        frame_counts[run["split"]] += len(times)
        truth = np.asarray([[m[k] for k in METRICS] for m in result["metrics"]], dtype=np.float64)
        truth_field = np.array(
            [
                np.column_stack(
                    [
                        f["temperature_c"],
                        f["oxygen_percent"],
                        f["smoke_kg_m3"],
                        np.asarray(f["velocity_m_s"], dtype=np.float64).reshape(-1, 3),
                    ]
                )
                for f in result["frames"]
            ],
            dtype=np.float64,
        )
        valid = np.asarray(physical["sampling"]["valid_mask"], dtype=bool)
        if run["id"] in CURVE_RUNS:
            curves[run["id"]] = {
                "split": run["split"],
                "config": config,
                "times_s": times.tolist(),
                "simulation": {name: truth[:, i].tolist() for i, name in enumerate(METRICS)},
                "predictions": {},
            }
        inputs = features(scene, config, physical, times)
        for model_id, model in models.items():
            ensure(inputs.shape[1] == model.metadata["input_features"], "Input schema mismatch")
            encoded = model.encoded(inputs)
            ensure(
                encoded.shape == (len(times), 1925) and np.isfinite(encoded).all(), "Invalid network outputs"
            )
            apply_initial_thermodynamics(encoded, times)
            predicted_field, predicted = decode_outputs(encoded, config)
            error = np.abs(predicted.astype(np.float64) - truth)
            excess = np.maximum(0, predicted[:, 1] - predicted[:, 0])
            row = {
                "run_id": run["id"],
                "scene_id": scene_id,
                "split": run["split"],
                "gravity_g": config["gravity_g"],
                "geometry_holdout": run["geometry_holdout"],
                "frames": len(times),
                "metric_errors": error,
                "peak_error_c": abs(float(predicted[:, 0].max()) - float(truth[:, 0].max())),
                "true_peak_c": float(truth[:, 0].max()),
                "predicted_peak_c": float(predicted[:, 0].max()),
                "consistency": {
                    "mean_above_global_max_frames": int((excess > 0.01).sum()),
                    "max_mean_above_global_max_c": float(excess.max()),
                },
            }
            if model.metadata["kind"] == "spatial_mlp":
                field_error = np.abs(predicted_field[:, valid].astype(np.float64) - truth_field[:, valid])
                hot = truth_field[:, valid, 0] > physical["config"]["ambient_temperature_c"] + 2
                row.update(
                    {
                        "field_errors": [field_error[:, :, i].ravel() for i in range(6)],
                        "hot_errors": field_error[:, :, 0][hot],
                        "spatial_peak_error_c": abs(
                            float(predicted_field[:, valid, 0].max()) - float(truth_field[:, valid, 0].max())
                        ),
                    }
                )
                sample_excess = np.maximum(0, predicted_field[:, valid, 0].max(axis=1) - predicted[:, 0])
                row["consistency"].update(
                    {
                        "sample_above_global_max_frames": int((sample_excess > 0.01).sum()),
                        "max_sample_above_global_max_c": float(sample_excess.max()),
                    }
                )
            evaluations[model_id].append(row)
            if run["id"] in CURVE_RUNS:
                curves[run["id"]]["predictions"][model_id] = {
                    name: predicted[:, i].tolist() for i, name in enumerate(METRICS)
                }
        run_proofs.append(
            {
                "id": run["id"],
                "split": run["split"],
                "family_id": run["family_id"],
                "frames": len(times),
                "valid_spatial_points": int(valid.sum()),
                "result_sha256": run["result_sha256"],
                "raw_device_csv_sha256": digest(directory / "ignis_devc.csv"),
                "deck_sha256": physical["deck_sha256"],
                "physical_scene_sha256": physical_scene_sha(scene),
                "all_checks_passed": True,
            }
        )
        if (index + 1) % 12 == 0:
            print("AUDITED_RUNS", index + 1, flush=True)

    groups = {
        "train": lambda r: r["split"] == "train",
        "validation": lambda r: r["split"] == "validation",
        "test": lambda r: r["split"] == "test",
        "test_geometry": lambda r: r["split"] == "test" and r["geometry_holdout"],
        "test_parameters": lambda r: r["split"] == "test" and not r["geometry_holdout"],
    }
    for scene_id in SCENES:
        for regime, gravity in (("microg", 0.0001), ("earth", 1.0)):
            groups[f"test_{scene_id}_{regime}"] = (
                lambda r, s=scene_id, g=gravity: r["split"] == "test"
                and r["scene_id"] == s
                and r["gravity_g"] == g
            )
    for model in models.values():
        for split in families:
            ensure(
                model.metadata["training_counts"][split]
                == {
                    "runs": sum(r["split"] == split for r in runs),
                    "families": len(families[split]),
                    "frames": frame_counts[split],
                },
                "Published split counts do not match the dataset",
            )
    metrics_report = {}
    for model_id, rows in evaluations.items():
        spatial = models[model_id].metadata["kind"] == "spatial_mlp"
        metrics_report[model_id] = {
            name: aggregate([r for r in rows if select(r)], spatial) for name, select in groups.items()
        }
        for name, assessment in models[model_id].metadata["metrics"].items():
            actual = metrics_report[model_id][name]
            for key, tolerance in zip(METRICS, (0.002, 0.002, 1e-5, 1e-10, 0.05)):
                ensure(
                    abs(actual["metric_errors"][key]["mae"] - assessment["metric_errors"][key]["mae"])
                    <= tolerance,
                    "Published and independently recomputed metric differ: "
                    + model_id
                    + "/"
                    + name
                    + "/"
                    + key,
                )
        metrics_report[model_id]["per_run"] = [
            {k: v for k, v in r.items() if k not in {"metric_errors", "field_errors", "hot_errors"}}
            | {"metric_mae": {name: float(r["metric_errors"][:, i].mean()) for i, name in enumerate(METRICS)}}
            for r in rows
        ]

    latency, domains = [], {}
    for model_id, model in models.items():
        for scene_id in SCENES:
            raw = next(r["config"] for r in runs if r["id"] == f"{scene_id}-f10-microg")
            cfg = RunConfig.model_validate({**raw, "mode": "prediction", "model_id": model_id})
            physical = geometry(scenes[scene_id], cfg.physical_config())
            measurements = []
            for _ in range(4):
                before = time.perf_counter()
                prediction = model.predict(scenes[scene_id], cfg)
                measurements.append(time.perf_counter() - before)
                validate_frames(prediction, physical, spatial=model.metadata["kind"] == "spatial_mlp")
            latency.append(
                {
                    "model_id": model_id,
                    "scene_id": scene_id,
                    "cold_call_s": measurements[0],
                    "warm_calls_s": measurements[1:],
                    "median_warm_s": float(np.median(measurements[1:])),
                    "frames": len(prediction["frames"]),
                    "metric_samples": len(prediction["metrics"]),
                    "mask_checks_passed": True,
                }
            )
        base = next(r["config"] for r in runs if r["id"] == "habitat-f10-microg")
        domains[model_id] = domain_checks(model, scenes["habitat"], base, RunConfig)
        at_edge = RunConfig.model_validate(
            {**base, "airflow_m_s": 0.4, "mode": "prediction", "model_id": model_id}
        )
        edge = model.predict(scenes["habitat"], at_edge)
        ensure(
            any("support observé" in w for w in edge["provenance"]["warnings"]),
            "Designed/observed support warning absent",
        )
        domains[model_id].append(
            {"case": "airflow_0.4_inside_design_outside_observed_training", "accepted_with_warning": True}
        )

    curve_report = {
        "selection": "Two runs fixed before audit: habitat-f10-microg and soyuz-f10-microg; no selection by error",
        "time_basis": "Predictions evaluated at original FDS timestamps; no interpolation of FDS labels",
        "runs": curves,
    }
    write_json(output / "model-comparison.json", curve_report)
    write_json(output / "model-metrics.json", metrics_report)
    write_json(output / "model-scene-identity.json", scene_equivalence)
    report = {
        "schema_version": 1,
        "integrity_passed": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Independent frozen-weight/dataset audit and prediction benchmark; not experimental validation",
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "inference_device": "CPU",
            "audit_script_sha256": digest(Path(__file__)),
        },
        "dataset": {
            "id": manifest["dataset_id"],
            "manifest_sha256": digest(manifest_path),
            "runs": len(runs),
            "frames": sum(frame_counts.values()),
            "split_frames": dict(frame_counts),
            "split_runs": dict(Counter(r["split"] for r in runs)),
            "versions": [
                {"fds": v[0], "compiler": v[1], "material_model": v[2], "runs": n}
                for v, n in versions.items()
            ],
            "physical_scene_hashes": scene_hashes,
            "physical_scene_hash_version": PHYSICAL_SCENE_HASH_VERSION,
            "unique_combinations": True,
            "family_partitions_disjoint": True,
            "raw_csv_reparse_matches_all_labels": True,
            "all_source_decks_reproduced": True,
        },
        "observed_training_ranges": observed_ranges,
        "observed_training_runs": 48,
        "models": model_proofs,
        "domain_checks": domains,
        "inference_latency": latency,
        "run_checks": run_proofs,
        "comparison_sha256": digest(output / "model-comparison.json"),
        "metrics_sha256": digest(output / "model-metrics.json"),
        "scene_identity_proof_sha256": digest(output / "model-scene-identity.json"),
        "elapsed_s": time.perf_counter() - started,
        "limitations": [
            "Weights unchanged; no retraining or test-set tuning.",
            "Models emulate exploratory FDS source transport at 0.2 m; no experimental NASA flame validation.",
            "A successful integrity audit is not an accuracy or physical-consistency guarantee.",
            "Inference latency includes geometry compilation and output construction, excludes model loading and HTTP transfer.",
            "Timing repeats share one CPU process; they are not a load or concurrency benchmark.",
            "Independent metrics use original FDS values; tiny differences from training reports reflect float32 target transforms.",
        ],
    }
    write_json(output / "model-audit.json", report)
    audit_sha = digest(output / "model-audit.json")
    metadata_proofs = {}
    for model_id, model in models.items():
        directory = root / "runtime/models" / model_id
        current = read(directory / "metadata.json")
        ensure(
            digest(directory / "metadata.json") == model_proofs[model_id]["metadata_before_audit_sha256"],
            "Model metadata changed concurrently during audit",
        )
        if current.get("physical_scene_hash_version", 1) != PHYSICAL_SCENE_HASH_VERSION:
            history = current.setdefault("physical_scene_hash_history", [])
            history.append(
                {
                    "version": current.get("physical_scene_hash_version", 1),
                    "hashes": current["physical_scene_hashes"],
                    "migration_audit_sha256": audit_sha,
                    "equivalence_proof_sha256": digest(output / "model-scene-identity.json"),
                }
            )
        current["physical_scene_hashes"] = scene_hashes
        current["physical_scene_hash_version"] = PHYSICAL_SCENE_HASH_VERSION
        current["observed_training_ranges"] = observed_ranges
        current["audit_sha"] = audit_sha
        current["audit_report"] = "model-audit.json"
        weight_path = directory / ("weights.pt" if current["kind"] == "spatial_mlp" else "weights.joblib")
        ensure(
            digest(weight_path) == model_proofs[model_id]["weights_sha256"], "Weights changed during audit"
        )
        write_json(directory / "metadata.json", current)
        metadata_proofs[model_id] = {
            "metadata_sha256": digest(directory / "metadata.json"),
            "weights_sha256": digest(weight_path),
        }
    write_json(
        output / "model-audit-metadata.json",
        {"audit_sha": audit_sha, "models": metadata_proofs, "weights_unchanged": True},
    )
    print(
        "AUDIT_COMPLETE",
        json.dumps(
            {
                "integrity_passed": True,
                "runs": len(runs),
                "frames": sum(frame_counts.values()),
                "audit_sha": audit_sha,
                "latency": latency,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def plot(curves_path: Path, target: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    report = read(curves_path)
    fig, axes = plt.subplots(2, 2, figsize=(13.6, 8), sharex=True)
    colors = {"simulation": "#182d42", "field-mlp-v2": "#c95b35", "metrics-forest-v2": "#267d99"}
    for column, identifier in enumerate(CURVE_RUNS):
        run = report["runs"][identifier]
        times = run["times_s"]
        for row, (metric, label, scale) in enumerate(
            (
                ("temperature_max_c", "T maximale du domaine (°C)", 1),
                ("heat_release_w", "Puissance chimique mesurée (kW)", 0.001),
            )
        ):
            ax = axes[row, column]
            ax.axvspan(0, run["config"]["ignition_duration_s"], color="#ece5d9", alpha=0.65)
            for source, values, title, style in (
                ("simulation", run["simulation"], "Simulation FDS", "-"),
                ("field-mlp-v2", run["predictions"]["field-mlp-v2"], "Réseau spatial", "-"),
                ("metrics-forest-v2", run["predictions"]["metrics-forest-v2"], "Extra Trees", "--"),
            ):
                ax.plot(
                    times,
                    np.asarray(values[metric]) * scale,
                    color=colors[source],
                    linewidth=1.8,
                    linestyle=style,
                    label=title,
                )
            ax.set_ylabel(label)
            ax.grid(alpha=0.16)
            if row == 0:
                ax.set_title(
                    ("Habitat" if column == 0 else "Capsule inspirée de Soyouz") + " · famille 10 · 10⁻⁴ g"
                )
            else:
                ax.set_xlabel("Temps physique (s)")
    axes[0, 0].legend(loc="upper right", fontsize=9)
    fig.suptitle("Deux cas réservés au test : les écarts de prédiction restent visibles", fontsize=15)
    fig.text(
        0.5,
        0.015,
        "Poids figés, aucun réentraînement sur ces cas. Instants FDS réels ; zone beige = source prescrite active.\n"
        "Labels synthétiques FDS, maille 0,20 m non démontrée convergée. Comparaison d’émulation, pas validation d’un incendie réel.",
        ha="center",
        fontsize=9,
        color="#354a5a",
    )
    fig.tight_layout(rect=(0, 0.065, 1, 0.95))
    fig.savefig(target, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plot-input", type=Path)
    parser.add_argument("--plot-output", type=Path)
    args = parser.parse_args()
    if args.plot_input:
        plot(args.plot_input, args.plot_output or args.plot_input.with_suffix(".png"))
        return
    from ignis.locking import ProcessLock

    root = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    with ProcessLock(root / "datasets/pilot-v2/generation.lock"), ProcessLock(root / "runtime/compute.lock"):
        audit(root, root / "runtime/model-audit")


if __name__ == "__main__":
    main()
