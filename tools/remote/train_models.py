"""Train real compact surrogates on the Windows GPU and evaluate whole-run holdouts."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
os.environ.setdefault("OMP_NUM_THREADS", "4")

import joblib
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch
from ignis.engine import write_json
from ignis.locking import ProcessLock
from ignis.ml.features import (
    METRICS,
    POINTS,
    apply_initial_thermodynamics,
    decode_outputs,
    encode_result,
    features,
)
from ignis.ml.surrogate import Surrogate, network
from ignis.provenance import canonical_sha, physical_scene_sha
from sklearn.ensemble import ExtraTreesRegressor


def evaluate(predicted, truth, masks, records, indices):
    channel_errors = [[] for _ in range(6)]
    metric_errors = [[] for _ in METRICS]
    peak_errors, spatial_peak_errors, hot_errors, run_field_errors = [], [], [], []
    for record in records:
        selection = np.intersect1d(np.arange(record["start"], record["end"]), indices)
        if not len(selection):
            continue
        pfield, pmetrics = decode_outputs(predicted[selection], record["config"])
        field, metrics = decode_outputs(truth[selection], record["config"], postprocess=False)
        valid = masks[selection, :POINTS*6].reshape(-1, POINTS, 6).astype(bool)
        for c in range(6):
            channel_errors[c].append(np.abs(pfield[:, :, c]-field[:, :, c])[valid[:, :, c]])
        for c in range(len(METRICS)):
            metric_errors[c].append(np.abs(pmetrics[:, c]-metrics[:, c]))
        peak_errors.append(abs(float(pmetrics[:, 0].max())-float(metrics[:, 0].max())))
        temperature_valid = valid[:, :, 0]
        error = np.abs(pfield[:, :, 0] - field[:, :, 0])
        hot = temperature_valid & (field[:, :, 0] > 22)
        hot_errors.append(error[hot])
        spatial_peak_errors.append(abs(float(pfield[:, :, 0][temperature_valid].max()) - float(field[:, :, 0][temperature_valid].max())))
        run_field_errors.append(float(error[temperature_valid].mean()))
    def describe(parts):
        values = np.concatenate(parts) if parts else np.array([])
        return {"mae": float(values.mean()), "p95_absolute_error": float(np.quantile(values, .95))} if len(values) else None
    return {"frames": len(indices), "runs": len(peak_errors),
            "metric_errors": {key: describe(parts) for key, parts in zip(METRICS, metric_errors)},
            "field_errors": {key: describe(parts) for key, parts in zip(
                ["temperature_c", "oxygen_percent", "smoke_kg_m3", "u_m_s", "v_m_s", "w_m_s"], channel_errors)},
            "run_temperature_peak_mae_c": float(np.mean(peak_errors)) if peak_errors else None,
            "spatial_temperature_peak_mae_c": float(np.mean(spatial_peak_errors)) if spatial_peak_errors else None,
            "temperature_field_mae_run_balanced_c": float(np.mean(run_field_errors)) if run_field_errors else None,
            "heated_points_temperature_error_c": describe(hot_errors),
            "heated_points_definition": "valid gas observations with true T > ambient + 2 C",
            "aggregation": "field_errors and metric_errors are sample weighted; peak and run_balanced errors weight runs equally"}


def main():
    root = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    dataset = root / "datasets/pilot-v2"
    manifest_bytes = (dataset / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    records, xparts, yparts, mparts, splits, flat_rows = [], [], [], [], [], []
    scene_ids = {r["scene_id"] for r in manifest["runs"] if r["status"] == "completed"}
    if scene_ids != {"habitat", "cargo", "crossflow", "soyuz"}:
        raise RuntimeError("Training requires valid simulations from all four scenes, including Soyuz")
    if len(manifest["runs"]) < 96 or any(r["status"] != "completed" for r in manifest["runs"]):
        raise RuntimeError("The 96-run pilot must be complete before final training")
    expected = {(scene, family, gravity) for scene in scene_ids for family in range(12) for gravity in (.0001, 1.)}
    actual = [(r["scene_id"], r["parameter_family"], r["config"]["gravity_g"]) for r in manifest["runs"]]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Pilot contains duplicate or missing scene/family/gravity cases")
    offset = 0
    physical_scene_hashes = {}
    spatial_dir = dataset / "spatial"
    spatial_dir.mkdir(exist_ok=True)
    for run in manifest["runs"]:
        directory = dataset / run["relative_path"]
        blob = (directory / "result.json").read_bytes()
        if hashlib.sha256(blob).hexdigest() != run["result_sha256"]:
            raise ValueError("Dataset result checksum mismatch: " + run["id"])
        result = json.loads(blob)
        for key in ("engine_version", "compiler_version", "material_model_version"):
            if result["provenance"].get(key) != manifest[key]:
                raise ValueError(f"Mixed {key} in dataset: {run['id']}")
        scene = json.loads((directory / "scene.json").read_text(encoding="utf-8"))
        physical = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        fingerprint = hashlib.sha256(json.dumps({"scene": scene, "config": run["config"],
            "compiler": manifest["compiler_version"], "material_model": manifest["material_model_version"]}, sort_keys=True).encode()).hexdigest()
        if fingerprint != run["fingerprint"]:
            raise ValueError("Saved scene/config changed: " + run["id"])
        checks = {"scene_sha256": canonical_sha(scene), "config_sha256": canonical_sha(physical["config"]),
                  "input_sha256": hashlib.sha256((directory / "ignis.fds").read_bytes()).hexdigest()}
        if any(result["provenance"].get(key) != value for key, value in checks.items()):
            raise ValueError("Physical provenance mismatch: " + run["id"])
        from ignis.ml.features import geometry
        rebuilt = geometry(scene, run["config"])
        if rebuilt["deck_sha256"] != physical["deck_sha256"] or rebuilt["sampling"] != physical["sampling"]:
            raise ValueError("Saved geometry or deck differs from compiler reconstruction: " + run["id"])
        identity = physical_scene_sha(scene)
        if scene["id"] in physical_scene_hashes and physical_scene_hashes[scene["id"]] != identity:
            raise ValueError("One scene ID has multiple physical geometries")
        physical_scene_hashes[scene["id"]] = identity
        times = [frame["time_s"] for frame in result["frames"]]
        x = features(scene, run["config"], physical, times)
        y, mask = encode_result(result, run["config"])
        xparts.append(x)
        yparts.append(y)
        mparts.append(mask)
        splits.extend([run["split"]]*len(x))
        records.append({**run, "start": offset, "end": offset+len(x)})
        offset += len(x)
        for row in result["metrics"]:
            flat_rows.append({"run_id": run["id"], "family_id": run["family_id"], "split": run["split"],
                              "origin": "simulation", **{k:v for k,v in run["config"].items() if isinstance(v,(int,float,str))},
                              **{key: row[key] for key in ["time_s", *METRICS]}})
        fields = {key: np.asarray([f[key] for f in result["frames"]], dtype=np.float32)
                  for key in ["temperature_c", "oxygen_percent", "smoke_kg_m3", "velocity_m_s"]}
        np.savez_compressed(spatial_dir / (run["id"] + ".npz"), time_s=np.array(times),
                            valid_mask=np.array(result["frames"][0]["valid_mask"]),
                            positions_m=np.array(result["frames"][0]["sample_positions_m"]), **fields)
    pq.write_table(pa.Table.from_pylist(flat_rows), dataset / "metrics.parquet", compression="zstd")
    X, Y, M = map(lambda parts: np.concatenate(parts).astype(np.float32), [xparts, yparts, mparts])
    splits = np.array(splits)
    groups = {split: np.flatnonzero(splits == split) for split in ["train", "validation", "test"]}
    families = {split: {r["family_id"] for r in records if r["split"] == split} for split in groups}
    assert not (families["train"] & families["test"] or families["train"] & families["validation"])
    assert not families["test"] & families["validation"]
    assert all(r["scene_id"] != "crossflow" for r in records if r["split"] == "train")
    output = root / "runtime/models"
    output.mkdir(parents=True, exist_ok=True)
    common = {"dataset_id": manifest["dataset_id"], "dataset_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
              "engine": "FDS 6.11.1", "mesh_cell_m": 0.2, "compiler_version": manifest["compiler_version"],
              "scientific_status": "learned_from_exploratory_fds", "trained_at": datetime.now(timezone.utc).isoformat(),
              "domain": {"scene_ids": sorted(scene_ids), "source_model": "prescribed_source",
                         "materials": ["cellulose", "pmma"], "gravity_values": [0.0001, 1.0],
                         "ranges": {"airflow_m_s": [0.05, 0.4], "oxygen_percent": [18, 24],
                                    "ignition_power_w": [500, 3000], "ignition_duration_s": [8, 25], "duration_s": [2, 60]}},
              "geometry_holdout": ["crossflow"], "input_features": X.shape[1], "output_features": Y.shape[1],
              "physical_scene_hashes": physical_scene_hashes, "physical_scene_hash_version": 2, "seed_conditioned": False,
              "observed_training_ranges": {key: [min(r["config"][key] for r in records if r["split"] == "train"),
                    max(r["config"][key] for r in records if r["split"] == "train")]
                    for key in ("airflow_m_s", "oxygen_percent", "ignition_power_w", "ignition_duration_s")},
              "training_counts": {key: {"frames": len(indices), "families": len(families[key]),
                                         "runs": sum(r["split"] == key for r in records)} for key, indices in groups.items()},
              "split_run_ids": {key: [r["id"] for r in records if r["split"] == key] for key in groups},
              "limitations": ["FDS synthetic labels; not an experimental NASA-trained flame predictor",
                              "Coarse mesh has not demonstrated convergence", "No coupled ignition prediction",
                              "Frame-level errors are temporally correlated; evaluation split uses entire scenario families"]}
    evaluation_groups = {**groups, "test_geometry": np.array([i for r in records if r["geometry_holdout"]
                                                               for i in range(r["start"], r["end"])], dtype=int),
                         "test_parameters": np.array([i for r in records if r["split"] == "test" and not r["geometry_holdout"]
                                                       for i in range(r["start"], r["end"])], dtype=int)}
    for scene_id in sorted(scene_ids):
        for label, gravity in [("microg", 0.0001), ("earth", 1.0)]:
            evaluation_groups[f"test_{scene_id}_{label}"] = np.array([i for r in records
                if r["split"] == "test" and r["scene_id"] == scene_id and r["config"]["gravity_g"] == gravity
                for i in range(r["start"], r["end"])], dtype=int)
    forest = ExtraTreesRegressor(n_estimators=160, min_samples_leaf=3, max_features=.85,
                                 n_jobs=4, random_state=20261114)
    start = time.perf_counter()
    forest.fit(X[groups["train"]], Y[groups["train"], POINTS*6:])
    baseline_pred = np.zeros_like(Y)
    baseline_pred[:, POINTS*6:] = forest.predict(X)
    apply_initial_thermodynamics(baseline_pred, X[:, 0])
    baseline_eval = {key: evaluate(baseline_pred, Y, M, records, indices) for key, indices in evaluation_groups.items() if key != "train"}
    for item in baseline_eval.values():
        item.pop("field_errors")
        for key in ("spatial_temperature_peak_mae_c", "temperature_field_mae_run_balanced_c",
                    "heated_points_temperature_error_c", "heated_points_definition"):
            item.pop(key)
    forest_dir = output / "metrics-forest-v2"
    forest_dir.mkdir(exist_ok=True)
    joblib.dump(forest, forest_dir / "weights.joblib", compress=3)
    metadata = {**common, "id": "metrics-forest-v2", "name": "Référence tabulaire · Extra Trees", "kind": "scalar_forest",
                "description": "Métriques temporelles uniquement, apprises sur les runs FDS du pilote.",
                "training_seconds": time.perf_counter()-start, "metrics": baseline_eval,
                "weights_sha256": hashlib.sha256((forest_dir/"weights.joblib").read_bytes()).hexdigest()}
    write_json(forest_dir / "metadata.json", metadata)
    print("BASELINE_TRAINED", json.dumps(baseline_eval), flush=True)
    if not torch.cuda.is_available():
        raise RuntimeError("The spatial model must train on the authorized Windows CUDA device")
    free, _ = torch.cuda.mem_get_info()
    if free < 4 * 1024**3:
        raise RuntimeError("Less than 4 GiB GPU memory free; retry after other workloads finish")
    torch.manual_seed(20261114)
    np.random.seed(20261114)
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda")
    net = network(X.shape[1], Y.shape[1]).to(device)
    train_x, train_y, train_m = [torch.from_numpy(a[groups["train"]]).to(device) for a in [X, Y, M]]
    val_x, val_y, val_m = [torch.from_numpy(a[groups["validation"]]).to(device) for a in [X, Y, M]]
    optimizer = torch.optim.AdamW(net.parameters(), lr=0.001, weight_decay=0.0001)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=240, eta_min=0.00005)
    history, best, best_state, best_epoch = [], float("inf"), None, 0
    start = time.perf_counter()
    for epoch in range(240):
        net.train()
        order = torch.randperm(len(train_x), device=device)
        total_loss = 0.0
        for batch in order.split(128):
            prediction = net(train_x[batch])
            weights = train_m[batch] * (1 + train_y[batch].abs().clamp(max=5)*0.5)
            weights[:, POINTS*6:] *= 4
            loss = ((prediction-train_y[batch]).square()*weights).sum()/weights.sum()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            optimizer.step()
            total_loss += float(loss.detach())
        scheduler.step()
        net.eval()
        with torch.inference_mode():
            vpred = net(val_x)
            validation = float(((vpred-val_y).square()*val_m).sum()/val_m.sum())
        history.append({"epoch": epoch+1, "train_loss": total_loss / len(order.split(128)), "validation_loss": validation})
        if validation < best - 1e-7:
            best, best_epoch = validation, epoch+1
            best_state = {key: value.detach().cpu().clone() for key,value in net.state_dict().items()}
        if (epoch+1) % 10 == 0:
            write_json(root / "runtime/training-progress.json", {"status": "training", "epoch": epoch+1,
                       "best_epoch": best_epoch, "best_validation_loss": best, "elapsed_s": time.perf_counter()-start})
            print("EPOCH", epoch+1, "validation", round(validation, 6), flush=True)
        if epoch+1-best_epoch >= 35:
            break
    net.load_state_dict(best_state)
    net.eval()
    with torch.inference_mode():
        predictions = np.concatenate([net(torch.from_numpy(X[i:i+256]).to(device)).cpu().numpy() for i in range(0,len(X),256)])
    apply_initial_thermodynamics(predictions, X[:, 0])
    evaluations = {key: evaluate(predictions, Y, M, records, indices) for key,indices in evaluation_groups.items() if key != "train"}
    ambient = np.zeros_like(Y)
    ambient_eval = evaluate(ambient, Y, M, records, groups["test"])
    neural_dir = output / "field-mlp-v2"
    neural_dir.mkdir(exist_ok=True)
    torch.save({"state_dict": best_state, "best_epoch": best_epoch}, neural_dir / "weights.pt")
    metadata = {**common, "id": "field-mlp-v2", "name": "Champ 3D · réseau conditionnel", "kind": "spatial_mlp",
                "description": "Champs thermiques, oxygène, suies et vitesse + métriques, prédits aux 320 points d’observation.",
                "training_seconds": time.perf_counter()-start, "best_epoch": best_epoch,
                "parameter_count": sum(p.numel() for p in net.parameters()), "device": torch.cuda.get_device_name(),
                "metrics": evaluations, "ambient_reference_test": ambient_eval,
                "peak_gpu_memory_mb": torch.cuda.max_memory_allocated()/1024**2,
                "weights_sha256": hashlib.sha256((neural_dir/"weights.pt").read_bytes()).hexdigest()}
    write_json(neural_dir / "metadata.json", metadata)
    write_json(neural_dir / "training-history.json", {"history": history})
    for model_dir in [neural_dir, forest_dir]:
        loaded = Surrogate.load(model_dir)
        assert np.isfinite(loaded.encoded(X[:2])).all()
    write_json(root / "runtime/training-progress.json", {"status": "completed", "models": ["field-mlp-v2", "metrics-forest-v2"],
               "best_epoch": best_epoch, "dataset_runs": len(records), "dataset_frames": len(X), "spatial_test_metrics": evaluations})
    print("TRAINING_COMPLETE", json.dumps(evaluations), flush=True)


if __name__ == "__main__":
    project_root = Path(os.getenv("IGNIS_HOME", "E:/IGNIS-Valley"))
    with ProcessLock(project_root / "datasets/pilot-v2/generation.lock"), ProcessLock(project_root / "runtime/compute.lock"):
        try:
            write_json(project_root / "runtime/training-progress.json", {"status": "training", "phase": "integrity_checks"})
            main()
        except Exception:
            write_json(project_root / "runtime/training-progress.json", {"status": "failed"})
            raise
