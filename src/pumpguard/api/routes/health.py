"""Application liveness endpoint."""
from fastapi import APIRouter
router=APIRouter(tags=["health"])
@router.get("/health",summary="Application health",description="Reports that the API process is responding.")
def health() -> dict[str, str]:
    """Return liveness state."""
    return {"status":"ok","service":"pumpguard-api"}
