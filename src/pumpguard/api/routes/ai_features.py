"""Optional AMD-backed maintenance, telemetry, and scenario explanations."""
from fastapi import APIRouter, HTTPException, Request

from pumpguard.detection.rules import DEFAULT_THRESHOLDS
from pumpguard.models.ai_feature import AiFeatureRequest, AiFeatureResponse
from pumpguard.models.diagnostic_chat import DiagnosticChatRequest
from pumpguard.services.diagnostics.providers import (
    ProviderInvalidResponse, ProviderRateLimited, ProviderTimedOut, ProviderUnavailable,
    ProviderUnsupportedModel,
)
from pumpguard.services.diagnostics.service import DiagnosticTimeout
from pumpguard.services.health_service import assess_reading
from pumpguard.services.telemetry_service import UnknownPumpError

router = APIRouter(tags=["ai-features"])

_QUESTIONS = {
    "maintenance_planner": (
        "Create a concise AI-generated draft maintenance plan. Include only the current rule finding, exact supporting "
        "evidence, qualified-engineer inspection steps, priority justified by the backend assessment, possible consequences "
        "as possibilities, and missing information. Do not invent parts, costs, history, durations, or confirmed physical defects."
    ),
    "telemetry_explanation": (
        "Explain the deterministic telemetry analysis: which signals changed, their direction and computed values, "
        "which deviations support the rule assessment, and what cannot be concluded. Do not recalculate, invent trends, "
        "or claim correlation proves causation."
    ),
    "scenario_analyst": (
        "Explain the recorded simulator scenario using only the authoritative snapshot, events, telemetry analysis, and "
        "rule assessment. Identify observed sequence and thresholds, label consequences as possibilities, and state what "
        "evidence is missing. Do not invent a scenario history or physical failure."
    ),
}


@router.post("/diagnostics/ai-feature", response_model=AiFeatureResponse,
             summary="Generate a bounded AMD-backed maintenance or telemetry explanation")
async def ai_feature(payload: AiFeatureRequest, request: Request) -> AiFeatureResponse:
    try:
        readings = request.app.state.telemetry.history(payload.pump_id, limit=24)
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
        "recorded_simulation_snapshot": snapshot,
        "configured_thresholds": [threshold.__dict__ for threshold in DEFAULT_THRESHOLDS],
        "context_limits": [
            "All telemetry and simulator records are synthetic backend records.",
            "Configured thresholds are the server rule-engine definitions and may be cited exactly.",
            "No physical inspection, inventory, cost, maintenance history, or repair duration is available.",
            "The rule-based assessment remains authoritative; AMD text is an interpretation or draft only.",
        ],
    }
    chat_request = DiagnosticChatRequest(pump_id=payload.pump_id, question=_QUESTIONS[payload.feature])
    try:
        result = await request.app.state.diagnostic_chat_service.respond(chat_request, context)
    except DiagnosticTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ProviderRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "1"}) from exc
    except ProviderTimedOut as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ProviderInvalidResponse as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ProviderUnsupportedModel as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AiFeatureResponse(feature=payload.feature, assistant_message=result.assistant_message,
                             provider=result.provider, is_mock=result.is_mock, latency_ms=result.latency_ms,
                             evidence_timestamp=latest_payload["timestamp"])
