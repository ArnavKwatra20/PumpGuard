import asyncio
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pumpguard.api.app import create_app
from pumpguard.models.diagnostic import DiagnosticContent, DiagnosticRequest
from pumpguard.services.diagnostics.providers import MockDiagnosticProvider, ProviderInvalidResponse, ProviderRateLimited
from pumpguard.services.diagnostics.service import DiagnosticService


def request_body():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "pump_id": "pump-01", "simulation_id": "session-a", "alert_episode_id": "episode-7",
        "assessment_timestamp": now,
        "telemetry": [{"timestamp": now, "temperature_c": 69.5, "vibration_mm_s": 7.1,
                       "sound_db": 79, "rpm": 1762, "pressure_kpa": 320, "load_percent": 65}],
        "trends": [], "detector": {"status": "warning", "score": 65, "predicted_faults": ["bearing_wear"], "confidence": None},
        "is_synthetic": True, "selected_scenario": "bearing_wear", "injected_scenario": "bearing_wear",
        "alert": {"episode_id": "episode-7", "metric": "vibration_mm_s", "severity": "warning",
                  "observed_value": 7.1, "expected_range": "0–4.5 mm/s", "explanation": "High vibration"},
        "events": [{"time_seconds": 1, "kind": "fault_injected", "scenario": "bearing_wear"}],
    }


def diagnostic_reading(reading):
    return {field: reading[field] for field in (
        "timestamp", "temperature_c", "vibration_mm_s", "sound_db", "rpm", "pressure_kpa", "load_percent",
    )}


def test_mock_provider_returns_valid_explicitly_labeled_diagnostic():
    provider = MockDiagnosticProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        assert client.get("/api/v1/diagnostics/status").json() == {
            "provider": "mock", "state": "mock_test_mode", "available": True,
            "is_mock": True, "configured": False, "model": None,
        }
        response = client.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 200
    result = response.json()
    assert result["is_mock"] is True and result["provider"] == "mock"
    assert result["human_review_required"] is True
    assert result["hypotheses"][0]["evidence"][0]["value"] == 69.5
    assert result["latency_ms"] >= 0 and result["correlation_id"]


@pytest.mark.parametrize(("mode", "status"), [("rate_limit", 429), ("malformed", 502), ("unavailable", 503)])
def test_provider_failure_modes_are_mapped_safely(mode, status):
    with TestClient(create_app(diagnostic_provider=MockDiagnosticProvider(mode))) as client:
        response = client.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == status
    assert "credential" not in response.text.lower()


def test_mismatched_trend_window_is_rejected_before_provider_call():
    class RecordingProvider:
        name = "amd"
        calls = 0
        async def diagnose(self, request):
            self.calls += 1
            return {}
    provider = RecordingProvider()
    body = request_body()
    body["trends"] = [{"metric": "vibration_mm_s", "initial_value": 6.0, "latest_value": 7.5,
                       "delta": 1.5, "elapsed_seconds": 1, "samples": 2}]
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        response = client.post("/api/v1/diagnostics", json=body)
    assert response.status_code == 502
    assert provider.calls == 0


def test_backend_derives_provider_trends_from_the_exact_submitted_telemetry_window():
    class TrendRecordingProvider:
        name = "mock"
        trends = None

        async def diagnose(self, request):
            self.trends = request.trends
            return await MockDiagnosticProvider().diagnose(request)

    provider = TrendRecordingProvider()
    body = request_body()
    body["telemetry"] = [
        {**body["telemetry"][0], "timestamp": "2026-10-17T00:00:00Z", "vibration_mm_s": 6.0},
        {**body["telemetry"][0], "timestamp": "2026-10-17T00:00:13Z", "vibration_mm_s": 7.5},
    ]
    body["trends"] = []
    body["assessment_timestamp"] = "2026-10-17T00:00:13Z"

    with TestClient(create_app(diagnostic_provider=provider)) as client:
        response = client.post("/api/v1/diagnostics", json=body)

    assert response.status_code == 200, response.text
    vibration = next(item for item in provider.trends if item.metric == "vibration_mm_s")
    assert (vibration.initial_value, vibration.latest_value, vibration.delta) == (6.0, 7.5, 1.5)
    assert (vibration.elapsed_seconds, vibration.samples) == (13, 2)


def test_diagnostic_uses_the_exact_window_from_its_backend_session_and_recomputes_assessment():
    class RecordingProvider:
        name = "mock"
        request = None

        async def diagnose(self, request):
            self.request = request
            return await MockDiagnosticProvider().diagnose(request)

    provider = RecordingProvider()
    session_id = "diagnostic-window"
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        generated = client.post("/api/v1/simulation/generate", json={
            "pump_id": "pump-01", "scenario": "bearing_wear", "sample_count": 4,
            "sampling_interval_seconds": 1, "random_seed": 41,
            "client_session_id": session_id,
        })
        assert generated.status_code == 200, generated.text
        selected = [diagnostic_reading(item) for item in generated.json()["readings"][-2:]]
        body = request_body()
        body.update({
            "client_session_id": session_id,
            "assessment_timestamp": selected[-1]["timestamp"],
            "telemetry": selected,
            "trends": [],
        })
        response = client.post("/api/v1/diagnostics", json=body)

    assert response.status_code == 200, response.text
    assert [item.timestamp.isoformat() for item in provider.request.telemetry] == [
        datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")).isoformat() for item in selected
    ]
    assert [item.vibration_mm_s for item in provider.request.telemetry] == [
        item["vibration_mm_s"] for item in selected
    ]
    assert provider.request.assessment.status == generated.json()["assessment"]["status"]
    assert provider.request.assessment.health_score == generated.json()["assessment"]["health_score"]
    assert provider.request.detector.status == provider.request.assessment.status
    assert provider.request.detector.score == provider.request.assessment.health_score


def test_diagnostic_rejects_another_sessions_window_before_provider_call():
    class RecordingProvider:
        name = "amd"
        calls = 0

        async def diagnose(self, request):
            self.calls += 1
            return {}

    provider = RecordingProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        old = client.post("/api/v1/simulation/generate", json={
            "pump_id": "pump-01", "scenario": "bearing_wear", "sample_count": 2,
            "sampling_interval_seconds": 1, "random_seed": 4,
            "client_session_id": "old-session", "start_time": "2026-10-16T00:00:00Z",
        }).json()
        current = client.post("/api/v1/simulation/generate", json={
            "pump_id": "pump-01", "scenario": "normal", "sample_count": 2,
            "sampling_interval_seconds": 1, "random_seed": 9,
            "client_session_id": "current-session", "start_time": "2026-10-17T00:00:00Z",
        }).json()
        body = request_body()
        body.update({
            "client_session_id": "current-session",
            "assessment_timestamp": old["readings"][-1]["timestamp"],
            "telemetry": [diagnostic_reading(item) for item in old["readings"]],
            "trends": [],
        })
        response = client.post("/api/v1/diagnostics", json=body)

    assert response.status_code == 409
    assert "does not match the selected session evidence window" in response.json()["detail"]
    assert provider.calls == 0
    assert current["readings"][-1]["timestamp"] != old["readings"][-1]["timestamp"]


def test_diagnostic_cache_key_is_scoped_to_session_and_exact_telemetry_window():
    first = DiagnosticRequest.model_validate(request_body())
    second_body = request_body()
    second_body["telemetry"][0]["vibration_mm_s"] = 7.2
    second = DiagnosticRequest.model_validate(second_body)
    third_body = request_body()
    third_body["client_session_id"] = "another-session"
    third = DiagnosticRequest.model_validate(third_body)

    assert DiagnosticService._key(first) != DiagnosticService._key(second)
    assert DiagnosticService._key(first) != DiagnosticService._key(third)


def test_diagnostic_request_rejects_duplicate_telemetry_timestamps():
    body = request_body()
    body["telemetry"] *= 2
    with pytest.raises(ValidationError, match="timestamps must be unique"):
        DiagnosticRequest.model_validate(body)


def test_trend_elapsed_accepts_only_javascript_millisecond_precision_difference():
    body = request_body()
    body["telemetry"] = [
        {**body["telemetry"][0], "timestamp": "2025-01-01T00:00:00.123900Z", "vibration_mm_s": 6.0},
        {**body["telemetry"][0], "timestamp": "2025-01-01T00:00:01.124100Z", "vibration_mm_s": 7.5},
    ]
    # Date.parse truncates these timestamp fractions to milliseconds (1.001 s),
    # while Python computes the exact difference (1.0002 s).
    body["trends"] = [{"metric": "vibration_mm_s", "initial_value": 6.0, "latest_value": 7.5,
                       "delta": 1.5, "elapsed_seconds": 1.001, "samples": 2}]
    DiagnosticService._validate_request_trends(DiagnosticRequest.model_validate(body))


def test_trend_elapsed_rejects_a_difference_beyond_browser_timestamp_precision():
    body = request_body()
    body["telemetry"] = [
        {**body["telemetry"][0], "timestamp": "2025-01-01T00:00:00.123900Z", "vibration_mm_s": 6.0},
        {**body["telemetry"][0], "timestamp": "2025-01-01T00:00:01.124100Z", "vibration_mm_s": 7.5},
    ]
    body["trends"] = [{"metric": "vibration_mm_s", "initial_value": 6.0, "latest_value": 7.5,
                       "delta": 1.5, "elapsed_seconds": 1.003, "samples": 2}]
    with pytest.raises(ProviderInvalidResponse, match="does not match its telemetry evidence window"):
        DiagnosticService._validate_request_trends(DiagnosticRequest.model_validate(body))


def test_timeout_is_bounded_and_returns_gateway_timeout(monkeypatch):
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_CATALOG_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_COMPLETION_TIMEOUT_SECONDS", "0.05")
    class SlowAMDProvider:
        name = "amd"

        async def diagnose(self, request):
            await asyncio.sleep(60)

    with TestClient(create_app(diagnostic_provider=SlowAMDProvider())) as client:
        response = client.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 504


def test_amd_provider_starts_without_credentials_but_reports_unavailable(monkeypatch):
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_PROVIDER", "amd")
    monkeypatch.delenv("RADEON_API_KEY", raising=False)
    with TestClient(create_app()) as client:
        health = client.get("/health")
        simulation = client.post("/api/v1/simulation/generate", json={"pump_id": "pump-no-key", "scenario": "bearing_wear"})
        status = client.get("/api/v1/diagnostics/status").json()
        result = client.post("/api/v1/diagnostics", json=request_body())
    assert health.status_code == 200
    assert simulation.status_code == 200, simulation.text
    assert status["provider"] == "amd_unavailable" and status["state"] == "amd_unconfigured"
    assert status["available"] is False
    assert status["configured"] is False and "RADEON_API_KEY" not in str(status)
    assert result.status_code == 503


def test_amd_status_marks_credentials_as_configured_without_claiming_a_live_health_check(monkeypatch):
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_PROVIDER", "amd")
    monkeypatch.setenv("RADEON_API_KEY", "unit-test-secret")
    with TestClient(create_app()) as client:
        status = client.get("/api/v1/diagnostics/status").json()
    assert status == {
        "provider": "amd", "state": "amd_configured", "available": True,
        "is_mock": False, "configured": True, "model": "DeepSeek-V4-Flash",
    }


def test_diagnostic_input_is_bounded_and_rejects_inconsistent_episode():
    body = request_body()
    body["telemetry"] *= 13
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/diagnostics", json=body)
        too_large = client.post("/api/v1/diagnostics", content=b" " * (32 * 1024 + 1), headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert too_large.status_code == 413
    mismatch = request_body()
    mismatch["alert_episode_id"] = "another-episode"
    with pytest.raises(ValidationError):
        DiagnosticRequest.model_validate(mismatch)


def test_duplicate_episode_requests_share_inflight_result_and_cache():
    provider = MockDiagnosticProvider()
    service = DiagnosticService(provider)
    parsed = DiagnosticRequest.model_validate(request_body())

    async def call_twice():
        first, second = await asyncio.gather(service.diagnose(parsed), service.diagnose(parsed))
        later = await service.diagnose(parsed)
        return first, second, later

    first, second, later = asyncio.run(call_twice())
    assert provider.calls == 1
    assert first.correlation_id == second.correlation_id
    assert second.cached is True
    assert later.cached is True and provider.calls == 1
    assert second.shared_inflight is True
    assert later.shared_inflight is False


def test_duplicate_amd_requests_are_labeled_shared_inflight_not_offline_cache():
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowAMDProvider:
        name = "amd"

        async def diagnose(self, request):
            started.set()
            await release.wait()
            return await MockDiagnosticProvider().diagnose(request)

    service = DiagnosticService(SlowAMDProvider())
    parsed = DiagnosticRequest.model_validate(request_body())

    async def call_twice():
        first_task = asyncio.create_task(service.diagnose(parsed))
        await started.wait()
        second_task = asyncio.create_task(service.diagnose(parsed))
        await asyncio.sleep(0)
        release.set()
        return await asyncio.gather(first_task, second_task)

    first, second = asyncio.run(call_twice())
    assert first.provider == second.provider == "amd"
    assert first.shared_inflight is False
    assert second.shared_inflight is True and second.cached is True


def test_invalid_mock_configuration_is_rejected():
    with pytest.raises(ValueError):
        MockDiagnosticProvider("real_amd")


def test_unsupported_evidence_claims_are_rejected_with_safe_reference_metadata(caplog):
    class UnsupportedEvidenceProvider:
        name = "mock"

        async def diagnose(self, request):
            result = await MockDiagnosticProvider().diagnose(request)
            result["hypotheses"][0]["evidence"][0]["value"] = 99
            return result

    with TestClient(create_app(diagnostic_provider=UnsupportedEvidenceProvider())) as client:
        response = client.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 502
    messages = [record.getMessage() for record in caplog.records if "evidence_value_mismatch" in record.getMessage()]
    assert messages
    assert "source=telemetry" in messages[-1]
    assert "field=temperature_c" in messages[-1]
    assert "value_type=float" in messages[-1]
    assert "99" not in messages[-1]


def test_grounded_numeric_prose_is_allowed_but_unsupported_numeric_prose_is_rejected(caplog):
    class NumericProseProvider:
        name = "mock"

        async def diagnose(self, request):
            result = await MockDiagnosticProvider().diagnose(request)
            result["summary"] = "The measured vibration is 7.1 mm/s; inspect the bearing."
            return result

    with TestClient(create_app(diagnostic_provider=NumericProseProvider())) as client:
        accepted = client.post("/api/v1/diagnostics", json=request_body())
    assert accepted.status_code == 200, accepted.text

    class UnsupportedNumericProseProvider(NumericProseProvider):
        async def diagnose(self, request):
            result = await super().diagnose(request)
            result["summary"] = "The measured vibration is 8.2 mm/s; inspect the bearing."
            return result

    with TestClient(create_app(diagnostic_provider=UnsupportedNumericProseProvider())) as client:
        rejected = client.post("/api/v1/diagnostics", json=request_body())
    assert rejected.status_code == 502
    assert rejected.json()["detail"] == "Diagnostic prose contains unsupported numerical evidence"
    messages = [record.getMessage() for record in caplog.records if "grounding rejected" in record.getMessage()]
    assert messages and "reason=trend_role_mismatch" in messages[-1]
    assert "metric_family=vibration" in messages[-1]
    assert "8.2" not in messages[-1]


def _trend_grounding_fixture(summary: str, evidence: list[dict[str, object]]):
    body = request_body()
    values = [6.0, 6.2, 1.91, 6.5, 6.7, 6.9, 7.0, 7.1, 7.2, 7.3, 7.4, 7.5]
    origin = datetime(2026, 10, 17, tzinfo=timezone.utc)
    body["telemetry"] = [
        {**body["telemetry"][0], "timestamp": (origin.replace(second=index)).isoformat(), "vibration_mm_s": value}
        for index, value in enumerate(values)
    ]
    body["trends"] = []
    request = DiagnosticRequest.model_validate(body)
    request = request.model_copy(update={"trends": DiagnosticService._calculate_request_trends(request)})
    content = DiagnosticContent.model_validate({
        "summary": summary,
        "hypotheses": [{"cause": "Possible bearing wear", "rank": 1, "uncertainty": "high",
                        "evidence": evidence, "missing_evidence": []}],
        "missing_evidence": [], "inspection_steps": ["Inspect the bearing safely."],
        "priority": "soon", "priority_rationale": "The rule assessment is a warning.",
        "limitations": ["Synthetic telemetry needs physical verification."], "human_review_required": True,
    })
    return content, request


def test_structured_diagnostic_rejects_the_reported_trend_window_mismatch():
    content, request = _trend_grounding_fixture(
        "Vibration increased from 1.91 to 7.30 mm/s.",
        [
            {"source": "telemetry", "field": "vibration_mm_s", "metric": "vibration_mm_s", "reading_index": 2, "value": 1.91},
            {"source": "telemetry", "field": "vibration_mm_s", "metric": "vibration_mm_s", "reading_index": 9, "value": 7.3},
        ],
    )
    trend = next(item for item in request.trends if item.metric == "vibration_mm_s")
    assert (trend.initial_value, trend.latest_value) == (6.0, 7.5)
    with pytest.raises(ProviderInvalidResponse, match="unsupported numerical evidence"):
        DiagnosticService._validate_grounding(content, request)


def test_structured_diagnostic_accepts_the_authoritative_trend_pair():
    content, request = _trend_grounding_fixture(
        "Vibration increased from 6.0 to 7.5 mm/s.",
        [
            {"source": "trend", "field": "initial_value", "metric": "vibration_mm_s", "value": 6.0},
            {"source": "trend", "field": "latest_value", "metric": "vibration_mm_s", "value": 7.5},
        ],
    )
    DiagnosticService._validate_grounding(content, request)


def test_structured_diagnostic_accepts_a_cited_rule_threshold_with_the_verified_trend():
    content, request = _trend_grounding_fixture(
        "Vibration increased from 6.0 to 7.5 mm/s. Warning at 7.5 mm/s against a 4.5 mm/s threshold.",
        [
            {"source": "trend", "field": "initial_value", "metric": "vibration_mm_s", "value": 6.0},
            {"source": "trend", "field": "latest_value", "metric": "vibration_mm_s", "value": 7.5},
            {"source": "alert", "field": "observed_value", "value": 7.5},
            {"source": "alert", "field": "expected_range", "value": "0–4.5 mm/s"},
        ],
    )
    request = request.model_copy(update={
        "alert": request.alert.model_copy(update={"observed_value": 7.5})
    })
    DiagnosticService._validate_grounding(content, request)


def test_structured_diagnostic_keeps_first_latest_and_delta_roles_distinct():
    content, request = _trend_grounding_fixture(
        "The vibration began at 6.0 mm/s and is now 7.5 mm/s; it increased by 1.5 mm/s.",
        [
            {"source": "trend", "field": "initial_value", "metric": "vibration_mm_s", "value": 6.0},
            {"source": "trend", "field": "latest_value", "metric": "vibration_mm_s", "value": 7.5},
            {"source": "trend", "field": "delta", "metric": "vibration_mm_s", "value": 1.5},
        ],
    )
    DiagnosticService._validate_grounding(content, request)


def test_structured_diagnostic_distinguishes_sample_count_from_elapsed_duration():
    content, request = _trend_grounding_fixture(
        "The vibration trend increased across 12 recorded samples.",
        [{"source": "trend", "field": "samples", "metric": "vibration_mm_s", "value": 12}],
    )
    DiagnosticService._validate_grounding(content, request)


def test_structured_diagnostic_rejects_a_number_without_a_metric_or_evidence_role():
    content, request = _trend_grounding_fixture(
        "The recorded value is 7.5.",
        [{"source": "trend", "field": "latest_value", "metric": "vibration_mm_s", "value": 7.5}],
    )
    with pytest.raises(ProviderInvalidResponse, match="unsupported numerical evidence"):
        DiagnosticService._validate_grounding(content, request)


@pytest.mark.parametrize("summary", [
    "Temperature increased from 6.0 to 7.5 mm/s.",
    "Vibration increased from 6.0 °C to 7.5 mm/s.",
    "Vibration increased from 6.0 mm/s to 7.5 dB.",
])
def test_structured_diagnostic_rejects_metric_and_unit_mismatches(summary):
    content, request = _trend_grounding_fixture(
        summary,
        [
            {"source": "trend", "field": "initial_value", "metric": "vibration_mm_s", "value": 6.0},
            {"source": "trend", "field": "latest_value", "metric": "vibration_mm_s", "value": 7.5},
        ],
    )
    with pytest.raises(ProviderInvalidResponse, match="unsupported numerical evidence"):
        DiagnosticService._validate_grounding(content, request)


@pytest.mark.parametrize("summary", [
    "The mean vibration was 7.5 mm/s.",
    "The minimum vibration was 7.5 mm/s.",
])
def test_structured_diagnostic_does_not_treat_trend_endpoint_as_other_statistic(summary):
    content, request = _trend_grounding_fixture(
        summary,
        [{"source": "trend", "field": "latest_value", "metric": "vibration_mm_s", "value": 7.5}],
    )
    with pytest.raises(ProviderInvalidResponse, match="unsupported numerical evidence"):
        DiagnosticService._validate_grounding(content, request)


def test_telemetry_evidence_rejects_a_mismatched_metric_association():
    class MismatchedMetricProvider:
        name = "mock"

        async def diagnose(self, request):
            result = await MockDiagnosticProvider().diagnose(request)
            result["hypotheses"][0]["evidence"][0]["metric"] = "vibration_mm_s"
            return result

    with TestClient(create_app(diagnostic_provider=MismatchedMetricProvider())) as client:
        response = client.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 502
    assert response.json()["detail"] == "Diagnostic telemetry evidence has an incorrect metric association"


def test_oversized_provider_output_is_rejected():
    class HugeProvider:
        name = "mock"

        async def diagnose(self, request):
            return {"summary": "x" * (33 * 1024)}

    with TestClient(create_app(diagnostic_provider=HugeProvider())) as client:
        response = client.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 502


def test_safe_rate_limit_retry_is_single_and_backed_off():
    class RetryProvider:
        name = "mock"

        def __init__(self):
            self.calls = 0
            self.success = MockDiagnosticProvider()

        async def diagnose(self, request):
            self.calls += 1
            if self.calls == 1:
                raise ProviderRateLimited(retry_after_seconds=.01, retry_safe=True)
            return await self.success.diagnose(request)

    provider = RetryProvider()
    service = DiagnosticService(provider, timeout_seconds=1)
    parsed = DiagnosticRequest.model_validate(request_body())
    result = asyncio.run(service.diagnose(parsed))
    assert result.provider == "mock"
    assert provider.calls == 2


def test_unverified_credentials_are_not_in_settings_repr(monkeypatch):
    from pumpguard.config import get_settings

    monkeypatch.setenv("RADEON_API_KEY", "test-secret-do-not-log")
    assert "test-secret-do-not-log" not in repr(get_settings())


def test_radeon_configuration_defaults_and_validation(monkeypatch):
    from pumpguard.config import get_settings
    monkeypatch.delenv("PUMPGUARD_DIAGNOSTIC_PROVIDER", raising=False)
    monkeypatch.delenv("RADEON_BASE_URL", raising=False)
    monkeypatch.delenv("RADEON_MODEL", raising=False)
    monkeypatch.delenv("RADEON_API_KEY", raising=False)
    settings = get_settings()
    assert settings.radeon_base_url == "https://developer.amd.com.cn/radeon/api/v1"
    assert settings.radeon_model == "DeepSeek-V4-Flash"
    assert settings.radeon_api_key is None
    assert settings.diagnostic_provider == "amd"
    monkeypatch.setenv("RADEON_BASE_URL", "http://unsafe.example/v1")
    with pytest.raises(ValueError, match="HTTPS"):
        get_settings()


def test_mock_provider_cannot_be_selected_as_a_runtime_provider(monkeypatch):
    from pumpguard.config import get_settings
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_PROVIDER", "mock")
    with pytest.raises(ValueError, match="must be amd"):
        get_settings()


def test_runtime_wires_one_amd_provider_to_all_ai_services(monkeypatch):
    from pumpguard.services.diagnostics.providers import AmdProvider
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_PROVIDER", "amd")
    monkeypatch.delenv("RADEON_API_KEY", raising=False)
    app = create_app()
    structured = app.state.diagnostic_service.provider
    chat = app.state.diagnostic_chat_service.provider
    assert isinstance(structured, AmdProvider)
    assert chat is structured
    assert structured.name == "amd_unavailable"


def _amd_trend_request_body():
    body = request_body()
    origin = datetime(2026, 10, 17, tzinfo=timezone.utc)
    values = [6.0, 1.91, 7.3, 7.5]
    body["telemetry"] = [
        {**body["telemetry"][0], "timestamp": origin.replace(second=index).isoformat(), "vibration_mm_s": value}
        for index, value in enumerate(values)
    ]
    body["assessment_timestamp"] = body["telemetry"][-1]["timestamp"]
    body["alert"]["observed_value"] = 7.5
    return body


@pytest.mark.parametrize(("summary", "evidence_value"), [
    ("Vibration increased from 1.91 to 7.30 mm/s.", 7.3),
    ("Vibration increased from 6.0 to 7.5 mm/s.", 7.5),
])
def test_amd_structured_explanation_renders_valid_schema_without_grounding_authorization(summary, evidence_value):
    class AmdNarrativeProvider:
        name = "amd"

        def __init__(self):
            self.request = None

        async def diagnose(self, request):
            self.request = request
            return {
                "summary": summary,
                "hypotheses": [{"cause": "Possible bearing wear", "rank": 1, "uncertainty": "high",
                    "evidence": [{"source": "trend", "field": "latest_value", "metric": "vibration_mm_s", "value": evidence_value}],
                    "missing_evidence": []}],
                "missing_evidence": [], "inspection_steps": ["Inspect the bearing safely."],
                "priority": "soon", "priority_rationale": "Demo explanation.",
                "limitations": ["Synthetic data."], "human_review_required": True,
            }

    provider = AmdNarrativeProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        response = client.post("/api/v1/diagnostics", json=_amd_trend_request_body())

    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "amd"
    assert response.json()["is_mock"] is False
    assert response.json()["summary"] == summary
    assert (provider.request.trends[1].initial_value, provider.request.trends[1].latest_value) == (6.0, 7.5)


def test_amd_schema_invalid_response_is_rejected_after_provider_success():
    class InvalidAMDProvider:
        name = "amd"
        calls = 0

        async def diagnose(self, request):
            self.calls += 1
            return {"summary": "A partial but successful provider response."}

    provider = InvalidAMDProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        response = client.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 502
    assert response.json()["detail"] == "Diagnostic provider returned an invalid response"
    assert provider.calls == 1


def test_diagnostic_provider_failure_does_not_mutate_detector_or_telemetry():
    with TestClient(create_app(diagnostic_provider=MockDiagnosticProvider("unavailable"))) as client:
        simulation = client.post("/api/v1/simulation/generate", json={"pump_id": "pump-alert", "scenario": "overheating", "random_seed": 4}).json()
        diagnostic = request_body()
        diagnostic["pump_id"] = "pump-alert"
        failure = client.post("/api/v1/diagnostics", json=diagnostic)
        assessment = client.get("/api/v1/pumps/pump-alert/assessment").json()
    assert simulation["assessment"]["status"] in {"warning", "critical"}
    assert failure.status_code == 503
    assert assessment == simulation["assessment"]


def test_amd_adapter_uses_verified_catalog_and_sends_only_bounded_evidence():
    import httpx
    import json
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    sent = []
    output = {"summary": "The supplied measurements show elevated vibration.",
        "hypotheses": [{"cause": "Possible bearing wear", "rank": 1, "uncertainty": "high",
            "evidence": [{"source": "telemetry", "field": "vibration_mm_s", "metric": "vibration_mm_s", "reading_index": 0, "value": 7.1}],
            "missing_evidence": ["Direct inspection"]}],
        "missing_evidence": ["Independent instrument confirmation"],
        "inspection_steps": ["Inspect the bearing under site safety procedures."],
        "priority": "soon", "priority_rationale": "Priority follows the supplied warning.",
        "limitations": ["Synthetic readings do not establish real equipment condition."], "human_review_required": True}

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash", "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}, "supported_parameters": ["max_tokens", "response_format"], "json_output": True, "providers": [{"streaming": True, "vision": False, "tools": True, "reasoning": True, "stability": "stable"}]}]})
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(200, json={"id": "chatcmpl-test", "object": "chat.completion", "created": 1,
            "model": "DeepSeek-V4-Flash", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(output)}}]})

    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    parsed = DiagnosticRequest.model_validate(request_body())
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        catalog = api.get("/api/v1/diagnostics/models")
        result = api.post("/api/v1/diagnostics", json=request_body())
    assert catalog.status_code == 200
    assert catalog.json()["models"][0]["id"] == "DeepSeek-V4-Flash"
    assert catalog.json()["models"][0]["capabilities_verified"] is True
    assert catalog.json()["models"][0]["capabilities"]["json_output"] is True
    assert result.status_code == 200, result.text
    assert result.json()["provider"] == "amd"
    assert "pump_id" not in sent[0]["messages"][1]["content"]
    assert "selected_scenario" not in sent[0]["messages"][1]["content"]
    sent_evidence = json.loads(sent[0]["messages"][1]["content"])
    assert sent_evidence["events"] == [{"time_seconds": 1.0, "kind": "fault_injected"}]
    assert "scenario" not in sent_evidence["events"][0]
    assert sent[0]["max_tokens"] == 1800
    assert sent[0]["response_format"] == {"type": "json_object"}
    contract = sent[0]["messages"][0]["content"]
    assert '"priority": exactly one of the JSON strings "routine", "soon", or "urgent"' in contract
    assert 'Never use shortened names such as "vibration", "temperature", or "pressure"' in contract
    client.close()


def test_diagnostic_evidence_value_is_required_by_schema():
    body = {
        "source": "telemetry", "field": "vibration_mm_s", "metric": "vibration_mm_s",
        "reading_index": 0,
    }
    from pumpguard.models.diagnostic import DiagnosticEvidenceReference
    with pytest.raises(ValidationError):
        DiagnosticEvidenceReference.model_validate(body)


def test_load_percent_is_a_supported_telemetry_evidence_metric():
    from pumpguard.models.diagnostic import DiagnosticEvidenceReference
    reference = DiagnosticEvidenceReference.model_validate({
        "source": "telemetry", "field": "load_percent", "metric": "load_percent",
        "reading_index": 0, "value": 65,
    })
    assert reference.metric == "load_percent"


def test_amd_schema_mismatch_is_rejected_without_coercion(caplog):
    import httpx
    import json
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    invalid = {
        "summary": "The supplied evidence warrants inspection.",
        "hypotheses": [{"cause": "Possible bearing wear", "rank": 1, "uncertainty": "high",
                        "evidence": [{"source": "telemetry", "field": "vibration_mm_s", "metric": "vibration",
                                      "reading_index": 0, "value": 7.1}], "missing_evidence": []}],
        "missing_evidence": ["Direct inspection"], "inspection_steps": ["Inspect the bearing."],
        "priority_rationale": "The rule assessment is a warning.",
        "limitations": ["Synthetic data requires human review."], "human_review_required": True,
    }

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash", "json_output": True}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(invalid)}}]})

    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret",
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    caplog.set_level("INFO")
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        response = api.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 502
    assert response.json()["detail"] == "Diagnostic provider returned an invalid response"
    assert "unit-test-secret" not in response.text
    assert "stage=json_parse outcome=valid" in caplog.text
    assert "stage=pydantic_validation outcome=invalid" in caplog.text
    assert "unit-test-secret" not in caplog.text
    client.close()


@pytest.mark.parametrize(("content", "detail"), [
    ('{"summary":', "AMD returned an invalid diagnostic response"),
    ("", "AMD returned an empty diagnostic response"),
    ("   \n", "AMD returned an empty diagnostic response"),
    (None, "AMD diagnostic content must be a string"),
    ('["not", "an", "object"]', "AMD diagnostic JSON must be an object"),
])
def test_amd_invalid_response_content_is_rejected_explicitly(content, detail):
    import httpx
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash", "json_output": True}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": content}}]})

    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret",
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        response = api.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 502
    assert response.json()["detail"] == detail
    assert "unit-test-secret" not in response.text
    client.close()


def test_amd_openai_envelope_rejects_partial_content_and_ignores_reasoning():
    """A successful AMD HTTP envelope is not a valid PumpGuard diagnosis by itself."""
    import httpx
    import json
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash", "json_output": True}]})
        # This mirrors the observed OpenAI-compatible envelope: content is the
        # generated answer, while reasoning is a separate provider field.
        return httpx.Response(200, json={"id": "chatcmpl-test", "object": "chat.completion", "created": 1,
            "model": "DeepSeek-V4-Flash", "choices": [{"index": 0, "finish_reason": "stop",
                "matched_stop": None, "logprobs": None,
                "message": {"role": "assistant", "content": json.dumps({"summary": "partial"}),
                             "reasoning": "A complete-looking rationale must not be used as the answer."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret",
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        response = api.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 502
    assert "reasoning" not in response.text.lower()
    assert "unit-test-secret" not in response.text
    client.close()


def test_amd_length_finish_reason_is_rejected_as_truncated_output():
    import httpx
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash", "json_output": True}]})
        return httpx.Response(200, json={"id": "chatcmpl-test", "object": "chat.completion", "created": 1,
            "model": "DeepSeek-V4-Flash", "choices": [{"index": 0, "finish_reason": "length",
                "message": {"role": "assistant", "content": '{"summary":"truncated'}}]})

    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret",
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        response = api.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 502
    assert response.json()["detail"] == "AMD diagnostic response was truncated by the output limit"
    assert '{"summary"' not in response.text
    client.close()


def test_amd_non_terminal_finish_reason_is_rejected():
    import httpx
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash", "json_output": True}]})
        return httpx.Response(200, json={"id": "chatcmpl-test", "object": "chat.completion", "created": 1,
            "model": "DeepSeek-V4-Flash", "choices": [{"index": 0, "finish_reason": "content_filter",
                "message": {"role": "assistant", "content": "{}"}}]})

    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret",
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        response = api.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 502
    assert response.json()["detail"] == "AMD returned an unsupported finish reason"
    client.close()


def test_amd_model_must_be_in_catalog_before_completion():
    import httpx
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    completion_calls = []
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [{"id": "another-model", "object": "model"}]})
        completion_calls.append(request)
        return httpx.Response(500)
    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        response = api.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 422
    assert completion_calls == []
    assert "unit-test-secret" not in response.text
    client.close()


@pytest.mark.parametrize("catalog_failure", ["server_error", "timeout", "connection"])
def test_amd_transient_catalog_failure_does_not_block_completion(catalog_failure):
    import httpx
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    calls = []
    structured = {
        "summary": "Synthetic telemetry warrants a qualified inspection.",
        "hypotheses": [{"cause": "Abnormal vibration", "rank": 1, "uncertainty": "high",
                        "evidence": [{"source": "telemetry", "field": "temperature_c", "metric": "temperature_c",
                                      "reading_index": 0, "value": 69.5}], "missing_evidence": []}],
        "missing_evidence": [], "inspection_steps": ["Inspect the rotating assembly under site procedures."],
        "priority": "soon", "priority_rationale": "The supplied alert warrants timely human review.",
        "limitations": ["Synthetic telemetry does not confirm a physical defect."], "human_review_required": True,
    }

    def handler(request):
        if request.url.path.endswith("/models"):
            calls.append("catalog")
            if catalog_failure == "server_error":
                return httpx.Response(503, json={"error": {"message": "temporary"}})
            if catalog_failure == "timeout":
                raise httpx.ReadTimeout("temporary", request=request)
            raise httpx.ConnectError("temporary", request=request)
        calls.append("completion")
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(structured)}}]})

    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        response = api.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "amd"
    assert calls == ["catalog", "completion"]
    assert "unit-test-secret" not in response.text
    client.close()


def test_amd_upstream_timeout_returns_504_without_sdk_retry(monkeypatch):
    import httpx
    from openai import OpenAI
    import pumpguard.services.diagnostics.providers as provider_module
    from pumpguard.services.diagnostics.providers import AmdProvider

    chat_attempts = []
    sdk_options = {}

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash"}]})
        chat_attempts.append(request)
        raise httpx.ReadTimeout("synthetic upstream timeout", request=request)

    def make_client(*, base_url, api_key, timeout, max_retries):
        sdk_options["max_retries"] = max_retries
        return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout,
                      max_retries=max_retries,
                      http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    monkeypatch.setattr(provider_module, "OpenAI", make_client)
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret")
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        response = api.post("/api/v1/diagnostics", json=request_body())

    assert sdk_options["max_retries"] == 0
    assert len(chat_attempts) == 1
    assert response.status_code == 504
    assert "unit-test-secret" not in response.text


def test_amd_upstream_error_returns_failure_without_mock_fallback():
    import httpx
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash", "json_output": True}]})
        return httpx.Response(503, json={"error": {"message": "provider unavailable"}})

    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret",
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        response = api.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 503
    assert response.json()["detail"] == "AMD gateway is temporarily unavailable"
    assert "mock" not in response.text.lower()
    assert "unit-test-secret" not in response.text
    client.close()


@pytest.mark.parametrize(("upstream_status", "expected_status", "detail"), [
    (401, 503, "AMD credentials were rejected"),
    (403, 503, "AMD credentials were rejected"),
    (429, 429, "AMD request rate limit reached"),
    (503, 503, "AMD gateway is temporarily unavailable"),
])
def test_amd_auth_rate_limit_and_upstream_errors_are_mapped_without_fallback(
    upstream_status, expected_status, detail,
):
    import httpx
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash"}]})
        return httpx.Response(upstream_status, json={"error": {"message": "provider failure"}})

    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret",
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        response = api.post("/api/v1/diagnostics", json=request_body())

    assert response.status_code == expected_status
    assert response.json()["detail"] == detail
    assert "unit-test-secret" not in response.text
    if upstream_status == 429:
        assert response.headers["retry-after"] == "1"
    client.close()


def test_strip_code_fence_removes_markdown_wrapper():
    from pumpguard.services.diagnostics.providers import _strip_code_fence

    fenced = '```json\n{"summary": "ok"}\n```'
    assert _strip_code_fence(fenced) == '{"summary": "ok"}'
    assert _strip_code_fence('```\n{"summary": "ok"}\n```') == '{"summary": "ok"}'
    # Non-fenced JSON is returned unchanged (trimmed).
    assert _strip_code_fence('  {"summary": "ok"}  ') == '{"summary": "ok"}'


def test_amd_fenced_json_response_is_parsed_successfully():
    import httpx
    import json
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    output = {"summary": "The supplied measurements show elevated vibration.",
        "hypotheses": [{"cause": "Possible bearing wear", "rank": 1, "uncertainty": "high",
            "evidence": [{"source": "telemetry", "field": "vibration_mm_s", "metric": "vibration_mm_s", "reading_index": 0, "value": 7.1}],
            "missing_evidence": ["Direct inspection"]}],
        "missing_evidence": ["Independent instrument confirmation"],
        "inspection_steps": ["Inspect the bearing under site safety procedures."],
        "priority": "soon", "priority_rationale": "Priority follows the supplied warning.",
        "limitations": ["Synthetic readings do not establish real equipment condition."], "human_review_required": True}

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash", "json_output": True}]})
        # Real models sometimes wrap JSON in a markdown fence even when JSON mode is requested.
        return httpx.Response(200, json={"id": "chatcmpl-test", "object": "chat.completion", "created": 1,
            "model": "DeepSeek-V4-Flash", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "```json\n" + json.dumps(output) + "\n```"}}]})

    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        result = api.post("/api/v1/diagnostics", json=request_body())
    assert result.status_code == 200, result.text
    assert result.json()["provider"] == "amd"
    assert result.json()["summary"] == output["summary"]
    client.close()


def test_amd_malformed_schema_returns_502_and_preserves_rule_result():
    import httpx
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash", "json_output": True}]})
        # Valid JSON but wrong schema (mirrors a real model inventing its own structure).
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 1,
            "model": "DeepSeek-V4-Flash", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": '{"schema_version":"1.0","diagnostic":{"ranked_hypotheses":[]}}'}}]})

    client = OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=client)
    with TestClient(create_app(diagnostic_provider=provider)) as api:
        simulation = api.post("/api/v1/simulation/generate", json={"pump_id": "pump-01", "scenario": "bearing_wear", "random_seed": 4}).json()
        diagnostic = request_body()
        diagnostic["pump_id"] = "pump-01"
        failure = api.post("/api/v1/diagnostics", json=diagnostic)
        assessment = api.get("/api/v1/pumps/pump-01/assessment").json()
    # Invalid provider output maps to 502; the rule-based assessment is untouched.
    assert failure.status_code == 502
    assert assessment == simulation["assessment"]
    client.close()
