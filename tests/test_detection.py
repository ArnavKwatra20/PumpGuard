import pytest
from pumpguard.models.telemetry import TelemetryReading
from pumpguard.detection.rules import detect_anomalies,identify_faults,score_health
from pumpguard.simulator.generator import TelemetryGenerator
from pumpguard.services.health_service import assess_reading
def reading(**kw):
    d=dict(pump_id="p1",temperature_c=68,vibration_mm_s=2,sound_db=68,rpm=1780);d.update(kw);return TelemetryReading(**d)
@pytest.mark.parametrize("metric,value", [("temperature_c",90),("vibration_mm_s",5),("sound_db",90),("rpm",1600)])
def test_each_threshold(metric,value):
    assert metric in [a.metric for a in detect_anomalies(reading(**{metric:value}))]
def test_multiple_critical_and_severity():
    result=detect_anomalies(reading(temperature_c=110,vibration_mm_s=9,sound_db=105,rpm=2200))
    assert len(result)==4 and all(x.severity=="critical" for x in result)
    assert score_health(result)==0
def test_score_bounds_and_repeatability():
    item=reading(temperature_c=90)
    x=assess_reading(item)
    assert 0<=x.health_score<=100
    assert x==assess_reading(item)
def test_invalid_input():
    with pytest.raises(ValueError):detect_anomalies({"temperature_c":-999})


def test_fault_pattern_rules_match_synthetic_scenarios():
    for scenario, expected in (("overheating", "overheating_pattern"), ("bearing_wear", "bearing_wear_pattern"), ("cavitation", "cavitation_pattern"), ("imbalance", "imbalance_pattern")):
        reading, _ = TelemetryGenerator(11).generate_one(scenario)
        assert expected in identify_faults(reading)
