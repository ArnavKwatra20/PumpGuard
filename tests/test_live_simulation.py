from datetime import datetime, timedelta, timezone

from pumpguard.simulator.generator import SCENARIOS
from pumpguard.simulator.live import LiveSimulationService


def sequence(scenario: str, count: int = 40, seed: int = 17):
    service = LiveSimulationService()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        service.next_sample("pump-live", scenario, seed, start + timedelta(seconds=index))
        for index in range(count)
    ]


def test_live_samples_are_reproducible_and_vary_over_time():
    first = sequence("normal")
    second = sequence("normal")
    assert first == second
    assert len({(row.temperature_c, row.vibration_mm_s, row.sound_db, row.rpm, row.pressure_kpa) for row in first}) > 30


def test_live_samples_without_client_timestamps_are_strictly_monotonic():
    service = LiveSimulationService()
    rows = [service.next_sample("pump-live", "normal", 17) for _ in range(40)]
    assert all(first.timestamp < second.timestamp for first, second in zip(rows, rows[1:]))


def test_normal_signal_remains_near_its_configured_operating_baseline():
    rows = sequence("normal", count=80)
    assert all(58 <= row.temperature_c <= 78 for row in rows)
    assert all(1.2 <= row.vibration_mm_s <= 3.0 for row in rows)
    assert all(58 <= row.sound_db <= 78 for row in rows)
    assert all(1735 <= row.rpm <= 1825 for row in rows)
    assert all(312 <= row.pressure_kpa <= 328 for row in rows)


def test_fault_scenarios_start_with_their_expected_signal_and_evolve():
    overheating = sequence("overheating")
    bearing = sequence("bearing_wear")
    cavitation = sequence("cavitation")
    imbalance = sequence("imbalance")
    assert overheating[0].temperature_c > 85
    assert overheating[-1].temperature_c > 85
    assert bearing[0].vibration_mm_s > 4.5
    assert bearing[-1].vibration_mm_s >= bearing[0].vibration_mm_s
    assert bearing[-1].temperature_c > bearing[0].temperature_c
    assert cavitation[0].pressure_kpa < 300
    assert cavitation[-1].vibration_mm_s > 4.5
    assert max(row.vibration_mm_s for row in imbalance[-10:]) - min(row.vibration_mm_s for row in imbalance[-10:]) > 1


def test_all_live_values_are_finite_and_inside_schema_limits():
    for scenario in SCENARIOS:
        rows = sequence(scenario)
        for row in rows:
            assert row.temperature_c == row.temperature_c and -20 <= row.temperature_c <= 250
            assert row.vibration_mm_s == row.vibration_mm_s and 0 <= row.vibration_mm_s <= 100
            assert row.sound_db == row.sound_db and 0 <= row.sound_db <= 160
            assert row.rpm == row.rpm and 0 <= row.rpm <= 30_000
            assert row.pressure_kpa == row.pressure_kpa and 0 <= row.pressure_kpa <= 2_000


def test_scenario_switch_resets_scenario_sequence_and_seed_restarts_it():
    service = LiveSimulationService()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = service.next_sample("pump-live", "overheating", 17, start)
    service.next_sample("pump-live", "overheating", 17, start + timedelta(seconds=1))
    service.next_sample("pump-live", "normal", 17, start + timedelta(seconds=2))
    restarted = service.next_sample("pump-live", "overheating", 17, start + timedelta(seconds=3))
    assert restarted.temperature_c == first.temperature_c


def test_first_live_fault_sample_does_not_fall_back_to_normal_baseline():
    service = LiveSimulationService()
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    expected = {
        "overheating": lambda row: row.temperature_c > 85,
        "bearing_wear": lambda row: row.vibration_mm_s > 4.5,
        "cavitation": lambda row: row.vibration_mm_s > 4.5 and row.pressure_kpa < 300,
        "imbalance": lambda row: row.vibration_mm_s > 8,
    }
    for scenario, signature_present in expected.items():
        first = service.next_sample(f"pump-{scenario}", scenario, 17, when)
        assert signature_present(first), scenario


def test_concurrent_client_scenarios_do_not_reset_each_others_live_sequence():
    service = LiveSimulationService()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first_bearing = service.next_sample("shared-pump", "bearing_wear", 42, start, client_session_id="dashboard-a")
    first_imbalance = service.next_sample("shared-pump", "imbalance", 42, start, client_session_id="dashboard-b")
    next_bearing = service.next_sample("shared-pump", "bearing_wear", 42, start + timedelta(seconds=1), client_session_id="dashboard-a")
    expected_bearing = sequence("bearing_wear", count=2, seed=42)

    assert first_bearing.vibration_mm_s == expected_bearing[0].vibration_mm_s
    assert first_imbalance.vibration_mm_s > 8
    assert next_bearing.vibration_mm_s == expected_bearing[1].vibration_mm_s
