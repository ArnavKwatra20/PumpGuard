"""Deterministic telemetry-intelligence tests."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from pumpguard.analysis.telemetry import TelemetryAnalysisService
from pumpguard.api.app import create_app
from pumpguard.models.telemetry import TelemetryReading

_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _readings(values: dict[str, list[float]], interval: float = 1.0, pump: str = "p1") -> list[TelemetryReading]:
    """Build readings from per-metric value lists at a fixed interval."""
    length = max(len(v) for v in values.values())
    defaults = {"temperature_c": 68.0, "vibration_mm_s": 2.0, "sound_db": 68.0, "rpm": 1780.0}
    readings = []
    for index in range(length):
        fields = dict(defaults)
        for metric, series in values.items():
            fields[metric] = series[index] if index < len(series) else series[-1]
        readings.append(TelemetryReading(pump_id=pump, timestamp=_BASE + timedelta(seconds=index * interval), **fields))
    return readings


def _metric(analysis, name):
    return next(m for m in analysis.metrics if m.metric == name)


def test_constant_signal_is_stable_with_zero_rate():
    svc = TelemetryAnalysisService()
    result = svc.analyze("p1", _readings({"temperature_c": [70.0] * 8}))
    temp = _metric(result, "temperature_c")
    assert temp.direction == "stable"
    assert temp.rate_per_second == 0.0
    assert temp.rolling_std == 0.0
    assert temp.excursions_high == 0 and temp.excursions_low == 0


def test_increasing_trend_has_positive_rate_and_units():
    svc = TelemetryAnalysisService()
    result = svc.analyze("p1", _readings({"vibration_mm_s": [float(i) for i in range(1, 11)]}))
    vib = _metric(result, "vibration_mm_s")
    assert vib.direction == "increasing"
    assert vib.rate_per_second == pytest.approx(1.0)
    assert vib.delta == pytest.approx(9.0)
    assert vib.unit == "mm/s"
    assert vib.rate_unit == "per_second"


def test_regression_slope_uses_local_time_origin_for_epoch_timestamps():
    svc = TelemetryAnalysisService()
    readings = _readings({"vibration_mm_s": [6.0, 6.5, 7.0, 7.5]})
    vib = _metric(svc.analyze("p1", readings), "vibration_mm_s")
    assert vib.rate_per_second == pytest.approx(0.5, abs=1e-8)


def test_sample_counts_count_incomplete_rows_not_missing_metric_cells():
    from types import SimpleNamespace

    readings = [
        SimpleNamespace(timestamp=_BASE + timedelta(seconds=index), temperature_c=68.0,
                        vibration_mm_s=(None if index == 1 else 2.0), sound_db=68.0, rpm=1780.0)
        for index in range(3)
    ]
    result = TelemetryAnalysisService().analyze("p1", readings)
    assert result.sample_count == 3
    assert result.valid_sample_count == 2
    assert result.missing_sample_count == 1
    assert _metric(result, "vibration_mm_s").missing_count == 1


def test_decreasing_trend_has_negative_rate():
    svc = TelemetryAnalysisService()
    result = svc.analyze("p1", _readings({"rpm": [float(v) for v in range(1800, 1780, -1)]}))
    rpm = _metric(result, "rpm")
    assert rpm.direction == "decreasing"
    assert rpm.rate_per_second < 0


def test_threshold_excursions_reuse_authoritative_bands():
    svc = TelemetryAnalysisService()
    # vibration high=4.5, critical_high=8 -> a value of 9 is both an excursion and a breach.
    result = svc.analyze("p1", _readings({"vibration_mm_s": [9.0] * 6}))
    vib = _metric(result, "vibration_mm_s")
    assert vib.threshold is not None and vib.threshold.high == 4.5
    assert vib.excursions_high == 6
    assert vib.critical_breaches == 6


def test_insufficient_samples_report_insufficient_data():
    svc = TelemetryAnalysisService()
    result = svc.analyze("p1", _readings({"temperature_c": [70.0]}))
    temp = _metric(result, "temperature_c")
    assert temp.insufficient_samples is True
    assert temp.direction == "insufficient_data"
    assert temp.rate_per_second is None


def test_irregular_timestamps_flag_sampling_not_regular():
    svc = TelemetryAnalysisService()
    values = [0, 1, 2, 10, 11, 12]
    readings = [TelemetryReading(pump_id="p1", timestamp=_BASE + timedelta(seconds=s),
                                 temperature_c=68, vibration_mm_s=2, sound_db=68, rpm=1780) for s in values]
    result = svc.analyze("p1", readings)
    assert result.sampling_regular is False
    assert any("irregular" in lim.lower() for lim in result.limitations)


def test_analysis_is_deterministic_and_repeatable():
    svc = TelemetryAnalysisService()
    readings = _readings({"vibration_mm_s": [float(i) for i in range(1, 9)]})
    assert svc.analyze("p1", readings).model_dump() == svc.analyze("p1", readings).model_dump()


def test_unsorted_input_is_ordered_before_analysis():
    svc = TelemetryAnalysisService()
    readings = _readings({"temperature_c": [70.0, 72.0, 74.0]})
    shuffled = [readings[2], readings[0], readings[1]]
    result = svc.analyze("p1", shuffled)
    temp = _metric(result, "temperature_c")
    assert temp.first_value == 70.0 and temp.latest_value == 74.0
    assert temp.direction == "increasing"


def test_compare_reports_shift_only_when_comparable():
    svc = TelemetryAnalysisService()
    baseline = _readings({"vibration_mm_s": [2.0] * 10})
    current = _readings({"vibration_mm_s": [float(v) for v in range(5, 15)]})
    comparison = svc.compare("p1", baseline, current)
    vib = next(m for m in comparison.metrics if m.metric == "vibration_mm_s")
    assert vib.comparable is True
    assert vib.rate_delta_per_second == pytest.approx(1.0)
    assert vib.mean_delta == pytest.approx(7.5)
    assert any("descriptive" in lim.lower() for lim in comparison.limitations)


def test_compare_single_sample_window_is_not_comparable():
    svc = TelemetryAnalysisService()
    baseline = _readings({"temperature_c": [70.0]})
    current = _readings({"temperature_c": [80.0]})
    comparison = svc.compare("p1", baseline, current)
    temp = next(m for m in comparison.metrics if m.metric == "temperature_c")
    assert temp.comparable is False
    assert temp.reason is not None


def test_ai_summary_is_compact_and_synthetic_labeled():
    svc = TelemetryAnalysisService()
    result = svc.analyze("p1", _readings({"vibration_mm_s": [float(i) for i in range(1, 9)]}))
    assert result.synthetic is True
    assert len(result.ai_summary) == 4
    assert all(item.unit for item in result.ai_summary)


def test_endpoint_404_for_unknown_asset():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/pumps/missing/telemetry/analysis")
    assert response.status_code == 404


def test_endpoint_analysis_is_read_only_and_live():
    with TestClient(create_app()) as client:
        client.post("/api/v1/simulation/generate", json={"pump_id": "pump-01", "scenario": "bearing_wear", "random_seed": 5, "sample_count": 40})
        before = client.get("/api/v1/pumps/pump-01/assessment").json()
        analysis = client.get("/api/v1/pumps/pump-01/telemetry/analysis", params={"limit": 40})
        compare = client.get("/api/v1/pumps/pump-01/telemetry/analysis/compare", params={"current": 15, "baseline": 15})
        after = client.get("/api/v1/pumps/pump-01/assessment").json()
    assert analysis.status_code == 200
    assert analysis.json()["sample_count"] == 40
    assert compare.status_code == 200
    assert compare.json()["baseline_sample_count"] == 15
    assert compare.json()["current_sample_count"] == 15
    # Analysis must never mutate the authoritative assessment.
    assert before == after


def test_endpoint_rejects_limit_below_two():
    with TestClient(create_app()) as client:
        client.post("/api/v1/simulation/generate", json={"pump_id": "pump-01", "scenario": "normal", "sample_count": 5})
        response = client.get("/api/v1/pumps/pump-01/telemetry/analysis", params={"limit": 1})
    assert response.status_code == 422


def test_analysis_and_compare_are_scoped_to_requested_client_session():
    with TestClient(create_app()) as client:
        for session, seed in (("browser-a", 11), ("browser-b", 27)):
            generated = client.post("/api/v1/simulation/generate", json={
                "pump_id": "shared-pump", "scenario": "bearing_wear", "random_seed": seed,
                "sample_count": 8, "client_session_id": session,
            })
            assert generated.status_code == 200
        analysis_a = client.get("/api/v1/pumps/shared-pump/telemetry/analysis",
                                params={"limit": 8, "client_session_id": "browser-a"})
        analysis_b = client.get("/api/v1/pumps/shared-pump/telemetry/analysis",
                                params={"limit": 8, "client_session_id": "browser-b"})
        compare = client.get("/api/v1/pumps/shared-pump/telemetry/analysis/compare",
                             params={"current": 3, "baseline": 3, "client_session_id": "browser-b"})
    assert analysis_a.status_code == analysis_b.status_code == compare.status_code == 200
    assert analysis_a.json()["sample_count"] == analysis_b.json()["sample_count"] == 8
    assert analysis_a.json()["metrics"] != analysis_b.json()["metrics"]
    assert compare.json()["baseline_sample_count"] == compare.json()["current_sample_count"] == 3


def test_analysis_rejects_malformed_client_session_id():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/pumps/p1/telemetry/analysis",
                              params={"client_session_id": "bad session!"})
    assert response.status_code == 422

