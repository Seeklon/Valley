from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    scene_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    mode: Literal["physics", "prediction"] = "physics"
    source_model: Literal["prescribed_source", "coupled_combustion"] = "prescribed_source"
    gravity_g: float = Field(default=0.0001, ge=0, le=1)
    airflow_m_s: float = Field(default=0.2, ge=0, le=1)
    oxygen_percent: float = Field(default=21, ge=15, le=30)
    material_id: Literal["cellulose", "pmma"] = "cellulose"
    ignition_power_w: float = Field(default=500, ge=0, le=10000)
    ignition_duration_s: float = Field(default=15, ge=0.1, le=120)
    duration_s: float = Field(default=60, ge=2, le=180)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    mesh_cell_m: float = Field(default=0.2, ge=0.1, le=0.4)
    sample_shape: tuple[int, int, int] = (8, 10, 4)
    model_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    ignition_kind: Literal["thermal", "resistive"] = "thermal"
    current_a: float = Field(default=5, ge=0, le=100)
    resistance_ohm: float = Field(default=20, gt=0, le=1000)

    @model_validator(mode="after")
    def validate_constraints(self) -> "RunConfig":
        if self.ignition_kind == "resistive" and self.source_model != "coupled_combustion":
            raise ValueError("L’allumage résistif exige la combustion couplée : I²R chauffe le solide.")
        if self.ignition_duration_s > self.duration_s:
            raise ValueError("La durée d’allumage doit rester inférieure à la durée du calcul.")
        if self.sample_shape != (8, 10, 4):
            raise ValueError("Cette version de l’interface utilise une grille d’observation 8×10×4.")
        if self.ignition_kind == "resistive" and self.current_a**2 * self.resistance_ohm > 10000:
            raise ValueError("La puissance résistive I²R dépasse 10 kW.")
        return self

    def physical_config(self) -> dict:
        config = self.model_dump(mode="json")
        if self.ignition_kind == "resistive":
            config["ignition_power_w"] = self.current_a**2 * self.resistance_ohm
        return config
