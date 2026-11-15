"""Bounded heat-only CUDA classifier and honest, all-case FDS/ML demo export.

No simulation, service activation, old weight modification, or test selection.
The target is a measured temperature >= ambient + 5 C, not ignition likelihood.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from ignis.ml.spatial_network import CHANNELS, FEATURE_VERSION, SpatialUNet, input_tensor
from torch import nn
from torch.nn import functional as F
from train_spatial import CaseStore, ProgressLog, require_cuda, source_hashes, write_json
from verify_spatial import state_sha

SEED = 20261114
HEAT_DELTA_C = 5.0
MODEL_ID = "hotspot-poc-20261114"
SCORE_SEMANTICS = "uncalibrated_hotspot_class_score"
METRIC_FILTER = "time_s > 0"
THRESHOLDS = np.unique(np.r_[1 / (1 + np.exp(-np.arange(-12.0, 12.01, 0.1))), 1.000001].astype(np.float32))
LIMITATIONS = [
    "POC de classification chaleur : T FDS >= température ambiante + 5 °C.",
    "Le score ML non calibré n'est ni une température ni une probabilité de départ de feu.",
    "Scénarios synthétiques FDS, sans validation expérimentale NASA ni garantie de sécurité.",
    "La source électrique est imposée ; le modèle ne prédit pas sa probabilité d'allumage.",
    "La fumée et la propagation de combustion ne sont pas prédites par ce classifieur.",
    "Grille d'observation 12 × 16 × 8 : les points ne constituent pas un champ continu validé.",
    "Les 40 cas test historiques ont déjà été examinés : géométries exclues du fitting, pas test vierge.",
    "Aucune affirmation de modèle généraliste ; matériaux, sources et conditions du corpus restent limités.",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def heat_target(case):
    observed = np.asarray(case["field_mask"][..., 0], dtype=bool)
    truth = case["temperature_c"] >= case["config"]["ambient_temperature_c"] + HEAT_DELTA_C
    return truth & observed, observed


def evaluation_mask(case):
    return heat_target(case)[1] & (case["time_s"] > 0)[:, None]


def gravity_group(case):
    return "microgravity" if case["config"]["gravity_g"] < 0.01 else "earth"


def metric_from_counts(tp, fp, fn, tn):
    tp, fp, fn, tn = (int(value) for value in (tp, fp, fn, tn))

    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "iou": ratio(tp, tp + fp + fn),
        "f1": ratio(2 * tp, 2 * tp + fp + fn),
        "false_positive_rate": ratio(fp, fp + tn),
        "n_valid": tp + fp + fn + tn,
    }


def classification(truth, score, observed, threshold):
    truth, score, observed = np.asarray(truth), np.asarray(score), np.asarray(observed)
    if truth.shape != score.shape or truth.shape != observed.shape:
        raise ValueError("Truth, scores and observation mask must align")
    if not np.isfinite(score[observed]).all():
        raise ValueError("Nonfinite scores at observed samples")
    predicted = score >= threshold
    return metric_from_counts(
        np.count_nonzero(observed & truth & predicted),
        np.count_nonzero(observed & ~truth & predicted),
        np.count_nonzero(observed & truth & ~predicted),
        np.count_nonzero(observed & ~truth & ~predicted),
    )


def add_metrics(rows):
    return metric_from_counts(*(sum(row[name] for row in rows) for name in ("tp", "fp", "fn", "tn")))


def assess_scores(cases, scores, threshold):
    if len(cases) != len(scores):
        raise ValueError("Every case must have one prediction array")
    rows = []
    for case, score in zip(cases, scores):
        truth, _ = heat_target(case)
        metric = classification(truth, score, evaluation_mask(case), threshold)
        rows.append(
            {
                "id": case["record"]["id"],
                "gravity": gravity_group(case),
                "incident_type": case["config"]["incident_type"],
                "sample_inactive": metric["tp"] + metric["fn"] == 0,
                **metric,
            }
        )
    groups = {
        name: add_metrics([row for row in rows if row["gravity"] == name])
        for name in ("microgravity", "earth")
    }
    groups["sample_inactive"] = add_metrics([row for row in rows if row["sample_inactive"]])
    groups["sample_active"] = add_metrics([row for row in rows if not row["sample_inactive"]])
    groups["incident_type"] = {
        kind: add_metrics([row for row in rows if row["incident_type"] == kind])
        for kind in sorted({row["incident_type"] for row in rows})
    }
    active_f1 = [row["f1"] for row in rows if not row["sample_inactive"]]
    inactive = [row for row in rows if row["sample_inactive"]]
    return {
        **add_metrics(rows),
        "groups": groups,
        "case_count": len(cases),
        "balanced_gravity_f1": sum(groups[name]["f1"] or 0 for name in ("microgravity", "earth")) / 2,
        "active_case_macro_f1": float(np.mean(active_f1)) if active_f1 else None,
        "sample_inactive_cases": len(inactive),
        "sample_inactive_cases_with_false_alarm": sum(row["fp"] > 0 for row in inactive),
        "cases": rows,
    }


def select_threshold(cases, scores):
    """One common threshold; mean microgravity/Earth F1, validation only.

    Fixed candidates and tie breaks are declared before any classifier fit.
    Counts come from all measured post-initial validation observations.
    """
    if not cases or any(case["record"]["split"] != "validation" for case in cases):
        raise ValueError("Threshold selection requires validation cases only")
    if len(cases) != len(scores):
        raise ValueError("Missing validation predictions")
    by_group = {name: [[], []] for name in ("microgravity", "earth")}
    for case, score in zip(cases, scores):
        truth, _ = heat_target(case)
        observed = evaluation_mask(case)
        if score.shape != truth.shape or not np.isfinite(score[observed]).all():
            raise ValueError("Invalid validation scores")
        group = by_group[gravity_group(case)]
        group[0].append(score[observed & truth])
        group[1].append(score[observed & ~truth])
    objective = np.zeros(len(THRESHOLDS))
    false_positives = np.zeros(len(THRESHOLDS), dtype=np.int64)
    for positives, negatives in by_group.values():
        if not positives:
            raise ValueError("Both gravity groups are required for validation selection")
        positive = np.sort(np.concatenate(positives))
        negative = np.sort(np.concatenate(negatives))
        if not len(positive):
            raise ValueError("Both validation gravity groups need measured positive observations")
        tp = len(positive) - np.searchsorted(positive, THRESHOLDS, side="left")
        fp = len(negative) - np.searchsorted(negative, THRESHOLDS, side="left")
        fn = len(positive) - tp
        objective += 0.5 * 2 * tp / np.maximum(1, 2 * tp + fp + fn)
        false_positives += fp
    best = max(range(len(THRESHOLDS)), key=lambda i: (objective[i], -false_positives[i], THRESHOLDS[i]))
    threshold = float(THRESHOLDS[best])
    assessment = assess_scores(cases, scores, threshold)
    return {
        "threshold": threshold,
        "selection_metric": "mean_microgravity_earth_f1",
        "selection_split": "validation",
        "value": float(objective[best]),
        "metrics": assessment,
        "candidate_curve": [
            {"threshold": float(t), "balanced_gravity_f1": float(f), "fp": int(n)}
            for t, f, n in zip(THRESHOLDS, objective, false_positives)
        ],
    }


def proximity_scores(case):
    """Label-free, fixed-in-time baseline: exp(-distance from compiled source patch/m)."""
    source_box = np.asarray(case["manifest"]["incident"]["source"]["bounds_m"]).reshape(3, 2)
    point = np.asarray(case["positions_m"])
    delta = np.maximum(np.maximum(source_box[:, 0] - point, point - source_box[:, 1]), 0)
    values = np.exp(-np.linalg.norm(delta, axis=1)).astype(np.float32)
    return np.broadcast_to(values, case["temperature_c"].shape).copy()


class HotspotClassifier(SpatialUNet):
    def __init__(self, width=16):
        super().__init__(width)
        self.field_head = nn.Conv3d(width, 1, 1)
        nn.init.zeros_(self.field_head.weight)
        nn.init.constant_(self.field_head.bias, -2.0)
        for parameter in self.global_head.parameters():
            parameter.requires_grad_(False)

    def forward(self, values):
        return super().forward(values)[0]


def classifier_architecture(width):
    return {
        "version": "heat-hotspot-unet3d-1",
        "feature_version": FEATURE_VERSION,
        "input_channels": list(CHANNELS),
        "widths": [width, 2 * width, 4 * width],
        "output": "one heat-class logit per sample",
        "heat_delta_c": HEAT_DELTA_C,
        "score_semantics": SCORE_SEMANTICS,
        "time_conditioning": "direct, no autoregression",
    }


def balanced_bce(logits, target, observed, *, validate=True):
    """Equal positive/background contributions on active frames, cold controls intact.

    Missing samples contribute no loss or gradient. No smoke or temperature
    regression target is used. Hard errors already receive larger BCE loss.
    """
    if logits.shape != target.shape or logits.shape != observed.shape:
        raise ValueError("Classification tensors must have identical shapes")
    observed, target = observed.bool(), target.bool()
    if validate and not observed.flatten(1).any(dim=1).all().item():
        raise ValueError("Each frame needs observed heat targets")
    safe_logits = torch.where(observed, logits, 0.0)
    errors = F.binary_cross_entropy_with_logits(safe_logits, target.to(logits.dtype), reduction="none")
    positive, negative = observed & target, observed & ~target
    dimensions = tuple(range(1, logits.ndim))
    npos, nneg = positive.sum(dimensions), negative.sum(dimensions)
    ploss = (errors * positive).sum(dimensions) / npos.clamp_min(1)
    nloss = (errors * negative).sum(dimensions) / nneg.clamp_min(1)
    present = (npos > 0).to(logits.dtype) + (nneg > 0).to(logits.dtype)
    return (ploss + nloss) / present.clamp_min(1)


def heat_loss(logits, target, observed, recipe, *, validate=True):
    loss = balanced_bce(logits, target, observed, validate=validate)
    if recipe == "balanced_bce":
        return loss
    if recipe != "dice_reflections":
        raise ValueError("Unknown classifier recipe")
    dimensions = tuple(range(1, logits.ndim))
    probability = torch.sigmoid(torch.where(observed.bool(), logits, 0.0)) * observed
    positive = target.bool() & observed.bool()
    count = positive.sum(dimensions)
    overlap = (probability * positive).sum(dimensions)
    dice = 1 - (2 * overlap + 1e-6) / (probability.sum(dimensions) + count + 1e-6)
    return loss + 0.5 * torch.where(count > 0, dice, 0.0)


def reflect_horizontal(x, target, observed, axis):
    """Reflect a scene and observations together; gravity/upward source face stay fixed.

    Fractional occupancy/material/source/vent grids move with the labels. The
    reflected coordinate, source location, relative displacement and boundary
    velocity channels are transformed as scalars/vectors require. No resampling.
    """
    if axis not in (0, 1):
        raise ValueError("Only horizontal reflections preserve the gravity/source-face setup")
    reflected = torch.flip(x, (axis + 2,))
    names = (
        ("x_over_width", "source_x_scaled", "source_dx", "boundary_u_scaled")
        if axis == 0
        else ("y_over_depth", "source_y_scaled", "source_dy", "boundary_v_scaled")
    )
    for name in names[:2]:
        reflected[:, CHANNELS.index(name)] = 1 - reflected[:, CHANNELS.index(name)]
    for name in names[2:]:
        reflected[:, CHANNELS.index(name)] *= -1
    return reflected, torch.flip(target, (axis + 2,)), torch.flip(observed, (axis + 2,))


def load_partition(store, split):
    cases = [store.get(index) for index in store.by_split[split]]
    store.cache.clear()
    return cases


def fit_cases(store):
    if store.snapshot["dataset_id"] != "spatial-compact-v1" or tuple(store.shape) != (12, 16, 8):
        raise ValueError("Expected verified compact dataset on the 12x16x8 grid")
    if [len(store.by_split[key]) for key in ("train", "validation", "test")] != [120, 40, 40]:
        raise ValueError("Expected 120 train / 40 validation / 40 historical test cases")
    return {split: load_partition(store, split) for split in ("train", "validation")}


class TrainingCache:
    def __init__(self, cases, device="cuda:0"):
        if any(case["record"]["split"] != "train" for case in cases):
            raise ValueError("Training cache must contain training cases only")
        x, y, masks, probabilities = [], [], [], []
        for case in cases:
            truth, observed = heat_target(case)
            frames = np.flatnonzero(case["time_s"] > 0)
            if not observed[frames].any(axis=1).all():
                raise ValueError("Every cached frame requires observed temperature labels")
            active = truth[frames].any(axis=1)
            # Half uniform times, half active times; each case has equal mass.
            p = np.full(len(frames), 1 / len(frames))
            if active.any():
                p = 0.5 * p + 0.5 * active / active.sum()
            probabilities.extend(p / len(cases))
            for frame in frames:
                x.append(
                    input_tensor(case["static"], case["config"], case["manifest"], case["time_s"][frame])
                )
                y.append(truth[frame].reshape(1, *case["shape"]))
                masks.append(observed[frame].reshape(1, *case["shape"]))
        self.x = torch.as_tensor(np.stack(x), device=device)
        self.y = torch.as_tensor(np.stack(y), device=device)
        self.mask = torch.as_tensor(np.stack(masks), device=device)
        self.probability = np.asarray(probabilities)
        if not np.isclose(self.probability.sum(), 1) or (self.probability <= 0).any():
            raise ValueError("Every training time must retain positive sampling probability")
        self.bytes = sum(v.numel() * v.element_size() for v in (self.x, self.y, self.mask))
        self.device_probability = torch.as_tensor(self.probability, device=device)

    def batch(self, rng, size, *, cuda_sampling=False):
        index = (
            torch.multinomial(self.device_probability, size, replacement=True)
            if cuda_sampling
            else torch.as_tensor(rng.choice(len(self.x), size, p=self.probability), device=self.x.device)
        )
        return [v.index_select(0, index) for v in (self.x, self.y, self.mask)]


def check_budget(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError("Bounded POC compute deadline reached; no more GPU work")


def benchmark_batches(network, cache, recipe, deadline, log):
    """25 measured steps per batch size, then restore initial state before fitting.

    Throughput selection uses only training data. The 5 GiB allocator guard
    remains active; select examples/second, never allocated VRAM percentage.
    """
    initial = {key: value.detach().cpu().clone() for key, value in network.state_dict().items()}
    rng = np.random.default_rng(SEED)
    rows = []
    for size in (32, 64, 128):
        network.load_state_dict(initial)
        optimizer = torch.optim.AdamW(
            (p for p in network.parameters() if p.requires_grad), lr=1e-3, weight_decay=1e-4
        )
        network.train()
        torch.cuda.synchronize()
        started = time.monotonic()
        for iteration in range(28):
            if iteration == 3:
                torch.cuda.synchronize()
                started = time.monotonic()
            check_budget(deadline)
            x, target, observed = cache.batch(rng, size, cuda_sampling=True)
            if recipe == "dice_reflections":
                x, target, observed = reflect_horizontal(x, target, observed, 0)
                x, target, observed = reflect_horizontal(x, target, observed, 1)
            optimizer.zero_grad(set_to_none=True)
            loss = heat_loss(network(x), target, observed, recipe, validate=False).mean()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(network.parameters(), 5.0, error_if_nonfinite=False)
            optimizer.step()
        torch.cuda.synchronize()
        seconds = time.monotonic() - started
        if not torch.isfinite(loss).item():
            raise ValueError("Nonfinite training-only throughput benchmark")
        row = {
            "batch_size": size,
            "warmup_steps": 3,
            "steps": 25,
            "seconds": seconds,
            "seconds_per_step": seconds / 25,
            "examples_per_second": size * 25 / seconds,
            "peak_allocator_bytes": torch.cuda.max_memory_allocated(),
        }
        rows.append(row)
        log.emit("training_throughput_benchmark", **row)
        del optimizer
    network.load_state_dict(initial)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    selected = max(rows, key=lambda row: row["examples_per_second"])["batch_size"]
    return selected, rows


def predict_cases(network, cases, deadline, batch_size=16):
    network.eval()
    result = []
    with torch.inference_mode():
        for case in cases:
            frames = []
            for start in range(0, len(case["time_s"]), batch_size):
                check_budget(deadline)
                x = np.stack(
                    [
                        input_tensor(case["static"], case["config"], case["manifest"], t)
                        for t in case["time_s"][start : start + batch_size]
                    ]
                )
                score = network(torch.as_tensor(x, device="cuda:0")).sigmoid()
                frames.append(score[:, 0].flatten(1).cpu().numpy())
            result.append(np.concatenate(frames))
    return result


def compact_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def selected_examples(rows):
    active = [
        row
        for row in rows
        if row["split"] == "validation"
        and row["gravity_g"] < 0.01
        and row["metrics"]["tp"] + row["metrics"]["fn"] > 0
    ]
    ordered = sorted(active, key=lambda row: (row["metrics"]["iou"], row["id"]))
    controls = sorted(
        [
            row
            for row in rows
            if row["split"] == "validation"
            and row["gravity_g"] < 0.01
            and row["metrics"]["tp"] + row["metrics"]["fn"] == 0
        ],
        key=lambda row: row["id"],
    )
    return {
        "representative": ordered[(len(ordered) - 1) // 2]["id"] if ordered else None,
        "failure": ordered[0]["id"] if ordered else None,
        "cold_control": controls[0]["id"] if controls else None,
    }


def compiled_scene(case):
    """Show the exact FDS AABB proxies, not prettier unsnapped Blender geometry."""
    manifest = case["manifest"]
    result = {
        "id": case["scene"].get("id", case["record"]["layout_id"]),
        "name": case["scene"].get("name", case["record"]["layout_id"]),
        "bounds_m": np.asarray(case["bounds_m"]).tolist(),
        "objects": [],
        "vents": [],
        "source": manifest["incident"]["source"],
        "geometry_semantics": "compiled FDS axis-aligned boxes",
    }
    for key in ("objects", "vents"):
        for obj in manifest[key]:
            box = np.asarray(obj["bounds_m"]).reshape(3, 2)
            result[key].append(
                {
                    **{
                        name: obj[name]
                        for name in (
                            "id",
                            "name",
                            "role",
                            "material_id",
                            "normal",
                            "combustible_material_id",
                            "thermal_thickness_m",
                        )
                        if name in obj
                    },
                    "center_m": box.mean(axis=1).tolist(),
                    "size_m": np.diff(box, axis=1)[:, 0].tolist(),
                }
            )
    return result


def export_case(path, case, scores, threshold, metric):
    truth, observed = heat_target(case)
    if scores.shape != truth.shape or not np.isfinite(scores[observed]).all():
        raise ValueError("Export requires exact, finite aligned predictions")
    frames = []
    for frame, time_s in enumerate(case["time_s"]):
        mask = observed[frame]
        # Python/JSON preserve the exact float32 prediction value: no rounding
        # may move a prediction across the frozen threshold.
        frames.append(
            {
                "time_s": float(time_s),
                "valid_mask": mask.tolist(),
                "temperature_c": [
                    float(t) if valid else None for t, valid in zip(case["temperature_c"][frame], mask)
                ],
                "hotspot_score": [float(s) if valid else None for s, valid in zip(scores[frame], mask)],
                "hotspot_truth": [bool(t) if valid else None for t, valid in zip(truth[frame], mask)],
                "predicted_hot_mask": [
                    bool(s >= threshold) if valid else None for s, valid in zip(scores[frame], mask)
                ],
            }
        )
    config = case["config"]
    compact_json(
        path,
        {
            "schema_version": "hotspot-poc-1",
            "id": case["record"]["id"],
            "split": case["record"]["split"],
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
            "score_threshold": threshold,
            "heat_delta_c": HEAT_DELTA_C,
            "metrics_time_filter": METRIC_FILTER,
            "metrics": metric,
            "frames": frames,
        },
    )


def save_weights(path, network, width, step, threshold):
    with Path(path).open("xb") as stream:
        torch.save(
            {
                "id": MODEL_ID,
                "architecture": classifier_architecture(width),
                "selected_step": step,
                "score_threshold": threshold,
                "state_dict": {
                    key: value.detach().cpu().clone() for key, value in network.state_dict().items()
                },
            },
            stream,
        )


def run(args):
    dataset, output = args.dataset.resolve(), args.output.resolve()
    if output == dataset or output.is_relative_to(dataset):
        raise ValueError("Output must remain outside the immutable source dataset")
    output.mkdir(parents=True, exist_ok=False)
    log = ProgressLog(output / "progress.jsonl")
    started = time.monotonic()
    deadline = started + args.seconds
    try:
        compute = require_cuda()
        torch.set_num_threads(4)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.manual_seed(SEED)
        torch.cuda.manual_seed_all(SEED)
        log.emit("poc_started", **compute, budget_seconds=args.seconds, pid=os.getpid())
        store = CaseStore(dataset)
        store.verify(log)
        partitions = fit_cases(store)
        write_json(output / "dataset-snapshot.json", store.snapshot)
        source = {
            **source_hashes(),
            "tools/remote/verify_spatial.py": hashlib.sha256(
                Path(__file__).with_name("verify_spatial.py").read_bytes()
            ).hexdigest(),
            "tools/remote/train_hotspot_poc.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        write_json(output / "sources.json", source)
        baseline_selection = select_threshold(
            partitions["validation"], [proximity_scores(c) for c in partitions["validation"]]
        )
        write_json(output / "baseline-validation-selection.json", baseline_selection)
        cache = TrainingCache(partitions["train"])
        log.emit("device_cache_ready", frames=len(cache.x), bytes=cache.bytes, cases=len(partitions["train"]))
        network = HotspotClassifier(args.width).to("cuda:0")
        throughput = []
        if args.benchmark_batches:
            args.batch_size, throughput = benchmark_batches(network, cache, args.recipe, deadline, log)
            write_json(
                output / "throughput.json", {"selected_batch_size": args.batch_size, "rows": throughput}
            )
        optimizer = torch.optim.AdamW(
            (p for p in network.parameters() if p.requires_grad), lr=1e-3, weight_decay=1e-4
        )
        rng = np.random.default_rng(SEED)
        best, best_state, history = None, None, []
        training_started = time.monotonic()
        last_loss, step, updates = None, 0, 0
        for step in range(1, args.steps + 1):
            if time.monotonic() >= deadline - 150:
                break
            network.train()
            x, target, observed = cache.batch(rng, args.batch_size, cuda_sampling=args.benchmark_batches)
            if args.recipe == "dice_reflections":
                for axis in (0, 1):
                    if rng.random() < 0.5:
                        x, target, observed = reflect_horizontal(x, target, observed, axis)
            optimizer.zero_grad(set_to_none=True)
            logits = network(x)
            loss = heat_loss(logits, target, observed, args.recipe, validate=False).mean()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(network.parameters(), 5.0, error_if_nonfinite=False)
            optimizer.step()
            updates += 1
            if step == 1 or step % args.validate_every == 0:
                if not torch.isfinite(loss).item():
                    raise ValueError("Nonfinite classifier loss")
                last_loss = float(loss.item())
            if step == 1:
                torch.cuda.synchronize()
                log.emit(
                    "cuda_training_started",
                    device_name=compute["device_name"],
                    device="cuda:0",
                    parameters=sum(p.numel() for p in network.parameters()),
                    optimizer_step_completed=True,
                    allocated_bytes=torch.cuda.memory_allocated(),
                    loss=last_loss,
                )
            if step % args.validate_every == 0:
                scores = predict_cases(network, partitions["validation"], deadline)
                selection = select_threshold(partitions["validation"], scores)
                improved = best is None or selection["value"] > best["value"]
                if improved:
                    best = {**selection, "step": step}
                    best_state = {
                        key: value.detach().cpu().clone() for key, value in network.state_dict().items()
                    }
                row = {
                    "step": step,
                    "loss": last_loss,
                    "balanced_gravity_f1": selection["value"],
                    "threshold": selection["threshold"],
                    "improved": improved,
                    "best_step": best["step"],
                    "microgravity": selection["metrics"]["groups"]["microgravity"],
                    "earth": selection["metrics"]["groups"]["earth"],
                }
                history.append(row)
                write_json(output / f"validation-step-{step:06d}.json", selection)
                log.emit("validation", **row)
        fit_elapsed = time.monotonic() - training_started
        if best is None:
            raise RuntimeError("Budget expired before the first validation; no deployable weights")
        network.load_state_dict(best_state, strict=True)
        frozen_state_sha = state_sha(network)
        threshold = best["threshold"]
        write_json(
            output / "frozen-selection.json",
            {
                "selected_at": utc_now(),
                "step": best["step"],
                "threshold": threshold,
                "selection_metric": best["selection_metric"],
                "value": best["value"],
                "selection_split": "validation",
                "state_sha256": frozen_state_sha,
                "baseline_threshold": baseline_selection["threshold"],
                "test_labels_used_for_selection": False,
            },
        )
        weights = output / "weights.pt"
        save_weights(weights, network, args.width, best["step"], threshold)
        reloaded = HotspotClassifier(args.width)
        reloaded.load_state_dict(
            torch.load(weights, map_location="cpu", weights_only=True)["state_dict"], strict=True
        )
        if state_sha(reloaded) != frozen_state_sha:
            raise RuntimeError("Saved/reloaded state mismatch")
        del reloaded, best_state, optimizer, cache
        torch.cuda.empty_cache()
        log.emit(
            "selection_frozen",
            step=best["step"],
            threshold=threshold,
            state_sha256=frozen_state_sha,
            elapsed_seconds=time.monotonic() - started,
        )
        # Historical test is loaded for evaluation only after all decisions freeze.
        partitions["test"] = load_partition(store, "test")
        demo = output / "demo"
        (demo / "cases").mkdir(parents=True)
        metrics, baseline_metrics, rows = {}, {}, []
        for split, cases in partitions.items():
            scores = predict_cases(network, cases, deadline)
            assessment = assess_scores(cases, scores, threshold)
            metrics[split] = assessment
            baseline_metrics[split] = {
                "all_cold": assess_scores(cases, [np.zeros_like(s) for s in scores], 0.5),
                "source_proximity": assess_scores(
                    cases, [proximity_scores(c) for c in cases], baseline_selection["threshold"]
                ),
            }
            for case, score, metric in zip(cases, scores, assessment["cases"]):
                record, config = case["record"], case["config"]
                identifier = record["id"]
                if Path(identifier).name != identifier or "/" in identifier or "\\" in identifier:
                    raise ValueError("Unsafe demo case identifier")
                export_case(demo / "cases" / (identifier + ".json"), case, score, threshold, metric)
                observed = evaluation_mask(case)
                rows.append(
                    {
                        "id": identifier,
                        "split": split,
                        "layout_id": record["layout_id"],
                        "evaluation_role": "historical_test_already_reviewed" if split == "test" else split,
                        "family": record.get("structural_family", record.get("family_id", "unknown")),
                        **{
                            key: config[key]
                            for key in ("gravity_g", "incident_type", "ambient_temperature_c", "airflow_m_s")
                        },
                        "peak_temperature_c": float(np.max(case["temperature_c"][observed])),
                        "metrics": metric,
                        "url": "./cases/" + identifier + ".json",
                    }
                )
            log.emit(
                "partition_exported",
                split=split,
                cases=len(cases),
                metrics={k: v for k, v in assessment.items() if k != "cases"},
            )
        torch.cuda.synchronize()
        compute_elapsed = time.monotonic() - started
        peak_bytes = torch.cuda.max_memory_allocated()
        del network
        torch.cuda.empty_cache()
        if compute_elapsed > args.seconds:
            raise TimeoutError("POC exceeded its declared compute budget")
        model = {
            "id": MODEL_ID,
            "name": "U-Net 3D — classification chaleur",
            "trained_at": utc_now(),
            "device": compute["device_name"],
            "heat_delta_c": HEAT_DELTA_C,
            "score_threshold": threshold,
            "score_semantics": SCORE_SEMANTICS,
            "training_seconds": fit_elapsed,
            "total_compute_seconds": compute_elapsed,
            "weights_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
            "state_sha256": frozen_state_sha,
            "dataset_sha256": store.snapshot_sha,
            "architecture": classifier_architecture(args.width),
            "selected_step": best["step"],
            "optimizer_steps": updates,
            "batch_size": args.batch_size,
            "seed": SEED,
            "recipe": args.recipe,
            "selection_metric": best["selection_metric"],
            "selection_split": "validation",
        }
        examples = selected_examples(rows)
        index = {
            "schema_version": "hotspot-poc-1",
            "generated_at": utc_now(),
            "model": model,
            "metrics_time_filter": METRIC_FILTER,
            "metrics": metrics,
            "baselines": baseline_metrics,
            "baseline_source_proximity_threshold": baseline_selection["threshold"],
            "baseline_source_proximity_radius_m": -math.log(baseline_selection["threshold"])
            if baseline_selection["threshold"] <= 1
            else None,
            "cases": rows,
            "default_case_id": examples["representative"],
            "example_cases": examples,
            "example_selection": "Validation microgravity only: lower median IoU among sample-active cases; lowest IoU failure; first ID sample-inactive control. Every case remains accessible.",
            "limitations": LIMITATIONS,
        }
        compact_json(demo / "hotspots.json", index)
        write_json(
            output / "report.json",
            {
                **index,
                "throughput_benchmark": throughput,
                "compute": compute,
                "peak_allocator_bytes": peak_bytes,
                "budget_seconds": args.seconds,
                "history": history,
                "loss": "equal positive/background BCE per active frame, observed background BCE on cold frames"
                + (" plus 0.5 soft Dice on active frames" if args.recipe == "dice_reflections" else ""),
                "augmentation": "independent X/Y reflection probability 0.5, matching coordinates/source/vent vectors/targets"
                if args.recipe == "dice_reflections"
                else "none",
                "sampler": "equal training case mass; half uniform times plus half sample-active times where present",
                "source_hashes": source,
                "reload_state_match": True,
            },
        )
        log.emit(
            "completed",
            model=model,
            peak_allocator_bytes=peak_bytes,
            examples=examples,
            cases_exported=len(rows),
            output=str(output),
        )
    except BaseException as exc:
        log.emit("failed", error=type(exc).__name__, message=str(exc))
        raise
    finally:
        log.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=650)
    parser.add_argument("--steps", type=int, default=16000)
    parser.add_argument("--width", type=int, choices=(16, 24), default=16)
    parser.add_argument("--batch-size", type=int, choices=(16, 32, 64, 128), default=32)
    parser.add_argument("--validate-every", type=int, default=500)
    parser.add_argument("--recipe", choices=("balanced_bce", "dice_reflections"), default="balanced_bce")
    parser.add_argument("--benchmark-batches", action="store_true")
    args = parser.parse_args(argv)
    if (
        not 240 <= args.seconds <= 1200
        or not 500 <= args.steps <= 30000
        or not 100 <= args.validate_every <= 2000
    ):
        parser.error("Require 240..1200 seconds, 500..30000 steps and 100..2000 validation interval")
    return args


if __name__ == "__main__":
    run(parse_args())
