"""Framework-independent assessment service."""
from pumpguard.detection.rules import detect_anomalies,identify_faults,score_health
from pumpguard.models.assessment import HealthAssessment
from pumpguard.models.telemetry import TelemetryReading
def assess_reading(r: TelemetryReading) -> HealthAssessment:
    """Build a deterministic score and pattern-based recommendations."""
    a=detect_anomalies(r); score=score_health(a)
    status="critical" if any(x.severity=="critical" for x in a) else ("warning" if a else "normal")
    rec=[]
    if r.temperature_c>85:rec.append("Inspect operating conditions and cooling or ventilation; verify temperature.")
    if r.vibration_mm_s>4.5:rec.append("Investigate abnormal vibration; inspect mounting, alignment, and rotating components.")
    if r.sound_db>85:rec.append("Inspect unusual acoustic noise and inlet conditions if cavitation is suspected.")
    if r.rpm<1650 or r.rpm>1900:rec.append("Verify commanded operating speed and tachometer reading.")
    if not rec:rec.append("Continue routine monitoring; no configured threshold was exceeded.")
    return HealthAssessment(pump_id=r.pump_id,timestamp=r.timestamp,health_score=score,status=status,anomalies=a,detected_faults=identify_faults(r),recommendations=rec)
