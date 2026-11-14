"""Run the Soyuz asset/import contract checks on Windows; never launch FDS."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--attempt", default="initial")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise RuntimeError("Run this verification on the Windows compute workstation")
    root = Path(__file__).resolve().parents[1]
    logs = root / "evidence" / "blender-roundtrip" / args.attempt
    logs.mkdir(parents=True, exist_ok=True)
    result_path = logs / "result.json"
    output = root / "scenes" / "imported" / "soyuz-import-check"
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite an existing import: {output}")
    source = root / "scenes" / "generated" / "soyuz.blend"
    source_hash = digest(source)
    result = {
        "schema_version": 1,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.system(),
        "python_version": platform.python_version(),
        "scene_id": "soyuz-import-check",
        "source_blend_sha256": source_hash,
        "source_catalog_sha256": digest(root / "scenes" / "catalog.json"),
        "tools_sha256": {
            name: digest(root / name)
            for name in (
                "tools/blender/export_scene.py",
                "tools/blender/validate_assets.py",
                "backend/ignis/physics/compiler.py",
                "backend/ignis/physics/materials.py",
            )
        },
        "steps": [],
        "fds_executed": False,
        "render_performed": False,
    }

    def run(name: str, command: list[str], marker: str | None = None) -> None:
        log_path = logs / f"{name}.log"
        start = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.run(
                command, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=180, check=False
            )
        step = {
            "name": name,
            "exit_code": process.returncode,
            "elapsed_s": round(time.monotonic() - start, 3),
            "log": log_path.relative_to(root).as_posix(),
            "log_sha256": digest(log_path),
        }
        result["steps"].append(step)
        text = log_path.read_text(encoding="utf-8", errors="replace")
        if process.returncode or (marker and marker not in text):
            raise RuntimeError(f"{name} failed: exit={process.returncode}, marker={marker!r}; see its log")

    try:
        run(
            "assets-windows",
            [sys.executable, str(root / "tools/blender/validate_assets.py"), "--require-all-artifacts"],
        )
        result["generated_assets"] = json.loads((logs / "assets-windows.log").read_text())["results"]
        base = [
            str(args.blender), "--background", str(source), "--python-exit-code", "2",
            "--python", str(root / "tools/blender/export_scene.py"), "--",
            "--scene-id", "soyuz-import-check",
            "--provenance", "Original IGNIS geometry; roundtrip verification",
            "--output", str(output),
            "--visual-collection", "01_VISUAL_CUTAWAY",
            "--physics-collection", "02_PHYSICAL_PROXY__enable_to_inspect",
        ]
        run("validate-original", [*base, "--validate-only"], "IGNIS_IMPORT_VALID")
        run("export", base, "IGNIS_IMPORT_EXPORTED")
        reopened = list(base)
        reopened[2] = str(output / "soyuz-import-check.blend")
        run("validate-reopened", [*reopened, "--validate-only"], "IGNIS_IMPORT_VALID")

        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        for artifact in manifest["artifacts"]:
            path = output / artifact["file"]
            if path.stat().st_size != artifact["bytes"] or digest(path) != artifact["sha256"]:
                raise ValueError(f"Export manifest hash mismatch: {path.name}")
        result["blender_version"] = manifest["blender_version"]
        result["exported_artifacts"] = manifest["artifacts"]
        catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
        imported = catalog["scenes"][0]
        original = next(
            scene for scene in json.loads((root / "scenes/catalog.json").read_text())["scenes"]
            if scene["id"] == "soyuz"
        )

        deltas = []

        def compare(first, second, context):
            if isinstance(first, (int, float)) and not isinstance(first, bool):
                delta = abs(float(first) - float(second))
                deltas.append(delta)
                if delta > 1e-5:
                    raise ValueError(f"Roundtrip changed {context}: {first!r} vs {second!r}")
            elif isinstance(first, list):
                if len(first) != len(second):
                    raise ValueError(f"Roundtrip changed {context} length")
                for index, (a, b) in enumerate(zip(first, second)):
                    compare(a, b, f"{context}[{index}]")
            elif first != second:
                raise ValueError(f"Roundtrip changed {context}: {first!r} vs {second!r}")

        for key in ("bounds_m", "source_position_m", "coordinate_system", "units"):
            compare(original[key], imported[key], key)
        for key, value in original["defaults"].items():
            compare(value, imported["defaults"].get(key), f"defaults.{key}")
        for collection, fields in (
            ("objects", ("role", "material_id", "center_m", "size_m")),
            ("vents", ("role", "center_m", "size_m", "normal", "nominal_speed_m_s")),
            ("sensors", ("position_m",)),
        ):
            first = {obj["id"]: obj for obj in original[collection]}
            second = {obj["id"]: obj for obj in imported[collection]}
            compare(set(first), set(second), collection + " IDs")
            for key, obj in first.items():
                for field in fields:
                    compare(obj[field], second[key][field], f"{collection}.{key}.{field}")
        result["contract_roundtrip"] = {
            "status": "passed", "tolerance_m": 1e-5, "max_numeric_delta": max(deltas),
            "objects": len(imported["objects"]), "vents": len(imported["vents"]),
            "sensors": len(imported["sensors"]), "defaults_preserved": True,
        }
        spec = importlib.util.spec_from_file_location("asset_validator", root / "tools/blender/validate_assets.py")
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        glb = validator.read_glb(output / "soyuz-import-check.glb")
        ids = {node.get("extras", {}).get("object_id") for node in glb.get("nodes", [])}
        expected = {
            obj["id"] for obj in original["objects"]
            if obj["role"] != "wall" and obj.get("visual_type") != "physical_only"
        }
        expected |= {obj["id"] for obj in original["vents"] + original["sensors"]}
        if expected - ids:
            raise ValueError(f"Imported GLB lost semantic IDs: {sorted(expected - ids)}")
        if not glb.get("meshes") or not glb.get("materials"):
            raise ValueError("Imported GLB has no visual geometry/materials")
        if any(
            node.get("name", "").startswith(("physical_AABB_", "studio_ground", "physical_domain"))
            for node in glb.get("nodes", [])
        ):
            raise ValueError("Imported GLB leaked physics or studio objects")
        if any(
            resource.get("uri") and not resource["uri"].startswith("data:")
            for resource in glb.get("buffers", []) + glb.get("images", [])
        ):
            raise ValueError("Imported GLB references external resources")
        result["imported_glb"] = {
            "nodes": len(glb["nodes"]), "semantic_ids": len(ids - {None}),
            "required_ids_preserved": True, "external_resources": False,
            "physics_or_studio_leak": False,
        }
        sys.path.insert(0, str(root / "backend"))
        from ignis.physics import compile_case

        compiled = compile_case(imported, {}, logs / "compiled-contract")
        result["compile_case"] = {
            "status": "passed", "configuration_overrides": {}, "mesh": compiled["mesh"],
            "devices": compiled["estimates"]["device_count"],
            "artifacts": [
                {"file": path.name, "sha256": digest(path), "bytes": path.stat().st_size}
                for path in sorted((logs / "compiled-contract").iterdir()) if path.is_file()
            ],
            "warnings": compiled["warnings"],
        }
        result["status"] = "passed"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        (logs / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        result["source_blend_preserved"] = digest(source) == source_hash
        if not result["source_blend_preserved"]:
            result["status"] = "failed"
        result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": result["status"], "evidence": result_path.relative_to(root).as_posix()}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
