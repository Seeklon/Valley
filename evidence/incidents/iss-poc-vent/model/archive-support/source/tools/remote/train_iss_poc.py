"""Bounded GPU fitting and export for known ISS-inspired module families.

The old compact dataset/model are untouched. This dedicated store permits
module families in each partition, but forbids shared layouts or physical
geometries. FDS reconstruction/provenance checks remain inherited unchanged.
"""

from __future__ import annotations

import argparse
import copy
import csv
import math
import os
import subprocess
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
import torch
from ignis.locking import ProcessLock
from ignis.ml.spatial_dataset import file_sha, read_spatial_index
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
from torch.nn import functional as F
from train_hotspot_poc import (
    THRESHOLDS,
    add_metrics,
    check_budget,
    classification,
    compact_json,
    compiled_scene,
    gravity_group,
    load_partition,
    proximity_scores,
    utc_now,
)
from train_spatial import CaseStore, ProgressLog, source_hashes, write_json
from verify_spatial import state_sha

SEED = 20261115
DATASET_ID = "iss-poc-20261115-v1"
METRIC_FILTER = "observed field samples and time_s > 0"
SELECTION = "mean_heat_smoke_macro_module_microgravity_f1"
LIMITATIONS = [
    "POC ciblé sur trois familles de modules inspirés de l'ISS, sans reproduction certifiée de l'ISS.",
    "La source électrique est imposée. Le modèle ne prédit pas sa probabilité d'allumage.",
    "Chaleur : T FDS >= température ambiante + 5 °C. Fumée : suie FDS >= 1e-6 kg/m³.",
    "Les scores ML ne sont ni des températures, ni des concentrations, ni des probabilités d'incendie.",
    "Les champs affichés sont des prédictions aux sondes, sans mesure validée entre les sondes.",
    "Données FDS synthétiques : aucune validation expérimentale NASA ni garantie de sécurité.",
    "Familles de modules communes aux partitions ; seules les dispositions/géométries sont disjointes.",
    "Un bon ajustement sur ces scènes ne prouve pas la généralisation à une station réelle.",
]


class ISSCaseStore(CaseStore):
    """Explicit known-family split, retaining all inherited compiler/label checks."""

    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        path = self.directory / "manifest.json"
        self.source_sha = file_sha(path)
        original = read_spatial_index(self.directory)
        if file_sha(path) != self.source_sha:
            raise ValueError("ISS manifest changed during snapshot acquisition")
        if original["dataset_id"] != DATASET_ID:
            raise ValueError("ISS-specific partition policy requires the exact ISS dataset ID")
        records = original["runs"]
        if len(records) != original.get("expected_runs", len(records)) or any(
            record.get("status", "completed") != "completed" for record in records
        ):
            raise ValueError("ISS dataset must be complete before fitting")
        self.records = copy.deepcopy(records)
        if not records or len({record["id"] for record in records}) != len(records):
            raise ValueError("Empty ISS dataset or duplicate case IDs")
        self.by_split = {split: [] for split in ("train", "validation", "test")}
        groups, families = {}, {split: set() for split in self.by_split}
        for index, record in enumerate(self.records):
            group, split = record.get("layout_id"), record["split"]
            module = record.get("structural_family")
            if not group or not module or split not in self.by_split:
                raise ValueError("ISS cases require layout, module family and split")
            if group in groups and groups[group] != split:
                raise ValueError("ISS layout leakage across partitions")
            if Path(record["id"]).name != record["id"] or "/" in record["id"] or "\\" in record["id"]:
                raise ValueError("Unsafe ISS case identifier")
            groups[group] = split
            families[split].add(module)
            self.by_split[split].append(index)
        if any(not values for values in self.by_split.values()):
            raise ValueError("ISS train, validation and test must all be present")
        if len(families["train"]) != 3 or any(values != families["train"] for values in families.values()):
            raise ValueError("Each ISS split must cover the same three named module families")
        self.snapshot = {
            "dataset_id": original["dataset_id"],
            "partition_policy": "known module families; disjoint layouts and reconstructed physical geometry",
            "source_manifest_sha256": self.source_sha,
            "source_merged_index_sha256": canonical_sha(original),
            "source_expected_runs": original.get("expected_runs", len(records)),
            "partial": False,
            "runs": self.records,
        }
        self.cache = OrderedDict()
        self.frames = {}
        self.shape = None


def module_id(case):
    return case["record"]["structural_family"]


def targets(case):
    observed = np.asarray(case["field_mask"], dtype=bool)
    truth = np.stack(
        [
            np.asarray(case["temperature_c"], dtype=np.float64)
            >= case["config"]["ambient_temperature_c"] + HEAT_DELTA_C,
            np.asarray(case["smoke_kg_m3"], dtype=np.float64) >= SMOKE_THRESHOLD_KG_M3,
        ],
        axis=-1,
    )
    if observed.shape != truth.shape:
        raise ValueError("Heat and smoke labels must align with their individual observation masks")
    return truth & observed, observed


def evaluation_mask(case):
    return targets(case)[1] & (case["time_s"] > 0)[:, None, None]


def assess_field(cases, scores, threshold, channel):
    if len(cases) != len(scores):
        raise ValueError("Each ISS case needs one score array")
    rows = []
    for case, score in zip(cases, scores):
        truth, _ = targets(case)
        if score.shape != truth.shape:
            raise ValueError("ISS class score dimensions disagree with the measured grid")
        metric = classification(
            truth[..., channel], score[..., channel], evaluation_mask(case)[..., channel], threshold
        )
        rows.append(
            {
                "id": case["record"]["id"],
                "module_id": module_id(case),
                "gravity": gravity_group(case),
                "incident_type": case["config"]["incident_type"],
                "sample_inactive": metric["tp"] + metric["fn"] == 0,
                **metric,
            }
        )
    groups = {
        name: add_metrics([r for r in rows if r["gravity"] == name]) for name in ("microgravity", "earth")
    }
    groups["module"] = {
        name: add_metrics([r for r in rows if r["module_id"] == name])
        for name in sorted({r["module_id"] for r in rows})
    }
    groups["microgravity_module"] = {
        name: add_metrics([r for r in rows if r["module_id"] == name and r["gravity"] == "microgravity"])
        for name in groups["module"]
    }
    groups["incident_type"] = {
        name: add_metrics([r for r in rows if r["incident_type"] == name])
        for name in sorted({r["incident_type"] for r in rows})
    }
    groups["sample_inactive"] = add_metrics([r for r in rows if r["sample_inactive"]])
    return {
        **add_metrics(rows),
        "groups": groups,
        "case_count": len(rows),
        "cases": rows,
        "sample_inactive_cases": sum(r["sample_inactive"] for r in rows),
        "sample_inactive_cases_with_false_alarm": sum(r["sample_inactive"] and r["fp"] > 0 for r in rows),
    }


def select_field_threshold(cases, scores, channel):
    """Predeclared validation-only macro-module microgravity F1 selection."""
    if not cases or any(case["record"]["split"] != "validation" for case in cases):
        raise ValueError("ISS threshold selection requires validation cases only")
    if len(cases) != len(scores):
        raise ValueError("Missing ISS validation predictions")
    grouped = {}
    for case, score in zip(cases, scores):
        if gravity_group(case) != "microgravity":
            continue
        truth, _ = targets(case)
        observed = evaluation_mask(case)[..., channel]
        values = score[..., channel]
        if score.shape != truth.shape or not np.isfinite(values[observed]).all():
            raise ValueError("Invalid ISS validation class scores")
        positive, negative = grouped.setdefault(module_id(case), ([], []))
        positive.append(values[observed & truth[..., channel]])
        negative.append(values[observed & ~truth[..., channel]])
    if not grouped:
        raise ValueError("ISS threshold selection requires microgravity validation cases")
    objective = np.zeros(len(THRESHOLDS))
    false_positives = np.zeros(len(THRESHOLDS), dtype=np.int64)
    positive_modules = 0
    for positive, negative in grouped.values():
        positive, negative = np.sort(np.concatenate(positive)), np.sort(np.concatenate(negative))
        tp = len(positive) - np.searchsorted(positive, THRESHOLDS, side="left")
        fp = len(negative) - np.searchsorted(negative, THRESHOLDS, side="left")
        fn = len(positive) - tp
        objective += 2 * tp / np.maximum(1, 2 * tp + fp + fn) / len(grouped)
        false_positives += fp
        positive_modules += bool(len(positive))
    best = max(range(len(THRESHOLDS)), key=lambda i: (objective[i], -false_positives[i], THRESHOLDS[i]))
    return {
        "threshold": float(THRESHOLDS[best]),
        "value": float(objective[best]),
        "selection_split": "validation",
        "selection_metric": "macro_module_microgravity_f1",
        "positive_modules": positive_modules,
        "module_count": len(grouped),
        "empty_positive_policy": "zero F1 in selection; report undefined ratios as null; FP tie-break retained",
        "metrics": assess_field(cases, scores, float(THRESHOLDS[best]), channel),
    }


def select_thresholds(cases, scores):
    fields = {name: select_field_threshold(cases, scores, i) for i, name in enumerate(OUTPUTS)}
    return {
        "fields": fields,
        "score_thresholds": {name: row["threshold"] for name, row in fields.items()},
        "value": sum(row["value"] for row in fields.values()) / len(OUTPUTS),
        "selection_metric": SELECTION,
        "selection_split": "validation",
    }


def dual_balanced_bce(logits, target, observed, *, validate=True):
    """Equal field mass, then positive/background mass within each observed field."""
    if logits.shape != target.shape or logits.shape != observed.shape or logits.shape[1] != 2:
        raise ValueError("Require matching [batch, 2, x, y, z] class tensors")
    observed, target = observed.bool(), target.bool()
    if validate and not observed.flatten(1).any(dim=1).all().item():
        raise ValueError("Each training frame needs observed targets")
    safe = torch.where(observed, logits, 0.0)
    error = F.binary_cross_entropy_with_logits(safe, target.to(logits.dtype), reduction="none")
    dims = tuple(range(2, logits.ndim))
    positive, negative = observed & target, observed & ~target
    npos, nneg = positive.sum(dims), negative.sum(dims)
    ploss = (error * positive).sum(dims) / npos.clamp_min(1)
    nloss = (error * negative).sum(dims) / nneg.clamp_min(1)
    present = (npos > 0).to(logits.dtype) + (nneg > 0).to(logits.dtype)
    per_field = (ploss + nloss) / present.clamp_min(1)
    return per_field.sum(1) / (present > 0).sum(1).clamp_min(1)


class TrainingCache:
    def __init__(self, cases, device="cuda:0"):
        if not cases or any(c["record"]["split"] != "train" for c in cases):
            raise ValueError("ISS training cache accepts training cases only")
        if len({tuple(case["shape"]) for case in cases}) != 1:
            raise ValueError("ISS training grids must have identical shapes")
        columns = {name: [] for name in ("x", "y", "mask")}
        probabilities = []
        for case in cases:
            truth, observed = targets(case)
            frames = np.flatnonzero(case["time_s"] > 0)
            if not len(frames) or not observed[frames].reshape(len(frames), -1).any(1).all():
                raise ValueError("Missing post-initial ISS training observations")
            active = truth[frames].reshape(len(frames), -1).any(1)
            weights = np.full(len(frames), 1 / len(frames))
            if active.any():
                weights = 0.5 * weights + 0.5 * active / active.sum()
            probabilities.extend(weights / len(cases))
            for frame in frames:
                columns["x"].append(
                    input_tensor(case["static"], case["config"], case["manifest"], case["time_s"][frame])
                )
                columns["y"].append(truth[frame].T.reshape(2, *case["shape"]))
                columns["mask"].append(observed[frame].T.reshape(2, *case["shape"]))
        self.values = [torch.as_tensor(np.stack(columns[key]), device=device) for key in ("x", "y", "mask")]
        self.probability = torch.as_tensor(probabilities, device=device, dtype=torch.float32)
        if not np.isclose(sum(probabilities), 1) or min(probabilities) <= 0:
            raise ValueError("All ISS training times must retain positive sampling probability")
        self.bytes = sum(v.numel() * v.element_size() for v in self.values)
        self.frames = len(probabilities)

    def batch(self, size):
        indices = torch.multinomial(self.probability, size, replacement=True)
        return [value.index_select(0, indices) for value in self.values]


def prepare_cuda():
    if not torch.cuda.is_available():
        raise RuntimeError("ISS fitting requires CUDA; no implicit CPU fallback")
    torch.cuda.set_device(0)
    free, total = torch.cuda.mem_get_info()
    budget = min(int(total * 0.82), int(free * 0.85))
    if budget < 4 * 1024**3:
        raise RuntimeError("Insufficient free GPU memory for the bounded ISS fit")
    torch.cuda.set_per_process_memory_fraction(budget / total, device=0)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    return {
        "device": "cuda:0",
        "device_name": torch.cuda.get_device_name(0),
        "torch_version": str(torch.__version__),
        "cuda_version": torch.version.cuda,
        "total_memory_bytes": total,
        "free_memory_at_start_bytes": free,
        "allocator_limit_bytes": budget,
        "memory_policy": "min(82% total, 85% initially free); utilization is measured separately",
    }


def predict_cases(network, cases, deadline, batch_size=32):
    network.eval()
    results = []
    with torch.inference_mode():
        for case in cases:
            chunks = []
            for start in range(0, len(case["time_s"]), batch_size):
                check_budget(deadline)
                values = np.stack(
                    [
                        input_tensor(case["static"], case["config"], case["manifest"], t)
                        for t in case["time_s"][start : start + batch_size]
                    ]
                )
                score = network(torch.as_tensor(values, device="cuda:0")).sigmoid()
                chunks.append(score.flatten(2).transpose(1, 2).cpu().numpy())
            results.append(np.concatenate(chunks))
    return results


def benchmark_batches(network, cache, deadline, log):
    """Pick useful samples/second on real training data, restoring weights after."""
    initial = {key: value.detach().cpu().clone() for key, value in network.state_dict().items()}
    rows = []
    for size in (32, 64, 128, 256):
        network.load_state_dict(initial)
        optimizer = torch.optim.AdamW((p for p in network.parameters() if p.requires_grad), lr=1e-3)
        network.train()
        x = y = mask = loss = None
        try:
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            started = time.monotonic()
            for iteration in range(18):
                check_budget(deadline)
                if iteration == 3:
                    torch.cuda.synchronize()
                    started = time.monotonic()
                x, y, mask = cache.batch(size)
                optimizer.zero_grad(set_to_none=True)
                loss = dual_balanced_bce(network(x), y, mask, validate=False).mean()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(network.parameters(), 5, error_if_nonfinite=False)
                optimizer.step()
                if not rows and iteration == 0:
                    torch.cuda.synchronize()
                    log.emit(
                        "cuda_optimizer_started",
                        phase="training-only throughput benchmark",
                        optimizer_step_completed=True,
                        device="cuda:0",
                        device_name=torch.cuda.get_device_name(0),
                    )
            torch.cuda.synchronize()
            elapsed = time.monotonic() - started
            if not torch.isfinite(loss).item():
                raise ValueError("Nonfinite ISS throughput benchmark")
            row = {
                "batch_size": size,
                "steps": 15,
                "warmup_steps": 3,
                "seconds": elapsed,
                "examples_per_second": size * 15 / elapsed,
                "peak_allocator_bytes": torch.cuda.max_memory_allocated(),
            }
            rows.append(row)
            log.emit("throughput_benchmark", **row)
        except torch.OutOfMemoryError:
            log.emit("throughput_batch_oom", batch_size=size)
            break
        finally:
            optimizer.zero_grad(set_to_none=True)
            del optimizer
            del x, y, mask, loss
            torch.cuda.empty_cache()
    network.load_state_dict(initial)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    if not rows:
        raise RuntimeError("No ISS training batch fits the GPU")
    return max(rows, key=lambda row: row["examples_per_second"])["batch_size"], rows


def export_case(path, case, scores, thresholds, metrics):
    truth, observed = targets(case)
    if scores.shape != truth.shape or not np.isfinite(scores).all():
        raise ValueError("ISS replay requires aligned finite class predictions")
    frames = []
    for frame, time_s in enumerate(case["time_s"]):
        row = {"time_s": float(time_s)}
        for i, name in enumerate(OUTPUTS):
            mask = observed[frame, :, i]
            measurement = case["temperature_c" if name == "heat" else "smoke_kg_m3"][frame]
            row["temperature_c" if name == "heat" else "soot_kg_m3"] = [
                float(v) if valid else None for v, valid in zip(measurement, mask)
            ]
            row[name + "_valid_mask"] = mask.tolist()
            row[name + "_score"] = [
                float(v) if valid else None for v, valid in zip(scores[frame, :, i], mask)
            ]
            row["hotspot_truth" if name == "heat" else "smoke_truth"] = [
                bool(v) if valid else None for v, valid in zip(truth[frame, :, i], mask)
            ]
            row["predicted_hot_mask" if name == "heat" else "predicted_smoke_mask"] = [
                bool(v >= thresholds[name]) if valid else None for v, valid in zip(scores[frame, :, i], mask)
            ]
        frames.append(row)
    config = case["config"]
    compact_json(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "id": case["record"]["id"],
            "split": case["record"]["split"],
            "layout_id": case["record"]["layout_id"],
            "module_id": module_id(case),
            "scene": compiled_scene(case),
            "conditions": {
                **{
                    key: config[key]
                    for key in (
                        "ambient_temperature_c",
                        "gravity_g",
                        "airflow_m_s",
                        "oxygen_percent",
                        "incident_type",
                        "duration_s",
                    )
                },
                "power_w": config["ignition_power_w"],
                "source_duration_s": config["ignition_duration_s"],
                "source_position_m": case["manifest"]["incident"]["source"]["position_m"],
            },
            "sample_positions_m": case["positions_m"].tolist(),
            "shape": case["shape"].tolist(),
            "score_thresholds": thresholds,
            "score_semantics": SCORE_SEMANTICS,
            "heat_delta_c": HEAT_DELTA_C,
            "smoke_threshold_kg_m3": SMOKE_THRESHOLD_KG_M3,
            "metrics_time_filter": METRIC_FILTER,
            "metrics": metrics,
            "frames": frames,
        },
    )


def examples(rows):
    validation = [row for row in rows if row["split"] == "validation" and row["gravity_g"] < 0.01]
    active = [
        row
        for row in validation
        if any(row["metrics"][field]["tp"] + row["metrics"][field]["fn"] for field in OUTPUTS)
    ]

    def score(row):
        return sum(row["metrics"][name]["iou"] or 0 for name in OUTPUTS) / 2

    ordered = sorted(active, key=lambda row: (score(row), row["id"]))
    controls = sorted([row for row in validation if row not in active], key=lambda row: row["id"])
    per_module = {}
    for module in sorted({row["module_id"] for row in rows}):
        candidates = [row for row in ordered if row["module_id"] == module]
        per_module[module] = candidates[(len(candidates) - 1) // 2]["id"] if candidates else None
    return {
        "representative": ordered[(len(ordered) - 1) // 2]["id"] if ordered else None,
        "failure": ordered[0]["id"] if ordered else None,
        "cold_control": controls[0]["id"] if controls else None,
        "modules": per_module,
    }


def inference_benchmark(weights, case, network, deadline):
    """Actual CPU/GPU replay timings for one validation trajectory, no solver call."""
    check_budget(deadline)
    started = time.perf_counter()
    predictor = ISSPredictor(weights, device="cpu")
    load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    reference = predictor.predict_arrays(case["config"], case["manifest"], case["time_s"])
    cpu_first_seconds = time.perf_counter() - started
    cpu, gpu = [], []
    for _ in range(3):
        check_budget(deadline)
        started = time.perf_counter()
        predictor.predict_arrays(case["config"], case["manifest"], case["time_s"])
        cpu.append(time.perf_counter() - started)
        torch.cuda.synchronize()
        started = time.perf_counter()
        scores = predict_cases(network, [case], deadline)[0]
        torch.cuda.synchronize()
        gpu.append(time.perf_counter() - started)
    valid = reference["valid_mask"]
    threshold = np.asarray([predictor.thresholds[name] for name in OUTPUTS])
    disagreements = np.count_nonzero(valid & ((reference["scores"] >= threshold) != (scores >= threshold)))
    return {
        "case_id": case["record"]["id"],
        "split": "validation",
        "frames": len(case["time_s"]),
        "points_per_frame": len(case["positions_m"]),
        "cpu_threads": torch.get_num_threads(),
        "cpu_checkpoint_load_seconds": load_seconds,
        "cpu_first_trajectory_seconds": cpu_first_seconds,
        "cpu_warm_trajectory_seconds": cpu,
        "gpu_warm_trajectory_seconds": gpu,
        "cpu_warm_median_seconds": float(np.median(cpu)),
        "gpu_warm_median_seconds": float(np.median(gpu)),
        "cpu_gpu_max_score_difference": float(np.max(np.abs(reference["scores"][valid] - scores[valid]))),
        "cpu_gpu_class_disagreements": int(disagreements),
        "timing_scope": "full trajectory input preparation and inference; CPU load separate, GPU model already loaded; no FDS runtime included",
        "fds_comparison": "Compare separately with this case's measured FDS wall time from dataset generation, not its simulated duration.",
    }


def start_telemetry(output, log):
    stream = (output / "gpu-telemetry.csv").open("x", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [
                "nvidia-smi",
                "--query-gpu=timestamp,utilization.gpu,memory.used,power.draw",
                "--format=csv,noheader,nounits",
                "-l",
                "1",
            ],
            stdout=stream,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        stream.close()
        log.emit("gpu_telemetry_unavailable", message=str(exc))
        return None, None
    return process, stream


def stop_telemetry(process, stream, output):
    if process is None:
        return {"available": False}
    process.terminate()
    process.wait(timeout=10)
    stream.close()
    rows = []
    for row in csv.reader((output / "gpu-telemetry.csv").read_text(encoding="utf-8").splitlines()):
        try:
            rows.append(
                {
                    "timestamp": row[0].strip(),
                    "utilization_percent": float(row[1]),
                    "memory_used_mib": float(row[2]),
                    "power_w": float(row[3]),
                }
            )
        except (ValueError, IndexError):
            continue
    usage = [row["utilization_percent"] for row in rows]
    return {
        "available": bool(rows),
        "sample_count": len(rows),
        "interval_s": 1,
        "utilization_max_percent": max(usage) if usage else None,
        "utilization_median_percent": float(np.median(usage)) if usage else None,
        "fraction_at_least_90_percent": sum(value >= 90 for value in usage) / len(usage) if usage else None,
        "scope": "whole bounded run, including dataset verification/evaluation/export; nvidia-smi device-wide measurement",
    }


def run(args):
    runtime = args.runtime or args.dataset.resolve().parent.parent / "runtime"
    args.compute_lock_path = Path(runtime).resolve() / "compute.lock"
    with ProcessLock(args.compute_lock_path):
        return _run_locked(args)


def _run_locked(args):
    dataset, output = args.dataset.resolve(), args.output.resolve()
    if output == dataset or output.is_relative_to(dataset):
        raise ValueError("ISS output must remain outside the immutable FDS dataset")
    output.mkdir(parents=True, exist_ok=False)
    log = ProgressLog(output / "progress.jsonl")
    started, best, best_state = time.monotonic(), None, None
    deadline = started + args.seconds
    telemetry_process = telemetry_stream = None
    try:
        write_json(
            output / "compute-lock.json",
            {
                "path": str(args.compute_lock_path),
                "owner_pid": os.getpid(),
                "mechanism": "OS-owned exclusive ProcessLock",
                "scope": "entire verified fit, evaluation and export",
                "acquired_before_cuda": True,
            },
        )
        torch.set_num_threads(4)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        torch.manual_seed(SEED)
        compute = prepare_cuda()
        telemetry_process, telemetry_stream = start_telemetry(output, log)
        torch.cuda.manual_seed_all(SEED)
        log.emit("iss_poc_started", pid=os.getpid(), budget_seconds=args.seconds, **compute)
        store = ISSCaseStore(dataset)
        store.verify(log)
        if tuple(store.shape) != (12, 16, 8):
            raise ValueError("ISS demo requires verified 12x16x8 observation grids")
        partitions = {split: load_partition(store, split) for split in ("train", "validation")}
        write_json(output / "dataset-snapshot.json", store.snapshot)
        source = source_hashes()
        for name in ("train_iss_poc.py", "iss_poc_model.py", "train_hotspot_poc.py", "verify_spatial.py"):
            source["tools/remote/" + name] = file_sha(Path(__file__).with_name(name))
        write_json(output / "sources.json", source)
        baseline_scores = [
            np.repeat(proximity_scores(c)[..., None], 2, axis=-1) for c in partitions["validation"]
        ]
        baseline = select_thresholds(partitions["validation"], baseline_scores)
        write_json(output / "baseline-validation-selection.json", baseline)
        cache = TrainingCache(partitions["train"])
        log.emit("device_cache_ready", bytes=cache.bytes, frames=cache.frames, cases=len(partitions["train"]))
        network = ISSClassifier(args.width).to("cuda:0")
        throughput = []
        if args.benchmark_batches:
            args.batch_size, throughput = benchmark_batches(network, cache, deadline, log)
        write_json(output / "throughput.json", {"selected_batch_size": args.batch_size, "rows": throughput})
        optimizer = torch.optim.AdamW(
            (p for p in network.parameters() if p.requires_grad), lr=1e-3, weight_decay=1e-4
        )
        history, updates = [], 0
        training_started = time.monotonic()
        for step in range(1, args.steps + 1):
            if time.monotonic() >= deadline - 180 or (output / "STOP").exists():
                break
            network.train()
            x, target, observed = cache.batch(args.batch_size)
            optimizer.zero_grad(set_to_none=True)
            loss = dual_balanced_bce(network(x), target, observed, validate=False).mean()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(network.parameters(), 5, error_if_nonfinite=False)
            optimizer.step()
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
                    raise ValueError("Nonfinite ISS class loss")
                scores = predict_cases(network, partitions["validation"], deadline)
                selection = select_thresholds(partitions["validation"], scores)
                improved = best is None or selection["value"] > best["value"]
                if improved:
                    best = {**selection, "step": step}
                    best_state = {
                        key: value.detach().cpu().clone() for key, value in network.state_dict().items()
                    }
                row = {
                    "step": step,
                    "loss": float(loss.item()),
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
        if best is None:
            raise RuntimeError("No ISS checkpoint reached validation within budget")
        network.load_state_dict(best_state, strict=True)
        frozen_sha = state_sha(network)
        thresholds = best["score_thresholds"]
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
            },
        )
        weights = output / "weights.pt"
        payload = {
            "id": MODEL_ID,
            "schema_version": SCHEMA_VERSION,
            "architecture": architecture(args.width),
            "sample_shape": list(store.shape),
            "score_thresholds": thresholds,
            "selected_step": best["step"],
            "dataset_sha256": store.snapshot_sha,
            "state_dict": best_state,
        }
        with weights.open("xb") as stream:
            torch.save(payload, stream)
        reloaded = ISSPredictor(weights)
        if state_sha(reloaded.network) != frozen_sha:
            raise RuntimeError("ISS CPU checkpoint reload changed the selected state")
        del reloaded, best_state, optimizer, cache, x, target, observed, loss
        torch.cuda.empty_cache()
        log.emit("selection_frozen", step=best["step"], state_sha256=frozen_sha, score_thresholds=thresholds)
        # Test predictions are produced only after all checkpoint/threshold decisions freeze.
        partitions["test"] = load_partition(store, "test")
        demo = output / "demo"
        (demo / "cases").mkdir(parents=True)
        metrics, baselines, rows = {}, {}, []
        for split, cases in partitions.items():
            scores = predict_cases(network, cases, deadline)
            metrics[split] = {
                name: assess_field(cases, scores, thresholds[name], i) for i, name in enumerate(OUTPUTS)
            }
            nearby = [np.repeat(proximity_scores(c)[..., None], 2, axis=-1) for c in cases]
            zeros = [np.zeros_like(value) for value in scores]
            baselines[split] = {
                name: {
                    "all_cold": assess_field(cases, zeros, 0.5, i),
                    "source_proximity": assess_field(cases, nearby, baseline["score_thresholds"][name], i),
                }
                for i, name in enumerate(OUTPUTS)
            }
            for number, (case, score) in enumerate(zip(cases, scores)):
                record, config = case["record"], case["config"]
                metric = {name: metrics[split][name]["cases"][number] for name in OUTPUTS}
                export_case(demo / "cases" / (record["id"] + ".json"), case, score, thresholds, metric)
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
                        "sha256": file_sha(demo / "cases" / (record["id"] + ".json")),
                    }
                )
            log.emit(
                "partition_exported",
                split=split,
                cases=len(cases),
                metrics={
                    name: {key: value for key, value in metric.items() if key != "cases"}
                    for name, metric in metrics[split].items()
                },
            )
        torch.cuda.synchronize()
        inference = inference_benchmark(weights, partitions["validation"][0], network, deadline)
        write_json(output / "inference-benchmark.json", inference)
        compute_seconds = time.monotonic() - started
        peak_bytes = torch.cuda.max_memory_allocated()
        del network
        torch.cuda.empty_cache()
        telemetry = stop_telemetry(telemetry_process, telemetry_stream, output)
        telemetry_process = telemetry_stream = None
        write_json(output / "gpu-telemetry-summary.json", telemetry)
        if compute_seconds > args.seconds:
            raise TimeoutError("ISS POC exceeded its declared compute budget")
        model = {
            "id": MODEL_ID,
            "name": "U-Net 3D — chaleur et fumée / modules ISS",
            "trained_at": utc_now(),
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
            "architecture": architecture(args.width),
            "selected_step": best["step"],
            "optimizer_steps": updates,
            "batch_size": args.batch_size,
            "seed": SEED,
            "selection_metric": SELECTION,
            "selection_split": "validation",
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
                "loss": "equal heat/smoke field mass; equal positive/background BCE per observed active field; cold false positives retained",
                "sampler": "equal case mass; half uniform times, half either-field-active times where available",
                "source_hashes": source,
                "reload_state_match": True,
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
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--runtime", type=Path, help="Shared dev runtime lock; default dataset grandparent/runtime"
    )
    parser.add_argument("--seconds", type=int, default=1200)
    parser.add_argument("--steps", type=int, default=20000)
    parser.add_argument("--width", type=int, choices=(16, 24), default=16)
    parser.add_argument("--batch-size", type=int, choices=(32, 64, 128, 256), default=128)
    parser.add_argument("--validate-every", type=int, default=500)
    parser.add_argument("--benchmark-batches", action="store_true")
    args = parser.parse_args(argv)
    if (
        not 300 <= args.seconds <= 1200
        or not 500 <= args.steps <= 30000
        or not 100 <= args.validate_every <= 1000
    ):
        parser.error("Require 300..1200 seconds, 500..30000 steps and 100..1000 validation interval")
    return args


if __name__ == "__main__":
    run(parse_args())
