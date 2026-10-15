"""Validated contracts for deterministic telemetry intelligence.

Provenance is explicit: every value is labeled measured, derived, or synthetic.
These summaries are compact and bounded so they can later be supplied to a hosted
model (e.g. AMD Token Factory) without sending large raw histories. Nothing here
infers physical causation from statistics.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TrendDirection = Literal["increasing", "decreasing", "stable", "insufficient_data"]
Provenance = Literal["measured", "derived", "synthetic"]


class ThresholdBand(BaseModel):
    """Authoritative expected range copied from the rule engine (never invented)."""
    model_config = ConfigDict(extra="forbid")
    low: float
    high: float
    critical_low: float
    critical_high: float
    unit: str


class MetricTrend(BaseModel):
    """Deterministic per-metric analysis over one telemetry window."""
    model_config = ConfigDict(extra="forbid")
    metric: str
    unit: str
    provenance: Provenance
    sample_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    elapsed_seconds: float | None = Field(default=None, ge=0)
    first_value: float | None = None
    latest_value: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    delta: float | None = None            # latest - first (unit)
    rate_per_second: float | None = None  # least-squares slope (unit/second)
    rate_unit: str = "per_second"
    direction: TrendDirection
    median_interval_seconds: float | None = Field(default=None, ge=0)
    sampling_regular: bool
    rolling_mean: float | None = None
    rolling_std: float | None = None
    threshold: ThresholdBand | None = None
    excursions_high: int = Field(default=0, ge=0)
    excursions_low: int = Field(default=0, ge=0)
    critical_breaches: int = Field(default=0, ge=0)
    insufficient_samples: bool


class WindowComparison(BaseModel):
    """Descriptive numeric shift between two aligned windows; not causal."""
    model_config = ConfigDict(extra="forbid")
    metric: str
    unit: str
    comparable: bool
    reason: str | None = None
    baseline_mean: float | None = None
    current_mean: float | None = None
    mean_delta: float | None = None
    baseline_rate_per_second: float | None = None
    current_rate_per_second: float | None = None
    rate_delta_per_second: float | None = None
    baseline_direction: TrendDirection | None = None
    current_direction: TrendDirection | None = None


class MetricAISummary(BaseModel):
    """Minimal, bounded per-metric facts suitable for a hosted model prompt."""
    model_config = ConfigDict(extra="forbid")
    metric: str
    unit: str
    latest_value: float | None
    mean: float | None
    rate_per_second: float | None
    direction: TrendDirection
    excursions_high: int = Field(ge=0)
    excursions_low: int = Field(ge=0)
    critical_breaches: int = Field(ge=0)


class TelemetryAnalysis(BaseModel):
    """Deterministic telemetry intelligence for one asset window."""
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    generator: Literal["deterministic_analysis"] = "deterministic_analysis"
    provenance: Provenance = "synthetic"
    synthetic: bool = True
    window_start: datetime | None = None
    window_end: datetime | None = None
    sample_count: int = Field(ge=0)
    valid_sample_count: int = Field(ge=0)
    missing_sample_count: int = Field(ge=0)
    sampling_regular: bool
    median_interval_seconds: float | None = Field(default=None, ge=0)
    metrics: list[MetricTrend] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    ai_summary: list[MetricAISummary] = Field(default_factory=list, max_length=16)


class ComparisonResult(BaseModel):
    """Result of comparing a baseline window against a current window."""
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    generator: Literal["deterministic_analysis"] = "deterministic_analysis"
    provenance: Provenance = "synthetic"
    synthetic: bool = True
    baseline_sample_count: int = Field(ge=0)
    current_sample_count: int = Field(ge=0)
    metrics: list[WindowComparison] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=10)
