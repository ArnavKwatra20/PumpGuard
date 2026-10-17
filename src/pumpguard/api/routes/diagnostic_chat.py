"""Server-context conversational diagnostic endpoint."""
from fastapi import APIRouter, HTTPException, Request

from pumpguard.models.diagnostic_chat import DiagnosticChatRequest, DiagnosticChatResponse
from pumpguard.detection.rules import DEFAULT_THRESHOLDS
from pumpguard.api.provider_errors import provider_http_error
from pumpguard.services.diagnostics.providers import DiagnosticProviderError
from pumpguard.services.diagnostics.service import DiagnosticTimeout
from pumpguard.services.health_service import assess_reading
from pumpguard.services.telemetry_service import UnknownPumpError

router = APIRouter(tags=["diagnostics"])


@router.post("/diagnostics/chat", response_model=DiagnosticChatResponse,
             summary="Ask a bounded evidence-context diagnostic question")
async def diagnostic_chat(payload: DiagnosticChatRequest, request: Request) -> DiagnosticChatResponse:
    """Build authoritative context from backend state; browser context is never trusted."""
    try:
        readings = request.app.state.telemetry.history(payload.pump_id, limit=12,
                                                       client_session_id=payload.client_session_id)
        latest = readings[0]
    except (UnknownPumpError, IndexError) as exc:
        raise HTTPException(status_code=404, detail=f"Unknown pump_id: {payload.pump_id}") from exc

    assessment = assess_reading(latest)
    analysis = request.app.state.telemetry_analysis.analyze(payload.pump_id, readings)
    context = {
        "pump_id": payload.pump_id,
        "latest_telemetry": latest.model_dump(mode="json"),
        "recent_telemetry": [item.model_dump(mode="json") for item in reversed(readings)],
        "sample_count": len(readings),
        "current_rule_assessment": assessment.model_dump(mode="json"),
        "recorded_trend_analysis": analysis.model_dump(mode="json"),
        "configured_thresholds": [threshold.__dict__ for threshold in DEFAULT_THRESHOLDS],
        "context_limits": [
            "Telemetry and assessment are synthetic backend records.",
            "Configured thresholds are the server rule-engine definitions and may be cited exactly.",
            "No backend-persisted alert history or physical inspection result is available in this chat context.",
        ],
    }
    provider_name = request.app.state.diagnostic_chat_service.provider.name
    try:
        return await request.app.state.diagnostic_chat_service.respond(payload, context)
    except (DiagnosticProviderError, DiagnosticTimeout) as exc:
        raise provider_http_error(exc, provider_name, include_context=True) from exc
