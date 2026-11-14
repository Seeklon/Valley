"""Traceable properties for a thermal precursor model, not an ignition model.

Guo et al. studied a laboratory NiCr/LDPE wire. These values must not be
silently assigned to spacecraft cable insulation or electrical connectors.
"""

from dataclasses import asdict, dataclass

GUO_2023_DOI = "https://doi.org/10.1016/j.firesaf.2023.103925"
GUO_2023_MANUSCRIPT = "https://hdl.handle.net/2115/95853"
REFERENCE_TEMPERATURE_K = 293.15
GAS_CONSTANT_J_MOL_K = 8.314
STEFAN_BOLTZMANN_W_M2_K4 = 5.670374419e-8


@dataclass(frozen=True)
class WireMaterial:
    preset: str
    conductor_density_kg_m3: float
    conductor_heat_capacity_j_kg_k: float
    conductor_conductivity_w_m_k: float
    resistivity_reference_ohm_m: float
    resistance_temperature_coefficient_per_k: float
    insulation_density_kg_m3: float
    solid_heat_capacity_j_kg_k: float
    liquid_heat_capacity_j_kg_k: float
    solid_conductivity_w_m_k: float
    liquid_conductivity_w_m_k: float
    solid_emissivity: float
    liquid_emissivity: float
    melting_temperature_k: float
    fusion_enthalpy_j_kg: float
    pyrolysis_prefactor_per_s: float
    pyrolysis_activation_energy_j_mol: float
    pyrolysis_enthalpy_j_kg: float

    @property
    def melting_start_enthalpy_j_kg(self) -> float:
        return self.solid_heat_capacity_j_kg_k * (self.melting_temperature_k - REFERENCE_TEMPERATURE_K)

    @property
    def melting_end_enthalpy_j_kg(self) -> float:
        return self.melting_start_enthalpy_j_kg + self.fusion_enthalpy_j_kg

    def insulation_state(self, enthalpy_j_kg: float) -> tuple[float, float]:
        """Invert specific enthalpy into temperature and liquid mass fraction.

        This equilibrium phase model is reversible on cooling. Supercooling,
        melt displacement and temperature gradients within a node are absent.
        """
        start = self.melting_start_enthalpy_j_kg
        end = self.melting_end_enthalpy_j_kg
        if enthalpy_j_kg < start:
            temperature = REFERENCE_TEMPERATURE_K + enthalpy_j_kg / self.solid_heat_capacity_j_kg_k
            return temperature, 0.0
        if enthalpy_j_kg <= end:
            return self.melting_temperature_k, (enthalpy_j_kg - start) / self.fusion_enthalpy_j_kg
        return (
            self.melting_temperature_k + (enthalpy_j_kg - end) / self.liquid_heat_capacity_j_kg_k,
            1.0,
        )

    def insulation_enthalpy(self, temperature_k: float, melt_fraction: float = 0.0) -> float:
        """Return J/kg relative to the solid at 293.15 K.

        ``melt_fraction`` only selects a state exactly on the melting plateau.
        """
        if temperature_k < self.melting_temperature_k:
            return self.solid_heat_capacity_j_kg_k * (temperature_k - REFERENCE_TEMPERATURE_K)
        if temperature_k == self.melting_temperature_k:
            return self.melting_start_enthalpy_j_kg + melt_fraction * self.fusion_enthalpy_j_kg
        return self.melting_end_enthalpy_j_kg + self.liquid_heat_capacity_j_kg_k * (
            temperature_k - self.melting_temperature_k
        )

    def provenance(self) -> dict:
        return {
            "preset": self.preset,
            "source_doi": GUO_2023_DOI,
            "author_manuscript": GUO_2023_MANUSCRIPT,
            "locations": {
                "geometry_and_resistivity": "manuscript page 2, section 2",
                "thermal_properties": "manuscript page 4, Table 2",
                "melting_and_pyrolysis": "manuscript page 4, equations 1 and 2",
            },
            "values_si": asdict(self),
            "resistance_note": (
                "The paper assumes constant NiCr resistance. Its rounded resistivity 1.1e-6 ohm m "
                "gives about 5.60 ohm/m for radius 0.25 mm; the measured 5.5 ohm/m is reported "
                "with +/-7% variation. No temperature coefficient was fitted."
            ),
            "transfer_limit": "Laboratory NiCr/LDPE specimen, not a qualified spacecraft cable.",
        }


NICHROME_LDPE_GUO2023 = WireMaterial(
    preset="nichrome_ldpe_guo2023",
    conductor_density_kg_m3=8410.0,
    conductor_heat_capacity_j_kg_k=481.0,
    conductor_conductivity_w_m_k=17.4,
    resistivity_reference_ohm_m=1.1e-6,
    resistance_temperature_coefficient_per_k=0.0,
    insulation_density_kg_m3=920.0,
    solid_heat_capacity_j_kg_k=2300.0,
    liquid_heat_capacity_j_kg_k=2500.0,
    solid_conductivity_w_m_k=0.34,
    liquid_conductivity_w_m_k=0.25,
    solid_emissivity=0.3,
    liquid_emissivity=0.1,
    melting_temperature_k=391.15,
    fusion_enthalpy_j_kg=140600.0,
    pyrolysis_prefactor_per_s=5.0e18,
    pyrolysis_activation_energy_j_mol=300000.0,
    pyrolysis_enthalpy_j_kg=962000.0,
)


def get_material(preset: str) -> WireMaterial:
    if preset != NICHROME_LDPE_GUO2023.preset:
        raise ValueError(f"Unsupported wire material preset: {preset}")
    return NICHROME_LDPE_GUO2023
