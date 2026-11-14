from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PreventionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    scene_id: str = Field(default="soyuz", pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    current_a: float = Field(default=5, ge=0, le=20)
    airflow_m_s: float = Field(default=0, ge=0, le=0.5)
    gravity_g: float = Field(default=0.0001, ge=0, le=1)
    ambient_temperature_c: float = Field(default=20, ge=0, le=50)
    oxygen_percent: float = Field(default=21, ge=15, le=30)
    pressure_pa: float = Field(default=101325, ge=60000, le=120000)
    duration_s: float = Field(default=20, ge=2, le=60)
    observation_cutoff_s: float = Field(default=0.5, ge=0, le=59)
    horizon_s: float = Field(default=5, gt=0, le=20)
    cutoff_s: float | None = Field(default=None, gt=0, le=60)

    @model_validator(mode="after")
    def temporal_contract(self):
        if self.observation_cutoff_s + self.horizon_s > self.duration_s:
            raise ValueError("L’instant observé et l’horizon doivent rester dans la durée du scénario.")
        if self.cutoff_s is not None and self.cutoff_s > self.duration_s:
            raise ValueError("La coupure programmée doit être comprise dans la durée du scénario.")
        return self


class PreventionInterpretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    component_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    question: str = Field(default="Quelles conclusions étayent cette estimation et quelles limites restent ?",
                          min_length=1, max_length=1500)
