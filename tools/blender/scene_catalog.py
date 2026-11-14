"""Canonical, dependency-free scene descriptions for IGNIS.

Run this with Python (not Blender) to regenerate scenes/catalog.json. The Blender
builder consumes that same file, so visual geometry and physical proxies retain
the same semantic object IDs. All positions are SI, Blender Z-up.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

BOUNDS = [5.6, 8.0, 3.2]


def add_incident_annotations(scene):
    """Explicit study assumptions kept separate from the original FDS pilot."""
    electrical = {"rack_power", "rack_avionics", "rack_atmosphere", "console_control", "life_support"}
    critical = {"rack_power", "rack_atmosphere", "life_support", "soyuz_console"}
    components, surfaces = [], {}
    for obj in scene["objects"]:
        if obj["id"] in electrical or obj.get("visual_type") in {"soyuz_seat", "soyuz_console", "cargo"}:
            surfaces[obj["id"]] = {"material_id": "pmma", "thickness_m": 0.002,
                "provenance": "Revêtement combustible hypothétique de démonstration ; aucun matériau de vol qualifié."}
        if obj["id"] not in electrical and obj["id"] != "soyuz_console":
            continue
        offsets = [-0.55, 0.55] if obj["id"] == "soyuz_console" else [0]
        for index, offset in enumerate(offsets):
            position = list(obj["center_m"])
            position[0] += offset
            position[2] += obj["size_m"][2] / 2
            suffix = f"-{index + 1}" if len(offsets) > 1 else ""
            components.append({"id": f"electrical-{obj['id']}{suffix}", "name": obj["name"] +
                (" · circuit gauche" if index == 0 else " · circuit droit") if len(offsets) > 1 else obj["name"],
                "object_id": obj["id"], "position_m": position, "face": 3,
                "kind": "electrical_equipment", "critical": obj["id"] in critical,
                "provenance": "Point d'incident hypothétique attaché au proxy de l'équipement ; source locale sur la face supérieure."})
    scene["incident_annotations"] = {"version": 1, "components": components,
        "surface_materials": surfaces, "critical_object_ids": sorted(critical & {o["id"] for o in scene["objects"]}),
        "passage_sensor_ids": ["sensor_forward"] if scene["id"] != "soyuz" else [],
        "provenance": "Hypothèses d'étude distinctes du pilote FDS initial ; les couleurs Blender ne définissent pas les propriétés physiques."}


def item(object_id, name, role, material, center, size, **extra):
    return {
        "id": object_id,
        "name": name,
        "role": role,
        "material_id": material,
        "center_m": center,
        "size_m": size,
        **extra,
    }


def walls(bounds=BOUNDS):
    # Physical wall objects are descriptive domain boundaries, not interior OBST.
    # Their thickness extends out of the fluid domain. The backend owns wall/VENT
    # boundary treatment; importing these AABBs as obstacles would block vents.
    x, y, z = bounds
    return [
        item("floor", "Plancher technique", "wall", "aluminium", [x / 2, y / 2, -0.04], [x, y, 0.08], surface_kind="floor", boundary="z_min"),
        item("ceiling", "Plafond technique", "wall", "aluminium", [x / 2, y / 2, z + 0.04], [x, y, 0.08], surface_kind="ceiling", boundary="z_max"),
        item("wall_port", "Paroi bâbord", "wall", "aluminium", [-0.04, y / 2, z / 2], [0.08, y, z], boundary="x_min"),
        item("wall_starboard", "Paroi tribord", "wall", "aluminium", [x + 0.04, y / 2, z / 2], [0.08, y, z], boundary="x_max"),
        item("wall_entry", "Paroi d'accès", "wall", "aluminium", [x / 2, -0.04, z / 2], [x, 0.08, z], boundary="y_min"),
        item("wall_aft", "Cloison arrière", "wall", "aluminium", [x / 2, y + 0.04, z / 2], [x, 0.08, z], boundary="y_max"),
    ]


def fixed_equipment():
    return [
        item("rack_power", "Rack · distribution électrique", "obstacle", "aluminium", [0.58, 1.55, 1.375], [0.94, 1.5, 2.55], visual_type="rack", yaw_deg=90, rack_kind="power"),
        item("rack_avionics", "Rack · acquisition et calcul", "obstacle", "aluminium", [0.58, 3.55, 1.375], [0.94, 1.5, 2.55], visual_type="rack", yaw_deg=90, rack_kind="avionics"),
        item("rack_atmosphere", "Rack · contrôle atmosphère", "obstacle", "aluminium", [0.58, 5.55, 1.375], [0.94, 1.5, 2.55], visual_type="rack", yaw_deg=90, rack_kind="atmosphere"),
        item("console_control", "Console · commande et télémétrie", "obstacle", "aluminium", [5.03, 2.1, 0.65], [0.9, 1.55, 1.1], visual_type="console", yaw_deg=-90),
        item("life_support", "Baie · fluides et filtration", "obstacle", "steel", [5.03, 4.2, 0.65], [0.9, 1.6, 1.1], visual_type="life_support", yaw_deg=-90),
        item("workbench", "Paillasse d'analyse", "obstacle", "aluminium", [4.82, 6.35, 0.55], [1.2, 1.6, 0.95], visual_type="workbench", yaw_deg=-90),
        item("aft_locker", "Armoire arrière", "obstacle", "aluminium", [1.05, 7.65, 1.35], [1.5, 0.5, 2.6], visual_type="locker", yaw_deg=0),
        item("experiment_base", "Socle instrumenté", "obstacle", "steel", [2.65, 3.55, 0.60], [0.95, 1.15, 1.05], visual_type="experiment", yaw_deg=0),
        item("fuel_sample", "Échantillon combustible", "fuel", "cellulose", [2.65, 3.55, 1.35], [0.60, 0.60, 0.05], visual_type="fuel", yaw_deg=0),
    ]


def vent(vent_id, role, center, size, normal, speed=0.2):
    return {"id": vent_id, "role": role, "center_m": center, "size_m": size, "normal": normal, "nominal_speed_m_s": speed}


def standard_vents():
    # Normals point from the inlet into the domain and from domain to outlet.
    return [
        vent("inlet_forward", "inlet", [2.8, 0, 1.6], [1.2, 0, 0.8], [0, 1, 0]),
        vent("outlet_aft", "outlet", [2.8, 8, 2.5], [1.2, 0, 0.8], [0, 1, 0]),
    ]


def sensors():
    return [
        {"id": "sensor_near", "name": "S01 · proximité de la source", "position_m": [2.65, 4.35, 1.6]},
        {"id": "sensor_aft", "name": "S02 · compartiment arrière", "position_m": [3.2, 6.7, 2.4]},
        {"id": "sensor_forward", "name": "S03 · accès", "position_m": [2.8, 0.8, 1.5]},
        {"id": "sensor_crown", "name": "S04 · haut du volume", "position_m": [2.65, 3.55, 2.9]},
    ]


def build_catalog():
    materials = [
        {"id": "cellulose", "name": "Cellulose — référence générique", "description": "Échantillon de référence. Les paramètres de combustion doivent être explicitement calibrés ; la couleur du modèle ne détermine aucune propriété thermique.", "color": "#bc9066", "provenance": {"kind": "generic_material", "nasa_calibrated": False}},
        {"id": "pmma", "name": "PMMA — référence générique", "description": "Polymère de référence ; aucune équivalence implicite à un matériau de vol.", "color": "#8bbdc5", "provenance": {"kind": "generic_material", "nasa_calibrated": False}},
        {"id": "aluminium", "name": "Aluminium", "description": "Structure et boîtiers. La bibliothèque thermique du backend porte les paramètres physiques.", "color": "#a8bec5", "provenance": {"kind": "generic_material"}},
        {"id": "steel", "name": "Acier", "description": "Supports, banc expérimental et interfaces mécaniques.", "color": "#586c7b", "provenance": {"kind": "generic_material"}},
        {"id": "glass", "name": "Verre", "description": "Éléments graphiques transparents ; rôle physique seulement si explicitement affecté à un proxy.", "color": "#a2cbd4", "provenance": {"kind": "generic_material"}},
        {"id": "insulation", "name": "Isolation — à caractériser", "description": "Habillage technique générique ; ne constitue pas un matériau certifié ni une propriété de combustion mesurée.", "color": "#d3d4bc", "provenance": {"kind": "generic_material", "nasa_calibrated": False}},
    ]
    common = {
        "bounds_m": BOUNDS,
        "coordinate_system": "right_handed_z_up",
        "units": "m",
        "sensors": sensors(),
        "source_position_m": [2.65, 3.55, 1.50],
        "defaults": {
            "source_model": "prescribed_source", "gravity_g": 0.0001,
            "airflow_m_s": 0.2, "oxygen_percent": 21,
            "material_id": "cellulose", "ignition_power_w": 500,
            "ignition_duration_s": 15, "duration_s": 60, "seed": 42,
        },
        "provenance": {
            "kind": "authored_synthetic_environment",
            "author": "IGNIS / Valley",
            "title": "Aster — compartiment expérimental original",
            "is_nasa_geometry": False,
            "scientific_status": "Uncalibrated authored geometry. No certified spacecraft reconstruction.",
            "visual_detail_policy": "Racks and equipment use AABB envelopes for calculation. Small fasteners, cables and handrails are decoration; not independently resolved.",
            "boundary_policy": "role=wall describes domain boundaries. Exclude wall AABBs from interior OBST; apply boundary conditions and vents in the solver.",
            "presentation_policy": "GLB uses a cutaway shell. The complete fluid domain is defined by bounds_m, never by the visible shell alone.",
        },
        "presentation": {
            "name": "ASTER / IGNIS EXPERIMENTAL HABITAT",
            "blender_file": "{id}.blend", "preview_image": "{id}-overview.png",
            "physical_camera_m": [10.9, -10.5, 9.1],
            "camera_target_m": [2.65, 4, 1.0],
            "cutaway": True,
        },
    }
    definitions = [
        ("habitat", "Aster · habitat instrumenté", "Compartiment de 5,6 × 8 × 3,2 m avec racks d'avionique, contrôle atmosphère, paillasse et banc de combustion central.", fixed_equipment(), standard_vents()),
        ("cargo", "Aster · configuration cargo", "Le compartiment reçoit trois conteneurs et un panneau PMMA. L'encombrement modifie les trajets de ventilation et les zones de recirculation possibles.", fixed_equipment() + [
            item("cargo_crate_01", "Conteneur cargo A", "obstacle", "aluminium", [3.50, 5.05, 0.65], [1.0, 1.1, 1.15], visual_type="cargo"),
            item("cargo_crate_02", "Conteneur cargo B", "obstacle", "aluminium", [2.30, 6.35, 0.55], [1.2, 1.0, 0.95], visual_type="cargo"),
            item("cargo_crate_03", "Conteneur cargo C", "obstacle", "aluminium", [3.80, 1.40, 0.48], [1.05, 0.9, 0.8], visual_type="cargo"),
        ], standard_vents()),
        ("crossflow", "Aster · ventilation transversale", "Même enveloppe et équipements avec soufflage depuis bâbord et extraction à tribord ; déflecteur central pour explorer les effets de la disposition.", fixed_equipment() + [
            item("flow_baffle", "Déflecteur instrumenté", "obstacle", "aluminium", [3.65, 4.6, 1.25], [0.12, 1.65, 2.2], visual_type="baffle"),
        ], [
            vent("inlet_port", "inlet", [0, 6.7, 1.8], [0, 0.8, 0.8], [1, 0, 0]),
            vent("outlet_starboard", "outlet", [5.6, 1.0, 1.8], [0, 0.8, 0.8], [1, 0, 0]),
        ]),
        ("soyuz", "Soyouz · capsule en coupe", "Capsule originale inspirée du module de descente Soyouz : coque arrondie, trois sièges inclinés, harnais, tableau de bord et hublots. Géométrie artistique et proxy de calcul approximatif ; aucun plan de vol officiel.", [
            item("soyuz_seat_left", "Siège gauche · coque et harnais", "obstacle", "aluminium", [0.70, 1.50, 0.70], [0.60, 1.10, 1.10], visual_type="soyuz_seat", seat_index=0),
            item("soyuz_seat_center", "Siège central · coque et harnais", "obstacle", "aluminium", [1.50, 1.50, 0.70], [0.60, 1.10, 1.10], visual_type="soyuz_seat", seat_index=1),
            item("soyuz_seat_right", "Siège droit · coque et harnais", "obstacle", "aluminium", [2.30, 1.50, 0.70], [0.60, 1.10, 1.10], visual_type="soyuz_seat", seat_index=2),
            item("soyuz_console", "Tableau de bord de capsule", "obstacle", "aluminium", [1.50, 0.30, 1.05], [1.80, 0.30, 0.50], visual_type="soyuz_console"),
            item("fuel_sample", "Coupon de matériau instrumenté", "fuel", "cellulose", [1.50, 0.75, 1.50], [0.20, 0.20, 0.05], visual_type="fuel"),
            *[item(f"capsule_corner_{i}", "Exclusion d'angle · coque approchée", "obstacle", "aluminium", [x, y, 1.3], [0.6, 0.6, 2.6], visual_type="physical_only", proxy_kind="coarse_capsule_shell")
              for i, (x, y) in enumerate([(0.3, 0.3), (2.7, 0.3), (0.3, 2.7), (2.7, 2.7)])]],
        [vent("inlet_port", "inlet", [0, 1.5, 0.8], [0, 0.4, 0.4], [1, 0, 0]),
         vent("outlet_starboard", "outlet", [3, 1.5, 0.8], [0, 0.4, 0.4], [1, 0, 0])]),
    ]
    scenes = []
    for scene_id, name, description, equipment, vents in definitions:
        scene = copy.deepcopy(common)
        scene.update({"id": scene_id, "name": name, "description": description,
                      "asset_url": f"/assets/scenes/{scene_id}.glb", "preview_url": f"/assets/scenes/{scene_id}-overview.png", "objects": walls() + equipment,
                      "vents": vents})
        if scene_id == "cargo":
            scene["defaults"]["material_id"] = "pmma"
            next(o for o in scene["objects"] if o["id"] == "fuel_sample")["material_id"] = "pmma"
        if scene_id == "soyuz":
            scene["bounds_m"] = [3.0, 3.0, 2.6]
            scene["objects"] = walls(scene["bounds_m"]) + equipment
            scene["visual_style"] = "soyuz"
            scene["source_position_m"] = [1.5, 0.75, 1.7]
            scene["sensors"] = [
                {"id": "sensor_near", "name": "S01 · tableau de bord", "position_m": [1.5, 0.75, 2.0]},
                {"id": "sensor_crew", "name": "S02 · volume équipage", "position_m": [1.5, 1.75, 1.6]},
                {"id": "sensor_aft", "name": "S03 · coque arrière", "position_m": [1.5, 2.5, 1.7]},
                {"id": "sensor_crown", "name": "S04 · couronne", "position_m": [1.5, 1.5, 2.3]},
            ]
            scene["defaults"]["mesh_cell_m"] = 0.2
            scene["provenance"]["title"] = "Capsule Soyouz — interprétation originale"
            scene["provenance"]["scientific_status"] = "Visually inspired by the Soyuz descent module, not flight CAD. Approximate 3 x 3 x 2.6 m computational envelope; four corner obstacles approximate the rounded shell. Seat proxies are filled AABB envelopes. No engineering or flight certification."
            scene["provenance"]["visual_detail_policy"] = "Rounded visual shell differs from the coarse four-corner AABB computational shell. This discrepancy must be retained in simulation provenance; quantitative capsule validation is not established."
            scene["presentation"]["name"] = "SOYUZ / DESCENT CAPSULE STUDY"
            scene["presentation"]["physical_camera_m"] = [5.2, -5.1, 5.9]
            scene["presentation"]["camera_target_m"] = [1.5, 1.5, 1.15]
        scene["presentation"]["blender_file"] = f"{scene_id}.blend"
        scene["presentation"]["preview_image"] = f"{scene_id}-overview.png"
        add_incident_annotations(scene)
        scenes.append(scene)
    return {"schema_version": 1, "materials": materials, "scenes": scenes}


def validate_catalog(catalog):
    errors = []
    if {s["id"] for s in catalog["scenes"]} != {"habitat", "cargo", "crossflow", "soyuz"}:
        errors.append("Expected habitat, cargo, crossflow and soyuz IDs")
    material_ids = {m["id"] for m in catalog["materials"]}
    for scene in catalog["scenes"]:
        object_ids = set()
        for obj in scene["objects"]:
            if obj["id"] in object_ids:
                errors.append(f"{scene['id']}: duplicate object {obj['id']}")
            object_ids.add(obj["id"])
            if obj["material_id"] not in material_ids:
                errors.append(f"{obj['id']}: unknown material")
            if obj["role"] != "wall":
                for c, n, bound in zip(obj["center_m"], obj["size_m"], scene["bounds_m"]):
                    if n <= 0 or c - n / 2 < -1e-6 or c + n / 2 > bound + 1e-6:
                        errors.append(f"{scene['id']}/{obj['id']}: outside domain")
        physical = [o for o in scene["objects"] if o["role"] in ("obstacle", "fuel")]
        for i, a in enumerate(physical):
            for b in physical[i + 1:]:
                if all(abs(x - y) < (s + t) / 2 - 1e-5 for x, y, s, t in zip(a["center_m"], b["center_m"], a["size_m"], b["size_m"])):
                    errors.append(f"{scene['id']}: intersecting proxies {a['id']}/{b['id']}")
        for v in scene["vents"]:
            zero_axes = [i for i, n in enumerate(v["size_m"]) if n == 0]
            if len(zero_axes) != 1:
                errors.append(f"{v['id']}: vent needs exactly one zero dimension")
            else:
                axis = zero_axes[0]
                if v["center_m"][axis] not in (0, scene["bounds_m"][axis]):
                    errors.append(f"{v['id']}: not on boundary")
        for sensor in scene["sensors"]:
            if not all(0 < p < d for p, d in zip(sensor["position_m"], scene["bounds_m"])):
                errors.append(f"{sensor['id']}: not in domain")
    if errors:
        raise ValueError("\n".join(errors))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[2] / "scenes" / "catalog.json")
    args = parser.parse_args()
    result = build_catalog()
    validate_catalog(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}: {len(result['scenes'])} scene variants")
