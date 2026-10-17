"""AMD-backed maintenance, telemetry, and scenario demo explanations."""
from dataclasses import asdict, is_dataclass
from fastapi import APIRouter, HTTPException, Request

from pumpguard.detection.rules import DEFAULT_THRESHOLDS
from pumpguard.models.ai_feature import AiFeatureRequest, AiFeatureResponse
from pumpguard.models.diagnostic_chat import DiagnosticChatRequest
from pumpguard.api.provider_errors import provider_http_error
from pumpguard.services.diagnostics.providers import DiagnosticProviderError
from pumpguard.services.diagnostics.service import DiagnosticTimeout
from pumpguard.services.health_service import assess_reading
from pumpguard.services.telemetry_service import UnknownPumpError

router = APIRouter(tags=["ai-features"])


_QUESTIONS = {
    "maintenance_planner": (
        "Create a concise AI-generated demo maintenance plan using the selected pump's telemetry, calculated trends, "
        "thresholds, and simulator context. Include the evidence that informed your recommendations, qualified-engineer "
        "inspection steps, a priority and rationale, possible consequences as possibilities, and missing information. "
        "Do not invent parts, costs, history, durations, or confirmed physical defects."
    ),
    "telemetry_explanation": (
        "Explain the calculated telemetry trends: which signals changed, their direction and computed values, how they "
        "relate to the configured thresholds and monitoring context when relevant, and what cannot be concluded. Do not "
        "recalculate, invent trends, or claim correlation proves causation."
    ),
    "scenario_analyst": (
        "Explain the recorded simulator scenario using the snapshot, events, telemetry, calculated trends, and available "
        "monitoring context. Identify the observed sequence and thresholds, label consequences as possibilities, and state "
        "what evidence is missing. Do not invent a scenario history or physical failure."
    ),
}


@router.post("/diagnostics/ai-feature", response_model=AiFeatureResponse,
             summary="Generate an AMD-backed maintenance, telemetry, or scenario explanation")
async def ai_feature(payload: AiFeatureRequest, request: Request) -> AiFeatureResponse:
    try:
        readings = request.app.state.telemetry.history(
            payload.pump_id, limit=24, client_session_id=payload.client_session_id,
        )
        latest = readings[0]
    except (UnknownPumpError, IndexError) as exc:
        raise HTTPException(status_code=404, detail=f"Unknown pump_id: {payload.pump_id}") from exc

    assessment = assess_reading(latest)
    analysis = request.app.state.telemetry_analysis.analyze(payload.pump_id, readings)
    snapshot = request.app.state.live_simulation.snapshot(payload.pump_id, payload.client_session_id)
    latest_payload = latest.model_dump(mode="json")
    context = {
        "feature": payload.feature,
        "authoritative_context": True,
        "latest_telemetry": latest_payload,
        "recent_telemetry": [item.model_dump(mode="json") for item in reversed(readings)],
        "sample_count": len(readings),
        "current_rule_assessment": assessment.model_dump(mode="json"),
        "deterministic_telemetry_analysis": analysis.model_dump(mode="json"),
        "recorded_simulation_snapshot": snapshot if snapshot is not None else {},
        "live_session_available": snapshot is not None,
        "configured_thresholds": [asdict(threshold) if is_dataclass(threshold) else dict(threshold)
                                  for threshold in DEFAULT_THRESHOLDS],
        "context_limits": [
            "All telemetry and simulator records are synthetic backend records.",
            "Configured thresholds are the server rule-engine definitions and may be cited exactly.",
            "No physical inspection, inventory, cost, maintenance history, or repair duration is available.",
            "A missing live simulation snapshot means this session has no recorded live scenario; do not infer one from batch telemetry.",
            "Use all supplied context to explain the telemetry; do not alter measurements or monitoring state.",
        ],
    }
    chat_request = DiagnosticChatRequest(pump_id=payload.pump_id, question=_QUESTIONS[payload.feature])
    provider_name = request.app.state.diagnostic_chat_service.provider.name
    try:
        result = await request.app.state.diagnostic_chat_service.respond(chat_request, context)
    except (DiagnosticProviderError, DiagnosticTimeout) as exc:
        raise provider_http_error(exc, provider_name, include_context=True) from exc
    return AiFeatureResponse(feature=payload.feature, assistant_message=result.assistant_message,
                             provider=result.provider, is_mock=result.is_mock, latency_ms=result.latency_ms,
                             evidence_timestamp=latest_payload["timestamp"])
