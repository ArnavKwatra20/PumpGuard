import type { Assessment, Anomaly, Scenario } from './api';
import type { Telemetry } from './engineering';

export type MetricKey = 'temperature_c' | 'vibration_mm_s' | 'sound_db' | 'rpm' | 'pressure_kpa';

export const MEASUREMENTS: Record<MetricKey, { label: string; unit: string; location: string; thresholded: boolean }> = {
  temperature_c: { label: 'Temperature', unit: '°C', location: 'Physical sensor location not specified', thresholded: true },
  vibration_mm_s: { label: 'Vibration', unit: 'mm/s', location: 'Physical sensor location not specified', thresholded: true },
  sound_db: { label: 'Sound level', unit: 'dB', location: 'Acoustic sensor location not specified', thresholded: true },
  rpm: { label: 'Rotational speed', unit: 'rpm', location: 'Tachometer location not specified', thresholded: true },
  pressure_kpa: { label: 'Pressure', unit: 'kPa', location: 'Pressure sensor location not specified', thresholded: false },
};

export const SCENARIO_BEHAVIOR: Record<Scenario, string> = {
  normal: 'Synthetic baseline with bounded sensor variation.',
  overheating: 'The live simulator ramps the generic temperature channel; batch generation applies a temperature offset.',
  bearing_wear: 'The live simulator ramps vibration and sound, with a small temperature increase and speed decrease.',
  cavitation: 'The live simulator lowers pressure and speed while adding irregular variation to vibration and sound.',
  imbalance: 'The live simulator oscillates vibration and modestly raises sound; no phase or frequency spectrum is modeled.',
};

export interface MetricTrend {
  metric: MetricKey;
  initialValue: number;
  latestValue: number;
  delta: number;
  direction: 'increased' | 'decreased' | 'unchanged';
  startTimestamp: string;
  endTimestamp: string;
  elapsedSeconds: number;
  samples: number;
}

export function calculateMetricTrend(readings: Telemetry[], metric: MetricKey): MetricTrend | null {
  const points = readings
    .filter((reading) => Number.isFinite(reading[metric]) && Number.isFinite(Date.parse(reading.timestamp)))
    .slice()
    .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp));
  if (points.length === 0) return null;
  const initial = points[0];
  const latest = points.at(-1)!;
  const initialValue = initial[metric] as number;
  const latestValue = latest[metric] as number;
  const delta = latestValue - initialValue;
  return {
    metric, initialValue, latestValue, delta,
    direction: delta > 0 ? 'increased' : delta < 0 ? 'decreased' : 'unchanged',
    startTimestamp: initial.timestamp, endTimestamp: latest.timestamp,
    elapsedSeconds: Math.max(0, (Date.parse(latest.timestamp) - Date.parse(initial.timestamp)) / 1000),
    samples: points.length,
  };
}

export function relatedAnomalies(assessment: Assessment | null, primaryMetric?: string | null): Anomaly[] {
  if (!assessment) return [];
  return assessment.anomalies.filter((anomaly) => anomaly.metric !== primaryMetric);
}

export interface CauseHypothesis { title: string; rationale: string }

/** Only surface unconfirmed areas for investigation when an existing measured/rule pattern supports them. */
export function possibleContributors(assessment: Assessment | null): CauseHypothesis[] {
  if (!assessment) return [];
  const metrics = new Set(assessment.anomalies.map((item) => item.metric));
  const patterns = new Set(assessment.detected_faults);
  const hypotheses: CauseHypothesis[] = [];
  if (patterns.has('overheating_pattern') || patterns.has('overheating') || metrics.has('temperature_c')) {
    hypotheses.push({
      title: 'Cooling or ventilation performance',
      rationale: 'The generic temperature channel is elevated or the backend emitted its overheating pattern. The API has no cooling-flow or component-specific temperature measurement, so this is unconfirmed.',
    });
  }
  if (patterns.has('bearing_wear_pattern') || patterns.has('bearing_wear')) {
    hypotheses.push({
      title: 'Bearing condition, lubrication, or alignment',
      rationale: 'The backend bearing-wear pattern is based on vibration, sound, and temperature rules. No direct bearing temperature, lubrication, or alignment channel is available; inspect these as possibilities only.',
    });
  }
  if (patterns.has('cavitation_pattern') || patterns.has('cavitation')) {
    hypotheses.push({
      title: 'Inlet restriction or insufficient suction',
      rationale: 'The backend cavitation pattern is based on vibration, sound, and reduced RPM. Pressure has no configured health threshold and does not establish a suction cause.',
    });
  }
  if (patterns.has('imbalance_pattern') || patterns.has('imbalance')) {
    hypotheses.push({
      title: 'Rotor balance or mounting',
      rationale: 'The backend imbalance pattern is based on vibration and sound levels. The simulator provides no phase angle or vibration spectrum to confirm rotor imbalance.',
    });
  }
  return hypotheses;
}

export function anomalyForMetric(assessment: Assessment | null, metric: string): Anomaly | undefined {
  return assessment?.anomalies.find((anomaly) => anomaly.metric === metric);
}
