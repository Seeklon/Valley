"""Targeted ISS data contracts; compiler checks only, no fabricated solver labels."""

from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

import pytest
from ignis.config import Settings
from ignis.provenance import canonical_sha

ROOT = Path(__file__).resolve().parents[1]


def script(filename):
    spec = importlib.util.spec_from_file_location(
        filename.removesuffix(".py"), ROOT / "tools/remote" / filename
    )
    module = importlib.util.module_from_spec(spec)
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT / "tools/remote"))
        spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def design_module():
    return script("iss_poc_design.py")


@pytest.fixture(scope="module")
def design(design_module):
    return design_module.build_design({})


def test_design_is_bounded_reproducible_and_geometries_are_disjoint(design_module, design):
    assert design["expected_runs"] == len(design["runs"]) == 108
    assert len(design["layouts"]) == 18
    assert canonical_sha(design_module.build_design({})) == canonical_sha(design)
    assert Counter(r["split"] for r in design["runs"]) == {"train": 72, "validation": 18, "test": 18}
    families, layouts = {}, {}
    for r in design["runs"]:
        layouts.setdefault(r["layout_id"], set()).add(r["split"])
        families.setdefault(r["structural_family"], set()).add(r["split"])
    assert all(len(splits) == 1 for splits in layouts.values())
    assert all(splits == {"train", "validation", "test"} for splits in families.values())
    assert len({r["fingerprint"] for r in design["runs"]}) == 108
    # Scales alone would disappear from normalized geometry. Each family must
    # retain six genuinely different equipment arrangements at model input.
    for family in design_module.FAMILIES:
        signatures = set()
        for layout in design["layouts"]:
            if layout["structural_family"] != family:
                continue
            scene = layout["scene"]
            signatures.add(
                canonical_sha(
                    [
                        {
                            key: [
                                round(value / scene["bounds_m"][axis], 8)
                                for axis, value in enumerate(obj[key])
                            ]
                            for key in ("center_m", "size_m")
                        }
                        for obj in scene["objects"]
                    ]
                )
            )
        assert len(signatures) == 6


def test_incidents_include_real_zero_input_controls_and_matched_gravities(design):
    counts = Counter(r["config"]["gravity_g"] for r in design["runs"])
    assert counts == {0.0001: 90, 1.0: 18}
    assert sum(r["config"]["ignition_power_w"] == 0 for r in design["runs"]) == 18
    assert {r["config"]["incident_type"] for r in design["runs"]} == {
        "flaming",
        "battery",
        "smoldering",
        "overheating",
        "arc",
    }
    by_id = {r["id"]: r for r in design["runs"]}
    for layout in design["layouts"]:
        microg = by_id[layout["layout_id"] + "-flame"]["config"]
        earth = by_id[layout["layout_id"] + "-flame-earth"]["config"]
        assert {k: v for k, v in microg.items() if k != "gravity_g"} == {
            k: v for k, v in earth.items() if k != "gravity_g"
        }
        assert microg["sample_shape"] == [12, 16, 8]
        assert microg["duration_s"] == 30
        assert len(layout["scene"]["components"]) == 3


def test_pilot_never_reads_or_generates_validation_and_test(design_module, design):
    selected = design_module.scheduled_runs(design, pilot=True)
    assert len(selected) == 6 and {r["split"] for r in selected} == {"train"}
    assert len({r["structural_family"] for r in selected}) == 3
    assert any(r["config"]["ignition_power_w"] == 0 for r in selected)
    full = design_module.scheduled_runs(design)
    assert len(full) == len({r["id"] for r in full}) == 108
    assert full[:6] == selected


def test_compiler_accepts_sources_and_physical_signatures_are_unique(design_module, design):
    report = design_module.preflight(design)
    assert report["unique_physical_layouts"] == 18
    assert report["unique_source_geometries"] == 54
    assert len({r["geometry_sha256"] for r in report["layouts"].values()}) == 18
    assert all(12000 <= r["cell_count"] <= 20000 for r in report["layouts"].values())


def test_expired_budget_preserves_plan_and_starts_no_solver(tmp_path, design):
    import time

    runner = script("generate_iss_poc.py")
    dataset = tmp_path / "iss"
    source = tmp_path / "old"
    source.mkdir()
    (source / "PAUSE").write_text("preserve")
    plan, index = runner.prepare_dataset(dataset, design)

    class Forbidden:
        def __init__(self, *args):
            pytest.fail("Expired budget must never invoke a solver")

    settings = Settings(ROOT, tmp_path / "runtime", None, 1, disk_reserve_gb=20)
    result = runner.execute_campaign(
        settings,
        dataset,
        plan,
        index,
        source=source,
        pilot=True,
        budget_s=1,
        started_at=time.monotonic() - 2,
        runner_factory=Forbidden,
    )
    assert result["state"] == "budget_exhausted"
    assert result["completed_runs"] == 0
    assert not (dataset / "index.json").exists()
    assert (source / "PAUSE").read_text() == "preserve"


def test_profile_uses_float64_threshold_and_excludes_t0_and_missing(tmp_path):
    import json

    import numpy as np

    runner = script("generate_iss_poc.py")
    (tmp_path / "config.json").write_text(json.dumps({"ambient_temperature_c": 20}))
    rounded_below = np.float32(1e-6)
    assert float(rounded_below) < 1e-6
    above = np.nextafter(rounded_below, np.float32(np.inf))
    np.savez(
        tmp_path / "fields.npz",
        time_s=np.array([0, 1]),
        temperature_c=np.array([[100, 100, 100], [20, 26, 100]], dtype=np.float32),
        smoke_kg_m3=np.array([[1, 1, 1], [rounded_below, above, 1]], dtype=np.float32),
        field_mask=np.array([[[1, 1], [1, 1], [1, 1]], [[1, 1], [1, 1], [0, 0]]], dtype=bool),
    )
    report = runner.label_profile(tmp_path)
    assert report["heat_positive"] == report["smoke_positive"] == 1
    assert report["heat_observed"] == report["smoke_observed"] == 2
