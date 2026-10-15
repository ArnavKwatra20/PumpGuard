from fastapi.testclient import TestClient

from pumpguard.api.app import create_app
from pumpguard.services.diagnostics.providers import ProviderTimedOut


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


def test_ai_feature_provider_failure_is_explicit_and_does_not_replace_rules():
    class FailingProvider(RecordingProvider):
        async def chat(self, request, context):
            raise ProviderTimedOut("AMD diagnostic chat request timed out")

    with TestClient(create_app(diagnostic_provider=FailingProvider())) as client:
        generated = client.post("/api/v1/simulation/generate", json=seed_request()).json()
        response = client.post("/api/v1/diagnostics/ai-feature", json={
            "pump_id": "feature-pump", "feature": "maintenance_planner",
        })
        assessment = client.get("/api/v1/pumps/feature-pump/assessment").json()
    assert response.status_code == 504
    assert assessment == generated["assessment"]


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
