import pytest
from fastapi.testclient import TestClient

from pumpguard.api.app import create_app
from pumpguard.services.diagnostics.providers import ProviderRateLimited, ProviderTimedOut, ProviderUnavailable


def seed_request():
    return {"pump_id": "feature-pump", "scenario": "overheating", "sample_count": 8,
            "sampling_interval_seconds": 1, "random_seed": 17}


class RecordingProvider:
    name = "mock"

    def __init__(self, response="The draft uses only the authoritative synthetic backend context."):
        self.response = response
        self.contexts = []

    async def diagnose(self, request):
        return {}

    async def chat(self, request, context):
        self.contexts.append(context)
        return self.response


def test_ai_features_reuse_deterministic_context_and_return_each_feature():
    provider = RecordingProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        generated = client.post("/api/v1/simulation/generate", json=seed_request())
        assert generated.status_code == 200
        for feature in ("maintenance_planner", "telemetry_explanation", "scenario_analyst"):
            response = client.post("/api/v1/diagnostics/ai-feature", json={
                "pump_id": "feature-pump", "feature": feature,
            })
            assert response.status_code == 200, response.text
            assert response.json()["feature"] == feature
            assert response.json()["evidence_timestamp"] == provider.contexts[-1]["latest_telemetry"]["timestamp"]
            context = provider.contexts[-1]
            assert context["authoritative_context"] is True
            assert context["deterministic_telemetry_analysis"]["generator"] == "deterministic_analysis"
            assert context["current_rule_assessment"]["status"] == generated.json()["assessment"]["status"]
            assert any(item["metric"] == "vibration_mm_s" and item["high"] == 4.5
                       for item in context["configured_thresholds"])
            assert context["context_limits"]
            assert context["sample_count"] == len(context["recent_telemetry"])


def test_all_advertised_ai_features_return_amd_output_without_grounding_gate():
    class AMDProvider(RecordingProvider):
        name = "amd"

        def __init__(self):
            super().__init__("The vibration increased from 1.91 to 7.30 mm/s in this explanation.")

    provider = AMDProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        assert client.post("/api/v1/simulation/generate", json=seed_request()).status_code == 200
        for feature in ("maintenance_planner", "telemetry_explanation", "scenario_analyst"):
            response = client.post("/api/v1/diagnostics/ai-feature", json={
                "pump_id": "feature-pump", "feature": feature,
            })
            assert response.status_code == 200, response.text
            assert response.json()["assistant_message"] == provider.response
            assert response.json()["provider"] == "amd"
            assert response.json()["is_mock"] is False
            assert provider.contexts[-1]["feature"] == feature
    assert len(provider.contexts) == 3


def test_amd_ai_features_have_no_pumpguard_request_count_cap():
    class AMDProvider(RecordingProvider):
        name = "amd"

        def __init__(self):
            super().__init__("AMD demo explanation.")
            self.diagnostic_calls = 0

        async def diagnose(self, request):
            self.diagnostic_calls += 1
            return {
                "summary": "Synthetic demo explanation.",
                "hypotheses": [{
                    "cause": "Synthetic vibration variation",
                    "rank": 1,
                    "uncertainty": "moderate",
                    "evidence": [{
                        "source": "telemetry", "field": "vibration_mm_s",
                        "metric": "vibration_mm_s", "reading_index": 0,
                        "value": request.telemetry[0].vibration_mm_s,
                    }],
                    "missing_evidence": [],
                }],
                "missing_evidence": [],
                "inspection_steps": ["Inspect the synthetic vibration trend."],
                "priority": "routine",
                "priority_rationale": "Demo output only.",
                "limitations": ["Synthetic telemetry only."],
                "human_review_required": True,
            }

    provider = AMDProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        assert client.post("/api/v1/simulation/generate", json=seed_request()).status_code == 200
        structured_request = {
            "pump_id": "feature-pump", "assessment_timestamp": "2026-10-17T00:00:00Z",
            "telemetry": [{
                "timestamp": "2026-10-17T00:00:00Z", "temperature_c": 60,
                "vibration_mm_s": 2, "sound_db": 70, "rpm": 1750,
                "pressure_kpa": 300, "load_percent": 50,
            }],
            "detector": {"status": "normal", "score": 100, "predicted_faults": [], "confidence": None},
        }
        structured = [client.post("/api/v1/diagnostics", json=structured_request) for _ in range(11)]
        chat = [client.post("/api/v1/diagnostics/chat", json={
            "pump_id": "feature-pump", "question": "Explain the current synthetic telemetry.",
        }) for _ in range(11)]
        features = [client.post("/api/v1/diagnostics/ai-feature", json={
            "pump_id": "feature-pump", "feature": "scenario_analyst",
        }) for _ in range(11)]

    assert [response.status_code for response in structured] == [200] * 11
    assert [response.status_code for response in chat] == [200] * 11
    assert [response.status_code for response in features] == [200] * 11
    assert provider.diagnostic_calls == 11  # Identical requests still get fresh AMD generations.
    assert len(provider.contexts) == 22


def test_ai_feature_accepts_configured_thresholds_repeated_in_provider_prose():
    provider = RecordingProvider(
        "Temperature remains below the 85 °C threshold; vibration remains below 4.5 mm/s. "
        "The configured RPM range is 1650–1900 rpm and sound threshold is 85 dB."
    )
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        generated = client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/ai-feature", json={
            "pump_id": "feature-pump", "feature": "maintenance_planner",
        })
    assert generated.status_code == 200
    assert response.status_code == 200, response.text


def test_ai_feature_uses_live_session_snapshot_when_available():
    provider = RecordingProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        live = client.post("/api/v1/simulation/live-sample", json={
            "pump_id": "feature-pump", "scenario": "cavitation", "client_session_id": "feature-session",
            "reset_session": True, "random_seed": 4,
        })
        assert live.status_code == 200, live.text
        response = client.post("/api/v1/diagnostics/ai-feature", json={
            "pump_id": "feature-pump", "feature": "scenario_analyst", "client_session_id": "feature-session",
        })
    assert response.status_code == 200, response.text
    assert provider.contexts[0]["recorded_simulation_snapshot"]["scenario"] == "cavitation"


def test_ai_feature_telemetry_is_scoped_to_the_selected_session():
    provider = RecordingProvider()
    with TestClient(create_app(diagnostic_provider=provider)) as client:
        other = client.post("/api/v1/simulation/generate", json={
            **seed_request(), "client_session_id": "other-session", "start_time": "2026-10-16T00:00:00Z",
        }).json()
        selected = client.post("/api/v1/simulation/generate", json={
            **seed_request(), "scenario": "bearing_wear", "client_session_id": "selected-session",
            "start_time": "2026-10-17T00:00:00Z",
        }).json()
        response = client.post("/api/v1/diagnostics/ai-feature", json={
            "pump_id": "feature-pump", "feature": "telemetry_explanation",
            "client_session_id": "selected-session",
        })

    assert response.status_code == 200, response.text
    context = provider.contexts[0]
    assert context["latest_telemetry"]["timestamp"] == selected["readings"][-1]["timestamp"]
    assert context["sample_count"] == len(selected["readings"])
    assert context["latest_telemetry"]["timestamp"] != other["readings"][-1]["timestamp"]


def test_ai_feature_provider_failure_is_explicit_and_does_not_replace_rules():
    class FailingProvider(RecordingProvider):
        name = "amd"
        async def chat(self, request, context):
            raise ProviderTimedOut("AMD diagnostic chat request timed out")

    with TestClient(create_app(diagnostic_provider=FailingProvider())) as client:
        generated = client.post("/api/v1/simulation/generate", json=seed_request()).json()
        response = client.post("/api/v1/diagnostics/ai-feature", json={
            "pump_id": "feature-pump", "feature": "maintenance_planner",
        })
        assessment = client.get("/api/v1/pumps/feature-pump/assessment").json()
    assert response.status_code == 504
    assert "No response from AMD was produced" in response.json()["detail"]
    assert "existing monitoring data remains unchanged" in response.json()["detail"]
    assert assessment == generated["assessment"]


@pytest.mark.parametrize(("error", "status", "detail"), [
    (ProviderRateLimited("AMD request rate limit reached"), 429, "AMD request rate limit reached"),
    (ProviderUnavailable("AMD credentials were rejected"), 503, "AMD credentials were rejected"),
])
def test_ai_feature_reports_amd_rate_limit_and_auth_errors(error, status, detail):
    class FailingAMDProvider(RecordingProvider):
        name = "amd"

        async def chat(self, request, context):
            raise error

    with TestClient(create_app(diagnostic_provider=FailingAMDProvider())) as client:
        client.post("/api/v1/simulation/generate", json=seed_request())
        response = client.post("/api/v1/diagnostics/ai-feature", json={
            "pump_id": "feature-pump", "feature": "maintenance_planner",
        })

    assert response.status_code == status
    assert detail in response.json()["detail"]
    assert "No response from AMD was produced" in response.json()["detail"]


def test_ai_feature_rejects_unknown_pump_and_extra_fields():
    with TestClient(create_app(diagnostic_provider=RecordingProvider())) as client:
        unknown = client.post("/api/v1/diagnostics/ai-feature", json={
            "pump_id": "missing", "feature": "telemetry_explanation",
        })
        extra = client.post("/api/v1/diagnostics/ai-feature", json={
            "pump_id": "feature-pump", "feature": "telemetry_explanation", "telemetry": [],
        })
    assert unknown.status_code == 404
    assert extra.status_code == 422
