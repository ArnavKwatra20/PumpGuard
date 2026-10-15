"""Deterministic fault-relationship and cascading-failure endpoints.

Read-only: these routes derive component/fault relationships from the current
rule-based assessment and never mutate detector, telemetry, or ML state.
"""
from fastapi import APIRouter, HTTPException, Request

from pumpguard.models.relationships import RelationshipAnalysis
from pumpguard.services.health_service import assess_reading
from pumpguard.services.telemetry_service import UnknownPumpError

router = APIRouter(tags=["relationships"])


@router.get("/pumps/{pump_id}/relationships", response_model=RelationshipAnalysis,
            summary="Fault-relationship and cascading-failure analysis")
def relationships(pump_id: str, request: Request) -> RelationshipAnalysis:
    """Analyze the latest assessment against the deterministic fault graph."""
    try:
        reading = request.app.state.telemetry.latest(pump_id)
    except UnknownPumpError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown pump_id: {pump_id}") from exc
    assessment = assess_reading(reading)
    return request.app.state.relationships.analyze(assessment)


@router.get("/relationships/catalog", summary="Component and fault relationship catalog")
def catalog() -> dict[str, object]:
    """Return the static knowledge base (components, faults, relationships)."""
    from pumpguard.relationships.knowledge import components_for, fault_definitions, relationships as rels
    # asset_id is a placeholder here; consumers bind components to an asset themselves.
    return {
        "components": [c.model_dump() for c in components_for("__catalog__")],
        "faults": [f.model_dump() for f in fault_definitions()],
        "relationships": [r.model_dump() for r in rels()],
        "generator": "deterministic_graph",
        "note": "Relationships are engineering hypotheses with provenance, not confirmed causes.",
    }
