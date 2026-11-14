"""Bounded campaign contracts with synthetic fixtures, never real FDS labels."""

from __future__ import annotations

import copy
import importlib.util
import time
from pathlib import Path

import pytest
from ignis.config import Settings
from ignis.engine import Cancelled, write_json
from ignis.locking import ProcessLock
from ignis.ml.spatial_dataset import file_sha, iter_spatial_cases, read_spatial_index
from ignis.physics import compile_case
from ignis.provenance import canonical_sha

ROOT = Path(__file__).resolve().parents[1]


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT / "tools/remote"))
        spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner():
    return load_module(ROOT / "tools/remote/generate_compact_spatial.py", "compact_runner_contract")


@pytest.fixture(scope="module")
def design(runner):
    return runner.compact.build_design(runner.original.compiler_hashes(ROOT), layout_count=50)


@pytest.fixture
def setup(runner, design, tmp_path):
    small = copy.deepcopy(design)
    small.update(layouts=small["layouts"][:2], runs=small["runs"][:4], expected_runs=4)
    dataset = tmp_path / "compact"
    plan, index = runner.prepare_dataset(dataset, small)
    settings = Settings(ROOT, tmp_path / "runtime", None, omp_threads=1, disk_reserve_gb=20)
    return dataset, plan, index, settings, tmp_path / "original"


@pytest.fixture
def fake_runner(setup):
    fixture = load_module(ROOT / "tests/test_spatial_corpus.py", "compact_spatial_fixture")
    settings = setup[3]

    class FakeRunner:
        calls = []

        def __init__(self, worker_settings):
            assert worker_settings.omp_threads == 1
            assert worker_settings.runtime != settings.runtime

        def run(self, scene, config, directory, *, cancel):
            assert not cancel()
            with pytest.raises(RuntimeError, match="autre instance"):
                with ProcessLock(settings.runtime / "compute.lock"):
                    pytest.fail("Global pool lock was not held")
            self.calls.append(directory.name)
            manifest = compile_case(scene, config, directory)
            result = fixture.fixture_result(manifest)
            write_json(directory / "result.json", result)
            (directory / "engine.log").write_text("Synthetic unit-test output, never FDS data")
            return result

    return FakeRunner


def run(runner, setup, factory, **kwargs):
    dataset, plan, index, settings, source = setup
    return runner.execute_campaign(
        settings, dataset, plan, index, source=source, runner_factory=factory, **kwargs
    )


def test_schedule_has_early_incident_and_structure_diversity(runner, design):
    ordered = runner.balanced_order(design)
    assert {r["id"] for r in ordered} == {r["id"] for r in design["runs"]}
    assert len(ordered) == 100
    assert len({r["config"]["incident_type"] for r in ordered[:10]}) == 5
    assert len({r["structural_family"] for r in ordered[:10]}) == 5
    assert {r["split"] for r in ordered[:10]} == {"train", "validation", "test"}
    for microg, earth in zip(ordered[::2], ordered[1::2]):
        assert microg["layout_id"] == earth["layout_id"]
        assert microg["config"]["gravity_g"] == 0.0001 and earth["config"]["gravity_g"] == 1


def test_completed_arrays_frozen_index_and_idempotent_resume(runner, setup, fake_runner):
    result = run(runner, setup, fake_runner)
    dataset, plan, _, _, _ = setup
    assert result["state"] == "completed" and result["ready_for_training"]
    assert result["newly_generated_runs"] == result["completed_runs"] == 4
    assert result["reused_runs"] == 0 and result["dataset_id"] == "spatial-compact-v1"
    assert len(list(iter_spatial_cases(dataset))) == 4
    assert read_spatial_index(dataset)["frozen_index_sha256"] == file_sha(dataset / "index.json")
    before = {r["id"]: r["file_hashes"] for r in read_spatial_index(dataset)["runs"]}
    design = {k: v for k, v in plan.items() if k not in {"design_sha256", "preflight"}}
    _, index = runner.prepare_dataset(dataset, design)
    resumed = (dataset, plan, index, setup[3], setup[4])
    assert run(runner, resumed, fake_runner)["newly_generated_runs"] == 0
    assert len(fake_runner.calls) == 4
    assert before == {r["id"]: r["file_hashes"] for r in read_spatial_index(dataset)["runs"]}


def test_changed_plan_and_untracked_artifacts_never_overwritten(runner, setup):
    dataset, plan, _, _, _ = setup
    before = (dataset / "plan.json").read_bytes()
    altered = {k: v for k, v in plan.items() if k not in {"design_sha256", "preflight"}}
    altered["expected_runs"] += 2
    with pytest.raises(ValueError, match="Existing compact plan differs"):
        runner.prepare_dataset(dataset, altered)
    assert (dataset / "plan.json").read_bytes() == before
    untracked = dataset.parent / "untracked"
    untracked.mkdir()
    (untracked / "valuable.txt").write_text("keep")
    with pytest.raises(FileExistsError, match="nothing will be overwritten"):
        runner.prepare_dataset(untracked, altered)
    assert (untracked / "valuable.txt").read_text() == "keep"


def test_expired_budget_starts_no_solver_or_partial_training(runner, setup, fake_runner):
    result = run(runner, setup, fake_runner, budget_s=1, started_at=time.monotonic() - 2)
    assert result["state"] == "budget_exhausted" and not result["ready_for_training"]
    assert result["newly_generated_runs"] == 0 and fake_runner.calls == []
    assert not (setup[0] / "index.json").exists()
    with pytest.raises(ValueError, match="incomplete"):
        list(iter_spatial_cases(setup[0]))


def test_deadline_cancellation_preserves_attempt_and_can_resume(runner, setup, fake_runner):
    class SlowRunner:
        def __init__(self, settings):
            pass

        def run(self, scene, config, directory, *, cancel):
            (directory / "partial.out").write_text("partial attempt remains inspectable")
            while not cancel():
                time.sleep(0.005)
            raise Cancelled()

    result = run(runner, setup, SlowRunner, budget_s=0.15, workers=1)
    assert result["state"] == "budget_exhausted" and not result["ready_for_training"]
    dataset, plan, _, settings, source = setup
    checkpoint = read_spatial_index(dataset)["runs"][0]
    assert checkpoint["status"] == "cancelled"
    assert (dataset / checkpoint["relative_path"] / "partial.out").exists()
    resumed = (dataset, plan, read_spatial_index(dataset), settings, source)
    assert run(runner, resumed, fake_runner)["state"] == "completed"
    assert list((dataset / "attempts").glob("*/001/partial.out"))


def test_solver_failure_excluded_from_complete_dataset(runner, setup):
    class BrokenRunner:
        def __init__(self, settings):
            pass

        def run(self, scene, config, directory, **kwargs):
            raise RuntimeError("deliberate fixture failure")

    result = run(runner, setup, BrokenRunner)
    assert result["state"] == "incomplete" and result["failed_runs"] == 4
    assert not result["ready_for_training"] and not (setup[0] / "index.json").exists()


def make_source(runner, setup, fake_runner):
    run(runner, setup, fake_runner)
    dataset, plan, _, settings, _ = setup
    index = read_spatial_index(dataset)
    original_design = {k: v for k, v in plan.items() if k not in {"design_sha256", "preflight"}}
    original_design.update(
        dataset_id=runner.original.DATASET_ID, design_version=runner.original.DESIGN_VERSION
    )
    original_plan = {
        **original_design,
        "design_sha256": canonical_sha(original_design),
        "preflight": plan["preflight"],
    }
    write_json(dataset / "plan.json", original_plan)
    index.update(
        dataset_id=runner.original.DATASET_ID,
        plan_sha256=file_sha(dataset / "plan.json"),
        design_sha256=original_plan["design_sha256"],
    )
    index.pop("frozen_index_sha256")
    write_json(dataset / "manifest.json", index)
    (dataset / "PAUSE").write_text("source stays paused")
    destination = dataset.parent / "new-compact"
    compact_design = {k: v for k, v in plan.items() if k not in {"design_sha256", "preflight"}}
    new_plan, new_index = runner.prepare_dataset(destination, compact_design)
    return destination, new_plan, new_index, settings, dataset


def test_verified_reuse_without_solver_or_source_mutation(runner, setup, fake_runner):
    target = make_source(runner, setup, fake_runner)
    source = target[-1]
    before = {str(p.relative_to(source)): file_sha(p) for p in source.rglob("*") if p.is_file()}
    result = run(runner, target, fake_runner)
    assert result["state"] == "completed" and result["reused_runs"] == 4
    assert result["newly_generated_runs"] == 0 and len(fake_runner.calls) == 4
    assert before == {str(p.relative_to(source)): file_sha(p) for p in source.rglob("*") if p.is_file()}
    assert len(list(iter_spatial_cases(target[0]))) == 4


def test_reuse_rejects_corrupt_or_unpaused_source(runner, setup, fake_runner):
    target = make_source(runner, setup, fake_runner)
    source = target[-1]
    pause = source / "PAUSE"
    pause.unlink()
    with pytest.raises(ValueError, match="must remain paused"):
        runner.reusable_records(source, target[1])
    pause.write_text("paused")
    field = next(source.glob("runs/*/fields.npz"))
    field.write_bytes(b"corrupt fixture")
    with pytest.raises(ValueError, match="checksum mismatch"):
        runner.reusable_records(source, target[1])
    assert not (target[0] / "runs").exists()


@pytest.mark.parametrize("budget", [0, -1, float("nan"), float("inf"), True])
def test_invalid_budget_starts_no_solver(runner, setup, fake_runner, budget):
    with pytest.raises(ValueError, match="positive and finite"):
        run(runner, setup, fake_runner, budget_s=budget)
    assert fake_runner.calls == []


def test_existing_compute_lock_blocks_dispatch(runner, setup, fake_runner):
    with ProcessLock(setup[3].runtime / "compute.lock"):
        with pytest.raises(RuntimeError, match="autre instance"):
            run(runner, setup, fake_runner)
    assert fake_runner.calls == []


def test_larger_plan_reuses_compact_prefix_once_and_preserves_both_sources(
    runner, design, setup, fake_runner
):
    compact_setup = make_source(runner, setup, fake_runner)
    assert run(runner, compact_setup, fake_runner)["reused_runs"] == 4
    compact_source = compact_setup[0]
    original_source = compact_setup[-1]
    before = {
        str(p): file_sha(p)
        for source in (compact_source, original_source)
        for p in source.rglob("*")
        if p.is_file()
    }
    larger_design = copy.deepcopy(design)
    larger_design.update(
        layouts=larger_design["layouts"][:3], runs=larger_design["runs"][:6], expected_runs=6
    )
    destination = compact_source.parent / "larger-compact"
    plan, index = runner.prepare_dataset(destination, larger_design)
    larger_setup = (destination, plan, index, setup[3], original_source)
    result = run(runner, larger_setup, fake_runner, reuse_compact=compact_source)
    assert result["state"] == "completed" and result["completed_runs"] == 6
    assert result["newly_generated_runs"] == 2 and result["reused_this_session"] == 4
    assert result["reused_by_source"] == {"spatial-corpus-v1": 0, "spatial-compact-v1": 4}
    assert len(fake_runner.calls) == 6  # Four original cases and two new cases, no duplicate solve.
    assert before == {str(p): file_sha(p) for p in map(Path, before)}
    assert len(list(iter_spatial_cases(destination))) == 6
    reused = [r for r in read_spatial_index(destination)["runs"] if "reused_from" in r]
    assert len(reused) == 4
    for record in reused:
        origin = record["reused_from"]
        assert origin["dataset_id"] == "spatial-compact-v1"
        assert Path(origin["dataset_path"]) == compact_source.resolve()
        assert origin["source_plan_sha256"] == file_sha(compact_source / "plan.json")
        assert origin["upstream"]["dataset_id"] == "spatial-corpus-v1"
        source_npz = compact_source / record["relative_path"] / "fields.npz"
        copied_npz = destination / record["relative_path"] / "fields.npz"
        assert file_sha(source_npz) == file_sha(copied_npz)
        assert not source_npz.samefile(copied_npz)


def test_compact_reuse_requires_completed_frozen_index(runner, setup, fake_runner):
    dataset, plan, _, _, _ = setup
    with pytest.raises(ValueError, match="complete.*frozen index"):
        runner.reusable_records(dataset, plan, compact_source=True)
    run(runner, setup, fake_runner)
    assert len(runner.reusable_records(dataset, plan, compact_source=True)) == 4
    index = read_spatial_index(dataset)
    index.pop("frozen_index_sha256")
    write_json(dataset / "manifest.json", index)
    with pytest.raises(ValueError, match="complete.*frozen index"):
        runner.reusable_records(dataset, plan, compact_source=True)


def test_compact_reuse_rejects_changed_inputs_compiler_and_corrupt_npz(runner, setup, fake_runner):
    run(runner, setup, fake_runner)
    dataset, plan, _, _, _ = setup
    changed = copy.deepcopy(plan)
    changed["runs"][0]["config"]["airflow_m_s"] += 0.01
    with pytest.raises(ValueError, match="different inputs"):
        runner.reusable_records(dataset, changed, compact_source=True)
    changed = copy.deepcopy(plan)
    changed["compiler_source_hashes"]["fds_executable_sha256"] = "changed executable"
    with pytest.raises(ValueError, match="provenance differs"):
        runner.reusable_records(dataset, changed, compact_source=True)
    field = next(dataset.glob("runs/*/fields.npz"))
    field.write_bytes(b"corrupt source fixture")
    with pytest.raises(ValueError, match="checksum mismatch"):
        runner.reusable_records(dataset, plan, compact_source=True)


def test_compact_source_output_overlap_is_rejected_before_writes(runner, setup, fake_runner):
    before = {str(p): file_sha(p) for p in setup[0].rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="independent of the compact reuse source"):
        run(runner, setup, fake_runner, reuse_compact=setup[0])
    assert fake_runner.calls == []
    assert before == {str(p): file_sha(p) for p in setup[0].rglob("*") if p.is_file()}
