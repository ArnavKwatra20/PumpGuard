import json

import httpx
from fastapi.testclient import TestClient
from openai import OpenAI

from pumpguard.api.app import create_app
from pumpguard.services.diagnostics.providers import AmdProvider, ProviderTimedOut, _CHAT_SYSTEM_INSTRUCTIONS
from pumpguard.services.diagnostics.chat import _normalize_chat_content, _validate_numeric_grounding


def seed_request():
    return {"pump_id": "chat-pump", "scenario": "bearing_wear", "sample_count": 4,
            "sampling_interval_seconds": 1, "random_seed": 9}


class RecordingChatProvider:
    name = "mock"

    def __init__(self, response="The latest backend evidence shows a warning condition."):
        self.response = response
        self.requests = []
        self.contexts = []

    async def diagnose(self, request):
        return {}

    async def chat(self, request, context):
        self.requests.append(request)
        self.contexts.append(context)
        return self.response


def test_chat_builds_context_from_authoritative_backend_state_and_returns_response():
    provider = RecordingChatProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        generated = client.post("/api/v1/simulation/generate", json=seed_request()).json()
        response = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "Why is this pump showing a warning?",
            "history": [{"role": "user", "content": "What changed?"}],
        })
    assert response.status_code == 200, response.text
    assert response.json()["assistant_message"] == provider.response
    assert provider.requests[0].question.startswith("Why is this pump")
    assert provider.contexts[0]["latest_telemetry"]["pump_id"] == "chat-pump"
    assert provider.contexts[0]["current_rule_assessment"]["health_score"] == generated["assessment"]["health_score"]


def test_chat_rejects_browser_supplied_telemetry_and_unknown_pump():
    with TestClient(create_app(diagnostic_provider=RecordingChatProvider())) as client:
        extra = client.post("/api/v1/diagnostics/chat", json={"pump_id": "chat-pump", "question": "Hi", "telemetry": []})
        unknown = client.post("/api/v1/diagnostics/chat", json={"pump_id": "missing", "question": "Hi"})
    assert extra.status_code == 422
    assert unknown.status_code == 404


def test_chat_bounds_question_and_history():
    with TestClient(create_app(diagnostic_provider=RecordingChatProvider())) as client:
        long_question = client.post("/api/v1/diagnostics/chat", json={"pump_id": "chat-pump", "question": "x" * 2001})
        too_many = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "Hi",
            "history": [{"role": "user", "content": "x"}] * 9,
        })
    assert long_question.status_code == 422
    assert too_many.status_code == 422


def test_chat_provider_failure_preserves_rule_assessment():
    class FailingProvider(RecordingChatProvider):
        async def chat(self, request, context):
            raise ProviderTimedOut("AMD diagnostic chat request timed out")

    with TestClient(create_app(diagnostic_provider=FailingProvider())) as client:
        generated = client.post("/api/v1/simulation/generate", json={**seed_request(), "scenario": "overheating"}).json()
        response = client.post("/api/v1/diagnostics/chat", json={"pump_id": "chat-pump", "question": "What happened?"})
        assessment = client.get("/api/v1/pumps/chat-pump/assessment").json()
    assert response.status_code == 504
    assert "No AMD-generated response was produced" in response.json()["detail"]
    assert "rule-based assessment remains authoritative" in response.json()["detail"]
    assert assessment == generated["assessment"]


def test_chat_empty_provider_content_is_rejected():
    with TestClient(create_app(diagnostic_provider=RecordingChatProvider("   "))) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/chat", json={"pump_id": "chat-pump", "question": "Explain this"})
    assert response.status_code == 502


def test_chat_normalizes_escaped_bold_and_rejects_corrupted_unit_text():
    with TestClient(create_app(diagnostic_provider=RecordingChatProvider(r"\*\*warning\*\* based on the current rule."))) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        normalized = client.post("/api/v1/diagnostics/chat", json={"pump_id": "chat-pump", "question": "Summarize the status"})
    assert normalized.status_code == 200, normalized.text
    assert normalized.json()["assistant_message"] == "**warning** based on the current rule."

    with TestClient(create_app(diagnostic_provider=RecordingChatProvider("The trend lasted 10 secondsasian."))) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        malformed = client.post("/api/v1/diagnostics/chat", json={"pump_id": "chat-pump", "question": "Summarize the status"})
    assert malformed.status_code == 200, malformed.text
    assert malformed.json()["assistant_message"] == "The trend lasted 10 seconds asian."

    with TestClient(create_app(diagnostic_provider=RecordingChatProvider("The thresholdaine bandsaine response is not readable."))) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        corrupted = client.post("/api/v1/diagnostics/chat", json={"pump_id": "chat-pump", "question": "Summarize the status"})
    assert corrupted.status_code == 502


def test_chat_normalizer_separates_glued_units_without_regex_failure():
    assert _normalize_chat_content("The trend lasted 10 secondsasian.") == "The trend lasted 10 seconds asian."


def test_chat_grounding_keeps_flow_and_context_counts_out_of_wrong_metric_families():
    context = {
        "sample_count": 24,
        "latest_telemetry": {"flow_rate": 48.0, "load_percent": 65.0, "cooling_effectiveness": 0.8},
        "current_rule_assessment": {"health_score": 100},
    }
    text = "The last 24 samples show flow 48 m3/h, load 65%, cooling effectiveness 0.8, and health score 100."
    _validate_numeric_grounding(text, context)


def test_chat_grounding_prefers_preceding_general_label_over_later_metric():
    context = {"latest_telemetry": {"cooling_effectiveness": 0.8, "temperature": 44.7}}
    _validate_numeric_grounding("Cooling effectiveness is 0.8 and bearing temperature is 44.7 °C.", context)


def test_chat_grounding_does_not_use_distant_metric_marker_for_range_values():
    context = {"configured_thresholds": {"rpm_low": 1650, "rpm_high": 1900}, "temperature": 64.7}
    _validate_numeric_grounding("RPM range is 1650–1900 in the normal band. Temperature is 64.7 °C.", context)


def test_chat_rejects_html_and_unbalanced_markdown_in_provider_text():
    for content in ("<script>alert(1)</script>", "**unclosed warning"):
        with TestClient(create_app(diagnostic_provider=RecordingChatProvider(content))) as client:
            client.post("/api/v1/simulation/generate", json=seed_request())
            response = client.post("/api/v1/diagnostics/chat", json={"pump_id": "chat-pump", "question": "Explain this"})
        assert response.status_code == 502


def test_chat_rejects_numerical_claims_not_present_in_authoritative_context(caplog):
    with TestClient(create_app(diagnostic_provider=RecordingChatProvider("The measured value is 999.9 mm/s."))) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/chat", json={"pump_id": "chat-pump", "question": "Explain this"})
    assert response.status_code == 502
    messages = [record.getMessage() for record in caplog.records if "grounding rejected" in record.getMessage()]
    assert messages
    assert "token='999.9'" in messages[-1]
    assert "metric_family=vibration" in messages[-1]
    assert len(messages[-1]) < 260


def test_chat_allows_qualitative_and_numbered_inspection_recommendations():
    for content in (
        "Inspect the bearings, alignment, lubrication, and mounting before any repair.",
        "1. Inspect the bearings.\n2. Check alignment and lubrication.",
    ):
        with TestClient(create_app(diagnostic_provider=RecordingChatProvider(content))) as client:
            client.post("/api/v1/simulation/generate", json=seed_request())
            response = client.post("/api/v1/diagnostics/chat", json={
                "pump_id": "chat-pump", "question": "What should an engineer inspect first?",
            })
        assert response.status_code == 200, response.text


def test_chat_accepts_exact_and_rounded_context_telemetry_values():
    for content in (
        "The measured vibration is 6.55 mm/s.",
        "The measured vibration is 6.6 mm/s after rounding.",
    ):
        with TestClient(create_app(diagnostic_provider=RecordingChatProvider(content))) as client:
            client.post("/api/v1/simulation/generate", json=seed_request())
            response = client.post("/api/v1/diagnostics/chat", json={
                "pump_id": "chat-pump", "question": "Which telemetry signal supports this?",
            })
        assert response.status_code == 200, response.text


def test_chat_accepts_authoritative_threshold_values_with_metric_family():
    content = "Temperature remains below the 85 °C high threshold, and vibration remains below the 4.5 mm/s threshold."
    with TestClient(create_app(diagnostic_provider=RecordingChatProvider(content))) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "What should an engineer inspect first?",
        })
    assert response.status_code == 200, response.text


def test_chat_associates_adjacent_supported_values_with_their_nearest_metric():
    content = ("Temperature remains below the 85 °C threshold; vibration remains below 4.5 mm/s. "
               "Sound remains below 85 dB and RPM stays within 1650–1900 rpm.")
    with TestClient(create_app(diagnostic_provider=RecordingChatProvider(content))) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "What should an engineer inspect first?",
        })
    assert response.status_code == 200, response.text


def test_chat_allows_supported_value_but_rejects_unsupported_numeric_claim(caplog):
    content = "Inspect the bearing first; vibration is 6.55 mm/s, but the increase is 42.0%."
    with TestClient(create_app(diagnostic_provider=RecordingChatProvider(content))) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "What should an engineer inspect first?",
        })
    assert response.status_code == 502
    messages = [record.getMessage() for record in caplog.records if "grounding rejected" in record.getMessage()]
    assert messages and "token='42.0'" in messages[-1]


def test_amd_chat_retries_once_with_grounding_feedback_and_accepts_corrected_answer():
    class CorrectingAMDProvider(RecordingChatProvider):
        name = "amd"

        def __init__(self):
            super().__init__()
            self.responses = [
                "The vibration is 999.9 mm/s; inspect the bearing.",
                "The rule assessment supports inspecting the bearing and vibration sensor.",
            ]

        async def chat(self, request, context):
            self.requests.append(request)
            self.contexts.append(context)
            return self.responses[len(self.requests) - 1]

    provider = CorrectingAMDProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "What should I inspect?",
        })

    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "amd"
    assert response.json()["is_mock"] is False
    assert response.json()["assistant_message"] == provider.responses[1]
    assert len(provider.requests) == 2
    assert "999.9 (vibration)" in provider.contexts[1]["_numeric_grounding_feedback"]
    assert "_numeric_grounding_feedback" not in provider.contexts[0]


def test_amd_chat_fails_closed_after_one_unsupported_numeric_retry():
    class StillUnsupportedAMDProvider(RecordingChatProvider):
        name = "amd"

        def __init__(self):
            super().__init__()

        async def chat(self, request, context):
            self.requests.append(request)
            self.contexts.append(context)
            return "The vibration is 999.9 mm/s; inspect the bearing."

    provider = StillUnsupportedAMDProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "What should I inspect?",
        })
        assessment = client.get("/api/v1/pumps/chat-pump/assessment")

    assert response.status_code == 502
    assert "No AMD-generated response was produced" in response.json()["detail"]
    assert len(provider.requests) == 2
    assert "999.9 (vibration)" in provider.contexts[1]["_numeric_grounding_feedback"]
    assert assessment.status_code == 200


def test_mock_chat_does_not_retry_numeric_grounding_failures():
    provider = RecordingChatProvider("The vibration is 999.9 mm/s; inspect the bearing.")
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "What should I inspect?",
        })

    assert response.status_code == 502
    assert len(provider.requests) == 1


def test_chat_condition_change_question_accepts_grounded_trend_values_and_rejects_unsupported_change_claim(caplog):
    class ConditionChangeProvider(RecordingChatProvider):
        async def chat(self, request, context):
            metric = next(item for item in context["recorded_trend_analysis"]["metrics"]
                          if item["metric"] == "vibration_mm_s")
            if "unsupported" in request.question:
                return "Vibration changed by 37.5%, which is unsupported by the supplied context."
            return (f"Vibration changed from {metric['first_value']:.1f} mm/s to "
                    f"{metric['latest_value']:.1f} mm/s in the supplied trend window. "
                    "Inspect the bearing and alignment before drawing a physical diagnosis.")

    with TestClient(create_app(diagnostic_provider=ConditionChangeProvider())) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        grounded = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "How has the pump condition changed?",
        })
        unsupported = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "How has the pump condition changed? unsupported",
        })
    assert grounded.status_code == 200, grounded.text
    assert unsupported.status_code == 502, unsupported.text
    rejection = [record.getMessage() for record in caplog.records if "grounding rejected" in record.getMessage()]
    assert rejection and "token='37.5'" in rejection[-1]


def test_chat_rejects_unsupported_measurements_thresholds_and_sample_counts():
    for content in (
        "The measured vibration is 999.9 mm/s.",
        "The threshold is 100 °C.",
        "The window contains 99 samples.",
    ):
        with TestClient(create_app(diagnostic_provider=RecordingChatProvider(content))) as client:
            client.post("/api/v1/simulation/generate", json=seed_request())
            response = client.post("/api/v1/diagnostics/chat", json={
                "pump_id": "chat-pump", "question": "Explain the current evidence.",
            })
        assert response.status_code == 502, (content, response.text)


def test_chat_ignores_asset_identifiers_timestamps_and_fault_name_numbers():
    content = ("The latest telemetry window (19:17:05 to 19:17:16 UTC) shows the current trend. "
               "Pump pump-01 reported fault-2 at 2026-10-14T13:12:36.745555Z; "
               "inspect the rotating assembly.")
    with TestClient(create_app(diagnostic_provider=RecordingChatProvider(content))) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "What should an engineer inspect first?",
        })
    assert response.status_code == 200, response.text


def amd_client(handler):
    return OpenAI(base_url="https://amd.example/v1", api_key="unit-test-secret",
                  http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_amd_chat_uses_final_content_not_reasoning_and_validates_envelope():
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash"}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "Use the measured vibration value for the next inspection.",
            "reasoning_content": "This hidden reasoning must not be shown."}}]})

    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=amd_client(handler))
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/chat", json={"pump_id": "chat-pump", "question": "What should I inspect?"})
    assert response.status_code == 200, response.text
    assert response.json()["assistant_message"].startswith("Use the measured")
    assert "reasoning" not in response.text.lower()


def test_amd_adapter_sends_grounding_feedback_as_system_instruction_and_revalidates():
    chat_requests = []

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash"}]})
        body = json.loads(request.content)
        chat_requests.append(body)
        content = ("The vibration is 999.9 mm/s; inspect the bearing." if len(chat_requests) == 1
                   else "Inspect the vibration sensor and bearing based on the current assessment.")
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": content}}]})

    provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=amd_client(handler))
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "chat-pump", "question": "What should I inspect?",
        })

    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "amd"
    assert response.json()["is_mock"] is False
    assert len(chat_requests) == 2
    retry_system = chat_requests[1]["messages"][0]["content"]
    retry_context = chat_requests[1]["messages"][1]["content"]
    assert "999.9 (vibration)" in retry_system
    assert "_numeric_grounding_feedback" not in retry_context


def test_amd_chat_prompt_forbids_unseen_numeric_estimates():
    assert "never estimate, interpolate" in _CHAT_SYSTEM_INSTRUCTIONS
    assert "omit it and state that the evidence is insufficient" in _CHAT_SYSTEM_INSTRUCTIONS


def test_amd_chat_rejects_empty_malformed_truncated_and_upstream_502_responses():
    cases = [
        (200, {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}, 502),
        (200, {"choices": []}, 502),
        (200, {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}, 502),
        (502, {"detail": "gateway"}, 503),
    ]
    for status, payload, expected in cases:
        def handler(request, status=status, payload=payload):
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": "DeepSeek-V4-Flash"}]})
            return httpx.Response(status, json=payload)

        provider = AmdProvider("https://amd.example/v1", "DeepSeek-V4-Flash", "unit-test-secret", client=amd_client(handler))
        with TestClient(create_app(diagnostic_provider=provider)) as client:
            client.post("/api/v1/simulation/generate", json=seed_request())
            response = client.post("/api/v1/diagnostics/chat", json={"pump_id": "chat-pump", "question": "Explain this"})
        assert response.status_code == expected, response.text

