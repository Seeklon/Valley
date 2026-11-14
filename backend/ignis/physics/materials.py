"""Versioned, explicit material assumptions for the first FDS demonstration.

These values are not fitted to NASA BASS and do not establish material ratings.
All FDS thermal quantities below follow the FDS units, notably kJ/(kg K).
"""

from copy import deepcopy

MODEL_VERSION = "ignis-fds-materials-2"
FDS_REFERENCE = "https://pages.nist.gov/fds-smv/manuals.html"
PMMA_REFERENCE = (
    "https://github.com/firemodels/fds/blob/FDS-6.11.1/Validation/"
    "FAA_Polymers/FDS_Input_Files/FAA_Polymers_PMMA.fds"
)
CELLULOSE_REFERENCE = (
    "https://github.com/firemodels/fds/blob/FDS-6.11.1/Verification/Pyrolysis/tga_analysis.fds"
)

MATERIALS = {
    "cellulose": {
        "id": "cellulose",
        "name": "Cellulose — approximation générique",
        "density_kg_m3": 500.0,
        "conductivity_w_m_k": 0.2,
        "specific_heat_kj_kg_k": 1.0,
        "emissivity": 1.0,
        "reference_temperature_c": 315.0,
        "reference_rate_s_inv": 0.0056,
        "heating_rate_k_min": 10.0,
        "heat_of_reaction_kj_kg": 1000.0,
        "heat_of_combustion_kj_kg": 16000.0,
        "char_yield": 0.4,
        "soot_yield": 0.015,
        "formula": {"C": 6, "H": 10, "O": 5},
        "gas_specific_heat_kj_kg_k": 1.5,
        "default_thickness_m": 0.005,
        "scientific_status": "generic_unvalidated",
        "provenance": {
            "sources": [CELLULOSE_REFERENCE],
            "note": "Dry-wood first-stage TGA tutorial parameters; char is inert here. "
            "Heat of combustion 16 MJ/kg and constant gas Cp 1.5 kJ/(kg K) are explicit illustrative assumptions. "
            "This is neither pure cellulose kinetics nor BASS SIBAL fabric calibration.",
        },
    },
    "pmma": {
        "id": "pmma",
        "name": "PMMA noir — paramètres de démonstration NIST",
        "density_kg_m3": 1100.0,
        "conductivity_w_m_k": 0.2,
        "specific_heat_kj_kg_k": 2.2,
        "emissivity": 0.85,
        "absorption_coefficient_m_inv": 2700.0,
        "arrhenius_a_s_inv": 8.5e12,
        "activation_energy_kj_kmol": 188000.0,
        "heat_of_reaction_kj_kg": 870.0,
        "heat_of_combustion_kj_kg": 25200.0,
        "char_yield": 0.0,
        "soot_yield": 0.02,
        "formula": {"C": 5, "H": 8, "O": 2},
        "gas_specific_heat_kj_kg_k": 1.8,
        "default_thickness_m": 0.0085,
        "scientific_status": "generic_unvalidated",
        "provenance": {
            "sources": [PMMA_REFERENCE],
            "note": "Solid parameters from the NIST FAA Polymers black-PMMA example. "
            "The reference is a solid-phase case. Gas surrogate C5H8O2, constant gas Cp "
            "1.8 kJ/(kg K) and soot yield 0.02 are additional assumptions; coupled microgravity use is not validated.",
        },
    },
}

INERT_MATERIALS = {
    "aluminium": (2700.0, 205.0, 0.90, 0.30),
    "steel": (7850.0, 45.0, 0.50, 0.70),
    "glass": (2500.0, 1.0, 0.80, 0.90),
    "insulation": (120.0, 0.08, 0.84, 0.90),
}


def material_catalog() -> list[dict]:
    """Return independent JSON-compatible records, including units and provenance."""
    records = deepcopy(list(MATERIALS.values()))
    for mid, (rho, conductivity, cp, emissivity) in INERT_MATERIALS.items():
        records.append(
            {
                "id": mid,
                "name": mid,
                "density_kg_m3": rho,
                "conductivity_w_m_k": conductivity,
                "specific_heat_kj_kg_k": cp,
                "emissivity": emissivity,
                "scientific_status": "generic_unvalidated",
                "provenance": {
                    "note": "Generic constant engineering assumptions; no specimen measurement. "
                    "Inert boundary treatment, not an assertion of material fire resistance.",
                    "sources": [FDS_REFERENCE],
                },
            }
        )
    return records


def _identifier(stem: str, namespace: str | None) -> str:
    # Incident scenes keep independent gas/solid identities for each material.
    # The absent namespace deliberately preserves legacy input bytes.
    if namespace is None:
        return stem
    if not namespace or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in namespace
    ):
        raise ValueError("Material namespace must contain only ASCII letters, digits or underscores")
    return f"{stem}_{namespace}"


def fuel_species_line(material_id: str, namespace: str | None = None) -> str:
    m = MATERIALS[material_id]
    f = m["formula"]
    return (
        f"&SPEC ID='{_identifier('IGNIS_FUEL', namespace)}', "
        f"C={f['C']}, H={f['H']}, O={f['O']}, "
        f"SPECIFIC_HEAT={m['gas_specific_heat_kj_kg_k']:.9g} /"
    )


def reaction_line(material_id: str, namespace: str | None = None) -> str:
    m = MATERIALS[material_id]
    return (
        f"&REAC ID='{_identifier('IGNIS_REACTION', namespace)}', FUEL='{_identifier('IGNIS_FUEL', namespace)}', "
        f"HEAT_OF_COMBUSTION={m['heat_of_combustion_kj_kg']:.9g}, "
        f"SOOT_YIELD={m['soot_yield']:.9g}, CO_YIELD=0.0 /"
    )


def solid_material_lines(material_id: str, namespace: str | None = None) -> list[str]:
    m = MATERIALS[material_id]
    parts = [
        f"&MATL ID='{_identifier('IGNIS_SOLID', namespace)}'",
        f"DENSITY={m['density_kg_m3']:.9g}",
        f"CONDUCTIVITY={m['conductivity_w_m_k']:.9g}",
        f"SPECIFIC_HEAT={m['specific_heat_kj_kg_k']:.9g}",
        f"EMISSIVITY={m['emissivity']:.9g}",
        "N_REACTIONS=1",
        f"SPEC_ID='{_identifier('IGNIS_FUEL', namespace)}'",
        f"NU_SPEC={1.0 - m['char_yield']:.9g}",
        f"HEAT_OF_REACTION={m['heat_of_reaction_kj_kg']:.9g}",
    ]
    if "arrhenius_a_s_inv" in m:
        parts.extend(
            [
                f"A={m['arrhenius_a_s_inv']:.9g}",
                f"E={m['activation_energy_kj_kmol']:.9g}",
                f"ABSORPTION_COEFFICIENT={m['absorption_coefficient_m_inv']:.9g}",
            ]
        )
    else:
        parts.extend(
            [
                f"REFERENCE_TEMPERATURE={m['reference_temperature_c']:.9g}",
                f"REFERENCE_RATE={m['reference_rate_s_inv']:.9g}",
                f"HEATING_RATE={m['heating_rate_k_min']:.9g}",
            ]
        )
    lines = []
    if m["char_yield"]:
        parts.extend([f"MATL_ID='{_identifier('IGNIS_CHAR', namespace)}'", f"NU_MATL={m['char_yield']:.9g}"])
        lines.append(
            f"&MATL ID='{_identifier('IGNIS_CHAR', namespace)}', DENSITY=500.0, CONDUCTIVITY=0.2, SPECIFIC_HEAT=1.0, EMISSIVITY=1.0 /"
        )
    lines.append(", ".join(parts) + " /")
    return lines
