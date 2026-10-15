"""Assessment response models."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
class Anomaly(BaseModel):
    """Explainable threshold finding."""
    model_config=ConfigDict(extra="forbid")
    metric:str
    observed_value:float
    expected_range:str
    severity:Literal["normal","warning","critical"]
    explanation:str
class HealthAssessment(BaseModel):
    """Rules-based status; not a failure probability."""
    model_config=ConfigDict(extra="forbid")
    pump_id:str
    timestamp:datetime
    health_score:int=Field(ge=0,le=100)
    status:Literal["normal","warning","critical"]
    anomalies:list[Anomaly]
    detected_faults:list[str]
    recommendations:list[str]
