import { describe, expect, it } from 'vitest';
import type { Assessment } from './api';
import type { Telemetry } from './engineering';
import { calculateMetricTrend, MEASUREMENTS, possibleContributors, relatedAnomalies, SCENARIO_BEHAVIOR } from './diagnostics';

const assessment: Assessment = {
  pump_id: 'pump-01', timestamp: '2026-01-01T00:00:02Z', health_score: 50, status: 'warning',
  anomalies: [
    { metric: 'temperature_c', observed_value: 91, expected_range: '20–85 °C', severity: 'warning', explanation: 'Above range' },
    { metric: 'vibration_mm_s', observed_value: 5, expected_range: '0–4.5 mm/s', severity: 'warning', explanation: 'Above range' },
  ],
  detected_faults: ['overheating_pattern'], recommendations: ['Inspect cooling or ventilation.'],
};

function row(timestamp: string, values: Partial<Telemetry> = {}): Telemetry {
  return { timestamp, pump_id: 'pump-01', temperature_c: 68, vibration_mm_s: 2, sound_db: 68, rpm: 1780, pressure_kpa: 320, operating_mode: 'steady', ...values };
}

describe('evidence-based diagnostics', () => {
  it('labels generic channels honestly and identifies pressure as unthresholded', () => {
    expect(MEASUREMENTS.temperature_c.location).toMatch(/not specified/i);
    expect(MEASUREMENTS.vibration_mm_s.location).toMatch(/not specified/i);
    expect(MEASUREMENTS.pressure_kpa.thresholded).toBe(false);
    expect(MEASUREMENTS.temperature_c.unit).toBe('°C');
  });

  it('calculates progression from timestamped samples in chronological order', () => {
    const trend = calculateMetricTrend([
      row('2026-01-01T00:00:02Z', { temperature_c: 72 }),
      row('2026-01-01T00:00:00Z', { temperature_c: 68 }),
    ], 'temperature_c');
    expect(trend).toMatchObject({ initialValue: 68, latestValue: 72, delta: 4, direction: 'increased', elapsedSeconds: 2, samples: 2 });
    expect(calculateMetricTrend([], 'temperature_c')).toBeNull();
    expect(calculateMetricTrend([row('invalid')], 'temperature_c')).toBeNull();
  });

  it('lists only other backend anomalies as related symptoms', () => {
    expect(relatedAnomalies(assessment, 'temperature_c').map((item) => item.metric)).toEqual(['vibration_mm_s']);
    expect(relatedAnomalies(null, 'temperature_c')).toEqual([]);
  });

  it('separates unconfirmed possible contributors and does not invent unsupported causes', () => {
    const causes = possibleContributors(assessment);
    expect(causes).toHaveLength(1);
    expect(causes[0].title).toMatch(/cooling/i);
    expect(causes[0].rationale).toMatch(/unconfirmed/i);
    expect(possibleContributors({ ...assessment, anomalies: [], detected_faults: [] })).toEqual([]);
  });

  it('describes each of the five implemented synthetic scenario behaviors', () => {
    expect(Object.keys(SCENARIO_BEHAVIOR)).toEqual(['normal', 'overheating', 'bearing_wear', 'cavitation', 'imbalance']);
    expect(SCENARIO_BEHAVIOR.imbalance).toMatch(/no phase/i);
    expect(SCENARIO_BEHAVIOR.cavitation).toMatch(/pressure/i);
  });
});
