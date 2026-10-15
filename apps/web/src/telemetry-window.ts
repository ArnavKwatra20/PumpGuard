import type { Telemetry } from './engineering';

/** Keep newest-first telemetry in a fixed-size client chart window. */
export function prependReadingWindow(current: Telemetry[], reading: Telemetry, limit = 120): Telemetry[] {
  return [reading, ...current].slice(0, Math.max(1, limit));
}
