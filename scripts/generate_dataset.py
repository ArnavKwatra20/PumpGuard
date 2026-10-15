"""Generate deterministic labeled synthetic raw telemetry CSV."""
import argparse
import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pumpguard.simulator.generator import SCENARIOS, SimulatorConditions, TelemetryGenerator

def generate_rows(samples_per_scenario: int, seed: int, interval_seconds: float, pump_count: int, start_time: datetime,
                  noise_scale: float = 1.0, operating_variation: float = 0.0,
                  baseline_temperature_c: float = 68.0, baseline_vibration_mm_s: float = 2.1,
                  operating_rpm: float = 1780.0, fault_intensity: float = 1.0,
                  temperature_drift: float = 0.0, vibration_drift: float = 0.0,
                  rpm_drift: float = 0.0) -> list[dict]:
    """Create balanced scenario segments distributed over several pump groups."""
    if samples_per_scenario < pump_count:
        raise ValueError("samples_per_scenario must be at least pump_count so every pump receives each scenario")
    if pump_count < 3:
        raise ValueError("pump_count must be at least 3 for group-aware train/validation/test splits")
    if interval_seconds < 0.1:
        raise ValueError("interval_seconds must be at least 0.1")
    condition_values = (noise_scale, operating_variation, baseline_temperature_c, baseline_vibration_mm_s,
                        operating_rpm, fault_intensity, temperature_drift, vibration_drift, rpm_drift)
    if any(not math.isfinite(value) for value in condition_values) or noise_scale < 0 or operating_variation < 0 or fault_intensity < 0:
        raise ValueError("simulator condition values must be finite; noise, variation, and fault intensity must be non-negative")
    if start_time.tzinfo is None or start_time.utcoffset() is None:
        raise ValueError("start_time must include a timezone")
    all_rows = []
    pump_block_seconds = len(SCENARIOS) * (samples_per_scenario + 1) * interval_seconds
    for scenario_index, scenario in enumerate(SCENARIOS):
        for pump_index in range(pump_count):
            count = samples_per_scenario // pump_count + (pump_index < samples_per_scenario % pump_count)
            centered = pump_index - (pump_count - 1) / 2
            conditions = SimulatorConditions(
                noise_scale=noise_scale,
                baseline_temperature_c=baseline_temperature_c + centered * operating_variation * 1.2,
                baseline_vibration_mm_s=baseline_vibration_mm_s + centered * operating_variation * 0.08,
                baseline_sound_db=68.0 + centered * operating_variation * 0.6,
                operating_rpm=operating_rpm + centered * operating_variation * 5,
                fault_intensity=fault_intensity,
                temperature_drift_c_per_sample=temperature_drift,
                vibration_drift_mm_s_per_sample=vibration_drift,
                rpm_drift_per_sample=rpm_drift,
            )
            generator = TelemetryGenerator(seed + scenario_index * 100_003 + pump_index * 1_009,
                                           conditions=conditions)
            pump_id = f"pump-{pump_index + 1:02d}"
            base = start_time + timedelta(seconds=pump_index * pump_block_seconds + scenario_index * (samples_per_scenario + 1) * interval_seconds)
            samples = generator.generate_sequence(scenario, count, interval_seconds, pump_id, base)
            for reading, label in samples:
                row = reading.model_dump(mode="json")
                row["scenario_label"] = label
                all_rows.append(row)
    all_rows.sort(key=lambda row: (row["pump_id"], row["timestamp"]))
    return all_rows

def main() -> None:
    """Parse arguments and write a reproducible raw dataset."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-per-scenario", type=int, default=100,
                        help="Total rows for each scenario across all pumps (default: 100)")
    parser.add_argument("--pump-count", type=int, default=5,
                        help="Distinct pump groups; at least 3 (default: 5)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise-scale", type=float, default=1.0,
                        help="Scale simulator sensor noise (default: 1.0 preserves Phase 2 behavior)")
    parser.add_argument("--operating-variation", type=float, default=0.0,
                        help="Add deterministic pump-specific operating offsets; synthetic only (default: 0)")
    parser.add_argument("--baseline-temperature-c", type=float, default=68.0)
    parser.add_argument("--baseline-vibration-mm-s", type=float, default=2.1)
    parser.add_argument("--operating-rpm", type=float, default=1780.0)
    parser.add_argument("--fault-intensity", type=float, default=1.0,
                        help="Scale hand-authored fault offsets; values below 1 create weaker signatures")
    parser.add_argument("--temperature-drift", type=float, default=0.0,
                        help="Synthetic temperature change per sample within each scenario sequence")
    parser.add_argument("--vibration-drift", type=float, default=0.0)
    parser.add_argument("--rpm-drift", type=float, default=0.0)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--start-time", default="2026-01-01T00:00:00+00:00",
                        help="ISO-8601 timezone-aware timestamp for reproducible runs")
    parser.add_argument("--output", type=Path, default=Path("data/raw/pump_telemetry.csv"))
    args = parser.parse_args()
    if args.samples_per_scenario < args.pump_count:
        parser.error("--samples-per-scenario must be >= --pump-count")
    if args.pump_count < 3:
        parser.error("--pump-count must be at least 3")
    try:
        start_time = datetime.fromisoformat(args.start_time.replace("Z", "+00:00"))
        rows = generate_rows(args.samples_per_scenario, args.seed, args.interval_seconds, args.pump_count,
                             start_time, args.noise_scale, args.operating_variation,
                             args.baseline_temperature_c, args.baseline_vibration_mm_s,
                             args.operating_rpm, args.fault_intensity, args.temperature_drift,
                             args.vibration_drift, args.rpm_drift)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    columns = ["timestamp", "pump_id", "temperature_c", "vibration_mm_s", "sound_db", "rpm", "operating_mode", "scenario_label"]
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} synthetic raw rows across {args.pump_count} pumps to {args.output}")

if __name__ == "__main__":
    main()
