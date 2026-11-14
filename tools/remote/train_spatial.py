"""Train a bounded CUDA 3D U-Net on a frozen, verified FDS dataset snapshot.

python tools/remote/train_spatial.py --home E:/IGNIS-Valley-dev --dataset E:/IGNIS-Valley-dev/datasets/incidents-v1 --model-id spatial-pilot-v1 --epochs 20 --batch-size 4
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import uuid
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from ignis.locking import ProcessLock
from ignis.ml.incidents import COMPILER_VERSION, GLOBAL_KEYS, INCIDENT_TYPES, file_sha
from ignis.ml.spatial_dataset import load_spatial_case, read_spatial_index
from ignis.ml.spatial_network import (
    FEATURE_VERSION,
    MODEL_IDS,
    SpatialUNet,
    architecture,
    checkpoint,
    decode_fields,
    decode_globals,
    encode_fields,
    encode_globals,
    geometry_channels,
    input_tensor,
    masked_loss,
    sampling_grid,
)
from ignis.physics import compile_case
from ignis.physics.materials import MODEL_VERSION
from ignis.provenance import canonical_sha

SEED = 20261114
CUDA_BUDGET_BYTES = 5 * 1024**3
MODEL_DATASETS = {
    "spatial-pilot-v1": ("incidents-v1", (8, 10, 4)),
    "spatial-corpus-v1": ("spatial-corpus-v1", (12, 16, 8)),
}
SOURCE_MODULES = {
    "tools/remote/train_spatial.py": None,
    "backend/ignis/ml/spatial_network.py": "ignis.ml.spatial_network",
    "backend/ignis/ml/spatial_dataset.py": "ignis.ml.spatial_dataset",
    "backend/ignis/physics/compiler.py": "ignis.physics.compiler",
    "backend/ignis/physics/incidents.py": "ignis.physics.incidents",
    "backend/ignis/physics/materials.py": "ignis.physics.materials",
}


def source_hashes():
    """Pin the loaded checkout's source bytes without depending on the shell cwd."""
    root = Path(__file__).resolve().parents[2]
    hashes = {}
    for relative_path, module_name in SOURCE_MODULES.items():
        path = (root / relative_path).resolve()
        loaded = Path(__file__ if module_name is None else sys.modules[module_name].__file__).resolve()
        if loaded != path:
            raise RuntimeError(f"Training module imported from a different checkout: {relative_path}")
        hashes[relative_path] = file_sha(path)
    return hashes


def execution_metadata(**arguments):
    """Record effective function arguments; a direct call is not presented as a CLI."""
    cli = bool(sys.argv) and Path(sys.argv[0]).resolve() == Path(__file__).resolve()
    return {
        "entrypoint": "tools/remote/train_spatial.py::train",
        "python_executable": sys.executable,
        "command_argv": [sys.executable, *sys.argv] if cli else None,
        "working_directory": str(Path.cwd()),
        "arguments": {
            key: str(value.resolve()) if isinstance(value, Path) else value
            for key, value in arguments.items()
        },
    }


def validate_dataset_identity(model_id, dataset_id, shape=None):
    expected_id, expected_shape = MODEL_DATASETS[model_id]
    if dataset_id != expected_id:
        raise ValueError(f"Model {model_id} requires dataset {expected_id}; received {dataset_id}")
    if shape is not None and tuple(shape) != expected_shape:
        raise ValueError(f"Model {model_id} requires sampling shape {expected_shape}; received {shape}")


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


class ProgressLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("x", encoding="utf-8")
        self.started = time.monotonic()

    def emit(self, stage, **values):
        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": round(time.monotonic() - self.started, 3),
            "stage": stage,
            **values,
        }
        line = json.dumps(event, ensure_ascii=False, allow_nan=False)
        self.stream.write(line + "\n")
        self.stream.flush()
        print(line, flush=True)

    def close(self):
        self.stream.close()


def require_cuda():
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for spatial training; CPU fallback is refused")
    device = torch.device("cuda:0")
    torch.cuda.set_device(device)
    total = torch.cuda.get_device_properties(device).total_memory
    budget = min(CUDA_BUDGET_BYTES, int(total * 0.8))
    torch.cuda.set_per_process_memory_fraction(budget / total, device=device)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)
    return {
        "device": str(device),
        "device_name": torch.cuda.get_device_name(device),
        "total_memory_bytes": total,
        "allocator_limit_bytes": budget,
        "memory_limit_basis": "PyTorch allocator; CUDA context/library overhead is additional",
        "torch_version": str(torch.__version__),
        "cuda_version": torch.version.cuda,
    }


def physical_signature(manifest):
    objects = [
        {
            key: obj.get(key)
            for key in ("bounds_m", "material_id", "combustible_material_id", "thermal_thickness_m")
        }
        for obj in manifest["objects"]
    ]
    vents = [{key: vent[key] for key in ("bounds_m", "normal", "role")} for vent in manifest["vents"]]
    return canonical_sha(
        {
            "bounds": manifest["sampling"]["bounds_m"],
            "objects": sorted(objects, key=canonical_sha),
            "vents": sorted(vents, key=canonical_sha),
        }
    )


class CaseStore:
    """Only indices plus at most two complete cases and their static grids live in RAM."""

    def __init__(self, directory, *, allow_incomplete=False):
        self.directory = Path(directory).resolve()
        path = self.directory / "manifest.json"
        self.source_sha = file_sha(path)
        original = read_spatial_index(self.directory)
        if file_sha(path) != self.source_sha:
            raise ValueError("Spatial manifest changed during snapshot acquisition; retry from the new index")
        records = original["runs"]
        if not allow_incomplete and (
            len(records) != original.get("expected_runs", len(records))
            or any(r.get("status", "completed") != "completed" for r in records)
        ):
            raise ValueError(
                "Dataset incomplete: explicit --allow-incomplete creates a completed-case snapshot"
            )
        self.records = copy.deepcopy([r for r in records if r.get("status", "completed") == "completed"])
        if not self.records or len({r["id"] for r in self.records}) != len(self.records):
            raise ValueError("Empty spatial snapshot or duplicate run IDs")
        groups, self.by_split = {}, {split: [] for split in ("train", "validation", "test")}
        structural_splits = {}
        for index, record in enumerate(self.records):
            group = record.get("layout_id", record.get("family_id"))
            split = record["split"]
            if not group or split not in self.by_split or (group in groups and groups[group] != split):
                raise ValueError("Missing or leaked layout/family split")
            if record.get("scene_id") == "crossflow" and split != "test":
                raise ValueError("Crossflow remains test-only")
            record["layout_id"] = group
            groups[group] = split
            self.by_split[split].append(index)
            structural_family = record.get("structural_family")
            if structural_family:
                if structural_family in structural_splits and structural_splits[structural_family] != split:
                    raise ValueError("Structural-family leakage across spatial partitions")
                structural_splits[structural_family] = split
        if any(not indices for indices in self.by_split.values()):
            raise ValueError("Train, validation and test partitions must all be present")
        self.snapshot = {
            "dataset_id": original["dataset_id"],
            "source_manifest_sha256": self.source_sha,
            "source_merged_index_sha256": canonical_sha(original),
            "source_expected_runs": original.get("expected_runs", len(records)),
            "partial": len(self.records) != original.get("expected_runs", len(records)),
            "runs": self.records,
        }
        self.cache = OrderedDict()
        self.frames = {}
        self.shape = None

    def folder(self, index):
        path = (self.directory / self.records[index]["relative_path"]).resolve()
        if not path.is_relative_to(self.directory):
            raise ValueError("Spatial case path leaves the dataset")
        return path

    def get(self, index):
        if index in self.cache:
            self.cache.move_to_end(index)
            return self.cache[index]
        case = load_spatial_case(self.folder(index), self.records[index])
        # Effective compiler config is authoritative; config.json is hashed separately.
        case["input_config"] = case["config"]
        case["config"] = case["manifest"]["config"]
        case["static"] = geometry_channels(case["manifest"])
        self.cache[index] = case
        while len(self.cache) > 2:
            self.cache.popitem(last=False)
        return case

    def verify(self, progress=None):
        """Read and verify sequentially; no corpus-sized list of target arrays exists."""
        import tempfile

        signatures = {}
        for index, record in enumerate(self.records):
            case = self.get(index)
            manifest, provenance = case["manifest"], case["provenance"]
            expected = {
                "origin": "simulation",
                "compiler_version": COMPILER_VERSION,
                "material_model_version": MODEL_VERSION,
                "scene_sha256": canonical_sha(case["scene"]),
                "config_sha256": canonical_sha(manifest["config"]),
                "input_sha256": manifest["deck_sha256"],
            }
            if any(provenance.get(key) != value for key, value in expected.items()):
                raise ValueError("Spatial labels must come from matching FDS simulations: " + record["id"])
            fingerprint = canonical_sha(
                {"scene": case["scene"], "config": case["input_config"], "compiler": COMPILER_VERSION}
            )
            if "fingerprint" in record and record["fingerprint"] != fingerprint:
                raise ValueError("Spatial run fingerprint mismatch")
            with tempfile.TemporaryDirectory(prefix="ignis-spatial-verify-") as directory:
                rebuilt = compile_case(case["scene"], case["input_config"], Path(directory))
            for key in ("sampling", "objects", "vents", "incident", "deck_sha256", "config_sha256"):
                if canonical_sha(manifest.get(key)) != canonical_sha(rebuilt.get(key)):
                    raise ValueError("Spatial compiler reconstruction mismatch: " + key)
            shape, bounds, positions, mask, _, _ = sampling_grid(manifest)
            if self.shape is not None and self.shape != shape:
                raise ValueError("A model snapshot must have a single sample shape; no resampling")
            self.shape = shape
            if (
                not np.array_equal(case["shape"], shape)
                or not np.array_equal(case["bounds_m"], bounds)
                or not np.array_equal(case["positions_m"], positions)
                or not np.array_equal(case["valid_mask"], np.broadcast_to(mask, case["valid_mask"].shape))
            ):
                raise ValueError("Spatial arrays disagree with compiled geometry")
            times = case["time_s"]
            if (
                not np.isfinite(times).all()
                or not len(times)
                or times[0] != 0
                or np.any(np.diff(times) <= 0)
                or abs(times[-1] - case["config"]["duration_s"]) > 0.01
            ):
                raise ValueError("Incomplete or unordered FDS trajectory")
            if (
                np.isinf(case["temperature_c"]).any()
                or np.isinf(case["smoke_kg_m3"]).any()
                or np.any(case["smoke_kg_m3"][case["field_mask"][..., 1]] < -1e-12)
                or not case["field_mask"].reshape(len(times), -1).any(axis=1).all()
                or not case["global_mask"].any(axis=1).all()
            ):
                raise ValueError("Invalid or entirely unobserved spatial frame")
            signature = physical_signature(manifest)
            if signature in signatures and signatures[signature] != record["split"]:
                raise ValueError("Physical geometry leakage despite different layout IDs")
            signatures[signature] = record["split"]
            record["geometry_signature"] = signature
            # Pin all effective input/target bytes even for the historical pilot.
            names = ["scene.json", "config.json", "manifest.json", "ignis.fds"]
            target = record.get("npz_file", "fields.npz")
            names.append(
                target if (self.folder(index) / target).exists() else record.get("result_file", "result.json")
            )
            hashes = {
                name: file_sha(self.folder(index) / name)
                for name in names
                if (self.folder(index) / name).exists()
            }
            record["file_hashes"] = {**record.get("file_hashes", {}), **hashes}
            self.frames[index] = [int(i) for i in np.flatnonzero(times > 0)]
            if progress and (index + 1) % 10 == 0:
                progress.emit("dataset_verification", checked=index + 1, runs=len(self.records))
        self.cache.clear()
        self.snapshot["sample_shape"] = list(self.shape)
        self.snapshot_sha = canonical_sha(self.snapshot)
        train = [self.records[i] for i in self.by_split["train"]]
        families = {self.get(i)["config"]["incident_type"] for i in self.by_split["train"]}
        if families != set(INCIDENT_TYPES):
            raise ValueError("Training snapshot must cover all five incident families")
        self.layout_counts = Counter(record["layout_id"] for record in train)


def frame_plan(store, rng, cap):
    """Balanced layout/run budget, renewed each epoch; only integer indices are stored."""
    plan = []
    train = store.by_split["train"]
    if cap < len(train):
        raise ValueError("max-train-frames must allow at least one frame per training case")
    for index in rng.permutation(train):
        record = store.records[index]
        count = max(1, cap // (len(store.layout_counts) * store.layout_counts[record["layout_id"]]))
        frames = store.frames[index]
        selected = rng.choice(frames, size=min(count, len(frames)), replace=False)
        weight = 1 / (store.layout_counts[record["layout_id"]] * len(selected))
        plan.extend((int(index), int(frame), weight) for frame in selected)
    if len(plan) > cap:
        raise ValueError("Frame cap too small for balanced layout allocation")
    mean = np.mean([row[2] for row in plan])
    return [(index, frame, weight / mean) for index, frame, weight in plan]


def training_batch(store, selected, device):
    inputs, fields, masks, globals_, global_masks, weights, active_weights = [], [], [], [], [], [], []
    for index, frame, weight in selected:
        case = store.get(index)
        ambient, shape = case["config"]["ambient_temperature_c"], store.shape
        raw = np.stack([case["temperature_c"][frame], case["smoke_kg_m3"][frame]], axis=-1)
        observed = case["field_mask"][frame]
        active = np.column_stack([raw[:, 0] >= ambient + 5, raw[:, 1] >= 1e-7]) & observed
        inputs.append(input_tensor(case["static"], case["config"], case["manifest"], case["time_s"][frame]))
        fields.append(encode_fields(raw, ambient).T.reshape(2, *shape))
        masks.append(observed.T.reshape(2, *shape))
        active_weights.append((1 + 4 * active).T.reshape(2, *shape))
        globals_.append(encode_globals(case["globals"][frame], ambient))
        global_masks.append(case["global_mask"][frame])
        weights.append(weight)
    values = (inputs, fields, masks, globals_, global_masks, weights, active_weights)
    return [
        torch.as_tensor(np.asarray(v), dtype=torch.bool if i in (2, 4) else torch.float32, device=device)
        for i, v in enumerate(values)
    ]


def fit_epoch(network, optimizer, store, rng, *, device, batch_size, max_frames, first_step=None):
    network.train()
    plan = frame_plan(store, rng, max_frames)
    total = 0.0
    for start in range(0, len(plan), batch_size):
        x, y, mask, g, gm, weights, active = training_batch(store, plan[start : start + batch_size], device)
        optimizer.zero_grad(set_to_none=True)
        predicted, global_predicted = network(x)
        loss = (
            (masked_loss(predicted, y, mask, active) + 0.25 * masked_loss(global_predicted, g, gm)) * weights
        ).mean()
        if not torch.isfinite(loss).item():
            raise ValueError("Nonfinite spatial training loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(network.parameters(), 5.0, error_if_nonfinite=True)
        optimizer.step()
        if first_step:
            first_step()
            first_step = None
        total += float(loss.item()) * len(x)
    return total / len(plan), len(plan)


def predict_case(network, case, *, device, batch_size):
    shape, ambient = tuple(case["shape"]), case["config"]["ambient_temperature_c"]
    fields, globals_ = [], []
    if network is None:
        return (
            np.broadcast_to([ambient, 0.0], (*case["temperature_c"].shape, 2)).copy(),
            np.tile([ambient, ambient, 0.0, 0.0], (len(case["time_s"]), 1)),
        )
    network.eval()
    with torch.inference_mode():
        for start in range(0, len(case["time_s"]), batch_size):
            times = case["time_s"][start : start + batch_size]
            inputs = np.stack(
                [input_tensor(case["static"], case["config"], case["manifest"], t) for t in times]
            )
            f, g = network(torch.from_numpy(inputs).to(device))
            fields.append(
                decode_fields(
                    f.cpu().numpy().reshape(len(times), 2, int(np.prod(shape))).transpose(0, 2, 1), ambient
                )
            )
            globals_.append(decode_globals(g.cpu().numpy(), ambient))
    fields, globals_ = np.concatenate(fields), np.concatenate(globals_)
    initial = case["time_s"] == 0
    fields[initial], globals_[initial] = [ambient, 0.0], [ambient, ambient, 0.0, 0.0]
    if not np.isfinite(fields).all() or not np.isfinite(globals_).all():
        raise ValueError("Nonfinite spatial evaluation prediction")
    return fields, globals_


def run_metrics(case, fields, globals_):
    truth = np.stack([case["temperature_c"], case["smoke_kg_m3"]], axis=-1)
    mask, gm, ambient = case["field_mask"], case["global_mask"], case["config"]["ambient_temperature_c"]
    delta = fields - truth
    encoded = abs(encode_fields(fields, ambient) - encode_fields(truth, ambient))
    global_encoded = abs(encode_globals(globals_, ambient) - encode_globals(case["globals"], ambient))
    hot, smoky = mask[..., 0] & (truth[..., 0] >= ambient + 5), mask[..., 1] & (truth[..., 1] >= 1e-7)
    observed_temperature, observed_smoke = mask[..., 0].any(), mask[..., 1].any()
    row = {
        "run_id": case["record"]["id"],
        "layout_id": case["record"]["layout_id"],
        "incident_type": case["config"]["incident_type"],
        "observations": int(mask.sum()),
        "temperature_mae_c": float(abs(delta[..., 0][mask[..., 0]]).mean()) if observed_temperature else None,
        "smoke_mae_kg_m3": float(abs(delta[..., 1][mask[..., 1]]).mean()) if observed_smoke else None,
        "temperature_peak_error_c": float(
            abs(fields[..., 0][mask[..., 0]].max() - truth[..., 0][mask[..., 0]].max())
        )
        if observed_temperature
        else None,
        "smoke_peak_error_kg_m3": float(
            abs(fields[..., 1][mask[..., 1]].max() - truth[..., 1][mask[..., 1]].max())
        )
        if observed_smoke
        else None,
        "hot_temperature_mae_c": float(abs(delta[..., 0][hot]).mean()) if hot.any() else None,
        "smoky_smoke_mae_kg_m3": float(abs(delta[..., 1][smoky]).mean()) if smoky.any() else None,
        "hot_observations": int(hot.sum()),
        "smoky_observations": int(smoky.sum()),
    }
    # Missing channels contribute no score, including wholly absent global fields.
    # A fully unobserved case remains unavailable rather than appearing perfect.
    field_error = encoded[mask].mean() if mask.any() else 0.0
    global_error = global_encoded[gm].mean() if gm.any() else 0.0
    selection = float(field_error + 0.25 * global_error)
    selection += 0.5 * float(encoded[..., 0][hot].mean()) if hot.any() else 0
    selection += 0.5 * float(encoded[..., 1][smoky].mean()) if smoky.any() else 0
    row["encoded_selection_error"] = selection if mask.any() or gm.any() else None
    for channel, key in enumerate(GLOBAL_KEYS):
        observed = gm[:, channel]
        row["fds_global_" + key + "_mae"] = (
            float(abs(globals_[:, channel][observed] - case["globals"][:, channel][observed]).mean())
            if observed.any()
            else None
        )
    return row


def summarize(rows):
    keys = [
        key
        for key, value in rows[0].items()
        if key
        not in {
            "run_id",
            "layout_id",
            "incident_type",
            "observations",
            "hot_observations",
            "smoky_observations",
        }
    ]
    layouts = []
    for layout in sorted({row["layout_id"] for row in rows}):
        selected = [row for row in rows if row["layout_id"] == layout]
        values = {key: [row[key] for row in selected if row[key] is not None] for key in keys}
        layouts.append(
            {"layout_id": layout, **{key: float(np.mean(v)) if v else None for key, v in values.items()}}
        )
    values = {key: [row[key] for row in layouts if row[key] is not None] for key in keys}
    return {
        "runs": len(rows),
        "layouts": len(layouts),
        "per_layout": layouts,
        "layout_balanced": {key: float(np.mean(v)) if v else None for key, v in values.items()},
    }


def evaluate(store, split, network=None, *, device="cpu", batch_size=4):
    rows = []
    for index in store.by_split[split]:
        case = store.get(index)
        fields, globals_ = predict_case(network, case, device=device, batch_size=batch_size)
        rows.append(run_metrics(case, fields, globals_))
    return {
        **summarize(rows),
        "per_run": rows,
        "per_incident_type": {
            kind: summarize([row for row in rows if row["incident_type"] == kind])
            for kind in INCIDENT_TYPES
            if any(row["incident_type"] == kind for row in rows)
        },
    }


def publish(output, metadata, payload, evaluation, snapshot):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ProcessLock(output.parent / ("." + output.name + ".publish.lock")):
        if output.exists():
            raise FileExistsError("Existing spatial model is preserved; use another version")
        stage = output.parent / ("." + output.name + "-staging-" + uuid.uuid4().hex)
        stage.mkdir()
        with (stage / "weights.pt").open("xb") as stream:
            torch.save(payload, stream)
        metadata["weights_sha256"] = file_sha(stage / "weights.pt")
        write_json(stage / "evaluation.json", evaluation)
        write_json(stage / "dataset-snapshot.json", snapshot)
        write_json(stage / "metadata.json", metadata)
        if output.exists():
            raise FileExistsError("Destination appeared; complete staging directory preserved")
        stage.rename(output)


def train(
    home,
    dataset_path,
    *,
    model_id="spatial-pilot-v1",
    epochs=20,
    batch_size=4,
    patience=5,
    max_frames=20000,
    allow_incomplete=False,
):
    home = Path(home)
    output = home / "runtime/models" / model_id
    if output.exists():
        raise FileExistsError("Existing model is preserved; training will not overwrite it")
    if (
        model_id not in MODEL_IDS
        or not 5 <= epochs <= 40
        or not 2 <= batch_size <= 8
        or not 2 <= patience <= 10
        or not 100 <= max_frames <= 100000
    ):
        raise ValueError("Invalid bounded spatial training configuration")
    compute = require_cuda()
    log = ProgressLog(home / "runtime/training" / (model_id + "-" + uuid.uuid4().hex + ".jsonl"))
    started = time.perf_counter()
    try:
        log.emit("cuda_available", **compute)
        sources = source_hashes()
        execution = execution_metadata(
            home=home,
            dataset_path=Path(dataset_path),
            model_id=model_id,
            epochs=epochs,
            batch_size=batch_size,
            patience=patience,
            max_frames=max_frames,
            allow_incomplete=allow_incomplete,
        )
        log.emit("source_snapshot", source_sha256=sources, execution=execution)
        store = CaseStore(dataset_path, allow_incomplete=allow_incomplete)
        validate_dataset_identity(model_id, store.snapshot["dataset_id"])
        store.verify(log)
        validate_dataset_identity(model_id, store.snapshot["dataset_id"], store.shape)
        log.emit(
            "dataset_verified",
            runs=len(store.records),
            shape=store.shape,
            splits={key: len(value) for key, value in store.by_split.items()},
            snapshot_sha256=store.snapshot_sha,
        )
        torch.manual_seed(SEED)
        torch.cuda.manual_seed_all(SEED)
        torch.set_num_threads(4)
        rng = np.random.default_rng(SEED)
        device = compute["device"]
        network = SpatialUNet().to(device)
        optimizer = torch.optim.AdamW(network.parameters(), lr=3e-4, weight_decay=1e-4)
        baseline_validation = evaluate(store, "validation")
        best, history, bad_epochs, best_epoch = None, [], 0, 0

        def first_step():
            torch.cuda.synchronize()
            log.emit(
                "cuda_training_started",
                device_name=compute["device_name"],
                parameter_count=sum(p.numel() for p in network.parameters()),
                allocated_bytes=torch.cuda.memory_allocated(),
                reserved_bytes=torch.cuda.memory_reserved(),
            )

        for epoch in range(1, epochs + 1):
            loss, frames = fit_epoch(
                network,
                optimizer,
                store,
                rng,
                device=device,
                batch_size=batch_size,
                max_frames=max_frames,
                first_step=first_step if epoch == 1 else None,
            )
            validation = evaluate(store, "validation", network, device=device, batch_size=batch_size)
            error = validation["layout_balanced"]["encoded_selection_error"]
            if best is None or error < best[0] - 1e-7:
                best = (error, checkpoint(network, model_id), validation)
                best_epoch, bad_epochs = epoch, 0
            else:
                bad_epochs += 1
            history.append(
                {
                    "epoch": epoch,
                    "training_loss": loss,
                    "training_frames": frames,
                    "validation": validation["layout_balanced"],
                }
            )
            log.emit("epoch", **history[-1], best_epoch=best_epoch)
            if epoch >= 5 and bad_epochs >= patience:
                break
        network.load_state_dict(best[1]["state_dict"], strict=True)
        # Held-out metrics are touched only now, after validation has fixed all weights.
        log.emit("model_selected", best_epoch=best_epoch, test_evaluations_so_far=0)
        test = evaluate(store, "test", network, device=device, batch_size=batch_size)
        baseline_test = evaluate(store, "test")
        compute.update(
            peak_allocated_bytes=torch.cuda.max_memory_allocated(),
            peak_reserved_bytes=torch.cuda.max_memory_reserved(),
        )
        metrics = {"validation": best[2], "test": test}
        baseline = {
            "name": "Ambient temperature, zero soot and chemical HRR",
            "validation": baseline_validation,
            "test": baseline_test,
        }
        metadata = {
            "id": model_id,
            "kind": "incident_3d_unet",
            "feature_version": FEATURE_VERSION,
            "compiler_version": COMPILER_VERSION,
            "material_model_version": MODEL_VERSION,
            "architecture": architecture(),
            "sample_shape": list(store.shape),
            "dataset_id": store.snapshot["dataset_id"],
            "dataset_manifest_sha256": store.source_sha,
            "dataset_snapshot_sha256": store.snapshot_sha,
            "training_compute": compute,
            "source_sha256": sources,
            "execution": execution,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "training_host": "Windows",
            "training_seconds": time.perf_counter() - started,
            "parameter_count": sum(p.numel() for p in network.parameters()),
            "metrics": metrics,
            "ambient_baseline": baseline,
            "training": {
                "seed": SEED,
                "epochs_requested": epochs,
                "epochs_completed": len(history),
                "best_epoch": best_epoch,
                "batch_size": batch_size,
                "patience": patience,
                "max_training_frames_per_epoch": max_frames,
                "case_cache": 2,
                "loss": "asinh SmoothL1; observed gas T/soot weighted 1+4 active; globals weight .25",
                "active_thresholds": {"temperature_above_ambient_c": 5, "smoke_kg_m3": 1e-7},
                "selection": "layout/run macro field encoded MAE + .5 hot + .5 smoky + .25 global encoded MAE",
                "test_selection": "never; one evaluation after restoring selected epoch",
                "history": history,
            },
            "provisional": True,
            "automatic_ui_activation": False,
            "quality_gate": {
                "beats_ambient_validation_selection": best[0]
                < baseline_validation["layout_balanced"]["encoded_selection_error"],
                "beats_ambient_test_selection": test["layout_balanced"]["encoded_selection_error"]
                < baseline_test["layout_balanced"]["encoded_selection_error"],
            },
            "limitations": [
                "Exploratory emulator of FDS assumptions; not experimental NASA labels.",
                "Pilot model validates the GPU pipeline, not generalisation to real habitats.",
                "Only sampled gas temperature/soot and independent FDS domain quantities are predicted.",
                "Boundary airflow conditions are inputs, not a learned or resolved velocity field.",
                "Nonuniform FDS sample coordinates retained; convolutions operate on their ordered index grid.",
                "No electrical failure probability, battery electrochemistry or safety certification.",
            ],
        }
        publish(output, metadata, best[1], {"model": metrics, "ambient_baseline": baseline}, store.snapshot)
        log.emit(
            "training_completed",
            model_directory=str(output),
            best_epoch=best_epoch,
            quality_gate=metadata["quality_gate"],
            **compute,
        )
        return metadata
    except Exception as exc:
        log.emit("failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        log.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("E:/IGNIS-Valley-dev"))
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--model-id", choices=MODEL_IDS, default="spatial-pilot-v1")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--patience", type=int, default=5)
    parser.add_argument("--max-train-frames", type=int, default=20000)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args(argv)
    args.dataset = args.dataset or args.home / "datasets" / MODEL_DATASETS[args.model_id][0]
    return args


def main():
    args = parse_args()
    if os.name != "nt":
        raise RuntimeError("Spatial training must run on the Windows CUDA workstation")
    with ProcessLock(args.home / "runtime/compute.lock"):
        train(
            args.home,
            args.dataset,
            model_id=args.model_id,
            epochs=args.epochs,
            batch_size=args.batch_size,
            patience=args.patience,
            max_frames=args.max_train_frames,
            allow_incomplete=args.allow_incomplete,
        )


if __name__ == "__main__":
    main()
