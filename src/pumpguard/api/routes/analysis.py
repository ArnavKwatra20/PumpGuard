"""Deterministic telemetry-intelligence endpoints (read-only, no AMD calls)."""
from fastapi import APIRouter, HTTPException, Query, Request

from pumpguard.models.telemetry_analysis import ComparisonResult, TelemetryAnalysis
from pumpguard.services.telemetry_service import UnknownPumpError

router = APIRouter(tags=["analysis"])


@router.get("/pumps/{pump_id}/telemetry/analysis", response_model=TelemetryAnalysis,
            summary="Deterministic trend, rate, rolling-stats, and excursion analysis")
def analyze(pump_id: str, request: Request, limit: int = Query(120, ge=2, le=1000)) -> TelemetryAnalysis:
    """Analyze the most recent window of recorded telemetry for one asset.

    Computations are deterministic and local; no hosted model is contacted, and the
    rule-based diagnostic engine is never modified here.
    """
    try:
        readings = request.app.state.telemetry.history(pump_id, limit=limit)
    except UnknownPumpError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown pump_id: {pump_id}") from exc
    return request.app.state.telemetry_analysis.analyze(pump_id, readings)


@router.get("/pumps/{pump_id}/telemetry/analysis/compare", response_model=ComparisonResult,
            summary="Compare a baseline window against a current window")
def compare(pump_id: str, request: Request, current: int = Query(30, ge=2, le=500),
            baseline: int = Query(30, ge=2, le=500)) -> ComparisonResult:
    """Compare the most recent ``current`` samples against the preceding ``baseline`` samples."""
    try:
        readings = request.app.state.telemetry.history(pump_id, limit=current + baseline)
    except UnknownPumpError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown pump_id: {pump_id}") from exc
    # history is newest-first; the newest `current` are the current window, the rest baseline.
    current_readings = readings[:current]
    baseline_readings = readings[current:current + baseline]
    return request.app.state.telemetry_analysis.compare(pump_id, baseline_readings, current_readings)
