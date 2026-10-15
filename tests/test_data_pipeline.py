from datetime import datetime, timedelta, timezone
import pytest
from pumpguard.data.pipeline import read_csv, validate_rows, write_csv
from pumpguard.simulator.generator import SCENARIOS, TelemetryGenerator
from scripts.generate_dataset import generate_rows

START = datetime(2026, 1, 1, tzinfo=timezone.utc)

def sample_rows():
    rows = []
    for pump in ("pump-01", "pump-02", "pump-03"):
        gen = TelemetryGenerator(10)
        for i, scenario in enumerate(SCENARIOS):
            reading, label = gen.generate_one(scenario, pump, START + timedelta(seconds=i))
            row = reading.model_dump(mode="json")
            row["scenario_label"] = label
            rows.append(row)
    return rows

def test_required_columns_numeric_schema_and_label_validation():
    rows = sample_rows()
    assert len(validate_rows(rows)) == len(rows)
    with pytest.raises(ValueError, match="missing required columns"):
        validate_rows([{k:v for k,v in rows[0].items() if k != "rpm"}])
    invalid = dict(rows[0], temperature_c="hot")
    with pytest.raises(ValueError, match="temperature_c must be numeric"):
        validate_rows([invalid])
    invalid = dict(rows[0], scenario_label="failure")
    with pytest.raises(ValueError, match="invalid scenario_label"):
        validate_rows([invalid])

def test_duplicate_and_timestamp_order_are_rejected():
    rows = sample_rows()
    with pytest.raises(ValueError, match="duplicate record"):
        validate_rows([rows[0], rows[0]])
    reversed_rows = [rows[1], rows[0]]
    with pytest.raises(ValueError, match="not ordered"):
        validate_rows(reversed_rows)

def test_generation_reproducible_and_grouped():
    a = generate_rows(9, 12, 1.0, 3, START)
    b = generate_rows(9, 12, 1.0, 3, START)
    assert a == b
    assert {r["pump_id"] for r in a} == {"pump-01", "pump-02", "pump-03"}
    assert len(a) == 45
    for pump in ("pump-01", "pump-02", "pump-03"):
        labels = {r["scenario_label"] for r in a if r["pump_id"] == pump}
        assert labels == set(SCENARIOS)

def test_csv_round_trip_preserves_feature_columns(tmp_path):
    rows = sample_rows()
    rows[0]["temperature_c_roll_mean_w2"] = 64.5
    rows[0]["feature_warmup"] = False
    target = write_csv(rows, tmp_path / "processed" / "features.csv")
    loaded = read_csv(target)
    assert loaded[0]["temperature_c_roll_mean_w2"] == "64.5"
    assert loaded[0]["feature_warmup"] == "False"
