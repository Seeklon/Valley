"""CPU-only input/encoder audit before the first ventilation FDS launch."""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("E:/IGNIS-Valley-dev")
sys.path[:0] = [str(ROOT / "app/backend"), str(ROOT / "app/tools/remote")]
import numpy as np
import torch
from ignis.locking import ProcessLock
from ignis.ml.spatial_network import STATIC_CHANNELS, geometry_channels
from ignis.physics import compile_case
from iss_poc_vent_design import build_design, scene_for_run
from generate_spatial_corpus import file_sha

base = ROOT / "runtime/iss-poc-vent"
expected = json.loads((base / "source-hashes.json").read_bytes())
assert all(file_sha(ROOT / "app" / name) == digest for name, digest in expected.items())
assert (ROOT / "datasets/spatial-corpus-v1/PAUSE").is_file()
assert not (ROOT / "datasets/iss-poc-20261115-vent").exists()
with ProcessLock(ROOT / "runtime/compute.lock"):
    pass
torch.set_num_threads(2)
design = build_design({})
checks = []
for layout in design["layouts"][:2]:
    scene = layout["scene"]
    members = [r for r in design["runs"] if r["ventilation_group_id"] == scene["id"] + "-flaming"]
    features, manifests = {}, {}
    for row in members:
        with tempfile.TemporaryDirectory(prefix="ignis-vent-encoder-") as directory:
            manifest = compile_case(scene_for_run(scene, row), row["config"], Path(directory))
        manifests[row["ventilation_state"]] = manifest
        features[row["ventilation_state"]] = geometry_channels(manifest)
    u = STATIC_CHANNELS.index("boundary_u_scaled")
    assert np.count_nonzero(features["still"][u:u + 3]) == 0
    np.testing.assert_allclose(features["fast"][u:u + 3], features["slow"][u:u + 3] * 3, atol=1e-6)
    np.testing.assert_allclose(features["fast"][u:u + 3], -features["reverse"][u:u + 3], atol=1e-6)
    axis = "xy".index(members[0]["ventilation_axis"])
    assert np.count_nonzero(features["fast"][u + axis]) > 0
    assert features["fast"][u + axis].min() >= 0
    assert features["reverse"][u + axis].max() <= 0
    for other in set(range(3)) - {axis}:
        assert np.count_nonzero(features["fast"][u + other]) == 0
    opening = STATIC_CHANNELS.index("inlet_area_fraction")
    np.testing.assert_array_equal(features["fast"][opening], features["reverse"][opening + 1])
    np.testing.assert_array_equal(features["fast"][opening + 1], features["reverse"][opening])
    np.testing.assert_array_equal(features["fast"][:opening], features["reverse"][:opening])
    checks.append({"layout_id": layout["layout_id"], "axis": "xy"[axis],
                   "still_velocity_zero": True, "speed_factor_three": True,
                   "reversal_changes_sign": True, "vent_roles_swap": True,
                   "other_static_features_unchanged": True})
report = {"checked_at": datetime.now(timezone.utc).isoformat(), "device": "cpu", "no_training": True,
          "torch_version": torch.__version__, "compute_lock_available": True,
          "source_hashes": expected, "checks": checks}
(base / "prelaunch-encoder.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
