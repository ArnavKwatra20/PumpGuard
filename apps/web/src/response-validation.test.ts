import { describe, expect, it } from 'vitest';
import { validateSimulationResponse } from './response-validation';
import type { SimulationResponse } from './api';

const now = Date.parse('2026-10-12T12:00:00.000Z');
const response: SimulationResponse = {
  scenario_label: 'overheating',
  readings: [{ timestamp: new Date(now).toISOString(), pump_id: 'pump-01', temperature_c: 80, vibration_mm_s: 2, sound_db: 68, rpm: 1780, pressure_kpa: 320, operating_mode: 'steady' }],
  assessment: { pump_id: 'pump-01', timestamp: new Date(now).toISOString(), health_score: 85, status: 'warning', anomalies: [{ metric: 'temperature_c', observed_value: 80, expected_range: '20–85 °C', severity: 'warning', explanation: 'High temperature' }], detected_faults: ['overheating_pattern'], recommendations: ['Inspect cooling'] },
};
const options = { pumpId: 'pump-01', scenario: 'overheating' as const, now, maxAgeMs: 30_000 };

describe('live API response validation', () => {
  it('accepts a current matching telemetry and assessment pair', () => {
    expect(validateSimulationResponse(response, options)).toEqual(response);
  });

  it.each([
    [{ ...response, scenario_label: 'normal' }, /different or invalid scenario/],
    [{ ...response, readings: [] }, /malformed telemetry/],
    [{ ...response, readings: [{ ...response.readings[0], temperature_c: Number.NaN }] }, /malformed telemetry/],
    [{ ...response, readings: [{ ...response.readings[0], rpm: 90_000 }] }, /malformed telemetry/],
    [{ ...response, readings: [{ ...response.readings[0], pump_id: 'pump-02' }] }, /different pump/],
    [{ ...response, assessment: { ...response.assessment, timestamp: new Date(now - 5_000).toISOString() } }, /malformed assessment/],
  ] as const)('rejects an invalid response', (invalid, message) => {
    expect(() => validateSimulationResponse(invalid, options)).toThrow(message);
  });

  it('rejects old, future-dated, and non-advancing readings', () => {
    const stale = { ...response, readings: [{ ...response.readings[0], timestamp: new Date(now - 60_000).toISOString() }], assessment: { ...response.assessment, timestamp: new Date(now - 60_000).toISOString() } };
    expect(() => validateSimulationResponse(stale, options)).toThrow(/stale telemetry/);
    const future = { ...response, readings: [{ ...response.readings[0], timestamp: new Date(now + 10_000).toISOString() }], assessment: { ...response.assessment, timestamp: new Date(now + 10_000).toISOString() } };
    expect(() => validateSimulationResponse(future, options)).toThrow(/future-dated/);
    expect(() => validateSimulationResponse(response, { ...options, newerThan: new Date(now).toISOString() })).toThrow(/timestamp did not advance/);
  });
});
