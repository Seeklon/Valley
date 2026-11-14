"""Protect source provenance and the distinction between observations and ignition labels."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("preignition_sources", ROOT / "tools/nasa/preignition_sources.py")
sources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sources)


@pytest.fixture(scope="module")
def catalog():
    return sources.validate()


@pytest.fixture
def small_archive(tmp_path, catalog):
    """A bounded copy of real annotations, with a short known source for failure injection."""
    identifier = "NTRS-19660008892"
    folder = tmp_path / "raw" / identifier
    folder.mkdir(parents=True)
    text = "Test methods\n\fVery small yellow flame appeared - extinguished itself\n\f"
    contents = {
        "source.txt": text.encode(),
        "metadata.json": json.dumps({"experimentalTable": [{"name": "wire log"}]}).encode(),
    }
    for name, content in contents.items():
        (folder / name).write_bytes(content)
    provenance = {
        "source_id": identifier,
        "distribution": "PUBLIC",
        "files": [
            {"name": name, "bytes": len(content), "sha256": sources.sha256(content)}
            for name, content in contents.items()
        ],
    }
    (folder / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    curated = json.loads((sources.EVIDENCE / "curated.json").read_text(encoding="utf-8"))
    curated["sources"] = {identifier: curated["sources"][identifier]}
    conclusion = copy.deepcopy(next(c for c in catalog["conclusions"] if c["id"] == "NASA-PRE-007"))
    conclusion["anchors"] = [{"pdf_page": 2, "quote": "Very small yellow flame appeared"}]
    curated["conclusions"] = [conclusion]
    for record in curated["experimental_records"]:
        record["anchors"] = [{"pdf_page": 2}]
    write_annotations(tmp_path, curated)
    return tmp_path, curated


def write_annotations(base, curated):
    (base / "curated.json").write_text(json.dumps(curated), encoding="utf-8")


def test_archived_catalogue_reproduces_exactly_and_all_sources_are_public(catalog):
    serialized = json.dumps(catalog, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    assert (sources.EVIDENCE / "catalog.json").read_text(encoding="utf-8") == serialized
    assert (len(catalog["sources"]), len(catalog["conclusions"]), len(catalog["experimental_records"])) == (13, 22, 3)
    assert all(s["distribution"] == "PUBLIC" and s["used_for_training"] is False for s in catalog["sources"])


def test_changed_bytes_are_detected_even_when_file_size_stays_equal(small_archive):
    base, _ = small_archive
    text_path = base / "raw/NTRS-19660008892/source.txt"
    text_path.write_bytes(b"X" + text_path.read_bytes()[1:])
    with pytest.raises(ValueError, match="Archived source changed"):
        sources.validate(base)


def test_archiving_refuses_to_replace_existing_evidence(tmp_path):
    path = tmp_path / "source.pdf"
    original = b"%PDF-original-public-source"
    sources.preserve(path, original)
    sources.preserve(path, original)
    with pytest.raises(ValueError, match="Refusing to replace"):
        sources.preserve(path, b"%PDF-different-source")
    assert path.read_bytes() == original


def test_source_artifact_cannot_reference_a_parent_directory(small_archive):
    base, _ = small_archive
    path = base / "raw/NTRS-19660008892/provenance.json"
    provenance = json.loads(path.read_text())
    provenance["files"][0]["name"] = "../../curated.json"
    path.write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes its source directory"):
        sources.validate(base)


@pytest.mark.parametrize("anchor, message", [
    ({"pdf_page": 0}, "Invalid physical PDF page"),
    ({"pdf_page": 3}, "Invalid physical PDF page"),
    ({"pdf_page": 2, "quote": "sustained ignition"}, "Quote is absent"),
    ({"text_lines": [1, 100]}, "Invalid source text line range"),
    ({"text_lines": [1, 1], "quote": "yellow flame"}, "Quote is absent"),
    ({"json_pointer": "/experimentalTable/4"}, "JSON pointer does not resolve"),
    ({"json_pointer": "/experimentalTable/-1"}, "JSON pointer does not resolve"),
    ({"section": "somewhere"}, "Unsupported source anchor"),
])
def test_unresolvable_anchors_are_rejected(small_archive, anchor, message):
    base, curated = small_archive
    curated["conclusions"][0]["anchors"] = [anchor]
    write_annotations(base, curated)
    with pytest.raises(ValueError, match=message):
        sources.validate(base)


@pytest.mark.parametrize("anchor", [
    {"pdf_page": 2, "quote": "VERY small  yellow\nflame"},
    {"text_lines": [1, 1], "quote": "Test methods"},
    {"json_pointer": "/experimentalTable/0/name"},
])
def test_pdf_text_and_metadata_anchors_resolve(small_archive, anchor):
    base, curated = small_archive
    curated["conclusions"][0]["anchors"] = [anchor]
    write_annotations(base, curated)
    assert sources.validate(base)["conclusions"][0]["anchors"] == [anchor]


def test_sparse_logs_keep_unknowns_switch_states_and_temperature_inequalities(catalog):
    records = {r["original_test_id"]: r for r in catalog["experimental_records"]}
    assert sum(len(r["samples"]) for r in records.values()) == 49
    for record in records.values():
        assert all(s["time_s"] == s["source_time_min"] * 60 for s in record["samples"])
        assert record["post_poweroff_observation_s"] is None
        assert record["conditions"]["oxygen_volume_fraction"] is None
        assert not any(record[key] for key in (
            "used_for_training", "eligible_for_ignition_model_validation", "eligible_for_thermal_model_validation"
        ))
    samples = {s["time_s"]: s for s in records["6-IIB-3"]["samples"]}
    assert samples[120]["temperature_c"] == 226
    assert samples[120]["current_a"] is None
    assert samples[120]["current_status"] == "not_recorded"
    assert (samples[1320]["temperature_c"], samples[1320]["temperature_qualifier"]) == (800, "gt")
    for identifier in ("3-IIB-1", "9-IIB-2"):
        last = records[identifier]["samples"][-1]
        assert last["current_status"] == "power_off"
        assert last["current_a"] is None
    assert records["6-IIB-3"]["samples"][-1]["current_a"] == 50.1


def test_transient_flame_and_censored_observations_are_distinct(catalog):
    observed, no_flame, cut_off = catalog["experimental_records"]
    assert observed["event"]["kind"] == "transient_self_extinguishing_flame"
    assert observed["event"]["time_s"] == 1260
    assert observed["event"]["time_precision_s"] is None
    assert observed["event"]["sustained_ignition"] is False
    assert [no_flame["observation_end_s"], cut_off["observation_end_s"]] == [1350, 1155]
    for record in (no_flame, cut_off):
        assert record["event"]["observed"] is False
        assert record["event"]["time_s"] is None
        assert record["event"]["censoring"].startswith("right_censored")


@pytest.mark.parametrize("flag", [
    "used_for_training", "eligible_for_ignition_model_validation", "eligible_for_thermal_model_validation",
])
def test_historical_examples_cannot_be_promoted_to_model_evidence(small_archive, flag):
    base, curated = small_archive
    curated["experimental_records"][0][flag] = True
    write_annotations(base, curated)
    with pytest.raises(ValueError, match="does not establish training or model-validation eligibility"):
        sources.validate(base)


@pytest.mark.parametrize("problem, message", [
    ("invented_event", "No-event records cannot invent an ignition time"),
    ("unit_error", "Source minutes and normalized seconds disagree"),
    ("power_off_zero", "Blank and power-off current cells must remain null"),
    ("forward_fill", "Blank and power-off current cells must remain null"),
    ("lost_inequality", "Temperature value or inequality is invalid"),
    ("negative_time", "Sample times must be finite, nonnegative and monotonic"),
    ("nonfinite_end", "Observation end must be finite and nonnegative"),
    ("short_window", "Samples extend beyond the observation window"),
    ("late_event", "Event falls outside the observation window"),
])
def test_semantic_data_corruption_is_rejected(small_archive, problem, message):
    base, curated = small_archive
    flame, no_flame, _ = curated["experimental_records"]
    if problem == "invented_event":
        no_flame["event"]["time_s"] = no_flame["observation_end_s"]
    elif problem == "unit_error":
        flame["samples"][1]["source_time_min"] = 150
    elif problem == "power_off_zero":
        flame["samples"][-1]["current_a"] = 0
    elif problem == "forward_fill":
        next(s for s in no_flame["samples"] if s["current_status"] == "not_recorded")["current_a"] = 20
    elif problem == "lost_inequality":
        next(s for s in no_flame["samples"] if s["temperature_qualifier"] == "gt")["temperature_qualifier"] = None
    elif problem == "negative_time":
        flame["samples"][0]["time_s"] = -0.5
    elif problem == "nonfinite_end":
        flame["observation_end_s"] = float("nan")
    elif problem == "short_window":
        flame["observation_end_s"] = 1200
    elif problem == "late_event":
        flame["event"]["time_s"] = 1400
    write_annotations(base, curated)
    with pytest.raises(ValueError, match=message):
        sources.validate(base)


def test_same_pairs_preserve_metric_specific_aging_and_unknown_uncertainty(catalog):
    same = next(c for c in catalog["conclusions"] if c["id"] == "NASA-PRE-015")
    quantities = same["quantities"]
    assert len(quantities) == 40
    by_key = {(q["material"], q["name"], q["aging_time_s"]): q["value"] for q in quantities}
    assert len(by_key) == 40
    assert {q["material"] for q in quantities} == {"Kapton", "Lampwick", "Silicone", "Teflon", "Pyrell"}
    assert {q["aging_time_s"] for q in quantities} == {0, 720}
    assert all(q["uncertainty"] is None for q in quantities)
    assert by_key["Kapton", "geometric_mean_diameter", 0] == 0.042
    assert by_key["Kapton", "geometric_mean_diameter", 720] == 0.089
    assert by_key["Teflon", "geometric_mean_diameter", 720] < by_key["Teflon", "geometric_mean_diameter", 0]
    assert by_key["Teflon", "diameter_of_average_mass", 720] > by_key["Teflon", "diameter_of_average_mass", 0]
    assert "label de délai d’allumage" in same["compatibility"]["not_valid_for"]


def test_fusing_times_and_unsuccessful_wire_break_current_are_not_ignition_thresholds(catalog):
    by_id = {c["id"]: c for c in catalog["conclusions"]}
    fusing = by_id["NASA-PRE-019"]
    assert "conductor_fusing" in fusing["mechanisms"]
    assert fusing["conditions"]["current_a"] == 60
    assert [(q["value"], q["unit"], q["sample_count"]) for q in fusing["quantities"]] == [
        (24.8, "s", 6), (14.4, "s", 6),
    ]
    gore_tex = next(q for q in by_id["NASA-PRE-010"]["quantities"] if "Gore-Tex" in q["name"])
    assert (gore_tex["value"], gore_tex["unit"]) == (9.23, "A")
    assert gore_tex["outcome"] == "no_ignition_in_test_conditions_not_a_threshold"
    assert by_id["NASA-PRE-014"]["quantities"] == []


def test_secondary_publications_do_not_become_independent_experiments(catalog):
    by_id = {c["id"]: c for c in catalog["conclusions"]}
    for first, second in [
        ("NASA-PRE-005", "NASA-PRE-007"), ("NASA-PRE-010", "NASA-PRE-013"),
        ("NASA-PRE-018", "NASA-PRE-019"), ("NASA-PRE-002", "NASA-PRE-015"),
        ("NASA-PRE-020", "NASA-PRE-021"),
    ]:
        assert by_id[first]["evidence_quality"]["independence_group"] == (
            by_id[second]["evidence_quality"]["independence_group"]
        )
    assert by_id["NASA-PRE-018"]["evidence_quality"]["tier"] == "summary"
    assert by_id["NASA-PRE-018"]["quantities"] == []
    assert "NASA-CONFLICT-KERLIX" in by_id["NASA-PRE-013"]["evidence_conflict_ids"]


def test_bounded_excerpt_retains_original_page_mapping_and_fulltext_limitations(catalog):
    by_id = {s["source_id"]: s for s in catalog["sources"]}
    morphology = by_id["NTRS-20160000940"]
    excerpt = next(a for a in morphology["artifacts"] if a["name"] == "selected-pages.pdf")
    assert excerpt["original_pdf_pages"] == [1, 5, 6, 16, 21, 30]
    assert excerpt["derived_from_sha256"] == morphology["remote_original_pdf"]["sha256"]
    assert morphology["remote_original_pdf"]["locally_retained"] is False
    assert not (sources.EVIDENCE / "raw/NTRS-20160000940/source.pdf").exists()
    bass = by_id["NTRS-20210011385"]
    assert "source.pdf" not in {a["name"] for a in bass["artifacts"]}
    conclusion = next(c for c in catalog["conclusions"] if c["id"] == "NASA-PRE-020")
    assert conclusion["anchors"][0]["text_lines"] == [3656, 3660]
    assert "pdf_page" not in conclusion["anchors"][0]
