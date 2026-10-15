import { describe, expect, it } from 'vitest';
import { calculateEngineeringMetrics, DEFAULT_ENGINEERING_REFERENCES, formatMetric } from './engineering';

describe('engineering display calculations', () => {
  it('converts RPM to rotational frequency and angular velocity', () => {
    const result = calculateEngineeringMetrics({ rpm: 1780, temperature_c: 73, vibration_mm_s: 4 });
    expect(result.rotationalFrequencyHz).toBeCloseTo(29.6667, 3);
    expect(result.angularVelocityRadS).toBeCloseTo((1780 * 2 * Math.PI) / 60, 8);
    expect(result.rpmDeviationPercent).toBe(0);
    expect(result.temperatureDeviationC).toBe(5);
    expect(result.vibrationIntensity).toBe(0.5);
  });

  it('handles missing, invalid, zero-speed and extreme values without NaN output', () => {
    expect(calculateEngineeringMetrics({}).angularVelocityRadS).toBeNull();
    expect(calculateEngineeringMetrics({ rpm: Number.NaN, temperature_c: Infinity, vibration_mm_s: -1 }).rpmDeviationPercent).toBeNull();
    const zero = calculateEngineeringMetrics({ rpm: 0, temperature_c: 68, vibration_mm_s: 0 });
    expect(zero.angularVelocityRadS).toBe(0);
    expect(zero.rotationalFrequencyHz).toBe(0);
    expect(zero.vibrationIntensity).toBe(0);
    expect(calculateEngineeringMetrics({ rpm: 2000, vibration_mm_s: 99 }).vibrationIntensity).toBe(1);
    expect(formatMetric(null)).toBe('—');
  });

  it('safely omits relative RPM deviation when its reference is zero', () => {
    expect(calculateEngineeringMetrics({ rpm: 1200 }, { ...DEFAULT_ENGINEERING_REFERENCES, rpm: 0 }).rpmDeviationPercent).toBeNull();
    expect(calculateEngineeringMetrics({ temperature_c: 70 }, { ...DEFAULT_ENGINEERING_REFERENCES, temperatureC: Number.NaN }).temperatureDeviationC).toBeNull();
  });
});
