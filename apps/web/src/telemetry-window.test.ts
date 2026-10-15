import { describe, expect, it } from 'vitest';
import type { Telemetry } from './engineering';
import { prependReadingWindow } from './telemetry-window';

const reading = (index: number): Telemetry => ({
  timestamp: new Date(Date.UTC(2026, 0, 1, 0, 0, index)).toISOString(), pump_id: 'pump-01',
  temperature_c: 68 + index / 100, vibration_mm_s: 2, sound_db: 68, rpm: 1780,
  pressure_kpa: 320, operating_mode: 'steady',
});

describe('bounded live chart window', () => {
  it('keeps newest samples first and trims the sliding window', () => {
    let window: Telemetry[] = [];
    for (let index = 0; index < 150; index += 1) window = prependReadingWindow(window, reading(index), 120);
    expect(window).toHaveLength(120);
    expect(window[0].temperature_c).toBe(reading(149).temperature_c);
    expect(window.at(-1)?.temperature_c).toBe(reading(30).temperature_c);
  });
});
