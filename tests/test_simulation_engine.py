from datetime import datetime, timedelta, timezone

import pytest

from pumpguard.simulator.engine import PumpSimulationEngine, SimulationConfig


def run(config, seed=17, count=20):
    engine = PumpSimulationEngine(seed, config)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [engine.tick("engine-pump", start + timedelta(seconds=i)) for i in range(count)]


def test_seed_and_configuration_replay_same_signals_and_simulation_clock():
    config = SimulationConfig(scenario="bearing_wear", load_percent=72, speed=1.5)
    first, second = run(config), run(config)
    assert first == second
    assert first[-1].simulation_time_seconds == 30


def test_load_and_cooling_have_coherent_bounded_effects():
    light = run(SimulationConfig(load_percent=25, cooling_effectiveness=1), count=1)[0]
    loaded = run(SimulationConfig(load_percent=90, cooling_effectiveness=1), count=1)[0]
    poorly_cooled = run(SimulationConfig(load_percent=90, cooling_effectiveness=.3), count=1)[0]
    assert loaded.rpm > light.rpm
    assert loaded.power_kw > light.power_kw
    assert poorly_cooled.motor_temperature_c > loaded.motor_temperature_c
    for item in (light, loaded, poorly_cooled):
        assert 0 <= item.flow_rate_m3_h <= 10000
        assert 0 <= item.current_a <= 10000
        assert 0 <= item.inlet_pressure_kpa <= 2000


def test_motor_speed_setpoint_controls_rpm_independently_of_simulation_clock():
    slower = run(SimulationConfig(rpm_setpoint=1450), seed=7, count=1)[0]
    faster = run(SimulationConfig(rpm_setpoint=2100), seed=7, count=1)[0]
    assert faster.rpm - slower.rpm == pytest.approx(650)
    assert slower.simulation_time_seconds == faster.simulation_time_seconds == 1


@pytest.mark.parametrize("scenario", ["normal", "overheating", "bearing_wear", "cavitation", "imbalance"])
def test_scenarios_produce_finite_in_range_measurements(scenario):
    rows = run(SimulationConfig(scenario=scenario), count=12)
    assert all(-20 <= row.temperature_c <= 250 for row in rows)
    assert all(0 <= row.vibration_mm_s <= 100 for row in rows)
    assert all(row.motor_temperature_c is not None and row.bearing_temperature_c is not None for row in rows)
    assert all(row.timestamp < next_row.timestamp for row, next_row in zip(rows, rows[1:]))


def test_inlet_restriction_reduces_flow_and_pressure():
    open_inlet = run(SimulationConfig(load_percent=65, inlet_restriction_percent=0), count=1)[0]
    restricted = run(SimulationConfig(load_percent=65, inlet_restriction_percent=65), count=1)[0]
    assert restricted.flow_rate_m3_h < open_inlet.flow_rate_m3_h
    assert restricted.inlet_pressure_kpa < open_inlet.inlet_pressure_kpa


def test_fault_injection_and_recovery_are_stateful_and_ground_truth_is_not_sensor_input():
    engine = PumpSimulationEngine(5, SimulationConfig(scenario="overheating", fault_enabled=False))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    steady = engine.tick("p", start)
    engine.update(fault_enabled=True)
    injected = engine.tick("p", start + timedelta(seconds=1))
    assert injected.temperature_c > steady.temperature_c
    assert "scenario" not in injected.model_dump()
    engine.update(fault_enabled=False)
    cooling = [engine.tick("p", start + timedelta(seconds=i)) for i in range(2, 12)]
    assert cooling[-1].temperature_c < injected.temperature_c
    assert engine.snapshot()["events"][0]["kind"] == "fault_injected"
    engine.reset()
    assert engine.snapshot()["time_seconds"] == 0


def test_controls_reject_values_outside_documented_bounds():
    with pytest.raises(ValueError):
        SimulationConfig(speed=10)
