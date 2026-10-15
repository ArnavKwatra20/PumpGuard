"""Bounded contracts for optional AMD-backed explanation features."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AiFeatureKind = Literal["maintenance_planner", "telemetry_explanation", "scenario_analyst"]


class AiFeatureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pump_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    feature: AiFeatureKind
    client_session_id: str | None = Field(default=None, min_length=1, max_length=64,
                                           pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class AiFeatureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature: AiFeatureKind
    assistant_message: str = Field(min_length=1, max_length=6000)
    provider: Literal["mock", "amd", "amd_unavailable"]
    is_mock: bool
    latency_ms: float = Field(ge=0, le=120000)
    evidence_timestamp: str
