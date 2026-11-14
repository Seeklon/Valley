"""Export an explicitly annotated imported Blender environment as an IGNIS scene.

This script deliberately never infers a thermal material from a shader or name.
Visual geometry is separate from axis-aligned physical proxies. See SCENES.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
PHYSICAL_ROLES = {"obstacle", "fuel", "wall"}
REQUIRED_DEFAULTS = {"gravity_g", "airflow_m_s", "oxygen_percent", "material_id",
                     "ignition_power_w", "ignition_duration_s", "duration_s", "seed"}


def identifier(value, context):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_\-]{0,63}", value):
        raise ValueError(f"{context}: expected lowercase identifier ([a-z][a-z0-9_-]{{0,63}})")
    return value


def vector(value, context, positive=False):
    try:
        result = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context}: expected three finite numbers") from exc
    if len(result) != 3 or not all(math.isfinite(v) for v in result):
        raise ValueError(f"{context}: expected three finite numbers")
    if positive and not all(v > 0 for v in result):
        raise ValueError(f"{context}: expected positive dimensions")
    return result


def required(obj, key):
    if key not in obj:
        raise ValueError(f"{obj.name}: missing explicit property {key}")
    return obj[key]


def annotation_world_matrices(physical):
    """Evaluate hidden annotation hierarchies without changing saved visibility.

    Blender may retain identity matrix_world values for disabled collections,
    even after a view_layer.update(). Temporarily enable the dependency graph,
    copy the evaluated transforms, then restore every visibility setting.
    """
    layers = []

    def visit(layer):
        layers.append(layer)
        for child in layer.children:
            visit(child)

    visit(bpy.context.view_layer.layer_collection)
    layer_states = [(layer, layer.exclude, layer.hide_viewport) for layer in layers]
    collection_states = [(collection, collection.hide_viewport)
                         for collection in {layer.collection for layer in layers}]
    object_states = [(obj, obj.hide_viewport) for obj in bpy.context.scene.objects]
    try:
        for collection, _ in collection_states:
            collection.hide_viewport = False
        for layer, _, _ in layer_states:
            layer.exclude = False
            layer.hide_viewport = False
        for obj, _ in object_states:
            obj.hide_viewport = False
        bpy.context.view_layer.update()
        return {obj: obj.matrix_world.copy() for obj in physical.all_objects}
    finally:
        for obj, hidden in object_states:
            obj.hide_viewport = hidden
        # Parent exclusion changes propagate to descendants: restore parents first.
        for layer, excluded, hidden in layer_states:
            layer.hide_viewport = hidden
            layer.exclude = excluded
        for collection, hidden in collection_states:
            collection.hide_viewport = hidden
        bpy.context.view_layer.update()


def position(obj, matrices):
    return vector(matrices[obj].translation, obj.name + " position")


def bounding_box(obj, matrices):
    if obj.type != "MESH":
        raise ValueError(f"{obj.name}: physical proxy must be a box mesh")
    if len(obj.data.vertices) != 8 or len(obj.data.polygons) != 6:
        raise ValueError(f"{obj.name}: proxy must be an explicit six-face box, not a visual mesh")
    if any(mod.show_viewport for mod in obj.modifiers):
        raise ValueError(f"{obj.name}: apply or remove proxy modifiers before export")
    corners = [matrices[obj] @ vertex.co for vertex in obj.data.vertices]
    low = [min(p[i] for p in corners) for i in range(3)]
    high = [max(p[i] for p in corners) for i in range(3)]
    # Reject a rotated box rather than silently replacing it with a larger AABB.
    if any(not all(min(abs(p[i] - low[i]), abs(p[i] - high[i])) < 1e-5 for i in range(3)) for p in corners):
        raise ValueError(f"{obj.name}: proxy is not axis aligned; edit an explicit AABB for the solver")
    size = vector([high[i] - low[i] for i in range(3)], obj.name + " size", positive=True)
    return [(low[i] + high[i]) / 2 for i in range(3)], size


def check_point(point, bounds, context, strict=False):
    if not all((0 < p < b if strict else -1e-6 <= p <= b + 1e-6) for p, b in zip(point, bounds)):
        raise ValueError(f"{context}: outside the [0,bounds_m] domain")


def catalog_from_scene(args):
    if abs(bpy.context.scene.unit_settings.scale_length - 1.0) > 1e-8:
        raise ValueError("Use scene scale_length=1 and explicit metre geometry before export; no implicit unit rescaling")
    visual = bpy.data.collections.get(args.visual_collection)
    physical = bpy.data.collections.get(args.physics_collection)
    if visual is None or physical is None:
        raise ValueError("Create separate visual and physical annotation collections before exporting")
    if not any(o.type == "MESH" for o in visual.all_objects):
        raise ValueError("The visual collection has no mesh")
    if set(visual.all_objects) & set(physical.all_objects):
        raise ValueError("Visual objects and physical annotation objects must be in separate collections")
    base = json.loads(args.material_catalog.read_text(encoding="utf-8"))
    material_ids = {m["id"] for m in base["materials"]}
    domain = [o for o in physical.all_objects if o.get("ignis_role") == "domain"]
    if len(domain) != 1:
        raise ValueError("Create exactly one ignis_role=domain proxy box")
    matrices = annotation_world_matrices(physical)
    center, bounds = bounding_box(domain[0], matrices)
    if any(abs(c - size / 2) > 1e-5 for c, size in zip(center, bounds)):
        raise ValueError("The domain minimum corner must be [0,0,0] in physical metres")
    objects, vents, sensors, sources, components = [], [], [], [], []
    seen = set()
    for obj in physical.all_objects:
        if "ignis_role" not in obj and obj.type == "EMPTY":
            continue  # organizational parents are not independent physical objects
        role = required(obj, "ignis_role")
        if role == "domain":
            continue
        object_id = identifier(required(obj, "ignis_id"), obj.name)
        if object_id in seen:
            raise ValueError(f"Duplicate annotation ID: {object_id}")
        seen.add(object_id)
        if role in PHYSICAL_ROLES:
            material = required(obj, "material_id")
            if material not in material_ids:
                raise ValueError(f"{obj.name}: unknown material_id={material}; add its provenance to the material catalog first")
            center, size = bounding_box(obj, matrices)
            if role != "wall":
                check_point([c - n / 2 for c, n in zip(center, size)], bounds, obj.name)
                check_point([c + n / 2 for c, n in zip(center, size)], bounds, obj.name)
            objects.append({"id": object_id, "name": obj.get("ignis_name", obj.name), "role": role,
                            "material_id": material, "center_m": center, "size_m": size,
                            "proxy_kind": "explicit_axis_aligned_box"})
            if "combustible_material_id" in obj:
                fuel = str(obj["combustible_material_id"])
                if fuel not in {"pmma", "cellulose"}:
                    raise ValueError(f"{obj.name}: combustible_material_id must be pmma or cellulose")
                objects[-1]["combustible_material_id"] = fuel
            if "thermal_thickness_m" in obj:
                thickness = float(obj["thermal_thickness_m"])
                if not math.isfinite(thickness) or not .00005 <= thickness <= .1:
                    raise ValueError(f"{obj.name}: thermal_thickness_m outside [.00005,.1] m")
                objects[-1]["thermal_thickness_m"] = thickness
            if "ignis_critical" in obj:
                objects[-1]["critical"] = bool(obj["ignis_critical"])
        elif role in {"inlet", "outlet"}:
            point = position(obj, matrices)
            size = vector(required(obj, "ignis_size_m"), obj.name + " ignis_size_m")
            normal = vector(required(obj, "ignis_normal"), obj.name + " ignis_normal")
            axes = [i for i, n in enumerate(size) if abs(n) < 1e-8]
            if len(axes) != 1 or any(n < 0 for n in size):
                raise ValueError(f"{obj.name}: vent size needs two positive sides and one zero normal dimension")
            axis = axes[0]
            if min(abs(point[axis]), abs(point[axis] - bounds[axis])) > 1e-5:
                raise ValueError(f"{obj.name}: vent must be on a domain boundary")
            for edge in (-1, 1):
                check_point([p + edge * n / 2 for p, n in zip(point, size)], bounds, obj.name)
            expected = 1 if point[axis] < bounds[axis] / 2 else -1
            if role == "outlet":
                expected *= -1
            if any(abs(n - (expected if i == axis else 0)) > 1e-6 for i, n in enumerate(normal)):
                raise ValueError(f"{obj.name}: inlet normal points inward, outlet normal outward; axis aligned unit vector required")
            speed = float(required(obj, "nominal_speed_m_s"))
            if not math.isfinite(speed) or speed <= 0:
                raise ValueError(f"{obj.name}: positive finite nominal_speed_m_s required")
            vents.append({"id": object_id, "role": role, "center_m": point, "size_m": size,
                          "normal": normal, "nominal_speed_m_s": speed})
        elif role == "sensor":
            point = position(obj, matrices)
            check_point(point, bounds, obj.name, strict=True)
            sensors.append({"id": object_id, "name": obj.get("ignis_name", obj.name), "position_m": point})
            if obj.get("ignis_passage", False):
                sensors[-1]["kind"] = "passage"
        elif role == "component":
            point = position(obj, matrices)
            check_point(point, bounds, obj.name, strict=True)
            if int(obj.get("source_face", 3)) != 3:
                raise ValueError(f"{obj.name}: this incident adapter supports exposed upper faces (source_face=3)")
            components.append({"id": object_id, "name": obj.get("ignis_name", obj.name),
                "object_id": identifier(required(obj, "source_object_id"), obj.name),
                "position_m": point, "face": 3,
                "kind": str(obj.get("component_kind", "electrical_equipment")),
                "critical": bool(obj.get("ignis_critical", False)),
                "provenance": str(obj.get("ignis_provenance", args.provenance))})
        elif role == "source":
            point = position(obj, matrices)
            check_point(point, bounds, obj.name, strict=True)
            sources.append(point)
        else:
            raise ValueError(f"{obj.name}: unsupported ignis_role={role}; move decorative meshes to the visual collection")
    if len(sources) != 1:
        raise ValueError("Define exactly one source annotation")
    if not vents or {v["role"] for v in vents} != {"inlet", "outlet"}:
        raise ValueError("Define at least one inlet and one outlet for the initial ventilated scene contract")
    if not sensors:
        raise ValueError("Define at least one sensor")
    if not any(o["role"] == "fuel" for o in objects):
        raise ValueError("Define at least one fuel proxy with an explicitly assigned material")
    solids = [o for o in objects if o["role"] in {"obstacle", "fuel"}]
    for component in components:
        parent = next((o for o in solids if o["id"] == component["object_id"]), None)
        if parent is None:
            raise ValueError(f"{component['id']}: source_object_id must reference a physical object")
        component_position = component["position_m"]
        if (abs(component_position[2] - parent["center_m"][2] - parent["size_m"][2]/2) > 1e-5
                or any(abs(component_position[a]-parent["center_m"][a]) >= parent["size_m"][a]/2 for a in (0, 1))):
            raise ValueError(f"{component['id']}: place the component inside the upper face of its object")
    for i, a in enumerate(solids):
        for b in solids[i + 1:]:
            if all(abs(x - y) < (s + t) / 2 - 1e-5 for x, y, s, t in zip(a["center_m"], b["center_m"], a["size_m"], b["size_m"])):
                raise ValueError(f"Physical proxies overlap: {a['id']} / {b['id']}")
    defaults = json.loads(required(bpy.context.scene, "ignis_defaults_json"))
    if missing := REQUIRED_DEFAULTS - set(defaults):
        raise ValueError("Missing explicit defaults: " + ", ".join(sorted(missing)))
    if defaults["material_id"] not in material_ids:
        raise ValueError("Default material_id is absent from the catalog")
    defaults.setdefault("source_model", "prescribed_source")
    scene = {"id": identifier(args.scene_id, "scene_id"), "name": args.name or args.scene_id,
             "description": args.description, "asset_url": f"/assets/scenes/{args.scene_id}.glb",
             "bounds_m": bounds, "coordinate_system": "right_handed_z_up", "units": "m",
             "objects": objects, "vents": vents, "sensors": sensors, "source_position_m": sources[0],
             "components": components,
             "defaults": defaults,
             "provenance": {"kind": "user_imported_annotated_environment", "source_file": Path(bpy.data.filepath).name,
                            "geometry_source": args.provenance,
                            "scientific_status": "Explicit user annotations; uncalibrated until tested against independent data.",
                            "boundary_policy": "role=wall describes domain boundaries, not interior OBST.",
                            "visual_detail_policy": "Only explicit physical proxies participate in calculation; shader materials do not define combustion."}}
    return {"schema_version": 1, "materials": base["materials"], "scenes": [scene]}, visual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--name")
    parser.add_argument("--description", default="Environment imported and explicitly annotated in Blender")
    parser.add_argument("--provenance", required=True, help="Geometry origin and applicable license/permission; no private file path needed")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--visual-collection", default="IGNIS_VISUAL")
    parser.add_argument("--physics-collection", default="IGNIS_PHYSICS")
    parser.add_argument("--material-catalog", type=Path, default=ROOT / "scenes" / "catalog.json")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    catalog, visual = catalog_from_scene(args)
    if args.validate_only:
        print("IGNIS_IMPORT_VALID", json.dumps({"id": args.scene_id, "objects": len(catalog["scenes"][0]["objects"])}), flush=True)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    catalog_path = args.output / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Propagate only explicitly given semantic metadata through visual hierarchy.
    physical_by_id = {o["id"]: o for o in catalog["scenes"][0]["objects"]}
    for obj in visual.all_objects:
        ancestor = obj
        while ancestor is not None and not (ancestor.get("ignis_id") or ancestor.get("object_id")):
            ancestor = ancestor.parent
        if ancestor is not None:
            semantic_id = ancestor.get("ignis_id", ancestor.get("object_id"))
            obj["object_id"] = semantic_id
            if semantic_id in physical_by_id:
                obj["role"] = physical_by_id[semantic_id]["role"]
                obj["material_id"] = physical_by_id[semantic_id]["material_id"]
        else:
            obj["role"] = "decoration"
    blend_path = args.output / f"{args.scene_id}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), copy=True)
    bpy.ops.object.select_all(action="DESELECT")
    curves = [o for o in visual.all_objects if o.type in {"CURVE", "FONT"}]
    for obj in curves:
        obj.hide_set(False)
        obj.select_set(True)
    if curves:
        bpy.context.view_layer.objects.active = curves[0]
        bpy.ops.object.convert(target="MESH")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in visual.all_objects:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = next(o for o in visual.all_objects if o.type == "MESH")
    glb_path = args.output / f"{args.scene_id}.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb_path), export_format="GLB", use_selection=True,
                              export_apply=True, export_extras=True, export_yup=True,
                              export_cameras=False, export_lights=False, export_animations=False)
    manifest = {"schema_version": 1, "scene_id": args.scene_id, "blender_version": bpy.app.version_string,
                "artifacts": [{"file": p.name, "bytes": p.stat().st_size,
                               "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in (blend_path, glb_path, catalog_path)],
                "verification": {"annotation_validation": "passed", "simulation_validation": "not_run", "render_inspected": False}}
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("IGNIS_IMPORT_EXPORTED", str(args.output), flush=True)


if __name__ == "__main__":
    main()
