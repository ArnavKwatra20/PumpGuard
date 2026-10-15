import { SCENARIOS, type Scenario, type SimulationResponse } from './api';
import type { Telemetry } from './engineering';

export interface ResponseValidationOptions {
  pumpId: string;
  scenario: Scenario;
  now?: number;
  maxAgeMs?: number;
  newerThan?: string | null;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function isTelemetryReading(value: unknown): value is Telemetry {
  if (!record(value)) return false;
  return typeof value.timestamp === 'string' && Number.isFinite(Date.parse(value.timestamp))
    && typeof value.pump_id === 'string' && value.pump_id.length > 0
    && finite(value.temperature_c) && finite(value.vibration_mm_s) && finite(value.sound_db)
    && finite(value.rpm) && (value.pressure_kpa === undefined || finite(value.pressure_kpa))
    && value.temperature_c >= -20 && value.temperature_c <= 250
    && value.vibration_mm_s >= 0 && value.vibration_mm_s <= 100
    && value.sound_db >= 0 && value.sound_db <= 160
    && value.rpm >= 0 && value.rpm <= 30_000
    && (value.pressure_kpa === undefined || (value.pressure_kpa >= 0 && value.pressure_kpa <= 2_000))
    && ['steady', 'startup', 'shutdown'].includes(String(value.operating_mode));
}

/** Reject malformed, mismatched, non-advancing, or stale backend samples before they reach UI state. */
export function validateSimulationResponse(value: unknown, options: ResponseValidationOptions): SimulationResponse {
  if (!record(value) || !SCENARIOS.includes(value.scenario_label as Scenario) || value.scenario_label !== options.scenario) {
    throw new Error('The API returned a response for a different or invalid scenario.');
  }
  if (!Array.isArray(value.readings) || value.readings.length === 0 || !value.readings.every(isTelemetryReading)) {
    throw new Error('The API returned malformed telemetry; waiting for a valid sample.');
  }
  const readings = value.readings as Telemetry[];
  if (readings.some((reading) => reading.pump_id !== options.pumpId)) {
    throw new Error('The API returned telemetry for a different pump.');
  }
  const latest = readings.at(-1)!;
  const timestamp = Date.parse(latest.timestamp);
  const now = options.now ?? Date.now();
  if (timestamp > now + 5_000) throw new Error('The API returned a future-dated sample; waiting for fresh telemetry.');
  if (options.maxAgeMs !== undefined && now - timestamp > options.maxAgeMs) {
    throw new Error('The API returned stale telemetry; waiting for a fresh sample.');
  }
  if (options.newerThan && timestamp <= Date.parse(options.newerThan)) {
    throw new Error('The API sample timestamp did not advance; waiting for fresh telemetry.');
  }

  const assessment = value.assessment;
  if (!record(assessment) || assessment.pump_id !== options.pumpId
    || typeof assessment.timestamp !== 'string' || !Number.isFinite(Date.parse(assessment.timestamp))
    || Math.abs(Date.parse(assessment.timestamp) - timestamp) > 1_000
    || !finite(assessment.health_score) || assessment.health_score < 0 || assessment.health_score > 100
    || !['normal', 'warning', 'critical'].includes(String(assessment.status))
    || !Array.isArray(assessment.anomalies) || !Array.isArray(assessment.detected_faults)
    || !assessment.detected_faults.every((fault) => typeof fault === 'string')
    || !Array.isArray(assessment.recommendations) || !assessment.recommendations.every((item) => typeof item === 'string')) {
    throw new Error('The API returned a malformed assessment; waiting for a valid response.');
  }
  for (const anomaly of assessment.anomalies) {
    if (!record(anomaly) || typeof anomaly.metric !== 'string' || !finite(anomaly.observed_value)
      || typeof anomaly.expected_range !== 'string'
      || !['normal', 'warning', 'critical'].includes(String(anomaly.severity))
      || typeof anomaly.explanation !== 'string') {
      throw new Error('The API returned malformed assessment evidence; waiting for a valid response.');
    }
  }
  return value as unknown as SimulationResponse;
}
