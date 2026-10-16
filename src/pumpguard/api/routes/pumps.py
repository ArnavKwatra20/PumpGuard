"""Pump inventory, telemetry, assessments, and simulation routes."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter,HTTPException,Query,Request
from pydantic import BaseModel,ConfigDict,Field
from pumpguard.models.telemetry import TelemetryReading
from pumpguard.models.assessment import HealthAssessment
class SimulationResponse(BaseModel):
    """Generated sensor readings, a separate label, and latest assessment."""
    scenario_label: str
    readings: list[TelemetryReading]
    assessment: HealthAssessment
    simulation: dict | None = None
from pumpguard.simulator.generator import TelemetryGenerator
from pumpguard.simulator.live import LiveSimulationService
from pumpguard.services.health_service import assess_reading
from pumpguard.services.telemetry_service import UnknownPumpError
router=APIRouter(tags=["pumps"])
class SimulationRequest(BaseModel):
    """Validated synthetic simulation parameters."""
    model_config=ConfigDict(extra="forbid")
    pump_id:str=Field(default="pump-01",min_length=1,max_length=64,pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    scenario:Literal["normal","overheating","bearing_wear","cavitation","imbalance"]="normal"
    sample_count:int=Field(default=10,ge=1,le=10000)
    sampling_interval_seconds:float=Field(default=1,ge=.1,le=86400)
    random_seed:int|None=None
    start_time:datetime|None=None
    client_session_id:str|None=Field(default=None,min_length=1,max_length=64,pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class LiveSampleRequest(BaseModel):
    """One new sample from the selected process-local live signal."""
    model_config=ConfigDict(extra="forbid")
    pump_id:str=Field(default="pump-01",min_length=1,max_length=64,pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    scenario:Literal["normal","overheating","bearing_wear","cavitation","imbalance"]="normal"
    random_seed:int|None=None
    client_session_id:str|None=Field(default=None,min_length=1,max_length=64,pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    reset_session:bool=False
    speed:float=Field(default=1,ge=.25,le=4)
    rpm_setpoint:float=Field(default=1780,ge=1200,le=2500)
    load_percent:float=Field(default=65,ge=10,le=100)
    cooling_effectiveness:float=Field(default=.8,ge=.2,le=1)
    inlet_restriction_percent:float=Field(default=0,ge=0,le=70)
    fault_severity:float=Field(default=1,ge=0,le=1)
    fault_enabled:bool|None=None
@router.get("/pumps",summary="List known pumps")
def pumps(request:Request)->list[str]:
    """List pump IDs present in this process memory."""
    return request.app.state.telemetry.list_pumps()
@router.get("/pumps/{pump_id}/telemetry/latest",response_model=TelemetryReading,summary="Latest telemetry")
def latest(pump_id: str, request: Request) -> TelemetryReading:
    """Get the most recent reading for a known pump."""
    try:return request.app.state.telemetry.latest(pump_id)
    except UnknownPumpError as exc:raise HTTPException(404,detail=f"Unknown pump_id: {pump_id}") from exc
@router.get("/pumps/{pump_id}/telemetry/history",response_model=list[TelemetryReading],summary="Telemetry history")
def history(pump_id: str, request: Request, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)) -> list[TelemetryReading]:
    """Get newest-first history; limit and offset are validated."""
    try:return request.app.state.telemetry.history(pump_id,limit,offset)
    except UnknownPumpError as exc:raise HTTPException(404,detail=f"Unknown pump_id: {pump_id}") from exc
@router.get("/pumps/{pump_id}/assessment",response_model=HealthAssessment,summary="Current health assessment")
def assessment(pump_id: str, request: Request) -> HealthAssessment:
    """Assess the latest reading using explainable rules."""
    try:r=request.app.state.telemetry.latest(pump_id)
    except UnknownPumpError as exc:raise HTTPException(404,detail=f"Unknown pump_id: {pump_id}") from exc
    return assess_reading(r)
@router.post("/simulation/generate",response_model=SimulationResponse,summary="Generate synthetic telemetry")
def generate(payload: SimulationRequest, request: Request) -> SimulationResponse:
    """Generate labeled scenario data; scenario label is not part of sensor model."""
    generator=TelemetryGenerator(payload.random_seed)
    try: labeled=generator.generate_sequence(payload.scenario,payload.sample_count,payload.sampling_interval_seconds,payload.pump_id,payload.start_time)
    except ValueError as exc:raise HTTPException(422,detail=str(exc)) from exc
    readings=[r for r,_ in labeled]
    request.app.state.telemetry.add_readings(readings, client_session_id=payload.client_session_id)
    return {"scenario_label":payload.scenario,"readings":readings,"assessment":assess_reading(readings[-1])}

@router.post("/simulation/live-sample",response_model=SimulationResponse,summary="Generate one live synthetic sample")
def live_sample(payload: LiveSampleRequest, request: Request) -> SimulationResponse:
    """Advance a bounded, seeded live scenario and assess its fresh sample."""
    try:
        reading=request.app.state.live_simulation.next_sample(payload.pump_id,payload.scenario,payload.random_seed,client_session_id=payload.client_session_id,
            reset_session=payload.reset_session, speed=payload.speed, load_percent=payload.load_percent,
            cooling_effectiveness=payload.cooling_effectiveness, inlet_restriction_percent=payload.inlet_restriction_percent, rpm_setpoint=payload.rpm_setpoint,
            fault_severity=payload.fault_severity, fault_enabled=payload.fault_enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc
    request.app.state.telemetry.add_readings([reading], client_session_id=payload.client_session_id)
    return {"scenario_label":payload.scenario,"readings":[reading],"assessment":assess_reading(reading),
            "simulation":request.app.state.live_simulation.snapshot(payload.pump_id,payload.client_session_id)}
