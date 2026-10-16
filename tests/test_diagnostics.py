import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pumpguard.api.app import create_app
from pumpguard.models.diagnostic import DiagnosticRequest
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
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_MOCK_MODE", "timeout")
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 504


def test_amd_provider_starts_without_credentials_but_reports_unavailable(monkeypatch):
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_PROVIDER", "amd")
    monkeypatch.delenv("RADEON_API_KEY", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        status = client.get("/api/v1/diagnostics/status").json()
        result = client.post("/api/v1/diagnostics", json=request_body())
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


def test_invalid_mock_configuration_is_rejected():
    with pytest.raises(ValueError):
        MockDiagnosticProvider("real_amd")


def test_unsupported_evidence_claims_are_rejected_as_invalid_provider_output():
    class UnsupportedEvidenceProvider:
        name = "mock"

        async def diagnose(self, request):
            result = await MockDiagnosticProvider().diagnose(request)
            result["hypotheses"][0]["evidence"][0]["value"] = 99
            return result

    with TestClient(create_app(diagnostic_provider=UnsupportedEvidenceProvider())) as client:
        response = client.post("/api/v1/diagnostics", json=request_body())
    assert response.status_code == 502


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
    messages = [record.getMessage() for record in caplog.records if "unsupported-prose-number" in record.getMessage()]
    assert messages and "token='8.2'" in messages[-1]


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
    monkeypatch.delenv("RADEON_BASE_URL", raising=False)
    monkeypatch.delenv("RADEON_MODEL", raising=False)
    monkeypatch.delenv("RADEON_API_KEY", raising=False)
    settings = get_settings()
    assert settings.radeon_base_url == "https://developer.amd.com.cn/radeon/api/v1"
    assert settings.radeon_model == "DeepSeek-V4-Flash"
    assert settings.radeon_api_key is None
    monkeypatch.setenv("RADEON_BASE_URL", "http://unsafe.example/v1")
    with pytest.raises(ValueError, match="HTTPS"):
        get_settings()


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
    assert sent[0]["max_tokens"] == 700
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


def test_amd_openai_envelope_rejects_partial_content_and_ignores_reasoning_content():
    """A successful AMD HTTP envelope is not a valid PumpGuard diagnosis by itself."""
    import httpx
    import json
    from openai import OpenAI
    from pumpguard.services.diagnostics.providers import AmdProvider

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash", "json_output": True}]})
        # This mirrors the observed OpenAI-compatible envelope: content is the
        # generated answer, while reasoning_content is a separate field.
        return httpx.Response(200, json={"id": "chatcmpl-test", "object": "chat.completion", "created": 1,
            "model": "DeepSeek-V4-Flash", "choices": [{"index": 0, "finish_reason": "stop",
                "matched_stop": None, "logprobs": None,
                "message": {"role": "assistant", "content": json.dumps({"summary": "partial"}),
                             "reasoning_content": "A complete-looking rationale must not be used as the answer."}}],
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
