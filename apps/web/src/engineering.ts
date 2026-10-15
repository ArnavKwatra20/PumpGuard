export interface Telemetry {
  timestamp: string;
  pump_id: string;
  temperature_c: number;
  vibration_mm_s: number;
  sound_db: number;
  rpm: number;
  pressure_kpa?: number;
  operating_mode: 'steady' | 'startup' | 'shutdown';
  motor_temperature_c?: number | null;
  bearing_temperature_c?: number | null;
  flow_rate_m3_h?: number | null;
  inlet_pressure_kpa?: number | null;
  outlet_pressure_kpa?: number | null;
  load_percent?: number | null;
  power_kw?: number | null;
  current_a?: number | null;
  cooling_effectiveness?: number | null;
  inlet_restriction_percent?: number | null;
  simulation_time_seconds?: number | null;
}

export interface EngineeringMetrics {
  angularVelocityRadS: number | null;
  rotationalFrequencyHz: number | null;
  rpmDeviationPercent: number | null;
  temperatureDeviationC: number | null;
  vibrationIntensity: number | null;
}

export interface EngineeringReferences {
  rpm: number;
  temperatureC: number;
  vibrationScaleMmS: number;
}

export const DEFAULT_ENGINEERING_REFERENCES: EngineeringReferences = {
  rpm: 1780,
  temperatureC: 68,
  vibrationScaleMmS: 8,
};

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function calculateEngineeringMetrics(
  telemetry: Partial<Telemetry>,
  references: EngineeringReferences = DEFAULT_ENGINEERING_REFERENCES,
): EngineeringMetrics {
  const rpm = finite(telemetry.rpm) && telemetry.rpm >= 0 ? telemetry.rpm : null;
  const temperature = finite(telemetry.temperature_c) ? telemetry.temperature_c : null;
  const vibration = finite(telemetry.vibration_mm_s) && telemetry.vibration_mm_s >= 0
    ? telemetry.vibration_mm_s
    : null;
  const referenceRpm = finite(references.rpm) && references.rpm > 0 ? references.rpm : null;
  const vibrationScale = finite(references.vibrationScaleMmS) && references.vibrationScaleMmS > 0
    ? references.vibrationScaleMmS
    : null;

  return {
    angularVelocityRadS: rpm === null ? null : (rpm * 2 * Math.PI) / 60,
    rotationalFrequencyHz: rpm === null ? null : rpm / 60,
    rpmDeviationPercent: rpm === null || referenceRpm === null
      ? null
      : ((rpm - referenceRpm) / referenceRpm) * 100,
    temperatureDeviationC: temperature === null || !finite(references.temperatureC)
      ? null
      : temperature - references.temperatureC,
    vibrationIntensity: vibration === null || vibrationScale === null
      ? null
      : Math.min(1, vibration / vibrationScale),
  };
}

export function formatMetric(value: number | null, digits = 1): string {
  return value === null ? '—' : value.toFixed(digits);
}
