"""Original capsule geometry inspired by Soyuz; not flight CAD or measured data.

Geometry helpers are supplied by build_scene.py so this module does not reset
Blender state or export files by itself.
"""

import math


def build_shell(scene, api):
    box, cylinder, cable, label = (api[n] for n in ("box", "cylinder", "cable", "label"))
    group, mesh = api["group"], api["object_mesh"]
    parent = group("soyuz_capsule_shell", object_id="capsule_shell", role="decoration", material_id="aluminium", cutaway=False)
    cx, cy = 1.5, 1.5
    rings = [(0.03, 1.34), (0.18, 1.46), (0.55, 1.48), (1.20, 1.40), (1.80, 1.24), (2.30, 0.97), (2.53, 0.72)]
    # Rear/port half of the curved pressure shell is retained in the cutaway.
    segments = 40
    angles = [math.radians(45 + 180 * i / segments) for i in range(segments + 1)]
    for skin, inset, mat in [("exterior_pressure_shell", 0, "ceramic"), ("interior_liner", 0.065, "panel")]:
        verts = [(cx + (r - inset) * math.cos(a), cy + (r - inset) * math.sin(a), z)
                 for z, r in rings for a in angles]
        faces = []
        for row in range(len(rings) - 1):
            for i in range(segments):
                a = row * (segments + 1) + i
                quad = (a, a + 1, a + segments + 2, a + segments + 1)
                faces.append(quad if inset == 0 else tuple(reversed(quad)))
        obj = mesh(skin, verts, faces, mat, parent=parent)
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
    for angle in (angles[0], angles[-1]):
        cable("pressure_shell_cut_edge", [(cx + r * math.cos(angle), cy + r * math.sin(angle), z) for z, r in rings], 0.035, "metal", parent)
    for z, radius in (rings[1], rings[3], rings[5], rings[-1]):
        cable("capsule_circumferential_frame", [(cx + (radius - 0.045) * math.cos(a), cy + (radius - 0.045) * math.sin(a), z) for a in angles], 0.024, "metal", parent)
    # Rounded heat-shield base and internal equipment deck.
    cylinder("heatshield_rim", (cx, cy, -0.10), (cx, cy, 0.07), 1.47, "structure", parent, 96)
    cylinder("equipment_deck", (cx, cy, 0.07), (cx, cy, 0.13), 1.34, "floor", parent, 96)
    for x in (0.54, 1.34, 2.14):
        box("seat_deck_rail", (x, 1.47, 0.16), (0.055, 1.65, 0.065), "metal", 0.012, parent)
        box("seat_deck_rail", (x + 0.30, 1.47, 0.16), (0.055, 1.65, 0.065), "metal", 0.012, parent)
    # Segmented fabric pads inside the curved shell, each with visible seams.
    for index, angle in enumerate([math.radians(a) for a in (65, 90, 115, 140, 165, 190)]):
        for row, (z, radius) in enumerate([(0.68, 1.405), (1.32, 1.30), (1.93, 1.07)]):
            if row == 2 and index in (0, 1, 4, 5):
                continue  # leave the optical portholes clear of fabric liners
            tangent = (-math.sin(angle), math.cos(angle), 0)
            position = (cx + radius * math.cos(angle), cy + radius * math.sin(angle), z)
            pad = box("quilted_liner_panel", position, (0.37, 0.055, 0.48), "ceramic" if row != 1 else "blue", 0.035, parent)
            pad.rotation_euler.z = angle + math.pi / 2
            if row == 0:
                label("liner_service_id", f"P-{index + 1:02d}", (position[0] - math.cos(angle) * 0.035, position[1] - math.sin(angle) * 0.035, z),
                      0.035, "structure", parent, right=tangent)
    # Two portholes mounted on retained shell sections.
    for number, degrees in enumerate((72, 172), 1):
        angle = math.radians(degrees)
        inward = (-math.cos(angle), -math.sin(angle), 0)
        center = (cx + 1.12 * math.cos(angle), cy + 1.12 * math.sin(angle), 1.88)
        outside = (center[0] - inward[0] * 0.08, center[1] - inward[1] * 0.08, center[2])
        inside = (center[0] + inward[0] * 0.05, center[1] + inward[1] * 0.05, center[2])
        cylinder("porthole_outer_frame", outside, inside, 0.245, "metal", parent, 40)
        glass_front = (inside[0] + inward[0] * 0.012, inside[1] + inward[1] * 0.012, inside[2])
        cylinder("porthole_optical_surface", inside, glass_front, 0.188, "screen", parent, 40)
        tangent = (-math.sin(angle), math.cos(angle), 0)
        for i in range(10):
            t = i * 2 * math.pi / 10
            pt = (inside[0] + tangent[0] * math.cos(t) * 0.217,
                  inside[1] + tangent[1] * math.cos(t) * 0.217, inside[2] + math.sin(t) * 0.217)
            cylinder("porthole_fastener", pt, (pt[0] + inward[0] * 0.012, pt[1] + inward[1] * 0.012, pt[2]), 0.013, "structure", parent, 8)
    # Crown hatch ring, partial to preserve interior visibility.
    for r, mat in ((0.72, "structure"), (0.65, "metal")):
        cable("crown_access_ring", [(cx + r * math.cos(a), cy + r * math.sin(a), 2.55) for a in angles], 0.045 if r == 0.72 else 0.022, mat, parent)
    for a in angles[::8]:
        cylinder("crown_latch", (cx + 0.65 * math.cos(a), cy + 0.65 * math.sin(a), 2.47),
                 (cx + 0.65 * math.cos(a), cy + 0.65 * math.sin(a), 2.62), 0.025, "gold", parent)
    # Real individual hoses and cable bundles follow the capsule circumference.
    for lane in range(4):
        z = 0.39 + lane * 0.055
        radius = 1.36
        cable("capsule_service_harness", [(cx + radius * math.cos(a), cy + radius * math.sin(a), z) for a in angles],
              0.014 if lane != 0 else 0.024, "orange" if lane == 0 else "metal" if lane == 1 else "teal", parent)
    for a in (math.radians(90), math.radians(145), math.radians(195)):
        points = [(cx + 1.35 * math.cos(a), cy + 1.35 * math.sin(a), 0.45),
                  (cx + 1.31 * math.cos(a), cy + 1.31 * math.sin(a), 1.1),
                  (cx + 1.12 * math.cos(a), cy + 1.12 * math.sin(a), 1.85),
                  (cx + 0.83 * math.cos(a), cy + 0.83 * math.sin(a), 2.38)]
        cable("capsule_vertical_conduit", points, 0.024, "gold", parent)
    # Original designation; no agency seal or claim of flight hardware provenance.
    box("capsule_identity_plate", (1.5, 2.65, 1.45), (0.98, 0.04, 0.26), "structure", 0.02, parent)
    label("capsule_identity", "SOYUZ / DESCENT STUDY", (1.06, 2.626, 1.48), 0.058, "white", parent)
    label("capsule_identity_secondary", "IGNIS  |  ORIGINAL INTERPRETATION", (1.06, 2.626, 1.38), 0.027, "white", parent)
    cylinder("coupon_support_column", (1.5, 0.44, 1.18), (1.5, 0.44, 1.44), 0.018, "metal", parent)
    cylinder("coupon_support_arm", (1.5, 0.44, 1.44), (1.5, 0.75, 1.44), 0.018, "metal", parent)
    box("coupon_instrument_tray", (1.5, 0.75, 1.465), (0.24, 0.24, 0.018), "metal", 0.008, parent)
    for x in (0.82, 2.18):
        box("capsule_lamp", (x, 2.44, 1.70), (0.25, 0.08, 0.10), "dark", 0.025, parent)
        box("capsule_lamp_diffuser", (x, 2.392, 1.70), (0.18, 0.01, 0.055), "lamp", 0.01, parent)


def build_seat(item, api):
    box, cylinder, cable, label = (api[n] for n in ("box", "cylinder", "cable", "label"))
    parent = api["equipment_group"](item)
    shell = "ceramic"
    box("seat_energy_absorber", (0, 0, -0.45), (0.40, 0.65, 0.13), "structure", 0.035, parent)
    for x in (-0.19, 0.19):
        cylinder("seat_damper", (x, 0.17, -0.42), (x, 0.20, -0.18), 0.035, "metal", parent)
    box("seat_moulded_pan", (0, -0.18, -0.17), (0.59, 0.64, 0.15), shell, 0.055, parent, (math.radians(-8), 0, 0))
    box("seat_moulded_back", (0, 0.24, 0.15), (0.57, 0.15, 0.80), shell, 0.055, parent, (math.radians(-25), 0, 0))
    box("seat_pan_cushion", (0, -0.19, -0.09), (0.45, 0.50, 0.10), "orange", 0.045, parent, (math.radians(-8), 0, 0))
    box("seat_back_cushion", (0, 0.16, 0.15), (0.44, 0.10, 0.63), "orange", 0.04, parent, (math.radians(-25), 0, 0))
    box("seat_headrest", (0, 0.39, 0.45), (0.35, 0.16, 0.19), "rubber", 0.04, parent, (math.radians(-15), 0, 0))
    for x in (-0.25, 0.25):
        cable("seat_contoured_frame", [(x, -0.48, -0.26), (x, -0.21, -0.1), (x, 0.07, 0.02), (x, 0.40, 0.48)], 0.022, "metal", parent)
        box("seat_side_bolster", (x, -0.07, 0.03), (0.07, 0.35, 0.12), "rubber", 0.025, parent)
        cylinder("seat_restraint_anchor", (x, 0.2, 0.1), (x, 0.21, 0.1), 0.04, "metal", parent)
    for x in (-0.13, 0.13):
        box("foot_support", (x, -0.46, -0.34), (0.22, 0.17, 0.10), "structure", 0.025, parent)
        # Straps follow the reclined cushion as a small real ribbon mesh.
        points = [(x, 0.23, 0.39), (x * 0.7, 0.06, 0.08), (x * 0.3, -0.25, -0.015)]
        verts = [(px + sign * 0.022, py - 0.008, pz) for px, py, pz in points for sign in (-1, 1)]
        api["object_mesh"]("shoulder_harness_webbing", verts, [(0, 1, 3, 2), (2, 3, 5, 4)], "gold", parent=parent)
    box("harness_buckle", (0, -0.27, -0.015), (0.09, 0.07, 0.055), "metal", 0.012, parent)
    box("harness_release", (0, -0.31, -0.005), (0.045, 0.015, 0.025), "orange", 0.004, parent)
    label("crew_seat_id", f"CREW / {item['seat_index'] + 1:02d}", (-0.20, -0.51, -0.20), 0.042, "white", parent)


def build_console(item, api):
    box, cylinder, label = (api[n] for n in ("box", "cylinder", "label"))
    parent = api["equipment_group"](item)
    # Front of console points toward the crew (+Y), unlike Aster racks.
    parent.rotation_euler.z = math.pi
    parent.scale.z = item["size_m"][2] / 0.8
    box("capsule_instrument_housing", (0, 0, 0), (1.80, 0.30, 0.80), "blue", 0.055, parent)
    api["front_panel"](parent, "capsule_instrument_face", 0, -0.167, 0, 1.72, 0.72, "panel")
    for side in (-1, 1):
        api["screen"](parent, "capsule_multifunction_display", side * 0.44, -0.190, 0.12, 0.60, 0.34,
                      "CABIN / SYS" if side == -1 else "FLIGHT / VIEW")
        for col in range(4):
            x = side * 0.44 - 0.18 + col * 0.12
            cylinder("capsule_toggle_base", (x, -0.20, -0.19), (x, -0.23, -0.19), 0.027, "structure", parent)
            cylinder("capsule_toggle", (x, -0.23, -0.19), (x, -0.27, -0.16), 0.009, "metal", parent)
        for col in range(3):
            box("capsule_annunciator", (side * 0.44 - 0.13 + col * 0.13, -0.205, 0.33), (0.07, 0.012, 0.025), "led" if col != 2 else "amber", 0.004, parent)
    for z in (-0.18, 0.04, 0.26):
        cylinder("capsule_gauge_rim", (0, -0.20, z), (0, -0.245, z), 0.078, "metal", parent, 24)
        cylinder("capsule_gauge_face", (0, -0.245, z), (0, -0.252, z), 0.063, "screen", parent, 24)
        box("capsule_gauge_needle", (0, -0.257, z + 0.02), (0.008, 0.005, 0.06), "display", 0, parent, (0, 0.6, 0))
    label("capsule_panel_legend", "SOYUZ / INSTRUMENT STUDY", (-0.68, -0.205, -0.32), 0.05, "structure", parent)
    # Second face keeps the forward cutaway informative from outside.
    label("capsule_panel_back", "INSTRUMENT BAY", (0.62, 0.156, 0.10), 0.07, "white", parent, right=(-1, 0, 0))
    for i in range(5):
        box("console_back_cooling_rib", (-0.6 + i * 0.3, 0.16, -0.07), (0.12, 0.035, 0.33), "metal", 0.008, parent)
