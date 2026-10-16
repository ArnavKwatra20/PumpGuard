"""Bounded, evidence-only diagnostic inference contracts."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing import Annotated

from pumpguard.models.telemetry import TelemetryReading


Scenario = Literal["normal", "overheating", "bearing_wear", "cavitation", "imbalance"]
Severity = Literal["warning", "critical"]


class DiagnosticTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    temperature_c: float = Field(ge=-20, le=250, allow_inf_nan=False)
    vibration_mm_s: float = Field(ge=0, le=100, allow_inf_nan=False)
    sound_db: float = Field(ge=0, le=160, allow_inf_nan=False)
    rpm: float = Field(ge=0, le=30000, allow_inf_nan=False)
    pressure_kpa: float | None = Field(default=None, ge=0, le=2000, allow_inf_nan=False)
    load_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)

    @classmethod
    def from_reading(cls, reading: TelemetryReading) -> "DiagnosticTelemetry":
        return cls(timestamp=reading.timestamp, temperature_c=reading.temperature_c,
                   vibration_mm_s=reading.vibration_mm_s, sound_db=reading.sound_db, rpm=reading.rpm,
                   pressure_kpa=reading.pressure_kpa, load_percent=reading.load_percent)


class DiagnosticTrend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Literal["temperature_c", "vibration_mm_s", "sound_db", "rpm", "pressure_kpa"]
    initial_value: float = Field(allow_inf_nan=False)
    latest_value: float = Field(allow_inf_nan=False)
    delta: float = Field(allow_inf_nan=False)
    elapsed_seconds: float = Field(ge=0, le=31_536_000)
    samples: int = Field(ge=1, le=120)


class DetectorEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["normal", "warning", "critical"]
    score: int = Field(ge=0, le=100)
    predicted_faults: list[Annotated[str, StringConstraints(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=8)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class AssessmentFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str = Field(min_length=1, max_length=64)
    observed_value: float = Field(allow_inf_nan=False)
    expected_range: str = Field(max_length=128)
    severity: Literal["normal", "warning", "critical"]
    explanation: str = Field(max_length=500)


class HealthAssessmentEvidence(BaseModel):
    """Structured copy of the authoritative deterministic health assessment."""
    model_config = ConfigDict(extra="forbid")
    status: Literal["normal", "warning", "critical"]
    health_score: int = Field(ge=0, le=100)
    anomalies: list[AssessmentFinding] = Field(default_factory=list, max_length=32)
    recommendations: list[str] = Field(default_factory=list, max_length=32)


class AlertEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode_id: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=64)
    severity: Severity
    observed_value: float = Field(allow_inf_nan=False)
    expected_range: str = Field(max_length=128)
    explanation: str = Field(max_length=500)


class DiagnosticEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_seconds: float = Field(ge=0, le=10_000_000)
    kind: str = Field(min_length=1, max_length=64)
    scenario: Scenario


class MLPredictionEvidence(BaseModel):
    """Optional uncalibrated synthetic-scenario classifier output."""
    model_config = ConfigDict(extra="forbid")
    label: Scenario
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    probabilities: dict[Scenario, float] = Field(default_factory=dict)
    model_version: str = Field(min_length=1, max_length=80)
    compute_provider: Literal["cpu", "amd_rocm", "cuda"]
    device: str = Field(min_length=1, max_length=32)
    execution_path: str = Field(min_length=1, max_length=40)
    interpretation: str = Field(default="Synthetic scenario classification only.", max_length=240)


class DiagnosticRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pump_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    simulation_id: str | None = Field(default=None, max_length=64)
    alert_episode_id: str | None = Field(default=None, max_length=128)
    assessment_timestamp: datetime
    telemetry: list[DiagnosticTelemetry] = Field(min_length=1, max_length=12)
    trends: list[DiagnosticTrend] = Field(default_factory=list, max_length=5)
    detector: DetectorEvidence
    assessment: HealthAssessmentEvidence | None = None
    is_synthetic: bool = True
    selected_scenario: Scenario | None = None
    injected_scenario: Scenario | None = None
    ml_prediction: MLPredictionEvidence | None = None
    alert: AlertEvidence | None = None
    events: list[DiagnosticEvent] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def consistent_episode(self) -> "DiagnosticRequest":
        if self.alert and self.alert_episode_id and self.alert.episode_id != self.alert_episode_id:
            raise ValueError("alert_episode_id must match alert.episode_id")
        if any(left.timestamp > right.timestamp for left, right in zip(self.telemetry, self.telemetry[1:])):
            raise ValueError("telemetry samples must be ordered oldest to newest")
        return self


class DiagnosticEvidenceReference(BaseModel):
    """Machine-checkable evidence pointer; no free-form measurement claims."""
    model_config = ConfigDict(extra="forbid")
    source: Literal["telemetry", "trend", "detector", "alert", "event", "ml_prediction", "assessment"]
    field: str = Field(min_length=1, max_length=64)
    metric: Literal["temperature_c", "vibration_mm_s", "sound_db", "rpm", "pressure_kpa", "load_percent"] | None = None
    reading_index: int | None = Field(default=None, ge=0, le=11)
    event_index: int | None = Field(default=None, ge=0, le=15)
    value: float | str


class DiagnosticHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cause: str = Field(min_length=1, max_length=160)
    rank: int = Field(ge=1, le=5)
    uncertainty: Literal["low", "moderate", "high"]
    evidence: list[DiagnosticEvidenceReference] = Field(min_length=1, max_length=5)
    missing_evidence: list[str] = Field(default_factory=list, max_length=8)


class DiagnosticContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=600)
    hypotheses: list[DiagnosticHypothesis] = Field(max_length=5)
    missing_evidence: list[str] = Field(default_factory=list, max_length=10)
    inspection_steps: list[str] = Field(min_length=1, max_length=8)
    priority: Literal["routine", "soon", "urgent"]
    priority_rationale: str = Field(min_length=1, max_length=400)
    limitations: list[str] = Field(min_length=1, max_length=10)
    human_review_required: Literal[True] = True

    @model_validator(mode="after")
    def hypotheses_are_ranked(self) -> "DiagnosticContent":
        ranks = [item.rank for item in self.hypotheses]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("hypothesis ranks must be unique and ordered starting at one")
        return self


class DiagnosticResult(DiagnosticContent):
    provider: Literal["mock", "amd", "amd_unavailable"]
    is_mock: bool
    latency_ms: float = Field(ge=0, le=120_000)
    correlation_id: str = Field(min_length=1, max_length=64)
    cached: bool = False
    assessment_timestamp: datetime
    ml_prediction: MLPredictionEvidence | None = None
