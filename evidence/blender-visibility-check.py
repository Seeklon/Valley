"""Exercise hidden/excluded annotations in the real exported Blender file."""

import argparse
import importlib.util
import json
from pathlib import Path

import bpy

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ignis_exporter", root / "tools/blender/export_scene.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
layers = []


def visit(layer):
    layers.append(layer)
    for child in layer.children:
        visit(child)


visit(bpy.context.view_layer.layer_collection)
physical = bpy.data.collections["02_PHYSICAL_PROXY__enable_to_inspect"]
physical_layer = next(layer for layer in layers if layer.collection == physical)


def visibility():
    return {
        "layers": [(layer.name, layer.exclude, layer.hide_viewport) for layer in layers],
        "collections": [(collection.name, collection.hide_viewport) for collection in bpy.data.collections],
        "objects": [(obj.name, obj.hide_viewport, obj.hide_render) for obj in bpy.context.scene.objects],
    }


args = argparse.Namespace(
    visual_collection="01_VISUAL_CUTAWAY", physics_collection=physical.name,
    material_catalog=root / "scenes/catalog.json", scene_id="soyuz-import-check",
    name=None, description="Roundtrip visibility check", provenance="Original IGNIS geometry",
)
result = {"schema_version": 1, "saved_physics_hidden": physical.hide_viewport, "checks": []}
for excluded in (False, True):
    physical_layer.exclude = excluded
    before = visibility()
    catalog, _ = exporter.catalog_from_scene(args)
    after = visibility()
    restored = before == after
    if not restored:
        print("IGNIS_VISIBILITY_DIFFERENCES " + json.dumps({
            key: {"before": before[key], "after": after[key]}
            for key in before if before[key] != after[key]
        }), flush=True)
        raise AssertionError("Exporter modified annotation visibility")
    result["checks"].append({
        "physics_layer_excluded": excluded, "visibility_preserved": restored,
        "objects": len(catalog["scenes"][0]["objects"]),
        "bounds_m": catalog["scenes"][0]["bounds_m"],
    })
result["status"] = "passed"
target = root / "evidence/blender-roundtrip/final/visibility.json"
target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print("IGNIS_VISIBILITY_VALID " + json.dumps(result), flush=True)
