"""Build the original Aster compartment: editable Blender, web GLB and images.

Blender >= 4.2, tested target 4.5 LTS. No external assets or Python packages.
Usage:
  blender --background --python tools/blender/build_scene.py -- --scene habitat \
    --output scenes/generated --render --samples 32

Run on the Windows compute workstation. Rendering is deliberately opt-in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import soyuz_geometry  # noqa: E402 — Blender scripts need their directory on sys.path first.

PALETTE = {
    "structure": ("132536", 0.65, 0.36),
    "blue": ("41677b", 0.5, 0.38),
    "panel": ("b6ccd0", 0.28, 0.42),
    "ceramic": ("e3e9dd", 0.05, 0.52),
    "dark": ("07121d", 0.32, 0.44),
    "rubber": ("17272d", 0.0, 0.82),
    "metal": ("95adb8", 0.8, 0.3),
    "gold": ("dd9b50", 0.6, 0.34),
    "orange": ("ea784b", 0.15, 0.42),
    "teal": ("38b9b0", 0.25, 0.32),
    "white": ("ebf0e7", 0.05, 0.4),
    "floor": ("243947", 0.45, 0.5),
    "screen": ("0b2939", 0.05, 0.26),
    "cellulose": ("ba976e", 0.0, 0.82),
    "pmma": ("74acba", 0.05, 0.28),
}
MATS = {}
VISUAL = None
PROXY = None
FULL_HULL = None
STUDIO = None
CURRENT = None


def srgb(value):
    return value / 12.92 if value < 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def rgba(code):
    return tuple(srgb(int(code[i:i + 2], 16) / 255) for i in (0, 2, 4)) + (1.0,)


def make_material(name, code, metallic=0, roughness=0.5, emission=0):
    mat = bpy.data.materials.new("ASTER_" + name)
    mat.diffuse_color = rgba(code)
    mat.use_nodes = True
    p = mat.node_tree.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = rgba(code)
    p.inputs["Metallic"].default_value = metallic
    p.inputs["Roughness"].default_value = roughness
    if emission:
        p.inputs["Emission Color"].default_value = rgba(code)
        p.inputs["Emission Strength"].default_value = emission
    return mat


def init_materials():
    for name, (code, metallic, roughness) in PALETTE.items():
        MATS[name] = make_material(name, code, metallic, roughness)
    for name, code, strength in [("led", "43dfc7", 2), ("amber", "ffac54", 2),
                                 ("lamp", "e9f4ed", 5), ("display", "66e3de", 1.1)]:
        MATS[name] = make_material(name, code, roughness=0.35, emission=strength)


def collection(name):
    result = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(result)
    return result


def metadata(obj, parent=None, **kwargs):
    if parent is not None:
        for key in ("object_id", "role", "material_id", "surface_kind", "cutaway"):
            if key in parent:
                obj[key] = parent[key]
    for key, value in kwargs.items():
        obj[key] = value
    return obj


def group(name, position=(0, 0, 0), rotation=0, **kwargs):
    obj = bpy.data.objects.new(name, None)
    CURRENT.objects.link(obj)
    obj.location = position
    obj.rotation_euler.z = rotation
    metadata(obj, **kwargs)
    return obj


def object_mesh(name, vertices, faces, material, location=(0, 0, 0), parent=None):
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    CURRENT.objects.link(obj)
    obj.parent = parent
    obj.location = location
    if material:
        mesh.materials.append(MATS[material])
    metadata(obj, parent)
    return obj


def box(name, loc, size, material, bevel=0.015, parent=None, rotation=None):
    x, y, z = (v / 2 for v in size)
    vertices = [(-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
                (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    obj = object_mesh(name, vertices, faces, material, loc, parent)
    if rotation:
        obj.rotation_euler = rotation
    if bevel and min(size) > 0.003:
        mod = obj.modifiers.new("Machined edge radius", "BEVEL")
        mod.width = min(bevel, min(size) * 0.22)
        mod.segments = 2
        mod.harden_normals = True
        mod = obj.modifiers.new("Weighted surface normals", "WEIGHTED_NORMAL")
        mod.keep_sharp = True
    return obj


def cylinder(name, start, end, radius, material, parent=None, vertices=12):
    a, b = Vector(start), Vector(end)
    length = (b - a).length
    coords = [(radius * math.cos(2 * math.pi * i / vertices), radius * math.sin(2 * math.pi * i / vertices), z)
              for z in (-length / 2, length / 2) for i in range(vertices)]
    faces = [(i, (i + 1) % vertices, (i + 1) % vertices + vertices, i + vertices) for i in range(vertices)]
    faces += [tuple(reversed(range(vertices))), tuple(range(vertices, vertices * 2))]
    obj = object_mesh(name, coords, faces, material, (a + b) / 2, parent)
    obj.rotation_euler = (b - a).to_track_quat("Z", "Y").to_euler()
    for polygon in obj.data.polygons[:vertices]:
        polygon.use_smooth = True
    return obj


def cable(name, points, radius=0.012, material="orange", parent=None):
    data = bpy.data.curves.new(name + "_curve", "CURVE")
    data.dimensions = "3D"
    data.resolution_u = 3
    data.bevel_depth = radius
    data.bevel_resolution = 2
    spline = data.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for point, coordinate in zip(spline.bezier_points, points):
        point.co = coordinate
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, data)
    CURRENT.objects.link(obj)
    obj.parent = parent
    data.materials.append(MATS[material])
    metadata(obj, parent)
    return obj


def label(name, text, loc, size=0.08, material="white", parent=None,
          right=(1, 0, 0), up=(0, 0, 1), align="LEFT"):
    data = bpy.data.curves.new(name + "_font", "FONT")
    data.body = text
    data.size = size
    data.align_x = align
    data.extrude = 0.0003
    data.resolution_u = 3
    obj = bpy.data.objects.new(name, data)
    CURRENT.objects.link(obj)
    obj.parent = parent
    obj.location = loc
    r, u = Vector(right), Vector(up)
    obj.rotation_euler = Matrix((r, u, r.cross(u))).transposed().to_euler()
    data.materials.append(MATS[material])
    metadata(obj, parent)
    return obj


def screw(name, x, y, z, parent, direction="front"):
    if direction == "front":
        cylinder(name, (x, y + 0.004, z), (x, y - 0.008, z), 0.012, "metal", parent, 8)
    else:
        cylinder(name, (x, y, z), (x, y, z + 0.012), 0.012, "metal", parent, 8)


def front_panel(parent, name, x, y, z, width, height, material="panel", screws=True):
    box(name, (x, y, z), (width, 0.035, height), material, 0.012, parent)
    if screws:
        for dx in (-1, 1):
            for dz in (-1, 1):
                screw(name + "_fastener", x + dx * (width / 2 - 0.04), y - 0.02, z + dz * (height / 2 - 0.04), parent)


def grille(parent, name, x, y, z, width, height, bars=12, accent="metal"):
    box(name + "_recess", (x, y, z), (width, 0.035, height), "dark", 0.015, parent)
    for i in range(bars):
        offset = -height / 2 + (i + 0.5) * height / bars
        box(name + "_louver", (x, y - 0.025, z + offset), (width - 0.045, 0.045, 0.018), accent, 0.003, parent,
            rotation=(math.radians(-15), 0, 0))
    for side in (-1, 1):
        box(name + "_border", (x + side * width / 2, y - 0.02, z), (0.028, 0.04, height + 0.04), "structure", 0.004, parent)


def screen(parent, name, x, y, z, width, height, title="SYSTEM / NOMINAL"):
    front_panel(parent, name + "_frame", x, y, z, width, height, "structure", False)
    box(name + "_glass", (x, y - 0.026, z), (width - 0.045, 0.009, height - 0.045), "screen", 0.008, parent)
    label(name + "_title", title, (x - width * 0.4, y - 0.034, z + height * 0.27), min(width * 0.06, 0.035), "display", parent)
    for row in range(3):
        line_width = width * (0.62 - row * 0.11)
        box(name + "_trace", (x - width * 0.35 + line_width / 2, y - 0.036, z + height * 0.09 - row * height * 0.15),
            (line_width, 0.003, 0.006), "led" if row != 2 else "blue", 0, parent)
    for col in range(4):
        box(name + "_meter", (x + width * 0.10 + col * width * 0.062, y - 0.036, z - height * 0.24),
            (width * 0.04, 0.004, height * (0.12 + col * 0.04)), "teal", 0, parent)


def handrail(parent, name, a, b, material="gold"):
    cylinder(name, a, b, 0.023, material, parent)
    for end in (a, b):
        p = Vector(end)
        cylinder(name + "_standoff", p, p + Vector((0, 0.065, 0)), 0.018, "metal", parent)


def dimensions_local(item):
    x, y, z = item["size_m"]
    return (y, x, z) if abs(item.get("yaw_deg", 0)) == 90 else (x, y, z)


def equipment_group(item):
    return group(item["id"], item["center_m"], math.radians(item.get("yaw_deg", 0)),
                 object_id=item["id"], role=item["role"], material_id=item["material_id"],
                 physical_center_m=item["center_m"], physical_size_m=item["size_m"], cutaway=False)


def build_rack(item):
    parent = equipment_group(item)
    width, depth, height = dimensions_local(item)
    y = -depth / 2 + 0.27
    # Hollow rack chassis: deep cartridges remain inside the physical envelope.
    box("rack_backplate", (0, depth / 2 - 0.03, 0), (width, 0.06, height), "structure", 0.02, parent)
    for side in (-1, 1):
        box("rack_sidewall", (side * (width / 2 - 0.025), 0, 0), (0.05, depth, height), "structure", 0.015, parent)
        box("rack_endplate", (0, 0, side * (height / 2 - 0.025)), (width, depth, 0.05), "structure", 0.015, parent)
    for side in (-1, 1):
        box("rack_vertical_rail", (side * (width / 2 - 0.045), y, 0), (0.07, 0.065, height - 0.08), "metal", 0.01, parent)
        for z in (-0.98, 0.0, 0.98):
            screw("rack_mount", side * (width / 2 - 0.045), y - 0.045, z, parent)
    front_panel(parent, "rack_header", 0, y - 0.005, 1.10, width - 0.18, 0.20, "blue")
    names = {"power": "01 / POWER DISTRIBUTION", "avionics": "02 / AVIONICS & DATA", "atmosphere": "03 / ATMOSPHERE CONTROL"}
    label("rack_identifier", names[item["rack_kind"]], (-width * 0.39, y - 0.027, 1.075), 0.044, "white", parent)
    kind = item["rack_kind"]
    if kind == "power":
        front_panel(parent, "power_breaker_panel", 0, y, 0.56, width - 0.18, 0.78, "panel")
        screen(parent, "power_monitor", -0.24, y - 0.035, 0.70, 0.64, 0.30, "BUS A / ONLINE")
        for col in range(3):
            for row in range(3):
                x, z = 0.19 + col * 0.13, 0.39 + row * 0.19
                box("breaker_recess", (x, y - 0.034, z), (0.09, 0.02, 0.12), "dark", 0.008, parent)
                box("breaker_toggle", (x, y - 0.055, z), (0.035, 0.045, 0.06), "orange" if row == 0 else "blue", 0.006, parent)
        label("power_voltage", "28 V DC", (-0.54, y - 0.031, 0.27), 0.06, "structure", parent)
        for i in range(3):
            z = -0.08 - i * 0.31
            front_panel(parent, "battery_drawer", 0, y, z, width - 0.18, 0.27, "blue")
            handrail(parent, "drawer_handle", (-0.30, y - 0.10, z), (0.30, y - 0.10, z), "metal")
            cylinder("drawer_led", (0.49, y - 0.019, z), (0.49, y - 0.032, z), 0.018, "led", parent)
        grille(parent, "power_lower_intake", 0, y, -1.06, width - 0.22, 0.18, 6)
    elif kind == "avionics":
        screen(parent, "avionics_display", 0, y, 0.57, width - 0.18, 0.75, "IGNIS / EXPERIMENT TELEMETRY")
        for row in range(4):
            z = -0.08 - row * 0.25
            front_panel(parent, "compute_blade", 0, y, z, width - 0.18, 0.21, "panel")
            grille(parent, "compute_blade_grille", -0.12, y - 0.023, z, 0.70, 0.12, 4)
            for col in range(3):
                cylinder("compute_port", (0.32 + col * 0.09, y - 0.017, z), (0.32 + col * 0.09, y - 0.041, z), 0.023, "dark", parent)
                cylinder("compute_port_status", (0.32 + col * 0.09, y - 0.042, z), (0.32 + col * 0.09, y - 0.049, z), 0.008, "led", parent, 8)
        for i in range(3):
            cable("patch_cable", [(0.29 + i * 0.10, y - 0.05, -0.08), (0.40 + i * 0.10, y - 0.16, -0.25),
                                  (0.52 + i * 0.045, y - 0.10, -0.60), (0.30 + i * 0.10, y - 0.05, -0.83)], 0.008, "orange" if i == 0 else "teal", parent)
        grille(parent, "data_lower_intake", 0, y, -1.11, width - 0.2, 0.14, 5)
    else:
        screen(parent, "atmosphere_monitor", -0.25, y, 0.72, 0.65, 0.48, "O2 / FLOW CONTROL")
        for i in range(3):
            cylinder("flow_gauge", (0.27, y - 0.01, 0.81 - i * 0.18), (0.27, y - 0.05, 0.81 - i * 0.18), 0.073, "metal", parent, 24)
            cylinder("gauge_face", (0.27, y - 0.05, 0.81 - i * 0.18), (0.27, y - 0.057, 0.81 - i * 0.18), 0.059, "ceramic", parent, 24)
            box("gauge_needle", (0.27, y - 0.062, 0.83 - i * 0.18), (0.008, 0.005, 0.055), "structure", 0, parent, (0, 0.45, 0))
        front_panel(parent, "filter_background", 0, y, -0.35, width - 0.18, 1.31, "blue")
        for i in range(3):
            x = -0.39 + i * 0.39
            cylinder("filter_cartridge", (x, y - 0.12, -0.82), (x, y - 0.12, 0.20), 0.125, "panel", parent, 20)
            for z in (-0.76, 0.12):
                cylinder("filter_collar", (x, y - 0.12, z - 0.03), (x, y - 0.12, z + 0.03), 0.139, "metal", parent, 20)
            box("filter_label", (x, y - 0.25, -0.29), (0.13, 0.01, 0.21), "white", 0.004, parent)
        grille(parent, "atmosphere_base_intake", 0, y, -1.12, width - 0.2, 0.13, 4)
    for side in (-1, 1):
        handrail(parent, "rack_service_handle", (side * (width / 2 - 0.12), y - 0.085, -0.4), (side * (width / 2 - 0.12), y - 0.085, 0.1))


def build_console(item):
    parent = equipment_group(item)
    width, depth, height = dimensions_local(item)
    y = -depth / 2
    box("console_pedestal", (0, 0, 0), (width, depth, height), "blue", 0.055, parent)
    box("console_worktop", (0, -0.035, height / 2 - 0.015), (width + 0.04, depth + 0.03, 0.07), "panel", 0.025, parent)
    for i in range(2):
        front_panel(parent, "console_access_door", -width / 4 + i * width / 2, y - 0.02, -0.03, (width - 0.15) / 2, height - 0.25, "panel")
        handrail(parent, "console_door_handle", (-0.08 + i * 0.16, y - 0.10, -0.12), (-0.08 + i * 0.16, y - 0.10, 0.12), "structure")
    # Display pedestal is a visual detail above the calculation envelope.
    monitor = group("console_display_mount")
    monitor.parent = parent
    monitor.location = (0, depth * 0.15, height / 2 + 0.30)
    metadata(monitor, parent)
    cylinder("display_stem", (0, 0, -0.3), (0, 0, -0.13), 0.035, "structure", monitor)
    screen(monitor, "control_screen", 0, 0, 0, width * 0.70, 0.42, "ASTER / CABIN OVERVIEW")
    box("keyboard", (0, -depth * 0.2, height / 2 + 0.04), (width * 0.52, 0.20, 0.025), "structure", 0.015, parent)
    for row in range(3):
        for col in range(10):
            box("key", (-width * 0.23 + col * width * 0.046, -depth * 0.2 - 0.055 + row * 0.05, height / 2 + 0.056),
                (width * 0.035, 0.032, 0.01), "panel", 0.002, parent)


def build_life_support(item):
    parent = equipment_group(item)
    w, d, h = dimensions_local(item)
    face = -d / 2 + 0.32
    box("fluid_bay_back", (0, d / 2 - 0.03, 0), (w, 0.06, h), "structure", 0.02, parent)
    for side in (-1, 1):
        box("fluid_bay_side", (side * (w / 2 - 0.025), 0, 0), (0.05, d, h), "structure", 0.015, parent)
        box("fluid_bay_end", (0, 0, side * (h / 2 - 0.025)), (w, d, 0.05), "structure", 0.015, parent)
    front_panel(parent, "fluid_bay_face", 0, face, 0, w - 0.12, h - 0.12, "blue")
    for i in range(3):
        x = -0.45 + i * 0.45
        cylinder("pressure_vessel", (x, face - 0.14, -0.35), (x, face - 0.14, 0.30), 0.15, "panel", parent, 20)
        for z in (-0.30, 0.25):
            cylinder("vessel_restraint", (x, face - 0.14, z - 0.028), (x, face - 0.14, z + 0.028), 0.165, "gold", parent, 20)
        cylinder("vessel_valve", (x, face - 0.14, 0.3), (x, face - 0.14, 0.40), 0.03, "metal", parent)
        cylinder("valve_wheel", (x, face - 0.16, 0.40), (x, face - 0.10, 0.40), 0.065, "teal", parent)
    label("fluid_label", "FLUID MANAGEMENT / 03", (-w * 0.4, face - 0.045, 0.44), 0.049, "white", parent)
    cable("fluid_manifold", [(-0.5, face - 0.10, 0.46), (0, face - 0.16, 0.48), (0.5, face - 0.10, 0.46)], 0.025, "metal", parent)


def build_workbench(item):
    parent = equipment_group(item)
    w, d, h = dimensions_local(item)
    box("bench_cabinet", (0, 0, -0.04), (w - 0.08, d - 0.06, h - 0.08), "blue", 0.04, parent)
    box("bench_top", (0, 0, h / 2 - 0.025), (w, d, 0.07), "ceramic", 0.025, parent)
    for i in range(3):
        z = -0.27 + i * 0.25
        front_panel(parent, "bench_drawer", 0, -d / 2, z, w - 0.12, 0.22, "panel")
        handrail(parent, "bench_drawer_handle", (-0.25, -d / 2 - 0.075, z), (0.25, -d / 2 - 0.075, z), "structure")
    box("instrument_case", (-0.38, 0.10, h / 2 + 0.13), (0.52, 0.37, 0.24), "structure", 0.025, parent)
    screen(parent, "instrument_display", -0.38, -0.095, h / 2 + 0.15, 0.37, 0.16, "SAMPLE / 04")
    for i in range(3):
        cylinder("sample_tube", (0.18 + i * 0.12, 0.10, h / 2 + 0.04), (0.18 + i * 0.12, 0.10, h / 2 + 0.20), 0.037, "metal", parent)
        cylinder("sample_cap", (0.18 + i * 0.12, 0.10, h / 2 + 0.20), (0.18 + i * 0.12, 0.10, h / 2 + 0.23), 0.042, "teal", parent)
    box("sample_tray", (0.32, 0.10, h / 2 + 0.04), (0.48, 0.27, 0.04), "dark", 0.012, parent)


def build_locker(item):
    parent = equipment_group(item)
    w, d, h = dimensions_local(item)
    box("locker_shell", (0, 0, 0), (w, d, h), "structure", 0.035, parent)
    for row in range(3):
        for col in range(2):
            x = (col - 0.5) * (w / 2)
            z = -h / 2 + (row + 0.5) * (h / 3)
            front_panel(parent, "stowage_door", x, -d / 2 - 0.012, z, w / 2 - 0.035, h / 3 - 0.03, "panel")
            handrail(parent, "stowage_latch", (x + 0.17, -d / 2 - 0.09, z - 0.08), (x + 0.17, -d / 2 - 0.09, z + 0.08), "structure")
            label("stowage_id", f"STW-{row * 2 + col + 1:02d}", (x - 0.27, -d / 2 - 0.033, z + 0.25), 0.05, "structure", parent)


def build_experiment(item):
    parent = equipment_group(item)
    w, d, h = dimensions_local(item)
    box("experiment_plinth", (0, 0, 0), (w * 0.88, d * 0.85, h - 0.06), "structure", 0.055, parent)
    box("experiment_top", (0, 0, h / 2 - 0.03), (w, d, 0.06), "metal", 0.025, parent)
    for side in (-1, 1):
        box("experiment_edge_light", (side * (w / 2 - 0.035), 0, h / 2 + 0.006), (0.016, d - 0.10, 0.009), "led", 0.002, parent)
    front_panel(parent, "experiment_control", 0, -d * 0.43, -0.1, w * 0.78, 0.60, "blue")
    screen(parent, "experiment_readout", 0, -d * 0.43 - 0.025, 0.03, 0.52, 0.23, "IGNIS / TEST ARTICLE")
    label("experiment_name", "COMBUSTION PLATFORM", (-0.34, -d * 0.43 - 0.024, -0.25), 0.039, "white", parent)
    for side in (-1, 1):
        cylinder("sample_standoff", (side * 0.25, -0.25, h / 2), (side * 0.25, -0.25, h / 2 + 0.20), 0.016, "metal", parent)
        cylinder("sample_standoff", (side * 0.25, 0.25, h / 2), (side * 0.25, 0.25, h / 2 + 0.20), 0.016, "metal", parent)
    cylinder("probe_arm", (0.38, 0.42, h / 2), (0.38, 0.42, h / 2 + 0.60), 0.018, "metal", parent)
    cylinder("probe_crossbar", (0.38, 0.42, h / 2 + 0.60), (0.02, 0.42, h / 2 + 0.60), 0.015, "metal", parent)
    cylinder("probe_tip", (0.02, 0.42, h / 2 + 0.60), (0.02, 0.42, h / 2 + 0.40), 0.008, "gold", parent)
    cable("instrument_harness", [(0.40, 0.30, -0.3), (0.46, 0.5, -0.05), (0.43, 0.47, 0.5), (0.38, 0.42, 0.9)], 0.009, "orange", parent)


def build_fuel(item):
    parent = equipment_group(item)
    w, d, h = item["size_m"]
    box("replaceable_fuel_coupon", (0, 0, 0), item["size_m"], item["material_id"], 0.003, parent)
    # Material weave is geometry, not a photographic texture or claimed NASA sample.
    if item["material_id"] == "cellulose":
        for i in range(17):
            x = -w * 0.46 + i * w * 0.0575
            box("sample_weave", (x, 0, h / 2 + 0.002), (0.004, d * 0.93, 0.003), "gold", 0, parent)
    for x in (-w * 0.46, w * 0.46):
        for y in (-d * 0.46, d * 0.46):
            screw("sample_clamp", x, y, h / 2 + 0.001, parent, "top")


def build_cargo(item):
    parent = equipment_group(item)
    w, d, h = dimensions_local(item)
    box("cargo_shell", (0, 0, 0), (w, d, h), "blue", 0.065, parent)
    for side in (-1, 1):
        front_panel(parent, "cargo_recess", 0, side * (d / 2 + 0.005), 0, w * 0.80, h * 0.72, "panel", False)
        for x in (-w * 0.32, w * 0.32):
            box("cargo_rib", (x, side * (d / 2 + 0.025), 0), (0.065, 0.035, h * 0.88), "structure", 0.01, parent)
        for z in (-h * 0.30, h * 0.30):
            box("cargo_corner_guard", (side * (w / 2 - 0.07), 0, z), (0.12, d + 0.02, 0.10), "structure", 0.018, parent)
    for side in (-1, 1):
        box("cargo_tie_band", (side * w * 0.30, 0, h / 2 + 0.008), (0.07, d, 0.015), "gold", 0.005, parent)
        cylinder("cargo_handle", (side * w / 2, -0.15, 0.12), (side * w / 2, 0.15, 0.12), 0.025, "metal", parent)
    label("cargo_identifier", item["id"].replace("cargo_crate_", "CARGO / "), (-w * 0.33, -d / 2 - 0.030, 0.06), 0.06, "structure", parent)
    label("cargo_mass_note", "RESTRAIN BEFORE TEST", (-w * 0.33, -d / 2 - 0.030, -0.07), 0.032, "structure", parent)


def build_baffle(item):
    parent = equipment_group(item)
    w, d, h = item["size_m"]
    box("flow_baffle_panel", (0, 0, 0), (w, d, h), "panel", 0.025, parent)
    for y in (-d / 2 + 0.04, d / 2 - 0.04):
        box("baffle_end_frame", (0, y, 0), (w + 0.025, 0.08, h), "blue", 0.01, parent)
    for z in (-h / 2 + 0.04, 0, h / 2 - 0.04):
        box("baffle_stiffener", (0, 0, z), (w + 0.03, d, 0.07), "metal", 0.008, parent)
    label("baffle_label", "FLOW / BAFFLE", (w / 2 + 0.003, -0.60, 0.78), 0.085, "structure", parent, right=(0, 1, 0))


BUILDERS = {"rack": build_rack, "console": build_console, "life_support": build_life_support,
            "workbench": build_workbench, "locker": build_locker, "experiment": build_experiment,
            "fuel": build_fuel, "cargo": build_cargo, "baffle": build_baffle,
            "physical_only": lambda item: None,
            "soyuz_seat": lambda item: soyuz_geometry.build_seat(item, globals()),
            "soyuz_console": lambda item: soyuz_geometry.build_console(item, globals())}


def build_hatch():
    parent = group("aft_pressure_hatch", (4.24, 7.92, 1.37), object_id="wall_aft", role="decoration", material_id="aluminium", cutaway=False)
    # Chamfered octagonal door and stepped frame, not a rectangular decal.
    for name, width, height, depth, mat in [("hatch_outer_coaming", 1.68, 2.59, 0.17, "structure"),
                                          ("hatch_pressure_seal", 1.49, 2.41, 0.19, "rubber"),
                                          ("hatch_door", 1.38, 2.29, 0.20, "panel")]:
        corner = 0.23
        outline = [(-width / 2 + corner, -height / 2), (width / 2 - corner, -height / 2),
                   (width / 2, -height / 2 + corner), (width / 2, height / 2 - corner),
                   (width / 2 - corner, height / 2), (-width / 2 + corner, height / 2),
                   (-width / 2, height / 2 - corner), (-width / 2, -height / 2 + corner)]
        vertices = [(x, y, z) for y in (0.035, -depth) for x, z in outline]
        faces = [tuple(reversed(range(8))), tuple(range(8, 16))] + [(i, (i + 1) % 8, (i + 1) % 8 + 8, i + 8) for i in range(8)]
        object_mesh(name, vertices, faces, mat, parent=parent)
    cylinder("hatch_window_frame", (0, -0.20, 0.38), (0, -0.25, 0.38), 0.32, "metal", parent, 40)
    cylinder("hatch_window", (0, -0.25, 0.38), (0, -0.257, 0.38), 0.267, "screen", parent, 40)
    for i in range(10):
        angle = math.pi * 2 * i / 10
        screw("window_bolt", 0.29 * math.sin(angle), -0.26, 0.38 + 0.29 * math.cos(angle), parent)
    cylinder("hatch_wheel_hub", (0, -0.21, -0.35), (0, -0.33, -0.35), 0.09, "structure", parent, 24)
    for i in range(3):
        a = math.pi * 2 * i / 3
        cylinder("hatch_wheel_spoke", (0, -0.33, -0.35), (math.sin(a) * 0.27, -0.33, -0.35 + math.cos(a) * 0.27), 0.023, "gold", parent)
        cylinder("hatch_handle", (math.sin(a) * 0.27, -0.33, -0.35 + math.cos(a) * 0.27),
                 (math.sin(a) * 0.27, -0.41, -0.35 + math.cos(a) * 0.27), 0.033, "gold", parent)
    label("hatch_id", "HATCH / 02", (-0.40, -0.205, -0.83), 0.075, "structure", parent)
    for z in (-0.65, 0.65):
        box("hatch_hinge", (0.68, -0.13, z), (0.17, 0.17, 0.22), "metal", 0.025, parent)


def build_shell(scene):
    floor = group("floor_main", object_id="floor", role="wall", surface_kind="floor", material_id="aluminium", cutaway=False)
    box("floor_substructure", (2.8, 4, -0.09), (5.72, 8.12, 0.18), "structure", 0.045, floor)
    for i in range(8):
        for j in range(8):
            box("floor_tile", (0.35 + i * 0.7, 0.5 + j, 0.009), (0.68, 0.975, 0.018), "floor" if (i + j) % 3 else "blue", 0.009, floor)
            if i in (2, 5):
                for k in range(5):
                    box("floor_drain_slot", (0.35 + i * 0.7, 0.25 + j + k * 0.12, 0.020), (0.31, 0.015, 0.002), "dark", 0, floor)
    for x in (1.45, 4.12):
        box("aisle_guidance_line", (x, 4.0, 0.021), (0.028, 7.45, 0.004), "teal", 0, floor)
    # The front and right shell are intentionally cut away for legible web viewing.
    for name, loc, size in [("front_cut_edge", (2.8, -0.035, 0.11), (5.68, 0.07, 0.22)),
                            ("starboard_cut_edge", (5.635, 4.0, 0.11), (0.07, 8.0, 0.22))]:
        obj = box(name, loc, size, "metal", 0.012)
        metadata(obj, object_id="wall_entry" if name.startswith("front") else "wall_starboard", role="wall", surface_kind="cut_edge", cutaway=False)
    port = group("port_visible_bulkhead", object_id="wall_port", role="wall", material_id="aluminium", surface_kind="wall", cutaway=False)
    box("port_shell_backing", (-0.055, 4.0, 1.6), (0.11, 8, 3.2), "structure", 0.015, port)
    for j in range(8):
        for row in range(3):
            box("port_service_panel", (0.007, j + 0.5, 0.55 + row * 1.02), (0.035, 0.95, 0.97), "panel" if row < 2 else "blue", 0.015, port)
        box("port_frame_rib", (0.07, j + 0.04, 1.6), (0.14, 0.06, 3.08), "metal", 0.015, port)
    aft = group("aft_visible_bulkhead", object_id="wall_aft", role="wall", material_id="aluminium", surface_kind="wall", cutaway=False)
    box("aft_shell_backing", (2.8, 8.05, 1.6), (5.6, 0.10, 3.2), "structure", 0.015, aft)
    for i in range(7):
        for row in range(3):
            box("aft_service_panel", (0.4 + i * 0.8, 7.984, 0.55 + row * 1.02), (0.76, 0.035, 0.97), "panel" if row < 2 else "blue", 0.015, aft)
    box("port_base_rail", (0.13, 4, 0.12), (0.18, 8, 0.18), "structure", 0.02, port)
    box("port_crown_rail", (0.11, 4, 3.1), (0.20, 8, 0.16), "structure", 0.02, port)
    box("aft_crown_rail", (2.8, 7.9, 3.10), (5.6, 0.2, 0.16), "structure", 0.02, aft)
    build_hatch()
    label("project_title", "ASTER / IGNIS", (2.18, 7.94, 3.00), 0.13, "white", aft)
    label("compartment_identifier", "EXPERIMENTAL HABITAT  |  ORIGINAL GEOMETRY", (2.18, 7.94, 2.87), 0.040, "white", aft)
    # Cable trays and individually routed power/data bundles.
    utilities = group("overhead_utilities", role="decoration", object_id="utility_routes", material_id="aluminium", cutaway=True)
    for x in (0.28, 0.43, 0.58):
        cylinder("longitudinal_service_conduit", (x, 0.18, 2.93), (x, 7.78, 2.93), 0.042 if x == 0.28 else 0.023, "metal" if x != 0.58 else "gold", utilities)
    for y in (0.35, 1.55, 2.55, 3.55, 4.55, 5.55, 6.55, 7.65):
        box("cable_tray_bracket", (0.42, y, 2.89), (0.62, 0.07, 0.06), "structure", 0.01, utilities)
    for j in range(3):
        for lane in range(3):
            cable("rack_feed", [(0.58, 1.55 + j * 2, 2.93 + lane * 0.025),
                                 (0.70 + lane * 0.035, 1.55 + j * 2, 2.84),
                                 (0.74 + lane * 0.035, 1.55 + j * 2, 2.63)], 0.012, "orange" if lane == 0 else "teal", utilities)
    for y in (1.0, 3.0, 5.0, 7.0):
        box("wall_lamp_housing", (0.16, y, 2.77), (0.16, 0.76, 0.14), "dark", 0.02, utilities)
        box("wall_light_diffuser", (0.245, y, 2.74), (0.015, 0.66, 0.07), "lamp", 0.005, utilities)
    # Right-side open rails preserve depth cues without concealing the cabin.
    rail = group("starboard_cutaway_guard", role="decoration", object_id="cutaway_rail", material_id="aluminium", cutaway=True)
    for y in (0.35, 3.0, 5.1, 7.7):
        cylinder("cutaway_guard_post", (5.5, y, 0.15), (5.5, y, 0.55), 0.025, "metal", rail)
    cylinder("cutaway_guard_rail", (5.5, 0.35, 0.55), (5.5, 7.7, 0.55), 0.022, "metal", rail)


def build_vents(scene):
    for vent in scene["vents"]:
        x, y, z = vent["center_m"]
        # Face points into the visible room for the inlet and outlet alike.
        if vent["size_m"][1] == 0:
            width = vent["size_m"][0]
            yaw = math.pi if y == 0 else 0
            position = (x, y + 0.045 if y == 0 else y - 0.045, z)
        else:
            width = vent["size_m"][1]
            yaw = math.pi / 2 if x == 0 else -math.pi / 2
            position = (x + 0.045 if x == 0 else x - 0.045, y, z)
        height = vent["size_m"][2]
        parent = group(vent["id"], position, yaw, object_id=vent["id"], role=vent["role"], material_id="aluminium", cutaway=False,
                       nominal_speed_m_s=vent["nominal_speed_m_s"], physical_center_m=vent["center_m"], physical_normal=vent["normal"])
        box("vent_frame", (0, 0, 0), (width + 0.09, 0.09, height + 0.09), "structure", 0.025, parent)
        grille(parent, "vent", 0, -0.051, 0, width, height, 12, "metal")
        box("vent_status_strip", (0, -0.08, -height / 2 - 0.028), (width * 0.8, 0.009, 0.012), "teal" if vent["role"] == "inlet" else "orange", 0, parent)
        label("vent_id", ("SUPPLY" if vent["role"] == "inlet" else "RETURN") + " / " + vent["id"].split("_")[-1].upper(),
              (-width * 0.43, -0.08, height / 2 + 0.075), 0.052, "white", parent)
        if scene.get("visual_style") == "soyuz":
            rear = group("capsule_vent_reverse_face")
            rear.parent = parent
            rear.rotation_euler.z = math.pi
            metadata(rear, parent)
            grille(rear, "capsule_vent_reverse", 0, -0.051, 0, width, height, 10, "metal")
        # A front cutaway inlet remains an explicit suspended section element.
        if y == 0:
            rear = group("inlet_cutaway_reverse_face")
            rear.parent = parent
            rear.rotation_euler.z = math.pi
            metadata(rear, parent)
            grille(rear, "vent_reverse", 0, -0.051, 0, width, height, 12, "metal")
            label("vent_reverse_id", "SUPPLY / CUTAWAY SECTION", (-width * 0.43, -0.08, height / 2 + 0.075), 0.042, "white", rear)
            for dx in (-width / 2, width / 2):
                cylinder("vent_mounting_stem", (dx, 0.02, -height / 2), (dx, 0.02, -z + 0.11), 0.018, "metal", parent)


def build_sensors(scene):
    for i, sensor in enumerate(scene["sensors"]):
        parent = group(sensor["id"], sensor["position_m"], object_id=sensor["id"], role="sensor", material_id="steel", cutaway=False)
        box("sensor_body", (0, 0, 0), (0.06, 0.06, 0.10), "metal", 0.01, parent)
        box("sensor_led", (0, -0.032, 0.01), (0.023, 0.006, 0.025), "led", 0.003, parent)
        cylinder("sensor_probe", (0, 0, -0.05), (0, 0, -0.16), 0.007, "gold", parent)
        label("sensor_label", f"S{i + 1:02d}", (0.05, 0, 0.02), 0.045, "teal", parent)
    # Sensor markers are visual instrument locations, not fluid obstacles.


def build_proxies(scene):
    global CURRENT
    CURRENT = PROXY
    domain = box("physical_domain", [d / 2 for d in scene["bounds_m"]], scene["bounds_m"], "blue", 0)
    domain.display_type = "WIRE"
    domain["ignis_role"] = "domain"
    for item in scene["objects"]:
        parent = group("proxy_" + item["id"], object_id=item["id"], role=item["role"], material_id=item["material_id"])
        obj = box("physical_AABB_" + item["id"], item["center_m"], item["size_m"], "orange" if item["role"] == "fuel" else "teal", 0, parent)
        obj.display_type = "WIRE"
        obj.hide_render = True
        obj["source"] = "scenes/catalog.json"
        obj["ignis_role"] = item["role"]
        obj["ignis_id"] = item["id"]
        obj["ignis_name"] = item["name"]
        obj["material_id"] = item["material_id"]
    for vent in scene["vents"]:
        obj = group("physical_" + vent["id"], vent["center_m"])
        obj["ignis_role"] = vent["role"]
        obj["ignis_id"] = vent["id"]
        obj["ignis_size_m"] = vent["size_m"]
        obj["ignis_normal"] = vent["normal"]
        obj["nominal_speed_m_s"] = vent["nominal_speed_m_s"]
    for sensor in scene["sensors"]:
        obj = group("physical_" + sensor["id"], sensor["position_m"])
        obj["ignis_role"] = "sensor"
        obj["ignis_id"] = sensor["id"]
        obj["ignis_name"] = sensor["name"]
    obj = group("physical_ignition_source", scene["source_position_m"])
    obj["ignis_role"] = "source"
    obj["ignis_id"] = "ignition_source"
    PROXY.hide_render = True
    PROXY.hide_viewport = True
    CURRENT = FULL_HULL
    for item in scene["objects"]:
        if item["role"] == "wall":
            obj = box("complete_" + item["id"], item["center_m"], item["size_m"], "panel", 0.01)
            metadata(obj, object_id=item["id"], role="wall", material_id="aluminium")
    FULL_HULL.hide_render = True
    FULL_HULL.hide_viewport = True
    CURRENT = VISUAL


def camera(name, position, target, lens=46):
    data = bpy.data.cameras.new(name)
    data.lens = lens
    data.clip_start = 0.05
    data.clip_end = 200
    obj = bpy.data.objects.new(name, data)
    STUDIO.objects.link(obj)
    obj.location = position
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def area_light(name, position, target, energy, size, color=(1, 1, 1)):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    STUDIO.objects.link(obj)
    obj.location = position
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def setup_studio(args, scene):
    global CURRENT
    CURRENT = STUDIO
    box("studio_ground", (2.8, 4, -0.23), (200, 200, 0.10), "dark", 0)
    world = bpy.data.worlds.new("ASTER studio atmosphere")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = rgba("7e9bac")
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.28
    area_light("Key softbox", (4, -3, 10), (2.5, 4, 0), 1900, 7)
    area_light("Cabin fill", (7, 4, 7), (2, 4, 1), 1700, 6, (0.76, 0.89, 1.0))
    area_light("Warm rim", (-3, 6, 6), (2.5, 4, 1), 1700, 5, (1.0, 0.79, 0.56))
    area_light("Front equipment fill", (3, 0, 4), (0.5, 4, 1), 450, 3)
    overview = camera("CAM_01_Cutaway_overview", scene["presentation"]["physical_camera_m"], scene["presentation"]["camera_target_m"], 47)
    detail = camera("CAM_02_Experiment_and_racks", (5.10, 0.80, 3.80), (1.90, 4.20, 1.45), 31)
    top = camera("CAM_03_Plan", (2.8, 4, 12.8), (2.8, 4, 0), 40)
    if scene.get("visual_style") == "soyuz":
        overview.data.lens = 50
        detail.location = (1.50, 2.25, 2.20)
        detail.rotation_euler = (Vector((1.5, 0.30, 1.0)) - detail.location).to_track_quat("-Z", "Y").to_euler()
        detail.data.lens = 27
        top.location = (1.5, 1.5, 8)
        top.rotation_euler = (Vector((1.5, 1.5, 0)) - top.location).to_track_quat("-Z", "Y").to_euler()
    top.data.type = "ORTHO"
    top.data.ortho_scale = 4.0 if scene.get("visual_style") == "soyuz" else 9.7
    render = bpy.context.scene
    render.camera = overview
    render.render.engine = "CYCLES"
    render.cycles.samples = args.samples
    render.cycles.use_denoising = True
    render.cycles.max_bounces = 6
    render.cycles.diffuse_bounces = 3
    render.cycles.glossy_bounces = 3
    render.render.resolution_x = args.width
    render.render.resolution_y = round(args.width * 0.6875)
    render.render.resolution_percentage = 100
    render.render.image_settings.file_format = "PNG"
    render.render.image_settings.color_mode = "RGB"
    render.view_settings.view_transform = "AgX"
    for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
        try:
            render.view_settings.look = look
            break
        except TypeError:
            pass
    if args.gpu:
        preferences = bpy.context.preferences.addons["cycles"].preferences
        configured = False
        for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
            try:
                preferences.compute_device_type = backend
                preferences.get_devices()
                available = [d for d in preferences.devices if d.type != "CPU"]
                if available:
                    for device in preferences.devices:
                        device.use = device.type != "CPU"
                    render.cycles.device = "GPU"
                    configured = True
                    print("IGNIS_RENDER_DEVICE", backend, [d.name for d in available], flush=True)
                    break
            except (TypeError, RuntimeError):
                continue
        if not configured:
            raise RuntimeError("--gpu requested but no supported Cycles GPU found; remove --gpu to use CPU explicitly")
    CURRENT = VISUAL
    return {"overview": overview, "detail": detail, "plan": top}


def prepare_export():
    bpy.ops.object.select_all(action="DESELECT")
    convertibles = [o for o in VISUAL.all_objects if o.type in {"CURVE", "FONT"}]
    if convertibles:
        for obj in convertibles:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = convertibles[0]
        bpy.ops.object.convert(target="MESH")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in VISUAL.all_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = next(o for o in VISUAL.all_objects if o.type == "MESH")


def mesh_statistics():
    depsgraph = bpy.context.evaluated_depsgraph_get()
    vertices, triangles = 0, 0
    for obj in VISUAL.all_objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        vertices += len(mesh.vertices)
        triangles += len(mesh.loop_triangles)
        evaluated.to_mesh_clear()
    return {"visual_objects": len(VISUAL.all_objects), "vertices": vertices, "triangles": triangles}


def file_info(path):
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def build(scene, args):
    global VISUAL, PROXY, FULL_HULL, STUDIO, CURRENT
    started = time.monotonic()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    MATS.clear()
    VISUAL = collection("01_VISUAL_CUTAWAY")
    PROXY = collection("02_PHYSICAL_PROXY__enable_to_inspect")
    FULL_HULL = collection("03_COMPLETE_HULL__hidden_in_presentation")
    STUDIO = collection("04_STUDIO__excluded_from_GLB")
    CURRENT = VISUAL
    init_materials()
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0
    bpy.context.scene["scene_id"] = scene["id"]
    bpy.context.scene["coordinate_convention"] = "metres, Blender Z-up; glTF transforms to Y-up"
    bpy.context.scene["physical_catalog"] = json.dumps(scene, ensure_ascii=False)
    bpy.context.scene["ignis_defaults_json"] = json.dumps(scene["defaults"])
    bpy.context.scene["scientific_status"] = "Original synthetic geometry; visual detail is not a resolved CFD mesh"
    if scene.get("visual_style") == "soyuz":
        soyuz_geometry.build_shell(scene, globals())
    else:
        build_shell(scene)
    for item in scene["objects"]:
        if item["role"] != "wall":
            BUILDERS[item["visual_type"]](item)
    build_vents(scene)
    build_sensors(scene)
    build_proxies(scene)
    cameras = setup_studio(args, scene)
    args.output.mkdir(parents=True, exist_ok=True)
    blend_path = args.output / f"{scene['id']}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    # Save the editable file BEFORE font/curve conversion for glTF export.
    prepare_export()
    glb_path = args.output / f"{scene['id']}.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb_path), export_format="GLB", use_selection=True,
                              export_apply=True, export_extras=True, export_yup=True,
                              export_cameras=False, export_lights=False, export_animations=False,
                              export_materials="EXPORT")
    stats = mesh_statistics()
    rendered = []
    if args.render:
        for view in args.views.split(","):
            if view not in cameras:
                raise ValueError(f"Unknown view {view}; use overview,detail,plan")
            bpy.context.scene.camera = cameras[view]
            path = args.output / f"{scene['id']}-{view}.png"
            bpy.context.scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            rendered.append(file_info(path))
    manifest = {
        "schema_version": 1,
        "scene_id": scene["id"], "blender_version": bpy.app.version_string,
        "catalog_sha256": hashlib.sha256(args.catalog.read_bytes()).hexdigest(),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "generator_sources": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in [Path(__file__), Path(__file__).with_name("soyuz_geometry.py"),
                                           Path(__file__).with_name("scene_catalog.py")]},
        "generated_elapsed_s": round(time.monotonic() - started, 2),
        "geometry": stats,
        "coordinates": {"physical": "Z-up, metres", "glb": "Y-up, metres", "physical_to_glb": "[x,z,-y]"},
        "artifacts": [file_info(blend_path), file_info(glb_path), *rendered],
        "presentation": {"cutaway": True, "source_geometry": "authored, not NASA CAD", "render_engine": "Cycles", "render_samples": args.samples},
        "verification": {"render_inspected": False, "note": "Rendering alone is not visual acceptance. Inspect overview and detail after generation."},
    }
    (args.output / f"{scene['id']}.manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("IGNIS_SCENE_COMPLETE", json.dumps({"id": scene["id"], **stats, "glb_bytes": glb_path.stat().st_size, "elapsed_s": manifest["generated_elapsed_s"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=("habitat", "cargo", "crossflow", "soyuz", "all"), default="habitat")
    parser.add_argument("--catalog", type=Path, default=ROOT / "scenes" / "catalog.json")
    parser.add_argument("--output", type=Path, default=ROOT / "scenes" / "generated")
    parser.add_argument("--render", action="store_true", help="Opt in to rendering on the Windows compute workstation")
    parser.add_argument("--gpu", action="store_true", help="Use an available Cycles GPU; explicit failure if none exists")
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--views", default="overview,detail", help="Comma-separated overview,detail,plan")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if args.width < 1600 or args.samples < 1:
        parser.error("Acceptance renders require width >=1600 and samples >=1")
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    if catalog["schema_version"] != 1:
        parser.error("Unsupported catalog schema")
    for scene in catalog["scenes"]:
        if args.scene in ("all", scene["id"]):
            build(scene, args)


if __name__ == "__main__":
    main()
