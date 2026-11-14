"""Incident geometry and semantics contracts; real solver checks remain separate."""

import copy
import hashlib

import pytest
from ignis.physics.compiler import compile_case
from ignis.physics.verification import verification_cases, verification_scene


@pytest.fixture
def scene():
    value = verification_scene()
    value["objects"].append(
        {
            "id": "console",
            "role": "obstacle",
            "material_id": "aluminium",
            "combustible_material_id": "pmma",
            "thermal_thickness_m": 0.003,
            "center_m": [1, 0.4, 0.2],
            "size_m": [1.6, 0.4, 0.4],
        }
    )
    value["components"] = [
        {
            "id": "left",
            "object_id": "console",
            "position_m": [0.5, 0.3, 0.4],
            "face": 3,
            "provenance": "authored test annotation",
        },
        {"id": "right", "object_id": "console", "position_m": [1.5, 0.3, 0.4], "face": 3},
    ]
    return value


@pytest.fixture
def config():
    return {
        **verification_cases()["transport"][1],
        "incident_type": "overheating",
        "component_id": "left",
        "source_model": "coupled_combustion",
    }


def compile_deck(tmp_path, scene, config, name="case"):
    manifest = compile_case(scene, config, tmp_path / name)
    return manifest, (tmp_path / name / "ignis.fds").read_text()


def test_two_sites_on_same_object_emit_different_local_patches(tmp_path, scene, config):
    left, deck_left = compile_deck(tmp_path, scene, config, "left")
    right, deck_right = compile_deck(tmp_path, scene, {**config, "component_id": "right"}, "right")
    for manifest in (left, right):
        source = manifest["incident"]["source"]
        assert source["object_id"] == "console"  # Never the old nearest fuel sample.
        assert source["area_m2"] == pytest.approx(0.04)
        assert source["area_m2"] < 1.6 * 0.4
        assert source["face"] == 3
        assert source["position_m"] == manifest["source"]["position_m"]
        assert manifest["compiler_version"] == "ignis-incidents-1"
    assert left["source"]["bounds_m"] != right["source"]["bounds_m"]
    assert deck_left != deck_right
    assert [line for line in deck_left.splitlines() if "ID='INCIDENT_PATCH'" in line] != [
        line for line in deck_right.splitlines() if "ID='INCIDENT_PATCH'" in line
    ]
    assert left["source"]["requested_position_m"] == [0.5, 0.3, 0.4]


@pytest.mark.parametrize(
    "updates,match",
    [
        ({"component_id": "unknown"}, "Unknown incident component"),
        ({"component_id": None}, "explicit component_id"),
        ({"incident_type": None}, "incident_type"),
        ({"incident_type": "plasma"}, "incident_type"),
    ],
)
def test_invalid_incident_never_falls_back_to_legacy_source(tmp_path, scene, config, updates, match):
    with pytest.raises(ValueError, match=match):
        compile_case(scene, {**config, **updates}, tmp_path / "case")
    assert not (tmp_path / "case").exists()


@pytest.mark.parametrize(
    "updates,match",
    [
        ({"object_id": "missing"}, "reference an existing"),
        ({"face": 1}, "face must be 3"),
        ({"position_m": [0.5, 0.3, 0.45]}, "original upper face"),
        ({"position_m": [0.5, 0.7, 0.4]}, "original upper face"),
        ({"position_m": [3, 0.3, 0.4]}, "outside the physical domain"),
        ({"position_m": [float("nan"), 0.3, 0.4]}, "finite SI coordinates"),
        ({"position_m": [True, 0.3, 0.4]}, "finite SI coordinates"),
    ],
)
def test_invalid_annotation_is_rejected(tmp_path, scene, config, updates, match):
    scene["components"][0].update(updates)
    with pytest.raises(ValueError, match=match):
        compile_case(scene, config, tmp_path / "case")


def test_original_face_is_validated_before_projecting_onto_snapped_face(tmp_path, scene, config):
    scene["objects"][1]["size_m"][2] = 0.38
    for component in scene["components"]:
        component["position_m"][2] = 0.39
    manifest, _ = compile_deck(tmp_path, scene, config)
    assert manifest["source"]["requested_position_m"][2] == pytest.approx(0.39)
    assert manifest["source"]["position_m"][2] == pytest.approx(0.4)


def test_location_lost_by_mesh_snapping_is_rejected(tmp_path, scene, config):
    scene["objects"][1]["size_m"][0] = 1.68  # Original lower x=.16 snaps inward to .2.
    scene["components"][0]["position_m"][0] = 0.18
    with pytest.raises(ValueError, match="outside its object after mesh snapping"):
        compile_case(scene, config, tmp_path / "case")


def test_source_blocked_only_after_snapping_is_rejected(tmp_path, scene, config):
    scene["objects"].append(
        {
            "id": "cover",
            "role": "obstacle",
            "material_id": "steel",
            "center_m": [0.5, 0.3, 0.62],
            "size_m": [0.2, 0.2, 0.4],
        }
    )  # Original lower z=.42 has a gap; the FDS lower z=.4 blocks the patch.
    with pytest.raises(ValueError, match="patch is blocked after mesh snapping by cover"):
        compile_case(scene, config, tmp_path / "case")


def test_partial_cover_does_not_block_another_exposed_source_patch(tmp_path, scene, config):
    scene["objects"].append(
        {
            "id": "cover",
            "role": "obstacle",
            "material_id": "steel",
            "center_m": [1.5, 0.3, 0.6],
            "size_m": [0.2, 0.2, 0.4],
        }
    )
    manifest, _ = compile_deck(tmp_path, scene, config)
    assert manifest["source"]["component_id"] == "left"


def test_source_at_ceiling_has_no_exposed_face(tmp_path, scene, config):
    scene["objects"][1]["center_m"][2] = 1.8
    for component in scene["components"]:
        component["position_m"][2] = 2.0
    with pytest.raises(ValueError, match="domain ceiling"):
        compile_case(scene, config, tmp_path / "case")


def test_distinct_sites_must_be_resolved_by_distinct_cells(tmp_path, scene, config):
    scene["components"][1]["position_m"] = [0.51, 0.3, 0.4]
    with pytest.raises(ValueError, match="share one mesh cell; refine the mesh"):
        compile_case(scene, config, tmp_path / "case")


def test_duplicate_component_ids_are_rejected(tmp_path, scene, config):
    scene["components"][1]["id"] = "left"
    with pytest.raises(ValueError, match="Duplicate component id"):
        compile_case(scene, config, tmp_path / "case")


def test_per_object_material_and_thickness_survive_an_imposed_fire(tmp_path, scene, config):
    manifest, deck = compile_deck(tmp_path, scene, {**config, "incident_type": "flaming"})
    assert "&REAC ID='IGNIS_REACTION_pmma', FUEL='IGNIS_FUEL_pmma'" in deck
    assert "&REAC ID='IGNIS_REACTION_cellulose', FUEL='IGNIS_FUEL_cellulose'" in deck
    assert "MATL_ID='IGNIS_SOLID_pmma', THICKNESS=0.003" in deck
    assert "MATL_ID='IGNIS_SOLID_cellulose', THICKNESS=0.005" in deck
    assert "MATL_ID='IGNIS_CHAR_cellulose', NU_MATL=0.4" in deck
    assert "QUANTITY='MASS FLUX', SPEC_ID='IGNIS_FUEL_cellulose'" in deck
    assert "QUANTITY='MASS FLUX', SPEC_ID='IGNIS_FUEL_pmma'" in deck
    assert len(manifest["surface_devices"]) == 2
    assert set(manifest["materials"]) == {"cellulose", "pmma"}
    console = next(obj for obj in manifest["objects"] if obj["id"] == "console")
    assert console["material_id"] == "aluminium"
    assert console["combustible_material_id"] == "pmma"
    assert manifest["incident"]["emitted_fuel_material_id"] == "pmma"


def test_incident_does_not_override_unannotated_fuel_material_with_global_selection(tmp_path, scene, config):
    manifest, deck = compile_deck(tmp_path, scene, {**config, "material_id": "pmma"})
    sample = next(obj for obj in manifest["objects"] if obj["id"] == "sample")
    assert sample["combustible_material_id"] == "cellulose"
    assert "IGNIS_SOLID_cellulose" in deck


@pytest.mark.parametrize(
    "family,parameter",
    [
        ("overheating", "EXTERNAL_FLUX="),
        ("arc", "EXTERNAL_FLUX="),
        ("flaming", "HRRPUA="),
        ("smoldering", "NET_HEAT_FLUX="),
        ("battery", "NET_HEAT_FLUX="),
    ],
)
def test_five_families_have_explicit_distinct_source_semantics(tmp_path, scene, config, family, parameter):
    manifest, deck = compile_deck(tmp_path, scene, {**config, "incident_type": family})
    source_line = next(line for line in deck.splitlines() if line.startswith("&SURF ID='INCIDENT_SOURCE'"))
    assert parameter in source_line
    for other in {"EXTERNAL_FLUX=", "HRRPUA=", "NET_HEAT_FLUX="} - {parameter}:
        assert other not in source_line
    if family in {"smoldering", "battery"}:
        assert "MASS_FLUX(1)=" in source_line
        assert "RAMP_MF(1)='SOURCE_RAMP'" in source_line
        assert "MATL_ID=" not in source_line
        assert "HRRPUA=" not in deck
        assert "&SPEC ID='SOOT' /" in deck
    assert manifest["incident"]["fault_probability"] is None
    assert manifest["incident"]["scientific_status"] == "prescribed_equivalent_incident_not_calibrated"
    assert manifest["source"]["flux_kw_m2"] * manifest["source"]["area_m2"] * 1000 == pytest.approx(1000)


def test_explicit_family_preserves_source_model_configuration(tmp_path, scene, config):
    config["source_model"] = "prescribed_source"
    manifest, deck = compile_deck(tmp_path, scene, config)
    assert manifest["config"]["source_model"] == "prescribed_source"
    assert manifest["incident"]["source_model_config"] == "prescribed_source"
    assert "EXTERNAL_FLUX=" in deck
    assert "HRRPUA=" not in deck
    assert len(manifest["surface_devices"]) == 2


def test_thermal_pulse_energy_and_clipping_are_explicit(tmp_path, scene, config):
    arc, _ = compile_deck(
        tmp_path, scene, {**config, "incident_type": "arc", "ignition_duration_s": 1}, "arc"
    )
    assert arc["incident"]["nominal_power_duration_j"] == 1000
    assert arc["incident"]["imposed_pulse_energy_j"] == pytest.approx(995)
    clipped, _ = compile_deck(
        tmp_path, scene, {**config, "duration_s": 1, "ignition_duration_s": 3}, "clipped"
    )
    assert clipped["incident"]["imposed_pulse_energy_j"] == pytest.approx(1000)
    assert clipped["source"]["ramp"][-1] == (1, 1)


def test_battery_growth_plateau_energy_and_smoke_have_documented_units(tmp_path, scene, config):
    full, _ = compile_deck(
        tmp_path,
        scene,
        {**config, "incident_type": "battery", "ignition_duration_s": 10, "duration_s": 12},
        "full",
    )
    assert full["source"]["imposed_pulse_energy_j"] == pytest.approx(8745)
    assert full["incident"]["emission"]["peak_mass_flow_kg_s"] == pytest.approx(1e-6)
    assert full["incident"]["emission"]["imposed_mass_kg"] == pytest.approx(8745e-9)
    clipped, _ = compile_deck(
        tmp_path,
        scene,
        {**config, "incident_type": "battery", "ignition_duration_s": 10, "duration_s": 1},
        "clipped",
    )
    assert clipped["source"]["ramp"][-1] == (1, 0.4)
    assert clipped["source"]["imposed_pulse_energy_j"] == pytest.approx(200)


@pytest.mark.parametrize(
    "updates", [{"ignition_power_w": 0}, {"ignition_duration_s": 0}, {"ignition_delay_s": 6}]
)
def test_inactive_incidents_have_no_injected_energy(tmp_path, scene, config, updates):
    manifest, deck = compile_deck(tmp_path, scene, {**config, **updates})
    assert manifest["source"]["imposed_pulse_energy_j"] == 0
    assert manifest["source"]["flux_kw_m2"] == 0
    assert "EXTERNAL_FLUX=" not in deck
    assert "RAMP_EF=" not in deck


def test_source_surface_device_measures_pyrolysis_not_prescribed_fuel(tmp_path, scene, config):
    manifest, _ = compile_deck(tmp_path, scene, {**config, "incident_type": "flaming"})
    source = manifest["source"]
    sensor = next(s for s in manifest["surface_devices"] if s["object_id"] == "console")
    assert sensor["position_m"] != source["position_m"]
    assert "excludes prescribed burner/emitter" in sensor["measurement_basis"]
    thermal, _ = compile_deck(tmp_path, scene, config, "thermal")
    sensor = next(s for s in thermal["surface_devices"] if s["object_id"] == "console")
    assert sensor["position_m"] == thermal["source"]["position_m"]


def test_no_fake_pyrolysis_device_when_source_occupies_whole_top_cell(tmp_path, config):
    scene = verification_scene()
    scene["objects"][0].update(center_m=[0.9, 0.9, 0.2], size_m=[0.2, 0.2, 0.4])
    scene["components"] = [{"id": "left", "object_id": "sample", "face": 3, "position_m": [0.9, 0.9, 0.4]}]
    manifest, deck = compile_deck(tmp_path, scene, {**config, "incident_type": "flaming"})
    assert manifest["surface_devices"] == []
    assert "QUANTITY='MASS FLUX'" not in deck
    assert any("no exposed reactive" in message for message in manifest["warnings"])


def test_incident_can_heat_inert_component_without_a_fuel_fallback(tmp_path, scene, config):
    scene["objects"] = [scene["objects"][1]]
    del scene["objects"][0]["combustible_material_id"]
    manifest, deck = compile_deck(tmp_path, scene, config)
    assert manifest["source"]["object_id"] == "console"
    assert manifest["surface_devices"] == []
    source_line = next(line for line in deck.splitlines() if line.startswith("&SURF ID='INCIDENT_SOURCE'"))
    assert "MATL_ID='INERT_aluminium'" in source_line
    assert manifest["incident"]["source_patch_reactive"] is False


def test_configuration_and_scene_not_mutated(tmp_path, scene, config):
    before_scene, before_config = copy.deepcopy(scene), copy.deepcopy(config)
    first, _ = compile_deck(tmp_path, scene, config, "first")
    second, _ = compile_deck(tmp_path, scene, config, "second")
    assert scene == before_scene and config == before_config
    assert first == second


@pytest.mark.parametrize(
    "name,deck_hash,manifest_hash",
    [
        (
            "cold",
            "01b894497f40f39232945e48400d19580c9ec320bd6e51c741fa42158ddec302",
            "1cad4500233170c373144207d2d77ca9eceb66d529db678b30f5b0cbab0e50b5",
        ),
        (
            "transport",
            "163b759369416032eb3a9282b8b8fb81d081ab0ad3bf916e119508365e8a5e8f",
            "653e3d1f65708cd55db30c4f13b70017c5fa65895dfba1dfad84cfcb45acd9a3",
        ),
        (
            "coupled",
            "ad47cbf21db6d1bf95e098ecd069f99ea92f06266fe7ed2c7e909ce4ae9a340a",
            "6781a9fc33e247699edcd48e9036af24b79b6534528427cb048fc3fb13f9bc64",
        ),
    ],
)
def test_legacy_deck_bytes_and_manifest_text_are_unchanged(tmp_path, name, deck_hash, manifest_hash):
    # Captured before the incident branch was introduced, not recomputed from its helpers.
    scene, config = verification_cases()[name]
    manifest = compile_case(scene, config, tmp_path / name)
    assert manifest["compiler_version"] == "ignis-fds-2"
    assert hashlib.sha256((tmp_path / name / "ignis.fds").read_bytes()).hexdigest() == deck_hash
    # Legacy JSON uses platform line endings; compare its complete normalized text.
    manifest_text = (tmp_path / name / "manifest.json").read_text(encoding="utf-8")
    assert hashlib.sha256(manifest_text.encode("utf-8")).hexdigest() == manifest_hash
