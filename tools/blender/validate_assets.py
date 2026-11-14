"""Lightweight artifact checks, without Blender, a renderer or third-party packages.

Checks GLB structure, required semantic IDs, embedded resources, artifact
manifest hashes and minimum render dimensions. This does not replace inspection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


def read_glb(path):
    data = path.read_bytes()
    if len(data) < 20:
        raise ValueError(f"{path.name}: truncated GLB")
    magic, version, size = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2 or size != len(data):
        raise ValueError(f"{path.name}: invalid GLB header")
    chunk_size, chunk_type = struct.unpack_from("<I4s", data, 12)
    if chunk_type != b"JSON" or 20 + chunk_size > len(data):
        raise ValueError(f"{path.name}: invalid JSON chunk")
    return json.loads(data[20:20 + chunk_size])


def validate(scene, folder):
    glb_path = folder / f"{scene['id']}.glb"
    data = read_glb(glb_path)
    node_ids = {n.get("extras", {}).get("object_id") for n in data.get("nodes", [])}
    expected = {o["id"] for o in scene["objects"] if o["role"] != "wall" and o.get("visual_type") != "physical_only"}
    expected |= {v["id"] for v in scene["vents"]}
    expected |= {s["id"] for s in scene["sensors"]}
    if missing := expected - node_ids:
        raise ValueError(f"{scene['id']}: GLB missing semantic IDs: {sorted(missing)}")
    if not data.get("meshes") or not data.get("materials"):
        raise ValueError(f"{scene['id']}: missing visual meshes or materials")
    for resource in data.get("buffers", []) + data.get("images", []):
        if resource.get("uri") and not resource["uri"].startswith("data:"):
            raise ValueError(f"{scene['id']}: GLB references external URI {resource['uri']}")
    # The selected scene must not include physics proxies or the studio plane.
    invalid_names = [n.get("name", "") for n in data.get("nodes", [])
                     if n.get("name", "").startswith(("physical_AABB_", "studio_ground", "physical_domain"))]
    if invalid_names:
        raise ValueError(f"{scene['id']}: calculation/studio objects leaked into GLB: {invalid_names}")
    manifest_path = folder / f"{scene['id']}.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checked, absent = [], []
    for artifact in manifest["artifacts"]:
        path = folder / artifact["file"]
        if not path.exists():
            absent.append(path.name)
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != artifact["sha256"] or path.stat().st_size != artifact["bytes"]:
            raise ValueError(f"{scene['id']}: hash/size mismatch for {path.name}")
        if path.suffix == ".png":
            header = path.read_bytes()[:24]
            if header[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack_from(">I", header, 16)[0] < 1600:
                raise ValueError(f"{path.name}: expected PNG width >=1600")
        checked.append(path.name)
    return {"id": scene["id"], "glb_bytes": glb_path.stat().st_size, "nodes": len(data.get("nodes", [])),
            "semantic_ids": len(node_ids - {None}), "verified_local_artifacts": checked,
            "artifacts_not_in_this_checkout": absent, "visual_review": "separate manual inspection required"}


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=root / "scenes" / "catalog.json")
    parser.add_argument("--folder", type=Path, default=root / "scenes" / "generated")
    parser.add_argument("--scene", default="all")
    parser.add_argument("--require-all-artifacts", action="store_true", help="Fail if .blend or other manifest artifacts are absent locally")
    args = parser.parse_args()
    scenes = json.loads(args.catalog.read_text(encoding="utf-8"))["scenes"]
    results = [validate(s, args.folder) for s in scenes if args.scene in ("all", s["id"])]
    if not results:
        parser.error("No matching scene")
    if args.require_all_artifacts and any(r["artifacts_not_in_this_checkout"] for r in results):
        raise ValueError("Some manifest artifacts are absent; run on the complete Windows artifact directory")
    print(json.dumps({"schema_version": 1, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
