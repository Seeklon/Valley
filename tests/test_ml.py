import copy
import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="ML numerical checks run in the Windows compute environment")

from ignis.ml.features import POINTS, apply_initial_thermodynamics, decode_outputs  # noqa: E402
from ignis.ml.surrogate import Surrogate  # noqa: E402
from ignis.provenance import canonical_sha, physical_scene_sha  # noqa: E402
from ignis.schema import RunConfig  # noqa: E402


def test_evaluation_never_clips_measured_truth():
    encoded = np.zeros((1, POINTS * 6 + 5), dtype=np.float32)
    encoded[0, POINTS * 6] = np.arcsinh((3000 - 20) / 30)
    _, measured = decode_outputs(encoded, {"oxygen_percent": 21}, postprocess=False)
    _, predicted = decode_outputs(encoded, {"oxygen_percent": 21})
    assert measured[0, 0] == pytest.approx(3000, abs=0.002)
    assert predicted[0, 0] == 2500


def test_initial_thermodynamics_does_not_erase_velocity():
    encoded = np.ones((2, POINTS * 6 + 5), dtype=np.float32)
    apply_initial_thermodynamics(encoded, [0, 1])
    field = encoded[:, : POINTS * 6].reshape(-1, POINTS, 6)
    assert not field[0, :, :3].any()
    assert (field[0, :, 3:] == 1).all()
    assert (encoded[1] == 1).all()


def test_model_rejects_changed_physics_but_allows_new_preview():
    root = Path(__file__).resolve().parents[1]
    scene = json.loads((root / "scenes/catalog.json").read_text(encoding="utf-8"))["scenes"][0]
    meta = {
        "mesh_cell_m": 0.2,
        "physical_scene_hashes": {scene["id"]: physical_scene_sha(scene)},
        "domain": {
            "scene_ids": [scene["id"]],
            "source_model": "prescribed_source",
            "materials": ["cellulose"],
            "gravity_values": [0.0001, 1],
            "ranges": {},
        },
    }
    model = Surrogate(meta, None)
    cfg = RunConfig(scene_id=scene["id"], mode="prediction")
    preview = copy.deepcopy(scene)
    preview["preview_url"] = "/new-preview.png"
    model.validate(cfg, preview)
    preview["source_position_m"][0] += 0.1
    with pytest.raises(ValueError, match="géométrie"):
        model.validate(cfg, preview)
    with pytest.raises(ValueError, match="0,20"):
        model.validate(cfg.model_copy(update={"mesh_cell_m": 0.4}), scene)


def test_physical_scene_identity_preserves_values_and_ignores_integer_float_spelling():
    original = {"id": "box", "objects": [{"center_m": [1, 4, 0], "size_m": [2, 8, 3]}]}
    equivalent = {"id": "box", "objects": [{"center_m": [1.0, 4.0, -0.0], "size_m": [2.0, 8.0, 3.0]}]}
    assert physical_scene_sha(original) == physical_scene_sha(equivalent)
    # Provenance of the actual FDS input is intentionally still byte/type sensitive.
    assert canonical_sha(original) != canonical_sha(equivalent)
    equivalent["objects"][0]["center_m"][1] = 4.000000000001
    assert physical_scene_sha(original) != physical_scene_sha(equivalent)
    equivalent = copy.deepcopy(original)
    equivalent["objects"][0]["center_m"][0] = True
    assert physical_scene_sha(original) != physical_scene_sha(equivalent)
    with pytest.raises(ValueError):
        physical_scene_sha({"bounds_m": [float("nan"), 1, 1]})
