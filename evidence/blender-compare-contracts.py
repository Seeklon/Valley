"""Compare canonical and Blender-roundtrip mesh contracts on Windows only."""

import argparse
import json
import sys
from pathlib import Path

if sys.platform != "win32":
    raise RuntimeError("Compile comparison must run on the Windows workstation")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from ignis.physics import compile_case  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--attempt", default="final")
args = parser.parse_args()
directory = root / "evidence" / "blender-roundtrip" / args.attempt
scene = next(s for s in json.loads((root / "scenes/catalog.json").read_text())["scenes"] if s["id"] == "soyuz")
reference = compile_case(scene, {}, directory / "reference-compiled-contract")
imported = json.loads((directory / "compiled-contract/manifest.json").read_text())
report = {"schema_version": 1, "tolerance_m": 1e-5, "differences": [], "fds_executed": False}
for collection in ("objects", "vents"):
    actual = {item["id"]: item for item in imported[collection]}
    for item in reference[collection]:
        delta = max(abs(a - b) for a, b in zip(item["bounds_m"], actual[item["id"]]["bounds_m"]))
        if delta > report["tolerance_m"]:
            report["differences"].append({
                "collection": collection, "id": item["id"], "max_delta_m": delta,
                "canonical": item["bounds_m"], "roundtrip": actual[item["id"]]["bounds_m"],
            })
report["mesh_shape_equal"] = reference["mesh"]["shape"] == imported["mesh"]["shape"]
report["canonical_devices"] = reference["estimates"]["device_count"]
report["roundtrip_devices"] = imported["estimates"]["device_count"]
report["gas_mask_equal"] = reference["sampling"]["valid_mask"] == imported["sampling"]["valid_mask"]
report["status"] = "passed" if (
    not report["differences"] and report["mesh_shape_equal"] and report["gas_mask_equal"]
    and report["canonical_devices"] == report["roundtrip_devices"]
) else "failed"
(directory / "mesh-comparison.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report))
