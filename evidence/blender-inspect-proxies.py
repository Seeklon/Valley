"""Diagnose hidden annotation transforms in the real saved Blender file."""

import json

import bpy


def snapshot(label):
    names = ["physical_domain", "physical_AABB_seat_left", "physical_ignition_source"]
    result = {"stage": label, "objects": []}
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        result["objects"].append({
            "name": name,
            "location": list(obj.location),
            "matrix_world": [list(row) for row in obj.matrix_world],
            "matrix_basis": [list(row) for row in obj.matrix_basis],
            "scale": list(obj.scale),
            "bounds": [list(v.co) for v in obj.data.vertices] if obj.type == "MESH" else None,
        })
    print("IGNIS_PROXY_SNAPSHOT " + json.dumps(result), flush=True)


snapshot("saved_hidden")
bpy.context.view_layer.update()
snapshot("updated_hidden")
physical = bpy.data.collections["02_PHYSICAL_PROXY__enable_to_inspect"]
physical.hide_viewport = False
bpy.context.view_layer.update()
snapshot("updated_visible")
