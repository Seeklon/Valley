"""Attach editable incident annotations to an existing .blend, without rebuilding visuals.

blender --background source.blend --python annotate_incidents.py -- --scene soyuz --output copy.blend
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def annotate(scene, collection_name="02_PHYSICAL_PROXY__enable_to_inspect"):
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        raise ValueError("The physical annotation collection is missing")
    annotations = scene["incident_annotations"]
    by_id = {o.get("ignis_id"): o for o in collection.all_objects if o.get("ignis_role") != "component"}
    for object_id, surface in annotations["surface_materials"].items():
        obj = by_id[object_id]
        obj["combustible_material_id"] = surface["material_id"]
        obj["thermal_thickness_m"] = surface["thickness_m"]
        obj["ignis_material_provenance"] = surface["provenance"]
    for object_id in annotations["critical_object_ids"]:
        by_id[object_id]["ignis_critical"] = True
    for sensor_id in annotations["passage_sensor_ids"]:
        by_id[sensor_id]["ignis_passage"] = True
    for component in annotations["components"]:
        obj = next((o for o in collection.all_objects
                    if o.get("ignis_role") == "component" and o.get("ignis_id") == component["id"]), None)
        if obj is None:
            obj = bpy.data.objects.new(component["id"], None)
            collection.objects.link(obj)
        obj.empty_display_type = "SPHERE"
        obj.empty_display_size = .07
        obj.location = component["position_m"]
        obj["ignis_role"] = "component"
        obj["ignis_id"] = component["id"]
        obj["ignis_name"] = component["name"]
        obj["source_object_id"] = component["object_id"]
        obj["source_face"] = component["face"]
        obj["component_kind"] = component["kind"]
        obj["ignis_critical"] = component["critical"]
        obj["ignis_provenance"] = component["provenance"]
    bpy.context.view_layer.update()
    return len(annotations["components"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path(__file__).resolve().parents[2]/"scenes/catalog.json")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:])
    if args.output.resolve() == Path(bpy.data.filepath).resolve():
        raise ValueError("Choose a distinct output path; preserve the original Blender scene")
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    scene = next(s for s in catalog["scenes"] if s["id"] == args.scene)
    count = annotate(scene)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output))
    print("IGNIS_INCIDENT_ANNOTATIONS", count, flush=True)
