from datetime import datetime,timezone
import pytest
from pydantic import ValidationError
from pumpguard.models.telemetry import TelemetryReading
from pumpguard.simulator.generator import SCENARIOS,TelemetryGenerator
def test_schema_rejects_invalid_and_defaults_id():
    r=TelemetryReading(temperature_c=60,vibration_mm_s=1,sound_db=60,rpm=1800)
    assert r.pump_id=="pump-01"
    with pytest.raises(ValidationError):TelemetryReading(temperature_c=999,vibration_mm_s=1,sound_db=60,rpm=1800)
def test_scenarios_and_reproducibility():
    t=datetime(2026,1,1,tzinfo=timezone.utc)
    for s in SCENARIOS:
        a=TelemetryGenerator(17).generate_sequence(s,20,1,"p1",t)
        b=TelemetryGenerator(17).generate_sequence(s,20,1,"p1",t)
        assert a==b and all(label==s for _,label in a)
def test_fault_patterns_are_distinguishable():
    means={}
    for s in SCENARIOS:
        rows=TelemetryGenerator(7).generate_sequence(s,80)
        means[s]=[sum(getattr(r,k) for r,_ in rows)/len(rows) for k in ("temperature_c","vibration_mm_s","sound_db")]
    assert means["overheating"][0]>means["normal"][0]+15
    assert means["bearing_wear"][1]>means["normal"][1]+3
    assert means["cavitation"][2]>means["normal"][2]+10
    assert means["imbalance"][1]>means["normal"][1]+5
def test_bad_generator_params():
    with pytest.raises(ValueError):TelemetryGenerator().generate_one("mystery")
    with pytest.raises(ValueError):TelemetryGenerator().generate_sequence(count=0)
    with pytest.raises(ValueError):TelemetryGenerator().generate_sequence(interval_seconds=0)
