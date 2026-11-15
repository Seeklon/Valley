"""Bounded, validation-selected ventilation adaptation of the unchanged V2 U-Net.

Only training examples are reflected. Their physical coordinates, source and
boundary vectors move with labels and masks. No new CFD is claimed by reflection.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
import torch
from evaluate_iss_ventilation import paired_metrics
from ignis.locking import ProcessLock
from ignis.ml.spatial_dataset import file_sha, read_spatial_index
from ignis.ml.spatial_network import CHANNELS
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
)
from train_hotspot_poc import check_budget, compact_json, load_partition, utc_now
from train_iss_poc import (
    METRIC_FILTER,
    dual_balanced_bce,
    evaluation_mask,
    examples,
    export_case,
    inference_benchmark,
    predict_cases,
    prepare_cuda,
    select_thresholds,
    start_telemetry,
    stop_telemetry,
)
from train_iss_poc_v2 import FAMILIES, LIMITATIONS, FactorizedTrainingCache, metrics_for
from train_spatial import CaseStore, ProgressLog, source_hashes, write_json
from verify_spatial import state_sha

DATASET_ID = "iss-poc-20261115-vent"
SEED = 2026111503
TRAINING_VERSION = "heat-smoke-ventilation-20261115"
V2_WEIGHTS_SHA256 = "37bf3e0c5394cbe52fe520ebf85cbf393cd9b4203751d5b1db5c0c79641f987a"
SELECTION = {
    "thresholds": "same macro-family microgravity F1 rule on V2+fresh validation",
    "checkpoint": "0.75 combined validation macro-family F1 + 0.25 fresh validation macro-family signed ventilation-change F1; equal heat/smoke mass",
    "old_validation_macro_f1_tolerance": 0.02,
    "combined_microgravity_precision_tolerance_per_field": 0.03,
    "combined_microgravity_recall_must_not_decrease_per_field": True,
    "explicit_zero_power_controls_false_positives": 0,
    "must_improve_composite_and_paired_over_recalibrated_v2": True,
    "test_used_for_selection": False,
}


def reflect_xy(values, target, observed, axes):
    """Reflect a complete batch around physical X/Y midplanes, preserving Z-up.

    Source-normalized coordinates are absolute fractions; displacement and
    velocity channels are signed vectors. The snapped sample coordinates need
    not be symmetric: retain 1-flipped_coordinate, never recreate a regular grid.
    """
    axes = tuple(axes)
    if len(set(axes)) != len(axes) or any(axis not in (0, 1) for axis in axes):
        raise ValueError("Only distinct horizontal X/Y reflections are supported")
    if values.ndim != 5 or values.shape[1] != len(CHANNELS):
        raise ValueError("Reflection requires the complete 54-channel input")
    if target.shape != observed.shape or target.shape != (values.shape[0], 2, *values.shape[2:]):
        raise ValueError("Reflection labels and individual observation masks must align")
    if not axes:
        return values, target, observed
    dims = tuple(axis + 2 for axis in axes)
    reflected = torch.flip(values, dims)
    for axis in axes:
        letter, velocity = ("x", "u") if axis == 0 else ("y", "v")
        coord = "x_over_width" if axis == 0 else "y_over_depth"
        for name in (coord, "source_" + letter + "_scaled"):
            reflected[:, CHANNELS.index(name)] = 1 - reflected[:, CHANNELS.index(name)]
        for name in ("source_d" + letter, "boundary_" + velocity + "_scaled"):
            reflected[:, CHANNELS.index(name)].neg_()
    return reflected, torch.flip(target, dims), torch.flip(observed, dims)


class VentilationTrainingCache(FactorizedTrainingCache):
    """Equal corpus mass, equal cases within corpus, all observed times retained."""

    def __init__(self, previous_cases, fresh_cases, device="cuda:0"):
        if not previous_cases or not fresh_cases:
            raise ValueError("Both previous and fresh training corpora are required")
        super().__init__([*previous_cases, *fresh_cases], device=device)
        previous = self.case < len(previous_cases)
        self.probability[previous] *= 0.5 / self.probability[previous].sum()
        self.probability[~previous] *= 0.5 / self.probability[~previous].sum()
        self.rng = np.random.default_rng(SEED)

    def batch(self, size):
        values = super().batch(size)
        choice = int(self.rng.integers(4))
        return reflect_xy(*values, tuple(axis for axis in (0, 1) if choice & (1 << axis)))


class VentilationCaseStore(CaseStore):
    """Whole-layout partitions, complete ventilation quartets and six families."""

    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.source_sha = file_sha(self.directory / "manifest.json")
        original = read_spatial_index(self.directory)
        if file_sha(self.directory / "manifest.json") != self.source_sha:
            raise ValueError("Ventilation index changed during acquisition")
        records = original["runs"]
        if original["dataset_id"] != DATASET_ID or original["expected_runs"] != 216 or len(records) != 216:
            raise ValueError("Require the complete 216-case ventilation dataset")
        if len({row["id"] for row in records}) != len(records):
            raise ValueError("Duplicate ventilation case IDs")
        self.records = copy.deepcopy(records)
        self.by_split = {split: [] for split in ("train", "validation", "test")}
        layouts, groups = {}, {}
        families = {split: set() for split in self.by_split}
        for index, record in enumerate(self.records):
            split, layout, family = record["split"], record["layout_id"], record["structural_family"]
            if (
                split not in self.by_split
                or family not in FAMILIES
                or not layout
                or record.get("status") != "completed"
            ):
                raise ValueError("Invalid ventilation case or unfinished simulation")
            if layout in layouts and layouts[layout] != split:
                raise ValueError("Ventilation layout leakage across partitions")
            if Path(record["id"]).name != record["id"] or "/" in record["id"] or "\\" in record["id"]:
                raise ValueError("Unsafe ventilation case ID")
            layouts[layout] = split
            families[split].add(family)
            self.by_split[split].append(index)
            group = record.get("ventilation_group_id")
            if group is not None:
                identity = (layout, split, record["ventilation_state"])
                groups.setdefault(group, []).append(identity)
        if [len(self.by_split[split]) for split in self.by_split] != [108, 54, 54]:
            raise ValueError("Ventilation split sizes must be 108/54/54")
        if len(layouts) != 24 or any(values != FAMILIES for values in families.values()):
            raise ValueError("Ventilation requires 24 layouts and all six families in each split")
        if len(groups) != 48 or any(
            len(rows) != 4
            or len({row[:2] for row in rows}) != 1
            or {row[2] for row in rows} != {"still", "slow", "fast", "reverse"}
            for rows in groups.values()
        ):
            raise ValueError("Incomplete or leaked ventilation quartet")
        self.snapshot = {
            "dataset_id": DATASET_ID,
            "source_manifest_sha256": self.source_sha,
            "source_merged_index_sha256": canonical_sha(original),
            "partial": False,
            "runs": self.records,
        }
        self.cache, self.frames, self.shape = OrderedDict(), {}, None

    def verify_before_selection(self, log):
        """Integrity-check only train/validation observations before freezing."""
        limited = copy.copy(self)
        limited.records = [record for record in self.records if record["split"] != "test"]
        limited.by_split = {
            split: [i for i, record in enumerate(limited.records) if record["split"] == split]
            for split in self.by_split
        }
        limited.snapshot = {**self.snapshot, "runs": limited.records}
        limited.cache, limited.frames = OrderedDict(), {}
        limited.verify(log)
        self.shape = limited.shape
        self.snapshot["sample_shape"] = list(self.shape)
        self.snapshot_sha = canonical_sha(self.snapshot)

    def verify_after_selection(self, log):
        """Enrich test provenance on an independent copy of the frozen snapshot."""
        verified = copy.copy(self)
        verified.records = copy.deepcopy(self.records)
        verified.snapshot = {**copy.deepcopy(self.snapshot), "runs": verified.records}
        verified.cache, verified.frames = OrderedDict(), {}
        verified.verify(log)
        return verified


def previous_store(dataset, snapshot_path, expected_sha):
    """Load the previously verified V2 snapshot; its test observations stay closed."""
    snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    if canonical_sha(snapshot) != expected_sha or snapshot["dataset_id"] != "iss-poc-20261115-v2":
        raise ValueError("Previous snapshot does not match the frozen V2 checkpoint")
    store = object.__new__(CaseStore)
    store.directory = Path(dataset).resolve()
    store.records = copy.deepcopy(snapshot["runs"])
    store.by_split = {
        split: [i for i, row in enumerate(store.records) if row["split"] == split]
        for split in ("train", "validation", "test")
    }
    store.cache, store.frames, store.shape = OrderedDict(), {}, tuple(snapshot["sample_shape"])
    store.snapshot, store.snapshot_sha = snapshot, expected_sha
    if [len(store.by_split[split]) for split in store.by_split] != [240, 48, 96]:
        raise ValueError("Unexpected frozen V2 partitions")
    return store


def geometry_orbit(manifest):
    """Normalized object geometry modulo the four supported XY reflections."""
    bounds = np.asarray(manifest["sampling"]["bounds_m"], dtype=np.float64)
    boxes = np.asarray([obj["bounds_m"] for obj in manifest["objects"]], dtype=np.float64)
    boxes = boxes.reshape(-1, 3, 2) / bounds[None, :, None]
    signatures = []
    for choice in range(4):
        transformed = boxes.copy()
        for axis in (0, 1):
            if choice & (1 << axis):
                transformed[:, axis] = 1 - transformed[:, axis, ::-1]
        signatures.append(canonical_sha(sorted(np.round(transformed, 8).reshape(-1, 6).tolist())))
    return min(signatures)


def verify_geometry_separation(previous, fresh):
    """Read input manifests, never test labels, to exclude reflected leakage."""
    known, new = {}, {}
    counts = {}
    for name, store, signatures in (("v2", previous, known), ("vent", fresh, new)):
        layouts = set()
        for index, record in enumerate(store.records):
            if record["layout_id"] in layouts:
                continue
            path = store.folder(index) / "manifest.json"
            if file_sha(path) != record["file_hashes"]["manifest.json"]:
                raise ValueError("Input geometry differs from its pinned simulation manifest")
            manifest = json.loads(path.read_text(encoding="utf-8"))
            signature = geometry_orbit(manifest)
            if signature in signatures and signatures[signature] != record["split"]:
                raise ValueError("Normalized reflected geometry leaks between partitions")
            if name == "vent" and signature in known:
                raise ValueError("Fresh ventilation geometry is a reflected/scaled copy of V2")
            signatures[signature] = record["split"]
            layouts.add(record["layout_id"])
        counts[name] = len(layouts)
    return {"layout_counts": counts, "reflection_orbit_overlap": 0, "test_observations_read": False}


def macro_f1(metrics):
    return float(
        np.mean(
            [
                metric["f1"] or 0.0
                for field in OUTPUTS
                for metric in metrics[field]["groups"]["microgravity_module"].values()
            ]
        )
    )


def validation_selection(previous, fresh, old_scores, fresh_scores):
    cases, scores = [*previous, *fresh], [*old_scores, *fresh_scores]
    if any(case["record"]["split"] != "validation" for case in cases):
        raise ValueError("Ventilation selection requires validation only")
    selected = select_thresholds(cases, scores)
    thresholds = selected["score_thresholds"]
    metrics = {name: row["metrics"] for name, row in selected["fields"].items()}
    paired = paired_metrics(fresh, fresh_scores, thresholds)
    response = float(
        np.mean([values[name]["f1"] or 0.0 for values in paired["by_family"].values() for name in OUTPUTS])
    )
    controls = [i for i, case in enumerate(cases) if case["config"]["ignition_power_w"] == 0]
    if len(controls) != 12:
        raise ValueError("Expected twelve explicit 0-W validation controls")
    control_fp = {name: sum(metrics[name]["cases"][i]["fp"] for i in controls) for name in OUTPUTS}
    old_metrics = metrics_for(previous, old_scores, thresholds)
    return {
        "score_thresholds": thresholds,
        "macro_f1": selected["value"],
        "paired_macro_f1": response,
        "value": 0.75 * selected["value"] + 0.25 * response,
        "old_validation_macro_f1": macro_f1(old_metrics),
        "combined_metrics": metrics,
        "old_validation_metrics": old_metrics,
        "paired": paired,
        "control_false_positives": control_fp,
        "selection": SELECTION,
    }


def promotion_guard(candidate, baseline):
    """Predeclared conservative promotion, measured on validation only."""
    failures = []
    if candidate["old_validation_macro_f1"] < baseline["old_validation_macro_f1"] - 0.02:
        failures.append("old_validation_macro_f1_regression")
    for name in OUTPUTS:
        new = candidate["combined_metrics"][name]["groups"]["microgravity"]
        old = baseline["combined_metrics"][name]["groups"]["microgravity"]
        if new["precision"] is None or new["precision"] < (old["precision"] or 0) - 0.03:
            failures.append(name + "_precision_regression")
        if new["recall"] is None or new["recall"] < (old["recall"] or 0):
            failures.append(name + "_recall_regression")
        if candidate["control_false_positives"][name] != 0:
            failures.append(name + "_zero_power_false_alarm")
    if candidate["value"] <= baseline["value"]:
        failures.append("no_composite_improvement")
    if candidate["paired_macro_f1"] <= baseline["paired_macro_f1"]:
        failures.append("no_ventilation_response_improvement")
    return {"promotable": not failures, "failures": failures}


def save_scores(directory, name, cases, scores):
    path = directory / (name + ".npz")
    if path.exists() or len(cases) != len(scores):
        raise ValueError("Score archive exists or cases are missing")
    np.savez_compressed(path, **{case["record"]["id"]: score for case, score in zip(cases, scores)})
    return {"relative_path": "comparison-scores/" + path.name, "sha256": file_sha(path)}


def run(args):
    lock = args.runtime.resolve() / "compute.lock"
    with ProcessLock(lock):
        return run_locked(args, lock)


def run_locked(args, lock):
    output = args.output.resolve()
    for dataset in (args.dataset.resolve(), args.previous_dataset.resolve()):
        if output == dataset or output.is_relative_to(dataset):
            raise ValueError("Training artifacts must remain outside immutable datasets")
    output.mkdir(parents=True, exist_ok=False)
    log = ProgressLog(output / "progress.jsonl")
    started = time.monotonic()
    deadline = started + args.seconds
    telemetry_process = telemetry_stream = None
    try:
        write_json(output / "selection-policy.json", SELECTION)
        write_json(
            output / "compute-lock.json",
            {"path": str(lock), "owner_pid": os.getpid(), "acquired_before_cuda": True},
        )
        torch.set_num_threads(4)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        torch.manual_seed(SEED)
        original = ISSPredictor(args.warm_start, expected_sha256=V2_WEIGHTS_SHA256)
        if original.metadata["architecture"] != architecture(16):
            raise ValueError("Ventilation adaptation keeps the exact V2 architecture")
        old_state = {
            key: value.detach().cpu().clone() for key, value in original.network.state_dict().items()
        }
        old_thresholds = dict(original.thresholds)
        old = previous_store(
            args.previous_dataset, args.previous_snapshot, original.metadata["dataset_sha256"]
        )
        warm_start = {
            "weights_sha256": original.weights_sha256,
            "dataset_sha256": old.snapshot_sha,
            "state_sha256": state_sha(original.network),
            "optimizer_state_reused": False,
        }
        del original
        fresh = VentilationCaseStore(args.dataset)
        disjoint = verify_geometry_separation(old, fresh)
        write_json(output / "geometry-disjointness.json", disjoint)
        fresh.verify_before_selection(log)
        if fresh.shape != old.shape or fresh.shape != (12, 16, 8):
            raise ValueError("Both corpora require the same verified 12x16x8 sample grid")
        write_json(output / "dataset-snapshot.json", fresh.snapshot)
        write_json(output / "previous-dataset-snapshot.json", old.snapshot)
        source = source_hashes()
        for name in (
            "train_iss_poc_vent.py",
            "train_iss_poc_v2.py",
            "train_iss_poc.py",
            "train_hotspot_poc.py",
            "iss_poc_model.py",
            "evaluate_iss_ventilation.py",
            "verify_spatial.py",
        ):
            source["tools/remote/" + name] = file_sha(Path(__file__).with_name(name))
        write_json(output / "sources.json", source)
        prior_train, train = load_partition(old, "train"), load_partition(fresh, "train")
        prior_val, val = load_partition(old, "validation"), load_partition(fresh, "validation")
        compute = prepare_cuda()
        telemetry_process, telemetry_stream = start_telemetry(output, log)
        torch.cuda.manual_seed_all(SEED)
        network = ISSClassifier(16).to("cuda:0")
        network.load_state_dict(old_state, strict=True)
        prior_scores = predict_cases(network, prior_val, deadline)
        original_scores = predict_cases(network, val, deadline)
        baseline = validation_selection(prior_val, val, prior_scores, original_scores)
        write_json(output / "v2-recalibrated-validation-selection.json", baseline)
        write_json(
            output / "v2-frozen-validation.json",
            metrics_for([*prior_val, *val], [*prior_scores, *original_scores], old_thresholds),
        )
        best, best_state = {**baseline, "step": 0}, copy.deepcopy(old_state)
        log.emit(
            "baseline_selected",
            value=baseline["value"],
            paired_macro_f1=baseline["paired_macro_f1"],
            score_thresholds=baseline["score_thresholds"],
        )
        cache = VentilationTrainingCache(prior_train, train)
        log.emit(
            "device_cache_ready",
            bytes=cache.bytes,
            frames=cache.frames,
            cases=len(prior_train) + len(train),
            reflections=4,
        )
        optimizer = torch.optim.AdamW(
            (p for p in network.parameters() if p.requires_grad), lr=1e-4, weight_decay=1e-4
        )
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.steps, eta_min=2e-5)
        training_started = time.monotonic()
        training_deadline = min(deadline - 200, training_started + args.training_seconds)
        history, updates = [], 0
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
                )
            if step % args.validate_every == 0:
                if not torch.isfinite(loss).item():
                    raise ValueError("Nonfinite ventilation training loss")
                candidate = validation_selection(
                    prior_val,
                    val,
                    predict_cases(network, prior_val, deadline),
                    predict_cases(network, val, deadline),
                )
                guard = promotion_guard(candidate, baseline)
                improved = guard["promotable"] and candidate["value"] > best["value"]
                if improved:
                    best = {**candidate, "step": step}
                    best_state = {
                        key: value.detach().cpu().clone() for key, value in network.state_dict().items()
                    }
                row = {
                    "step": step,
                    "loss": float(loss.item()),
                    "value": candidate["value"],
                    "macro_f1": candidate["macro_f1"],
                    "paired_macro_f1": candidate["paired_macro_f1"],
                    "guard": guard,
                    "improved": improved,
                    "best_step": best["step"],
                }
                history.append(row)
                write_json(output / f"validation-step-{step:06d}.json", {**candidate, "guard": guard})
                log.emit("validation", **row)
        training_seconds = time.monotonic() - training_started
        network.load_state_dict(best_state, strict=True)
        frozen_sha, thresholds = state_sha(network), best["score_thresholds"]
        frozen = {
            "selected_at": utc_now(),
            "step": best["step"],
            "score_thresholds": thresholds,
            "state_sha256": frozen_sha,
            "selection": SELECTION,
            "value": best["value"],
            "paired_macro_f1": best["paired_macro_f1"],
            "new_weights_selected": best["step"] > 0,
            "test_labels_used_for_selection": False,
            "v2_frozen_thresholds": old_thresholds,
            "v2_recalibrated_thresholds": baseline["score_thresholds"],
            "baseline_value": baseline["value"],
            "baseline_paired_macro_f1": baseline["paired_macro_f1"],
            "promotion_guard": promotion_guard(best, baseline),
        }
        write_json(output / "frozen-selection.json", frozen)
        frozen_dataset_sha = fresh.snapshot_sha
        weights = output / "weights.pt"
        with weights.open("xb") as stream:
            torch.save(
                {
                    "id": MODEL_ID,
                    "schema_version": SCHEMA_VERSION,
                    "architecture": architecture(16),
                    "sample_shape": list(fresh.shape),
                    "score_thresholds": thresholds,
                    "selected_step": best["step"],
                    "dataset_sha256": fresh.snapshot_sha,
                    "previous_dataset_sha256": old.snapshot_sha,
                    "state_dict": best_state,
                    "training_version": TRAINING_VERSION,
                    "warm_start": warm_start,
                },
                stream,
            )
        reloaded = ISSPredictor(weights)
        if state_sha(reloaded.network) != frozen_sha:
            raise RuntimeError("Existing inference loader changed the selected state")
        del reloaded, cache, optimizer, scheduler, best_state, prior_train
        if updates:
            del x, target, observed, loss
        torch.cuda.empty_cache()
        log.emit("selection_frozen", **frozen)
        # The fresh test is first read only after thresholds and state are frozen.
        verified = fresh.verify_after_selection(log)
        # The full integrity pass may enrich test provenance; selection binds to
        # the immutable preselection source snapshot already saved on disk.
        write_json(output / "postfreeze-verified-dataset-snapshot.json", verified.snapshot)
        test = load_partition(verified, "test")
        old_network = ISSClassifier(16).to("cuda:0")
        old_network.load_state_dict(old_state, strict=True)
        audit, demo = output / "comparison-scores", output / "demo"
        audit.mkdir()
        (demo / "cases").mkdir(parents=True)
        metrics, comparisons, archives, rows = {}, {}, {}, []
        for split, cases in (("train", train), ("validation", val), ("test", test)):
            scores = predict_cases(network, cases, deadline)
            metrics[split] = metrics_for(cases, scores, thresholds)
            if split != "train":
                original = (
                    original_scores if split == "validation" else predict_cases(old_network, cases, deadline)
                )
                archives[split] = {
                    "v2": save_scores(audit, "v2-" + split, cases, original),
                    "candidate": save_scores(audit, "candidate-" + split, cases, scores),
                }
                comparisons[split] = {
                    "v2_frozen": metrics_for(cases, original, old_thresholds),
                    "v2_recalibrated": metrics_for(cases, original, baseline["score_thresholds"]),
                    "v2_recalibrated_paired": paired_metrics(cases, original, baseline["score_thresholds"]),
                    "candidate_paired": paired_metrics(cases, scores, thresholds),
                }
            for number, (case, score) in enumerate(zip(cases, scores)):
                check_budget(deadline)
                record, config = case["record"], case["config"]
                metric = {name: metrics[split][name]["cases"][number] for name in OUTPUTS}
                path = demo / "cases" / (record["id"] + ".json")
                export_case(path, case, score, thresholds, metric)
                mask = evaluation_mask(case)
                rows.append(
                    {
                        "id": record["id"],
                        "split": split,
                        "layout_id": record["layout_id"],
                        "family": record["structural_family"],
                        "module_id": record["structural_family"],
                        "evaluation_role": "fresh_ventilation_holdout" if split == "test" else split,
                        **{
                            key: config[key]
                            for key in ("gravity_g", "incident_type", "ambient_temperature_c", "airflow_m_s")
                        },
                        **{
                            key: record.get(key)
                            for key in (
                                "ventilation_group_id",
                                "ventilation_state",
                                "ventilation_axis",
                                "reverse_ventilation",
                            )
                        },
                        "peak_temperature_c": float(np.max(case["temperature_c"][mask[..., 0]])),
                        "peak_soot_kg_m3": float(np.max(case["smoke_kg_m3"][mask[..., 1]])),
                        "metrics": metric,
                        "url": "./cases/" + path.name,
                        "sha256": file_sha(path),
                    }
                )
            log.emit("partition_exported", split=split, cases=len(cases))
        inference = inference_benchmark(weights, val[0], network, deadline)
        write_json(output / "inference-benchmark.json", inference)
        elapsed = time.monotonic() - started
        telemetry = stop_telemetry(telemetry_process, telemetry_stream, output)
        telemetry_process = telemetry_stream = None
        write_json(output / "gpu-telemetry-summary.json", telemetry)
        chosen = examples(rows)
        model = {
            "id": MODEL_ID,
            "name": "U-Net 3D — adaptation ventilation",
            "training_version": TRAINING_VERSION,
            "trained_at": utc_now(),
            "weights_sha256": file_sha(weights),
            "state_sha256": frozen_sha,
            "dataset_sha256": frozen_dataset_sha,
            "score_thresholds": thresholds,
            "score_semantics": SCORE_SEMANTICS,
            "heat_delta_c": HEAT_DELTA_C,
            "smoke_threshold_kg_m3": SMOKE_THRESHOLD_KG_M3,
            "architecture": architecture(16),
            "warm_start": warm_start,
            "selected_step": best["step"],
            "new_weights_selected": best["step"] > 0,
            "training_seconds": training_seconds,
            "total_compute_seconds": elapsed,
            "optimizer_steps": updates,
            "batch_size": args.batch_size,
            "device": compute["device_name"],
            "seed": SEED,
            "selection_split": "validation",
        }
        index = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": utc_now(),
            "model": model,
            "metrics_time_filter": METRIC_FILTER,
            "metrics": metrics,
            "comparisons": comparisons,
            "comparison_thresholds": {
                "v2_frozen": old_thresholds,
                "v2_recalibrated": baseline["score_thresholds"],
            },
            "cases": rows,
            "default_case_id": chosen["representative"],
            "example_cases": chosen,
            "limitations": LIMITATIONS
            + [
                "Augmentation par quatre réflexions horizontales ; aucune nouvelle simulation produite par ces transformations."
            ],
        }
        compact_json(demo / "index.json", index)
        write_json(
            output / "report.json",
            {
                **index,
                "selection": frozen,
                "history": history,
                "score_archives": archives,
                "validation_baseline": baseline,
                "validation_selected": best,
                "sources": source,
                "gpu_telemetry": telemetry,
                "inference_benchmark": inference,
                "compute": compute,
                "budget_seconds": args.seconds,
                "sampler": "50% frozen V2 training corpus + 50% fresh training corpus; equal cases inside corpus; unchanged active/uniform time mixture",
                "augmentation": "uniform identity/X/Y/XY reflection per batch; all 54 features, both labels and field masks transformed",
                "loss": "unchanged equal-field balanced positive/background BCE",
                "optimizer": {"name": "AdamW", "lr": 1e-4, "eta_min": 2e-5, "weight_decay": 1e-4},
                "old_test_observations_read": False,
                "fresh_test_read_after_freeze": True,
                "reload_state_match": True,
                "geometry_disjointness": disjoint,
            },
        )
        if elapsed > args.seconds:
            raise TimeoutError("Ventilation fitting exceeded its bounded compute budget")
        log.emit("completed", model=model, cases_exported=len(rows), output=str(output))
    except BaseException as exc:
        log.emit("failed", error=type(exc).__name__, message=str(exc))
        raise
    finally:
        if telemetry_process is not None:
            stop_telemetry(telemetry_process, telemetry_stream, output)
        log.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "output", "warm-start", "previous-snapshot", "previous-dataset", "runtime"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--training-seconds", type=int, default=300)
    parser.add_argument("--steps", type=int, default=15000)
    parser.add_argument("--batch-size", type=int, choices=(32, 64, 128), default=128)
    parser.add_argument("--validate-every", type=int, default=1000)
    args = parser.parse_args(argv)
    if (
        not 300 <= args.seconds <= 600
        or not 30 <= args.training_seconds <= 300
        or not 1000 <= args.steps <= 20000
        or not 250 <= args.validate_every <= 1000
    ):
        parser.error(
            "Require 300..600s total,30..300s training,1000..20000 steps,250..1000 validation interval"
        )
    return args


if __name__ == "__main__":
    run(parse_args())
