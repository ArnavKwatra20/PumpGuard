"""Validated synthetic telemetry, separate from scenario truth."""
from datetime import datetime,timezone
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
class TelemetryReading(BaseModel):
    """Synthetic sensor sample with explicit units."""
    model_config=ConfigDict(extra="forbid")
    timestamp:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
    pump_id:str=Field(default="pump-01",min_length=1,max_length=64,pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    temperature_c:float=Field(ge=-20,le=250,allow_inf_nan=False)
    vibration_mm_s:float=Field(ge=0,le=100,allow_inf_nan=False)
    sound_db:float=Field(ge=0,le=160,allow_inf_nan=False)
    rpm:float=Field(ge=0,le=30000,allow_inf_nan=False)
    pressure_kpa:float=Field(default=320,ge=0,le=2000,allow_inf_nan=False)
    operating_mode:Literal["steady","startup","shutdown"]="steady"
    # Optional simulator instrumentation; existing readings and API clients remain valid.
    motor_temperature_c:float|None=Field(default=None,ge=-20,le=250,allow_inf_nan=False)
    bearing_temperature_c:float|None=Field(default=None,ge=-20,le=250,allow_inf_nan=False)
    flow_rate_m3_h:float|None=Field(default=None,ge=0,le=10000,allow_inf_nan=False)
    inlet_pressure_kpa:float|None=Field(default=None,ge=0,le=2000,allow_inf_nan=False)
    outlet_pressure_kpa:float|None=Field(default=None,ge=0,le=2000,allow_inf_nan=False)
    load_percent:float|None=Field(default=None,ge=0,le=100,allow_inf_nan=False)
    power_kw:float|None=Field(default=None,ge=0,le=10000,allow_inf_nan=False)
    current_a:float|None=Field(default=None,ge=0,le=10000,allow_inf_nan=False)
    cooling_effectiveness:float|None=Field(default=None,ge=0,le=1,allow_inf_nan=False)
    inlet_restriction_percent:float|None=Field(default=None,ge=0,le=100,allow_inf_nan=False)
    simulation_time_seconds:float|None=Field(default=None,ge=0,allow_inf_nan=False)
