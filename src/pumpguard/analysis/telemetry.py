"""Deterministic telemetry intelligence over recorded synthetic telemetry.

All calculations are pure functions of the supplied readings: time-window trends,
least-squares rate-of-change with real timestamps, rolling statistics sized to the
available sampling, threshold excursions reusing the authoritative rule-engine
bands, and missing/invalid/insufficient-sample handling. No physical causation is
inferred from statistics. The rule-based diagnostic engine remains authoritative.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from pumpguard.detection.rules import DEFAULT_THRESHOLDS
from pumpguard.models.telemetry import TelemetryReading
from pumpguard.models.telemetry_analysis import (
    ComparisonResult,
    MetricAISummary,
    MetricTrend,
    TelemetryAnalysis,
    ThresholdBand,
    WindowComparison,
)

# Canonical sensors analyzed, with fixed units (pressure has no authoritative band).
_ANALYZED_METRICS = ("temperature_c", "vibration_mm_s", "sound_db", "rpm")
_UNITS = {"temperature_c": "°C", "vibration_mm_s": "mm/s", "sound_db": "dB", "rpm": "rpm"}
_THRESHOLDS = {t.metric: ThresholdBand(low=t.low, high=t.high, critical_low=t.critical_low,
                                       critical_high=t.critical_high, unit=t.unit)
               for t in DEFAULT_THRESHOLDS}
_MIN_SAMPLES_FOR_TREND = 2
_ROLLING_WINDOW = 5


def _as_utc(reading: TelemetryReading):
    return reading.timestamp


def _sorted_oldest_first(readings: Sequence[TelemetryReading]) -> list[TelemetryReading]:
    return sorted(readings, key=_as_utc)


def _linear_slope(xs: list[float], ys: list[float]) -> float | None:
    """Least-squares slope of ys over xs; None when undefined (e.g. zero variance in x)."""
    n = len(xs)
    if n < _MIN_SAMPLES_FOR_TREND:
        return None
    # Epoch timestamps lose sub-second precision when squared around 1e9.
    # Translate to a local origin before regression; slope is translation invariant.
    local_xs = [x - xs[0] for x in xs]
    mean_x = sum(local_xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in local_xs)
    if sxx <= 0.0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(local_xs, ys))
    return sxy / sxx


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


class TelemetryAnalysisService:
    """Compute deterministic, evidence-backed telemetry intelligence."""

    def __init__(self, rolling_window: int = _ROLLING_WINDOW) -> None:
        if rolling_window < 1:
            raise ValueError("rolling_window must be positive")
        self.rolling_window = rolling_window

    def _sampling_profile(self, ordered: list[TelemetryReading]) -> tuple[float | None, bool]:
        if len(ordered) < 2:
            return None, False  # a single sample is not "regular" by evidence
        intervals = [(b.timestamp - a.timestamp).total_seconds()
                     for a, b in zip(ordered, ordered[1:])]
        positive = [i for i in intervals if i > 0]
        if not positive:
            return None, False
        median = _median(positive)
        regular = all(abs(i - median) <= max(0.25 * median, 1e-6) for i in positive)
        return median, regular

    def _metric_trend(self, metric: str, ordered: list[TelemetryReading]) -> MetricTrend:
        unit = _UNITS[metric]
        threshold = _THRESHOLDS.get(metric)
        values: list[float] = []
        times: list[float] = []
        missing = 0
        for reading in ordered:
            raw = getattr(reading, metric, None)
            if raw is None or not math.isfinite(float(raw)):
                missing += 1
                continue
            values.append(float(raw))
            times.append(reading.timestamp.timestamp())
        valid = len(values)
        insufficient = valid < _MIN_SAMPLES_FOR_TREND
        first_ts = ordered[0].timestamp if ordered else None
        last_ts = ordered[-1].timestamp if ordered else None
        elapsed = (last_ts - first_ts).total_seconds() if ordered else None
        _, regular = self._sampling_profile(ordered)
        base = dict(metric=metric, unit=unit, provenance="synthetic", sample_count=len(ordered),
                    valid_count=valid, missing_count=missing, first_timestamp=first_ts, last_timestamp=last_ts,
                    elapsed_seconds=elapsed if (elapsed and elapsed >= 0) else None,
                    threshold=threshold, insufficient_samples=insufficient, sampling_regular=regular)
        if valid == 0:
            return MetricTrend(**base, direction="insufficient_data", rate_unit="per_second")

        first_value, latest_value = values[0], values[-1]
        minimum, maximum = min(values), max(values)
        mean = sum(values) / valid
        delta = latest_value - first_value
        rate = None if insufficient else _linear_slope(times, values)
        direction = "insufficient_data"
        if rate is not None:
            scale = max(abs(mean), 1e-6)
            if rate > 0 and (delta > 0.01 * scale):
                direction = "increasing"
            elif rate < 0 and (delta < -0.01 * scale):
                direction = "decreasing"
            else:
                direction = "stable"

        roll_mean = roll_std = None
        window = self.rolling_window
        if valid >= window:
            tail = values[-window:]
            tail_mean = sum(tail) / window
            tail_var = sum((x - tail_mean) ** 2 for x in tail) / window
            roll_mean, roll_std = tail_mean, tail_var ** 0.5

        high = low = critical = 0
        if threshold:
            for v in values:
                if v < threshold.low:
                    low += 1
                elif v > threshold.high:
                    high += 1
                if v < threshold.critical_low or v > threshold.critical_high:
                    critical += 1

        return MetricTrend(**base, first_value=first_value, latest_value=latest_value, minimum=minimum,
                           maximum=maximum, mean=mean, delta=delta, rate_per_second=rate, rate_unit="per_second",
                           direction=direction, rolling_mean=roll_mean, rolling_std=roll_std,
                           excursions_high=high, excursions_low=low, critical_breaches=critical)

    def analyze(self, asset_id: str, readings: Sequence[TelemetryReading]) -> TelemetryAnalysis:
        ordered = _sorted_oldest_first(readings)
        median_interval, regular = self._sampling_profile(ordered)
        metrics = [self._metric_trend(metric, ordered) for metric in _ANALYZED_METRICS]
        ai_summary = [MetricAISummary(metric=m.metric, unit=m.unit, latest_value=m.latest_value, mean=m.mean,
                                      rate_per_second=m.rate_per_second, direction=m.direction,
                                      excursions_high=m.excursions_high, excursions_low=m.excursions_low,
                                      critical_breaches=m.critical_breaches) for m in metrics]
        valid_sample_count = sum(
            all(getattr(reading, metric, None) is not None
                and math.isfinite(float(getattr(reading, metric))) for metric in _ANALYZED_METRICS)
            for reading in ordered
        )
        missing_sample_count = len(ordered) - valid_sample_count
        limitations = [
            "Telemetry is synthetic simulator output; it does not represent a real machine.",
            "Rate-of-change is a least-squares slope over the window, not a physical failure rate.",
            "Threshold excursions reuse authoritative rule-engine bands; no thresholds were invented.",
        ]
        if not regular:
            limitations.append("Sampling intervals are irregular; rolling statistics assume evenly spaced samples.")
        if missing_sample_count:
            limitations.append("Some readings were missing or non-finite and were excluded from statistics.")
        return TelemetryAnalysis(
            asset_id=asset_id, synthetic=True,
            window_start=ordered[0].timestamp if ordered else None,
            window_end=ordered[-1].timestamp if ordered else None,
            sample_count=len(ordered), valid_sample_count=valid_sample_count,
            missing_sample_count=missing_sample_count, sampling_regular=regular,
            median_interval_seconds=median_interval, metrics=metrics, limitations=limitations, ai_summary=ai_summary,
        )

    def compare(self, asset_id: str, baseline: Sequence[TelemetryReading],
                current: Sequence[TelemetryReading]) -> ComparisonResult:
        """Compare two windows only where units and time alignment permit it."""
        baseline_analysis = self.analyze(asset_id, baseline)
        current_analysis = self.analyze(asset_id, current)
        baseline_by_metric = {m.metric: m for m in baseline_analysis.metrics}
        current_by_metric = {m.metric: m for m in current_analysis.metrics}
        comparisons: list[WindowComparison] = []
        for metric in _ANALYZED_METRICS:
            b = baseline_by_metric[metric]
            c = current_by_metric[metric]
            # Comparable only when both windows have a defined rate (>= 2 valid samples) and share a unit.
            comparable = (b.unit == c.unit) and b.rate_per_second is not None and c.rate_per_second is not None
            reason = None if comparable else "Insufficient valid samples or mismatched units for comparison."
            comparisons.append(WindowComparison(
                metric=metric, unit=c.unit, comparable=comparable, reason=reason,
                baseline_mean=b.mean, current_mean=c.mean,
                mean_delta=(c.mean - b.mean) if (b.mean is not None and c.mean is not None) else None,
                baseline_rate_per_second=b.rate_per_second, current_rate_per_second=c.rate_per_second,
                rate_delta_per_second=(c.rate_per_second - b.rate_per_second) if comparable else None,
                baseline_direction=b.direction, current_direction=c.direction,
            ))
        limitations = [
            "Comparison is descriptive; a difference between windows does not establish a cause.",
            "Both windows are synthetic simulator telemetry.",
            "Windows are aligned by metric and unit only; no cross-sensor time normalization is applied.",
        ]
        return ComparisonResult(
            asset_id=asset_id, synthetic=True,
            baseline_sample_count=baseline_analysis.sample_count,
            current_sample_count=current_analysis.sample_count,
            metrics=comparisons, limitations=limitations,
        )


