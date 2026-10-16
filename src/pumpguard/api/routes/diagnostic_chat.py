"""Server-context conversational diagnostic endpoint."""
from fastapi import APIRouter, HTTPException, Request

from pumpguard.models.diagnostic_chat import DiagnosticChatRequest, DiagnosticChatResponse
from pumpguard.detection.rules import DEFAULT_THRESHOLDS
from pumpguard.services.diagnostics.providers import (
    ProviderInvalidResponse, ProviderRateLimited, ProviderTimedOut, ProviderUnavailable,
    ProviderUnsupportedModel,
)
from pumpguard.services.diagnostics.service import DiagnosticTimeout
from pumpguard.services.health_service import assess_reading
from pumpguard.services.telemetry_service import UnknownPumpError

router = APIRouter(tags=["diagnostics"])


def _provider_failure_detail(exc: Exception) -> str:
    return (f"{exc}. No AMD-generated response was produced; "
            "the rule-based assessment remains authoritative.")


@router.post("/diagnostics/chat", response_model=DiagnosticChatResponse,
             summary="Ask a bounded evidence-context diagnostic question")
async def diagnostic_chat(payload: DiagnosticChatRequest, request: Request) -> DiagnosticChatResponse:
    """Build authoritative context from backend state; browser context is never trusted."""
    try:
        readings = request.app.state.telemetry.history(payload.pump_id, limit=12)
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
    try:
        return await request.app.state.diagnostic_chat_service.respond(payload, context)
    except DiagnosticTimeout as exc:
        raise HTTPException(status_code=504, detail=_provider_failure_detail(exc)) from exc
    except ProviderRateLimited as exc:
        raise HTTPException(status_code=429, detail=_provider_failure_detail(exc), headers={"Retry-After": "1"}) from exc
    except ProviderTimedOut as exc:
        raise HTTPException(status_code=504, detail=_provider_failure_detail(exc)) from exc
    except ProviderInvalidResponse as exc:
        raise HTTPException(status_code=502, detail=_provider_failure_detail(exc)) from exc
    except ProviderUnsupportedModel as exc:
        raise HTTPException(status_code=422, detail=_provider_failure_detail(exc)) from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=_provider_failure_detail(exc)) from exc
