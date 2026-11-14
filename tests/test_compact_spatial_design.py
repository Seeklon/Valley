"""Compact-plan and model identity checks; no real solver or training."""

from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

import pytest
from ignis.provenance import canonical_sha

ROOT = Path(__file__).resolve().parents[1]


def load_script(filename, module_name):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "tools/remote" / filename)
    module = importlib.util.module_from_spec(spec)
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT / "tools/remote"))
        spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def compact():
    return load_script("compact_spatial_design.py", "compact_design_contract")


@pytest.fixture(scope="module")
def design(compact):
    return compact.build_design(compact.original.compiler_hashes(ROOT))


def test_default_has_200_geometries_400_cases_and_all_disjoint_families(design):
    assert design["dataset_id"] == "spatial-compact-v1"
    assert design["design_version"] == "procedural-spatial-compact-design-1"
    assert design["expected_runs"] == len(design["runs"]) == 400
    assert len(design["layouts"]) == len({row["scene_sha256"] for row in design["layouts"]}) == 200
    assert len({row["id"] for row in design["runs"]}) == 400
    assert len({row["fingerprint"] for row in design["runs"]}) == 400
    assert Counter(row["split"] for row in design["runs"]) == {"train": 240, "validation": 80, "test": 80}
    assert Counter(row["split"] for row in design["layouts"]) == {"train": 120, "validation": 40, "test": 40}
    assert {row["split"] for row in design["runs"][:6]} == {"train", "validation", "test"}
    family_splits, layout_splits = {}, {}
    for row in design["runs"]:
        family_splits.setdefault(row["structural_family"], set()).add(row["split"])
        layout_splits.setdefault(row["layout_id"], set()).add(row["split"])
    assert len(family_splits) == 10 and all(len(splits) == 1 for splits in family_splits.values())
    assert len(layout_splits) == 200 and all(len(splits) == 1 for splits in layout_splits.values())


def test_incidents_are_balanced_within_each_family_and_gravity_is_paired(compact, design):
    assert Counter(row["config"]["incident_type"] for row in design["runs"]) == dict.fromkeys(
        compact.original.INCIDENT_TYPES, 80
    )
    assert Counter(row["config"]["gravity_g"] for row in design["runs"]) == {0.0001: 200, 1.0: 200}
    combinations = Counter(
        (row["structural_family"], row["config"]["incident_type"]) for row in design["runs"]
    )
    assert len(combinations) == 50 and set(combinations.values()) == {8}
    assert Counter(row["condition_id"] for row in design["runs"]) == {0: 200, 1: 200}
    for index, (microg, earth) in enumerate(zip(design["runs"][::2], design["runs"][1::2])):
        assert microg["config"]["incident_type"] == compact.original.INCIDENT_TYPES[(index // 10) % 5]
        assert microg["condition_id"] == (index // 50) % 2
        assert microg["config"]["gravity_g"] == 0.0001 and earth["config"]["gravity_g"] == 1
        assert microg["layout_id"] == earth["layout_id"]
        assert {key: value for key, value in microg["config"].items() if key != "gravity_g"} == {
            key: value for key, value in earth["config"].items() if key != "gravity_g"
        }


def test_selected_sources_and_controls_span_the_original_envelope(design):
    configs = [row["config"] for row in design["runs"][::2]]
    scenes = {row["layout_id"]: row["scene"] for row in design["layouts"]}
    assert {config["component_id"] for config in configs} == {f"electrical-{n:02d}" for n in range(6)}
    for key, lower, upper in [
        ("ignition_power_w", 500, 3000),
        ("airflow_m_s", 0.05, 0.4),
        ("oxygen_percent", 18, 24),
    ]:
        values = [config[key] for config in configs]
        assert lower <= min(values) < lower + 0.1 * (upper - lower)
        assert upper - 0.1 * (upper - lower) < max(values) <= upper
    for row in design["runs"]:
        scene, config = scenes[row["layout_id"]], row["config"]
        assert config["component_id"] in {item["id"] for item in scene["components"]}
        assert config["sample_shape"] == [12, 16, 8]
        assert config["duration_s"] == 30
        assert config["ignition_duration_s"] == (1 if config["incident_type"] == "arc" else 10)


def test_compact_cases_match_original_exactly_for_verified_artifact_reuse(compact, design):
    original = compact.original.build_design(design["compiler_source_hashes"])
    original_runs = {row["id"]: row for row in original["runs"]}
    original_layouts = {row["layout_id"]: row for row in original["layouts"]}
    assert all(row == original_runs[row["id"]] for row in design["runs"])
    assert all(row == original_layouts[row["layout_id"]] for row in design["layouts"])
    assert design["source_dataset_id"] == original["dataset_id"]
    assert design["source_design_version"] == original["design_version"]


def test_design_is_reproducible_prefix_stable_and_does_not_build_full_plan(compact, design, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Compact planning must not allocate the original 20,000-case design")

    monkeypatch.setattr(compact.original, "build_design", forbidden)
    duplicate = compact.build_design(design["compiler_source_hashes"])
    assert canonical_sha(design) == canonical_sha(duplicate)
    smaller = compact.build_design(design["compiler_source_hashes"], layout_count=50)
    assert smaller["layouts"] == design["layouts"][:50]
    assert smaller["runs"] == design["runs"][:100]
    assert smaller["expected_runs"] == 100
    assert canonical_sha(smaller) != canonical_sha(design)


@pytest.mark.parametrize("count", [50, 100, 500, 1000])
def test_configurable_counts_preserve_balanced_incidents_per_family(compact, count):
    design = compact.build_design({}, layout_count=count)
    assert len(design["layouts"]) == count and design["expected_runs"] == count * 2
    combinations = Counter(
        (row["structural_family"], row["config"]["incident_type"]) for row in design["runs"]
    )
    assert len(combinations) == 50 and set(combinations.values()) == {count * 2 // 50}


@pytest.mark.parametrize("count", [True, False, 0, -50, 1, 49, 51, 1050, 50.0, "200", None])
def test_invalid_layout_count_is_rejected_before_geometry_construction(compact, count, monkeypatch):
    monkeypatch.setattr(compact.original, "procedural_scene", lambda *a: pytest.fail("validate count first"))
    with pytest.raises(ValueError, match="positive multiple of 50"):
        compact.build_design({}, layout_count=count)


def test_changed_original_design_requires_explicit_compatibility_review(compact, monkeypatch):
    monkeypatch.setattr(compact.original, "DESIGN_VERSION", "unreviewed-new-version")
    with pytest.raises(ValueError, match="Original design version changed"):
        compact.build_design({})


def test_compiler_preflight_accepts_all_200_compact_geometries_without_solver(compact, design):
    report = compact.original.preflight(design)
    assert report["unique_physical_layouts"] == 200
    assert len({row["geometry_sha256"] for row in report["layouts"].values()}) == 200
    assert report["unique_source_geometries"] == sum(
        len(row["scene"]["components"]) for row in design["layouts"]
    )
    assert all(12000 <= row["cell_count"] <= 60000 for row in report["layouts"].values())


@pytest.fixture(scope="module")
def training():
    pytest.importorskip("torch")
    return load_script("train_spatial.py", "compact_train_identity_contract")


def test_compact_training_identity_preserves_existing_channels_and_grid(training, tmp_path):
    from ignis.ml.spatial_network import CHANNELS, MODEL_IDS

    assert "spatial-compact-v1" in MODEL_IDS and len(CHANNELS) == 54
    assert training.MODEL_DATASETS["spatial-compact-v1"] == ("spatial-compact-v1", (12, 16, 8))
    args = training.parse_args(["--home", str(tmp_path), "--model-id", "spatial-compact-v1"])
    assert args.dataset == tmp_path / "datasets/spatial-compact-v1"
    training.validate_dataset_identity(args.model_id, "spatial-compact-v1", (12, 16, 8))


@pytest.mark.parametrize(
    "model_id,dataset_id,shape",
    [
        ("spatial-compact-v1", "spatial-corpus-v1", (12, 16, 8)),
        ("spatial-compact-v1", "incidents-v1", (12, 16, 8)),
        ("spatial-compact-v1", "spatial-compact-v1", (8, 10, 4)),
        ("spatial-corpus-v1", "spatial-compact-v1", (12, 16, 8)),
        ("spatial-pilot-v1", "spatial-compact-v1", (8, 10, 4)),
    ],
)
def test_compact_identity_cannot_be_confused_with_full_or_pilot(training, model_id, dataset_id, shape):
    with pytest.raises(ValueError, match="requires"):
        training.validate_dataset_identity(model_id, dataset_id, shape)
