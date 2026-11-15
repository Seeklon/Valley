"""Prospective membership and immutable inference contracts; CPU only."""

# ruff: noqa: E402
import copy
import importlib.util
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")

from ignis.ml.spatial_network import FEATURE_VERSION, SpatialUNet, architecture
from ignis.provenance import canonical_sha


@pytest.fixture
def evaluator(monkeypatch):
    scripts = Path(__file__).parents[1] / "tools/remote"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("hotspot_evaluation_test", scripts / "evaluate_hotspots.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def planned_cases():
    runs = []
    for index in range(150):
        layout = f"procedural-{index:04d}"
        split = "train" if index % 10 < 6 else "validation" if index % 10 < 8 else "test"
        kind = ("overheating", "arc", "flaming", "smoldering", "battery")[(index // 10) % 5]
        for gravity in (0.0001, 1.0):
            identifier = f"{layout}-{kind}-{gravity}"
            runs.append(
                {
                    "id": identifier,
                    "layout_id": layout,
                    "fingerprint": canonical_sha({"id": identifier}),
                    "split": split,
                    "config": {"gravity_g": gravity, "incident_type": kind},
                    "status": "completed",
                    "geometry_signature": f"geometry-{index}",
                }
            )
    return {"dataset_id": "spatial-compact-v1", "expected_runs": 300, "runs": runs}


def test_membership_is_pure_plan_projection_and_matches_exact_new_cases(evaluator):
    plan = planned_cases()
    before = copy.deepcopy(plan)
    frozen = evaluator.freeze_membership(plan)
    assert plan == before
    assert frozen["plan_design_sha256"] == canonical_sha(plan)
    assert len(frozen["runs"]) == 100
    assert Counter(row["split"] for row in frozen["runs"]) == {"train": 60, "validation": 20, "test": 20}
    assert all(100 <= evaluator.layout_index(row["layout_id"]) < 150 for row in frozen["runs"])
    selected = evaluator.match_records(plan["runs"], frozen)
    assert set(selected) == set(range(200, 300))
    frozen["created_at"] = "2026-11-14T12:00:00Z"
    assert evaluator.match_records(list(reversed(plan["runs"])), frozen) == [
        299 - index for index in selected
    ]
    with_preflight = {**plan, "preflight": {"future": "ignored"}, "design_sha256": canonical_sha(plan)}
    assert evaluator.freeze_membership(with_preflight)["plan_design_sha256"] == canonical_sha(plan)


@pytest.mark.parametrize(
    "change", ["old_layout", "duplicate", "missing", "wrong_fingerprint", "split_changed"]
)
def test_prospective_set_rejects_membership_drift(evaluator, change):
    plan = planned_cases()
    frozen = evaluator.freeze_membership(plan)
    if change == "old_layout":
        frozen["runs"][0]["layout_id"] = "procedural-0099"
    elif change == "duplicate":
        frozen["runs"][1] = copy.deepcopy(frozen["runs"][0])
    elif change == "missing":
        frozen["runs"].pop()
    elif change == "wrong_fingerprint":
        frozen["runs"][0]["fingerprint"] = "a" * 64
    else:
        plan["runs"][200]["split"] = "test"
    with pytest.raises(ValueError):
        evaluator.match_records(plan["runs"], frozen)


def test_missing_or_incomplete_generated_cases_are_not_evaluated(evaluator):
    plan = planned_cases()
    frozen = evaluator.freeze_membership(plan)
    with pytest.raises(ValueError, match="complete 300"):
        evaluator.match_records(plan["runs"][:-1], frozen)
    plan["runs"][200]["status"] = "pending"
    with pytest.raises(ValueError, match="completion changed"):
        evaluator.match_records(plan["runs"], frozen)


def test_new_layout_names_cannot_hide_old_physical_geometry(evaluator):
    plan = planned_cases()
    frozen = evaluator.freeze_membership(plan)
    plan["runs"][200]["geometry_signature"] = plan["runs"][0]["geometry_signature"]
    store = SimpleNamespace(
        records=plan["runs"], snapshot={"dataset_id": "spatial-compact-v1"}, shape=(12, 16, 8)
    )
    with pytest.raises(ValueError, match="absent from development"):
        evaluator.load_prospective_cases(store, frozen)


def test_groups_use_native_labels_and_gravity_without_pairing_different_rooms(evaluator):
    records = planned_cases()["runs"][200:]
    cases = [{"record": row, "config": row["config"]} for row in records]
    counts = {"tp": 1, "fp": 2, "fn": 3, "tn": 4}
    metrics = {"per_run": [], "per_case_diagnostics": [], "peak_alignment": []}
    for number, row in enumerate(records):
        metrics["per_run"].append(
            {"run_id": row["id"], "layout_id": row["layout_id"], "temperature_mae_c": float(number)}
        )
        metrics["per_case_diagnostics"].append({"run_id": row["id"], "hot": counts, "smoky": counts})
        metrics["peak_alignment"].append(
            {
                "run_id": row["id"],
                "layout_id": row["layout_id"],
                "peak_is_hot": row["split"] != "test",
                "peak_location_amplitude_error_c": 2,
                "peak_displacement_at_true_time_m": 3,
                "peak_time_error_s": 4,
            }
        )
    result = evaluator.grouped_metrics(metrics, cases)
    assert {key: value["runs"] for key, value in result["native_split"].items()} == evaluator.NATIVE_COUNTS
    assert result["native_split"]["train"]["layouts"] == 30
    assert (
        result["native_split"]["test"]["hot_peak_alignment"]["layout_balanced"]["peak_time_error_s"] is None
    )
    micro = result["gravity_g"]["0.0001"]
    earth = result["gravity_g"]["1.0"]
    assert micro["runs"] == earth["runs"] == 50
    assert micro["layout_balanced"]["temperature_mae_c"] == 49
    assert earth["layout_balanced"]["temperature_mae_c"] == 50
    assert micro["diagnostics"]["hot"]["tp"] == 50
    crossed = result["native_split_by_gravity_g"]
    assert crossed["train"]["0.0001"]["runs"] == crossed["train"]["1.0"]["runs"] == 30
    assert crossed["validation"]["0.0001"]["runs"] == crossed["test"]["0.0001"]["runs"] == 10
    metrics["per_run"][1] = metrics["per_run"][0]
    with pytest.raises(ValueError, match="exact prospective membership"):
        evaluator.grouped_metrics(metrics, cases)


def checkpoint(path, **updates):
    payload = {
        "state_dict": SpatialUNet(base_channels=16).state_dict(),
        "feature_version": FEATURE_VERSION,
        "architecture": architecture(16),
        "scope": "unit test only; no scientific evidence",
        **updates,
    }
    torch.save(payload, path)
    return payload


def test_checkpoint_loading_is_frozen_exact_and_schema_checked(evaluator, tmp_path):
    path = tmp_path / "weights.pt"
    checkpoint(path)
    before = evaluator.file_sha(path)
    first, metadata = evaluator.load_checkpoint(path, device="cpu")
    second, replay = evaluator.load_checkpoint(path, device="cpu")
    assert evaluator.file_sha(path) == before == metadata["file_sha256"]
    assert metadata["state_sha256"] == replay["state_sha256"]
    assert not first.training and not second.training
    assert not any(p.requires_grad for p in first.parameters())
    checkpoint(path, feature_version="incompatible")
    with pytest.raises(ValueError, match="feature schema"):
        evaluator.load_checkpoint(path, device="cpu")
    payload = checkpoint(path)
    payload["architecture"]["fields"] = ["invented"]
    torch.save(payload, path)
    with pytest.raises(ValueError, match="architecture"):
        evaluator.load_checkpoint(path, device="cpu")


def test_nonfinite_checkpoint_is_rejected(evaluator, tmp_path):
    path = tmp_path / "weights.pt"
    payload = checkpoint(path)
    payload["state_dict"]["field_head.bias"][0] = float("nan")
    torch.save(payload, path)
    with pytest.raises(ValueError, match="nonfinite"):
        evaluator.load_checkpoint(path, device="cpu")


@pytest.mark.parametrize("schema", ["runs", "effective_partitions"])
def test_checkpoint_history_requires_disjoint_geometry_in_every_partition(evaluator, tmp_path, schema):
    path = tmp_path / "weights.pt"
    sidecar = path.with_name("dataset-snapshot.json")
    rows = [{"geometry_signature": letter * 64} for letter in "acd"]
    snapshot = (
        {"runs": rows}
        if schema == "runs"
        else {"effective_partitions": dict(zip(("train", "validation", "test"), [[row] for row in rows]))}
    )
    sidecar.write_text(json.dumps(snapshot))
    result = evaluator.verify_checkpoint_history(path, {"b" * 64})
    assert result["no_geometry_overlap"] and result["historical_geometry_count"] == 3
    assert result["file_sha256"] == evaluator.file_sha(sidecar)
    with pytest.raises(ValueError, match="overlaps"):
        evaluator.verify_checkpoint_history(path, {"d" * 64})
    sidecar.write_text(json.dumps({"runs": [{}]}))
    with pytest.raises(ValueError, match="geometry signatures"):
        evaluator.verify_checkpoint_history(path, {"b" * 64})
    sidecar.unlink()
    with pytest.raises(FileNotFoundError):
        evaluator.verify_checkpoint_history(path, {"b" * 64})


def test_checkpoint_history_includes_other_source_datasets_and_rejects_unknown_schema(evaluator, tmp_path):
    path = tmp_path / "weights.pt"
    sidecar = path.with_name("dataset-snapshot.json")
    snapshot = {
        "effective_partitions": {
            split: [{"geometry_signature": "a" * 64}] for split in ("train", "validation", "test")
        },
        "sources": {"historical-extra": {"runs": [{"geometry_signature": "b" * 64}]}},
    }
    sidecar.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match="overlaps"):
        evaluator.verify_checkpoint_history(path, {"b" * 64})
    sidecar.write_text(json.dumps({"unexpected": []}))
    with pytest.raises(ValueError, match="Incompatible"):
        evaluator.verify_checkpoint_history(path, {"b" * 64})


def test_plot_output_is_exclusive_and_model_names_cannot_escape(evaluator, tmp_path):
    path = tmp_path / "plots.json.gz"
    evaluator.write_plots(path, [])
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        evaluator.write_plots(path, ["replacement"])
    assert path.read_bytes() == original
    for entries in (["ambient=a.pt"], ["../outside=a.pt"], ["new=a.pt", "new=b.pt"], ["a=x.pt", "b=x.pt"]):
        with pytest.raises(ValueError):
            evaluator.parse_checkpoints(entries)


def test_expired_verification_stops_before_inference_without_complete_report(
    evaluator, monkeypatch, tmp_path
):
    plan = planned_cases()
    membership = evaluator.freeze_membership(plan)
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "manifest.json").write_text(
        json.dumps({"design_sha256": membership["plan_design_sha256"], "frozen_index_sha256": "a" * 64})
    )
    member_path = tmp_path / "membership.json"
    member_path.write_text(json.dumps(membership))
    pause = tmp_path / "datasets/spatial-corpus-v1/PAUSE"
    pause.parent.mkdir(parents=True)
    pause.touch()
    weights = tmp_path / "weights.pt"
    weights.write_bytes(b"never loaded")
    args = SimpleNamespace(
        home=tmp_path,
        dataset=dataset,
        membership=member_path,
        output=tmp_path / "result",
        seconds=1,
        checkpoint=[f"new={weights}"],
    )
    monkeypatch.setattr(evaluator, "require_cuda", lambda: {"device": "mock; not GPU execution"})
    monkeypatch.setattr(evaluator.torch, "set_num_threads", lambda value: None)
    monkeypatch.setattr(evaluator.time, "perf_counter", lambda: 0)

    class FakeStore:
        records = plan["runs"]

        def __init__(self, directory):
            pass

        def verify(self, progress):
            monkeypatch.setattr(evaluator.time, "perf_counter", lambda: 2)
            progress.emit("dataset_verification", checked=10)

    monkeypatch.setattr(evaluator, "CaseStore", FakeStore)
    with pytest.raises(TimeoutError, match="no complete comparison"):
        evaluator.run_evaluation(args)
    assert not (args.output / "report.json").exists()
    assert weights.read_bytes() == b"never loaded"


def test_cli_rejects_budget_above_three_minutes(evaluator):
    with pytest.raises(SystemExit):
        evaluator.parse_args(
            [
                "--dataset",
                "d",
                "--membership",
                "m",
                "--checkpoint",
                "new=w",
                "--output",
                "o",
                "--seconds",
                "181",
            ]
        )
