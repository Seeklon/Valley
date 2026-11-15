"""Bounded retraining of the existing heat/smoke U-Net, with frozen-v1 comparisons.

Architecture, physical targets, feature encoder and inference loader stay unchanged.
Only new training layouts update weights; all selection uses new validation layouts.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
import torch
from ignis.locking import ProcessLock
from ignis.ml.spatial_dataset import file_sha, read_spatial_index
from ignis.ml.spatial_network import STATIC_CHANNELS
from ignis.provenance import canonical_sha
from iss_poc_model import (
    HEAT_DELTA_C,
    MODEL_ID,
    OUTPUTS,
    SCHEMA_VERSION,
    SCORE_SEMANTICS,
    SMOKE_THRESHOLD_KG_M3,
    ISSClassifier,
    ISSPredictor,
    architecture,
    input_tensor,
)
from train_hotspot_poc import (
    check_budget,
    compact_json,
    load_partition,
    proximity_scores,
    utc_now,
)
from train_iss_poc import (
    METRIC_FILTER,
    SELECTION,
    assess_field,
    benchmark_batches,
    dual_balanced_bce,
    evaluation_mask,
    examples,
    export_case,
    inference_benchmark,
    module_id,
    predict_cases,
    prepare_cuda,
    select_thresholds,
    start_telemetry,
    stop_telemetry,
    targets,
)
from train_spatial import CaseStore, ProgressLog, source_hashes, write_json
from verify_spatial import state_sha

SEED = 2026111502
DATASET_ID = "iss-poc-20261115-v2"
TRAINING_VERSION = "heat-smoke-retraining-20261115-v2"
V1_WEIGHTS_SHA256 = "6ab66833116e2b5b1a514a4cf2fa9095e370a38f93a946f9d497fabc4dbd3392"
FAMILIES = {
    "iss-laboratory",
    "iss-node",
    "iss-service",
    "habitat-cargo",
    "habitat-capsule",
    "habitat-central-racks",
}
LIMITATIONS = [
    "Réentraînement du même U-Net 3D sur six familles de compartiments synthétiques, dont trois inspirées de l'ISS.",
    "Capsule, racks et soute sont des géométries rectangulaires simplifiées, pas des plans de véhicules réels.",
    "La source électrique est imposée. Le modèle ne prédit pas sa probabilité d'allumage.",
    "Chaleur : T FDS >= température ambiante + 5 °C. Fumée : suie FDS >= 1e-6 kg/m³.",
    "Les scores ML ne sont ni des températures, ni des concentrations, ni des probabilités d'incendie.",
    "Les champs affichés sont des prédictions aux sondes, sans mesure validée entre les sondes.",
    "Données FDS synthétiques : aucune validation expérimentale NASA ni garantie de sécurité.",
    "Familles communes aux partitions ; dispositions et géométries disjointes, y compris vis-à-vis de toute la v1.",
    "Test de nouvelles dispositions de familles connues, pas preuve de généralisation à des familles ou stations réelles inconnues.",
]


class RetrainingCaseStore(CaseStore):
    """Dedicated six-family policy; inherited reconstruction/label checks unchanged."""

    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        path = self.directory / "manifest.json"
        self.source_sha = file_sha(path)
        original = read_spatial_index(self.directory)
        if file_sha(path) != self.source_sha:
            raise ValueError("Retraining manifest changed during snapshot acquisition")
        if original["dataset_id"] != DATASET_ID:
            raise ValueError("Retraining requires the exact v2 dataset ID")
        records = original["runs"]
        if len(records) != original.get("expected_runs", len(records)) or any(
            record.get("status", "completed") != "completed" for record in records
        ):
            raise ValueError("Retraining dataset must be complete before fitting")
        if not records or len({record["id"] for record in records}) != len(records):
            raise ValueError("Empty retraining dataset or duplicate case IDs")
        self.records = copy.deepcopy(records)
        self.by_split = {split: [] for split in ("train", "validation", "test")}
        layouts, families = {}, {split: set() for split in self.by_split}
        for index, record in enumerate(self.records):
            layout, split, family = record.get("layout_id"), record["split"], record.get("structural_family")
            if not layout or split not in self.by_split or family not in FAMILIES:
                raise ValueError(
                    "Retraining case needs a valid layout, split and one of the six named families"
                )
            if layout in layouts and layouts[layout] != split:
                raise ValueError("Retraining layout leakage across partitions")
            if Path(record["id"]).name != record["id"] or "/" in record["id"] or "\\" in record["id"]:
                raise ValueError("Unsafe retraining case identifier")
            layouts[layout] = split
            families[split].add(family)
            self.by_split[split].append(index)
        if any(values != FAMILIES for values in families.values()):
            raise ValueError("Each retraining split must cover the same six named families")
        self.snapshot = {
            "dataset_id": original["dataset_id"],
            "partition_policy": "six known families; disjoint layouts and reconstructed physical geometry",
            "source_manifest_sha256": self.source_sha,
            "source_merged_index_sha256": canonical_sha(original),
            "source_expected_runs": original.get("expected_runs", len(records)),
            "partial": False,
            "runs": self.records,
        }
        self.cache, self.frames, self.shape = OrderedDict(), {}, None


def normalized_geometry(manifest):
    """Ignore names, materials and overall scale when comparing object layouts."""
    bounds = np.asarray(manifest["sampling"]["bounds_m"], dtype=np.float64)
    boxes = [
        np.round(np.asarray(obj["bounds_m"], dtype=np.float64).reshape(3, 2) / bounds[:, None], 8)
        .reshape(-1)
        .tolist()
        for obj in manifest["objects"]
    ]
    return canonical_sha(sorted(boxes))


def verify_disjointness(store, previous_snapshot, previous_dataset, expected_snapshot_sha):
    """Use v1 input manifests only; do not read its observations or test metrics."""
    previous = json.loads(Path(previous_snapshot).read_text(encoding="utf-8"))
    if canonical_sha(previous) != expected_snapshot_sha or previous["dataset_id"] != "iss-poc-20261115-v1":
        raise ValueError("Warm-start snapshot is not the frozen v1 training artifact")
    old_layouts = {record["layout_id"] for record in previous["runs"]}
    old_physical = {record["geometry_signature"] for record in previous["runs"]}
    old_normalized, seen = set(), set()
    previous_dataset = Path(previous_dataset).resolve()
    for record in previous["runs"]:
        if record["layout_id"] in seen:
            continue
        manifest_path = (previous_dataset / record["relative_path"] / "manifest.json").resolve()
        if not manifest_path.is_relative_to(previous_dataset):
            raise ValueError("Prior manifest path leaves its dataset")
        if file_sha(manifest_path) != record["file_hashes"]["manifest.json"]:
            raise ValueError("Prior compiled geometry no longer matches its frozen snapshot")
        old_normalized.add(normalized_geometry(json.loads(manifest_path.read_text(encoding="utf-8"))))
        seen.add(record["layout_id"])
    normalized_splits = {}
    for index, record in enumerate(store.records):
        if record["layout_id"] in old_layouts or record["geometry_signature"] in old_physical:
            raise ValueError("New retraining geometry overlaps the already examined v1 corpus")
        signature = normalized_geometry(store.get(index)["manifest"])
        if signature in old_normalized:
            raise ValueError("New retraining geometry is a scaled copy of a v1 layout")
        if signature in normalized_splits and normalized_splits[signature] != record["split"]:
            raise ValueError("Normalized geometry leakage across new partitions")
        normalized_splits[signature] = record["split"]
    return {
        "previous_dataset_sha256": expected_snapshot_sha,
        "previous_layout_count": len(old_layouts),
        "new_layout_count": len({record["layout_id"] for record in store.records}),
        "new_normalized_geometry_count": len(normalized_splits),
        "all_v1_partitions_excluded": True,
        "physical_geometry_overlap": 0,
        "normalized_geometry_overlap": 0,
        "normalized_geometry_partition_overlap": 0,
    }


class FactorizedTrainingCache:
    """Store static geometry once per case and broadcast only the sampled batch."""

    def __init__(self, cases, device="cuda:0"):
        if not cases or any(case["record"]["split"] != "train" for case in cases):
            raise ValueError("Retraining cache accepts training cases only")
        if len({tuple(case["shape"]) for case in cases}) != 1:
            raise ValueError("Retraining grids must have identical shapes")
        columns = {name: [] for name in ("condition", "case", "y", "mask")}
        probabilities = []
        for case_index, case in enumerate(cases):
            truth, observed = targets(case)
            frames = np.flatnonzero(case["time_s"] > 0)
            if not len(frames) or not observed[frames].reshape(len(frames), -1).any(1).all():
                raise ValueError("Missing post-initial retraining observations")
            active = truth[frames].reshape(len(frames), -1).any(1)
            weights = np.full(len(frames), 1 / len(frames))
            if active.any():
                weights = 0.5 * weights + 0.5 * active / active.sum()
            probabilities.extend(weights / len(cases))
            for frame in frames:
                values = input_tensor(case["static"], case["config"], case["manifest"], case["time_s"][frame])
                condition = values[len(STATIC_CHANNELS) :, 0, 0, 0].copy()
                if not np.array_equal(
                    values[len(STATIC_CHANNELS) :],
                    np.broadcast_to(condition[:, None, None, None], values[len(STATIC_CHANNELS) :].shape),
                ):
                    raise ValueError("Condition channels must be spatially constant for factorized caching")
                columns["condition"].append(condition)
                columns["case"].append(case_index)
                columns["y"].append(truth[frame].T.reshape(2, *case["shape"]))
                columns["mask"].append(observed[frame].T.reshape(2, *case["shape"]))
        self.static = torch.as_tensor(np.stack([case["static"] for case in cases]), device=device)
        self.condition = torch.as_tensor(np.stack(columns["condition"]), device=device)
        self.case = torch.as_tensor(columns["case"], device=device, dtype=torch.long)
        self.y = torch.as_tensor(np.stack(columns["y"]), device=device)
        self.mask = torch.as_tensor(np.stack(columns["mask"]), device=device)
        self.probability = torch.as_tensor(probabilities, device=device, dtype=torch.float32)
        if not np.isclose(sum(probabilities), 1) or min(probabilities) <= 0:
            raise ValueError("Every training time must retain positive sampling probability")
        self.bytes = sum(
            value.numel() * value.element_size()
            for value in (self.static, self.condition, self.case, self.y, self.mask, self.probability)
        )
        self.frames = len(probabilities)

    def gather(self, indices):
        indices = torch.as_tensor(indices, device=self.case.device, dtype=torch.long)
        static = self.static.index_select(0, self.case.index_select(0, indices))
        condition = self.condition.index_select(0, indices)[:, :, None, None, None]
        values = torch.cat([static, condition.expand(-1, -1, *static.shape[2:])], dim=1)
        return values, self.y.index_select(0, indices), self.mask.index_select(0, indices)

    def batch(self, size):
        return self.gather(torch.multinomial(self.probability, size, replacement=True))


def metrics_for(cases, scores, thresholds):
    return {name: assess_field(cases, scores, thresholds[name], i) for i, name in enumerate(OUTPUTS)}


def run(args):
    runtime = args.runtime or args.dataset.resolve().parent.parent / "runtime"
    args.compute_lock_path = Path(runtime).resolve() / "compute.lock"
    with ProcessLock(args.compute_lock_path):
        return _run_locked(args)


def _run_locked(args):
    dataset, output = args.dataset.resolve(), args.output.resolve()
    if output == dataset or output.is_relative_to(dataset):
        raise ValueError("Retraining output must remain outside the immutable FDS dataset")
    output.mkdir(parents=True, exist_ok=False)
    log = ProgressLog(output / "progress.jsonl")
    started = time.monotonic()
    deadline = started + args.seconds
    telemetry_process = telemetry_stream = None
    try:
        write_json(
            output / "compute-lock.json",
            {
                "path": str(args.compute_lock_path),
                "owner_pid": os.getpid(),
                "mechanism": "OS-owned exclusive ProcessLock",
                "scope": "entire verified retraining, evaluation and export",
                "acquired_before_cuda": True,
            },
        )
        torch.set_num_threads(4)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        torch.manual_seed(SEED)
        original = ISSPredictor(args.warm_start, expected_sha256=V1_WEIGHTS_SHA256)
        if original.metadata["architecture"] != architecture(16):
            raise ValueError("Retraining must use the unchanged width-16 v1 architecture")
        old_state = {
            key: value.detach().cpu().clone() for key, value in original.network.state_dict().items()
        }
        old_thresholds = dict(original.thresholds)
        warm_start = {
            "weights_sha256": original.weights_sha256,
            "state_sha256": state_sha(original.network),
            "dataset_sha256": original.metadata["dataset_sha256"],
            "score_thresholds": old_thresholds,
            "optimizer_state_reused": False,
            "architecture_unchanged": True,
        }
        del original
        compute = prepare_cuda()
        telemetry_process, telemetry_stream = start_telemetry(output, log)
        torch.cuda.manual_seed_all(SEED)
        log.emit(
            "retraining_started",
            pid=os.getpid(),
            budget_seconds=args.seconds,
            warm_start=warm_start,
            **compute,
        )
        store = RetrainingCaseStore(dataset)
        store.verify(log)
        check_budget(deadline)
        if tuple(store.shape) != (12, 16, 8):
            raise ValueError("Retraining requires verified 12x16x8 observation grids")
        disjoint = verify_disjointness(
            store, args.previous_snapshot, args.previous_dataset, warm_start["dataset_sha256"]
        )
        write_json(output / "geometry-disjointness.json", disjoint)
        write_json(output / "dataset-snapshot.json", store.snapshot)
        source = source_hashes()
        for name in (
            "train_iss_poc_v2.py",
            "train_iss_poc.py",
            "iss_poc_model.py",
            "train_hotspot_poc.py",
            "verify_spatial.py",
        ):
            source["tools/remote/" + name] = file_sha(Path(__file__).with_name(name))
        write_json(output / "sources.json", source)
        partitions = {split: load_partition(store, split) for split in ("train", "validation")}
        nearby_validation = [
            np.repeat(proximity_scores(case)[..., None], 2, axis=-1) for case in partitions["validation"]
        ]
        baseline = select_thresholds(partitions["validation"], nearby_validation)
        write_json(output / "baseline-validation-selection.json", baseline)
        network = ISSClassifier(16).to("cuda:0")
        network.load_state_dict(old_state, strict=True)
        original_validation_scores = predict_cases(network, partitions["validation"], deadline)
        original_recalibration = select_thresholds(partitions["validation"], original_validation_scores)
        write_json(output / "v1-recalibrated-validation-selection.json", original_recalibration)
        write_json(
            output / "v1-frozen-validation.json",
            metrics_for(partitions["validation"], original_validation_scores, old_thresholds),
        )
        best = {**original_recalibration, "step": 0}
        best_state = copy.deepcopy(old_state)
        log.emit(
            "warm_start_validation", value=best["value"], score_thresholds=best["score_thresholds"], step=0
        )
        cache = FactorizedTrainingCache(partitions["train"])
        log.emit(
            "device_cache_ready",
            bytes=cache.bytes,
            frames=cache.frames,
            cases=len(partitions["train"]),
            factorized=True,
        )
        throughput = []
        if args.benchmark_batches:
            args.batch_size, throughput = benchmark_batches(network, cache, deadline, log)
        # Throughput benchmarking restores weights; restore this run's distinct seed too.
        torch.manual_seed(SEED)
        torch.cuda.manual_seed_all(SEED)
        write_json(output / "throughput.json", {"selected_batch_size": args.batch_size, "rows": throughput})
        optimizer = torch.optim.AdamW(
            (p for p in network.parameters() if p.requires_grad), lr=3e-4, weight_decay=1e-4
        )
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.steps, eta_min=5e-5)
        history, updates = [], 0
        training_started = time.monotonic()
        training_deadline = min(deadline - 240, training_started + args.training_seconds)
        for step in range(1, args.steps + 1):
            if time.monotonic() >= training_deadline or (output / "STOP").exists():
                break
            network.train()
            x, target, observed = cache.batch(args.batch_size)
            optimizer.zero_grad(set_to_none=True)
            loss = dual_balanced_bce(network(x), target, observed, validate=False).mean()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(network.parameters(), 5, error_if_nonfinite=False)
            optimizer.step()
            scheduler.step()
            updates += 1
            if step == 1:
                torch.cuda.synchronize()
                log.emit(
                    "cuda_training_started",
                    optimizer_step_completed=True,
                    device="cuda:0",
                    device_name=compute["device_name"],
                    loss=float(loss.item()),
                    parameters=sum(p.numel() for p in network.parameters()),
                    allocated_bytes=torch.cuda.memory_allocated(),
                )
            if step % args.validate_every == 0:
                if not torch.isfinite(loss).item():
                    raise ValueError("Nonfinite retraining class loss")
                scores = predict_cases(network, partitions["validation"], deadline)
                selection = select_thresholds(partitions["validation"], scores)
                improved = selection["value"] > best["value"]
                if improved:
                    best = {**selection, "step": step}
                    best_state = {
                        key: value.detach().cpu().clone() for key, value in network.state_dict().items()
                    }
                row = {
                    "step": step,
                    "loss": float(loss.item()),
                    "learning_rate": scheduler.get_last_lr()[0],
                    "value": selection["value"],
                    "score_thresholds": selection["score_thresholds"],
                    "improved": improved,
                    "best_step": best["step"],
                    "fields": {
                        key: value["metrics"]["groups"]["microgravity"]
                        for key, value in selection["fields"].items()
                    },
                }
                history.append(row)
                write_json(output / f"validation-step-{step:06d}.json", selection)
                log.emit("validation", **row)
        training_seconds = time.monotonic() - training_started
        network.load_state_dict(best_state, strict=True)
        frozen_sha = state_sha(network)
        thresholds = best["score_thresholds"]
        improvement = best["value"] - original_recalibration["value"]
        write_json(
            output / "frozen-selection.json",
            {
                "selected_at": utc_now(),
                "step": best["step"],
                "score_thresholds": thresholds,
                "selection_metric": SELECTION,
                "value": best["value"],
                "state_sha256": frozen_sha,
                "test_labels_used_for_selection": False,
                "baseline_thresholds": baseline["score_thresholds"],
                "v1_frozen_thresholds": old_thresholds,
                "v1_recalibrated_thresholds": original_recalibration["score_thresholds"],
                "v1_recalibrated_validation_value": original_recalibration["value"],
                "validation_weight_improvement": improvement,
                "new_weights_selected": best["step"] > 0,
            },
        )
        weights = output / "weights.pt"
        payload = {
            "id": MODEL_ID,
            "schema_version": SCHEMA_VERSION,
            "architecture": architecture(16),
            "sample_shape": list(store.shape),
            "score_thresholds": thresholds,
            "selected_step": best["step"],
            "dataset_sha256": store.snapshot_sha,
            "state_dict": best_state,
            "training_version": TRAINING_VERSION,
            "warm_start": warm_start,
        }
        with weights.open("xb") as stream:
            torch.save(payload, stream)
        reloaded = ISSPredictor(weights)
        if state_sha(reloaded.network) != frozen_sha:
            raise RuntimeError("Existing inference loader changed the selected retrained state")
        del reloaded, best_state, optimizer, scheduler, cache
        if updates:
            del x, target, observed, loss
        torch.cuda.empty_cache()
        log.emit(
            "selection_frozen",
            step=best["step"],
            state_sha256=frozen_sha,
            score_thresholds=thresholds,
            validation_weight_improvement=improvement,
        )
        # No test prediction or test summary occurs before every selection decision is frozen.
        partitions["test"] = load_partition(store, "test")
        old_network = ISSClassifier(16).to("cuda:0")
        old_network.load_state_dict(old_state, strict=True)
        demo = output / "demo"
        (demo / "cases").mkdir(parents=True)
        audit = output / "comparison-scores"
        audit.mkdir()
        metrics, baselines, comparisons, rows = {}, {}, {}, []
        for split, cases in partitions.items():
            scores = predict_cases(network, cases, deadline)
            metrics[split] = metrics_for(cases, scores, thresholds)
            nearby = [np.repeat(proximity_scores(case)[..., None], 2, axis=-1) for case in cases]
            zeros = [np.zeros_like(value) for value in scores]
            baselines[split] = {
                name: {
                    "all_cold": assess_field(cases, zeros, 0.5, i),
                    "source_proximity": assess_field(cases, nearby, baseline["score_thresholds"][name], i),
                }
                for i, name in enumerate(OUTPUTS)
            }
            if split != "train":
                old_scores = (
                    original_validation_scores
                    if split == "validation"
                    else predict_cases(old_network, cases, deadline)
                )
                score_path = audit / ("v1-" + split + ".npz")
                np.savez_compressed(
                    score_path, **{case["record"]["id"]: score for case, score in zip(cases, old_scores)}
                )
                comparisons[split] = {
                    "v1_frozen": metrics_for(cases, old_scores, old_thresholds),
                    "v1_recalibrated": metrics_for(
                        cases, old_scores, original_recalibration["score_thresholds"]
                    ),
                    "v1_score_archive": {
                        "relative_path": str(score_path.relative_to(output)).replace("\\", "/"),
                        "sha256": file_sha(score_path),
                    },
                    "same_cases_as_retrained_model": True,
                }
            for number, (case, score) in enumerate(zip(cases, scores)):
                check_budget(deadline)
                record, config = case["record"], case["config"]
                metric = {name: metrics[split][name]["cases"][number] for name in OUTPUTS}
                case_path = demo / "cases" / (record["id"] + ".json")
                export_case(case_path, case, score, thresholds, metric)
                mask = evaluation_mask(case)
                rows.append(
                    {
                        "id": record["id"],
                        "split": split,
                        "layout_id": record["layout_id"],
                        "family": module_id(case),
                        "module_id": module_id(case),
                        "evaluation_role": "unseen_layout_known_module_family" if split == "test" else split,
                        **{
                            key: config[key]
                            for key in ("gravity_g", "incident_type", "ambient_temperature_c", "airflow_m_s")
                        },
                        "peak_temperature_c": float(np.max(case["temperature_c"][mask[..., 0]])),
                        "peak_soot_kg_m3": float(np.max(case["smoke_kg_m3"][mask[..., 1]])),
                        "metrics": metric,
                        "url": "./cases/" + record["id"] + ".json",
                        "sha256": file_sha(case_path),
                    }
                )
            log.emit(
                "partition_exported",
                split=split,
                cases=len(cases),
                metrics={name: metric["groups"]["microgravity"] for name, metric in metrics[split].items()},
            )
        inference = inference_benchmark(weights, partitions["validation"][0], network, deadline)
        write_json(output / "inference-benchmark.json", inference)
        compute_seconds = time.monotonic() - started
        peak_bytes = torch.cuda.max_memory_allocated()
        del network, old_network
        torch.cuda.empty_cache()
        telemetry = stop_telemetry(telemetry_process, telemetry_stream, output)
        telemetry_process = telemetry_stream = None
        write_json(output / "gpu-telemetry-summary.json", telemetry)
        if compute_seconds > args.seconds:
            raise TimeoutError("Retraining exceeded its declared compute budget")
        model = {
            "id": MODEL_ID,
            "name": "U-Net 3D réentraîné — chaleur et fumée / six compartiments",
            "trained_at": utc_now(),
            "training_version": TRAINING_VERSION,
            "warm_start": warm_start,
            "device": compute["device_name"],
            "training_seconds": training_seconds,
            "total_compute_seconds": compute_seconds,
            "weights_sha256": file_sha(weights),
            "state_sha256": frozen_sha,
            "dataset_sha256": store.snapshot_sha,
            "heat_delta_c": HEAT_DELTA_C,
            "smoke_threshold_kg_m3": SMOKE_THRESHOLD_KG_M3,
            "score_thresholds": thresholds,
            "score_semantics": SCORE_SEMANTICS,
            "architecture": architecture(16),
            "selected_step": best["step"],
            "optimizer_steps": updates,
            "batch_size": args.batch_size,
            "seed": SEED,
            "selection_metric": SELECTION,
            "selection_split": "validation",
            "new_weights_selected": best["step"] > 0,
            "validation_weight_improvement": improvement,
        }
        chosen = examples(rows)
        index = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": utc_now(),
            "model": model,
            "metrics_time_filter": METRIC_FILTER,
            "metrics": metrics,
            "baselines": baselines,
            "baseline_source_proximity_thresholds": baseline["score_thresholds"],
            "baseline_source_proximity_radius_m": {
                name: -math.log(value) if value <= 1 else None
                for name, value in baseline["score_thresholds"].items()
            },
            "comparisons": comparisons,
            "comparison_thresholds": {
                "v1_frozen": old_thresholds,
                "v1_recalibrated": original_recalibration["score_thresholds"],
            },
            "cases": rows,
            "default_case_id": chosen["representative"],
            "example_cases": chosen,
            "example_selection": "Validation microgravity only: lower median mean heat/smoke IoU among active cases per module; lowest mean IoU failure; first ID jointly inactive control. All cases accessible.",
            "limitations": LIMITATIONS,
        }
        compact_json(demo / "index.json", index)
        write_json(
            output / "report.json",
            {
                **index,
                "throughput_benchmark": throughput,
                "compute": compute,
                "inference_benchmark": inference,
                "gpu_telemetry": telemetry,
                "peak_allocator_bytes": peak_bytes,
                "budget_seconds": args.seconds,
                "history": history,
                "loss": "unchanged: equal heat/smoke field mass; equal positive/background BCE per observed active field; cold false positives retained",
                "sampler": "equal case mass; half uniform times, half either-field-active times where available",
                "optimizer": {
                    "name": "AdamW",
                    "initial_lr": 3e-4,
                    "weight_decay": 1e-4,
                    "schedule": "cosine",
                    "minimum_lr": 5e-5,
                },
                "source_hashes": source,
                "reload_state_match": True,
                "geometry_disjointness": disjoint,
            },
        )
        log.emit(
            "completed",
            model=model,
            cases_exported=len(rows),
            output=str(output),
            peak_allocator_bytes=peak_bytes,
        )
    except BaseException as exc:
        log.emit("failed", error=type(exc).__name__, message=str(exc))
        raise
    finally:
        if telemetry_process is not None:
            stop_telemetry(telemetry_process, telemetry_stream, output)
        log.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "output", "warm-start", "previous-snapshot", "previous-dataset"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--training-seconds", type=int, default=300)
    parser.add_argument("--steps", type=int, default=20000)
    parser.add_argument("--batch-size", type=int, choices=(32, 64, 128, 256), default=64)
    parser.add_argument("--validate-every", type=int, default=1000)
    parser.add_argument("--benchmark-batches", action="store_true")
    args = parser.parse_args(argv)
    if (
        not 300 <= args.seconds <= 600
        or not 30 <= args.training_seconds <= 300
        or not 1000 <= args.steps <= 30000
        or not 250 <= args.validate_every <= 1000
    ):
        parser.error(
            "Require 300..600 seconds total, 30..300 training seconds, 1000..30000 steps, 250..1000 validation interval"
        )
    return args


if __name__ == "__main__":
    run(parse_args())
