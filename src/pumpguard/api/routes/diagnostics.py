"""Explicit operator-triggered diagnostic inference endpoint."""
import asyncio
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from pumpguard.models.diagnostic import (
    DiagnosticRequest, DiagnosticResult, DiagnosticTelemetry, DetectorEvidence,
    HealthAssessmentEvidence, MLPredictionEvidence,
)
from pumpguard.services.diagnostics.providers import ProviderInvalidResponse, ProviderRateLimited, ProviderTimedOut, ProviderUnsupportedModel, ProviderUnavailable
from pumpguard.services.diagnostics.service import DiagnosticTimeout
from pumpguard.services.health_service import assess_reading
from pumpguard.services.telemetry_service import UnknownPumpError

router = APIRouter(tags=["diagnostics"])
MAX_DIAGNOSTIC_REQUEST_BYTES = 32 * 1024


@router.get("/diagnostics/status", summary="Diagnostic provider availability")
def diagnostic_status(request: Request) -> dict[str, object]:
    provider = request.app.state.diagnostic_service.provider
    if provider.name == "mock":
        return {"provider": "mock", "state": "mock_test_mode", "available": True,
                "is_mock": True, "configured": False, "model": None}
    configured = bool(getattr(provider, "configured", False))
    return {"provider": provider.name,
            "state": "amd_configured" if configured else "amd_unconfigured",
            # This is configuration readiness, not a live upstream health check.
            "available": configured, "is_mock": False, "configured": configured,
            "model": getattr(provider, "model", None)}


@router.get("/diagnostics/models", summary="Inspect AMD Token Factory model catalog")
async def diagnostic_models(request: Request) -> dict[str, object]:
    provider = request.app.state.diagnostic_service.provider
    if provider.name == "mock":
        return {"configured": False, "models": [], "capabilities_verified": False}
    if not getattr(provider, "configured", False):
        raise HTTPException(status_code=503, detail="AMD API key is not configured")
    try:
        models = await provider.list_models()
        return {"configured": True, "models": models,
                "capabilities_verified": any(model.get("capabilities_verified") for model in models)}
    except ProviderRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": "1"}) from exc
    except ProviderTimedOut as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/diagnostics", response_model=DiagnosticResult,
             summary="Request structured AMD demo explanation",
             openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": DiagnosticRequest.model_json_schema()}}}})
async def diagnose(request: Request) -> DiagnosticResult:
    """Bound and validate request bytes before dispatching to the configured provider."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_DIAGNOSTIC_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="Diagnostic request exceeds the 32 KiB limit")
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        payload = DiagnosticRequest.model_validate_json(body)
    except ValidationError as exc:
        errors = [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
        raise HTTPException(status_code=422, detail=errors) from exc
    if payload.client_session_id:
        try:
            stored = request.app.state.telemetry.history(
                payload.pump_id, limit=1000, client_session_id=payload.client_session_id,
            )
        except UnknownPumpError as exc:
            raise HTTPException(status_code=409,
                detail="Diagnostic telemetry session is unavailable; generate a fresh simulation and retry.") from exc
        stored_oldest_first = list(reversed(stored))
        # A dashboard tick can arrive between the last rendered reading and this
        # request. Match the exact submitted window ending at its assessment time,
        # while excluding any later backend samples from this request's evidence.
        eligible = [reading for reading in stored_oldest_first
                    if reading.timestamp <= payload.assessment_timestamp]
        expected_window = eligible[-len(payload.telemetry):]
        canonical_window = [DiagnosticTelemetry.from_reading(reading) for reading in expected_window]
        if (not expected_window or expected_window[-1].timestamp != payload.assessment_timestamp
                or canonical_window != payload.telemetry):
            raise HTTPException(status_code=409,
                detail="Diagnostic telemetry does not match the selected session evidence window; refresh the assessment and retry.")
        authoritative_assessment = assess_reading(expected_window[-1])
        payload = payload.model_copy(update={
            "telemetry": canonical_window,
            "detector": DetectorEvidence(
                status=authoritative_assessment.status,
                score=authoritative_assessment.health_score,
                predicted_faults=authoritative_assessment.detected_faults,
                confidence=None,
            ),
            "assessment": HealthAssessmentEvidence.model_validate(
                authoritative_assessment.model_dump(exclude={"pump_id", "timestamp", "detected_faults"})
            ),
        })
    try:
        ml_prediction = await asyncio.to_thread(request.app.state.ml_inference.predict, payload.telemetry)
        if ml_prediction:
            payload = payload.model_copy(update={"ml_prediction": MLPredictionEvidence.model_validate(ml_prediction)})
        return await request.app.state.diagnostic_service.diagnose(payload)
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
