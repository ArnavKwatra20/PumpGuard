from datetime import datetime, timedelta, timezone
import math
from pumpguard.data.features import engineer_features
from pumpguard.data.splitting import input_feature_names

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

def row(pump, second, temp, vib=1.0, sound=50.0, rpm=1000.0, label="normal"):
    return {"timestamp": T0 + timedelta(seconds=second), "pump_id": pump,
            "temperature_c": temp, "vibration_mm_s": vib, "sound_db": sound,
            "rpm": rpm, "operating_mode": "steady", "scenario_label": label}

def test_rolling_delta_lag_relative_and_warmup_values():
    rows = [row("p1", i, float(i + 1)) for i in range(4)]
    out = engineer_features(rows, windows=(3,), lags=(1,))
    assert out[0]["temperature_c_roll_mean_w3"] is None
    assert out[1]["temperature_c_roll_mean_w3"] is None
    assert out[2]["temperature_c_roll_mean_w3"] == 2.0
    assert math.isclose(out[2]["temperature_c_roll_std_w3"], math.sqrt(2 / 3))
    assert out[2]["temperature_c_delta"] == 1.0
    assert out[2]["temperature_c_relative_change"] == 0.5
    assert out[2]["temperature_c_lag_1"] == 2.0
    assert out[0]["feature_warmup"] is True
    assert out[2]["feature_warmup"] is False

def test_sort_future_independence_and_zero_relative_change():
    source = [row("p1", 1, 0), row("p1", 0, 2), row("p1", 2, 8)]
    baseline = engineer_features(source, windows=(2,), lags=(1,))
    changed_future = [dict(r) for r in source]
    changed_future[2]["temperature_c"] = 999
    altered = engineer_features(changed_future, windows=(2,), lags=(1,))
    assert [r["timestamp"] for r in baseline] == sorted(r["timestamp"] for r in baseline)
    assert baseline[0]["temperature_c_roll_mean_w2"] is None
    assert baseline[1]["temperature_c_relative_change"] == -1.0
    assert baseline[2]["temperature_c_relative_change"] is None
    assert baseline[0]["temperature_c"] == altered[0]["temperature_c"]
    assert baseline[1]["temperature_c_roll_mean_w2"] == altered[1]["temperature_c_roll_mean_w2"]

def test_rolling_windows_do_not_cross_pumps_and_label_is_not_feature():
    rows = [row("p2", 0, 100), row("p1", 0, 1), row("p1", 1, 3)]
    out = engineer_features(rows, windows=(2,), lags=(1,))
    p2 = next(r for r in out if r["pump_id"] == "p2")
    assert p2["temperature_c_roll_mean_w2"] is None
    names = input_feature_names(out)
    assert "temperature_c_roll_mean_w2" in names
    assert "scenario_label" not in names
    assert "pump_id" not in names
