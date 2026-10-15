"""Explicit model-compute diagnostics; these routes do not alter deterministic health state."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


@router.get("/status", summary="Inspect optional ML model and compute provider")
def ml_status(request: Request) -> dict[str, object]:
    return request.app.state.ml_inference.status()
