"""Explicit sensor thresholds and deterministic score."""
from dataclasses import dataclass
from collections.abc import Iterable, Mapping
from pydantic import ValidationError
from pumpguard.models.assessment import Anomaly
from pumpguard.models.telemetry import TelemetryReading
@dataclass(frozen=True)
class Threshold:
    """Expected range with critical outer bounds."""
    metric:str; low:float; high:float; critical_low:float; critical_high:float; unit:str
DEFAULT_THRESHOLDS=(Threshold("temperature_c",20,85,10,105,"°C"),Threshold("vibration_mm_s",0,4.5,0,8,"mm/s"),Threshold("sound_db",45,85,35,100,"dB"),Threshold("rpm",1650,1900,1500,2050,"rpm"))
def detect_anomalies(reading: TelemetryReading | Mapping[str, object], thresholds: tuple[Threshold, ...] = DEFAULT_THRESHOLDS) -> list[Anomaly]:
    """Detect out-of-range values; malformed input raises ValueError."""
    if not isinstance(reading,TelemetryReading):
        try: reading=TelemetryReading.model_validate(reading)
        except (ValidationError,TypeError,ValueError) as e: raise ValueError(f"Invalid telemetry reading: {e}") from e
    out=[]
    for x in thresholds:
        val=float(getattr(reading,x.metric))
        if x.low<=val<=x.high: continue
        sev="critical" if val<x.critical_low or val>x.critical_high else "warning"
        bound=f"below {x.low:g}" if val<x.low else f"above {x.high:g}"
        out.append(Anomaly(metric=x.metric,observed_value=val,expected_range=f"{x.low:g}–{x.high:g} {x.unit}",severity=sev,explanation=f"{x.metric} is {bound} its illustrative range."))
    return out
def score_health(anomalies: Iterable[Anomaly]) -> int:
    """100 minus 15 per warning and 35 per critical, floored to zero."""
    return max(0,100-sum(35 if a.severity=="critical" else 15 for a in anomalies))
def identify_faults(r: TelemetryReading) -> list[str]:
    """Return heuristic indicators only, not diagnostic conclusions."""
    t,v,s=r.temperature_c,r.vibration_mm_s,r.sound_db; f=[]
    if t>85 and v<=4.5:f.append("overheating_pattern")
    if v>4.5 and s>80 and r.rpm<1750:f.append("cavitation_pattern")
    elif v>4.5 and s>75 and t<=85:f.append("bearing_wear_pattern")
    if v>6 and s<=75:f.append("imbalance_pattern")
    return f
