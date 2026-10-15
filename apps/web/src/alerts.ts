import type { Anomaly, Assessment } from './api';

export type ComponentId = 'motor' | 'bearing' | 'casing' | 'shaft' | 'impeller' | 'pump';
export type AlertSeverity = 'warning' | 'critical';
export type AlertState = 'active' | 'acknowledged' | 'resolved';
export interface AlertEvent {
  id: string; pump_id: string; metric: string; timestamp: string; observed_value: number;
  expected_range: string; severity: AlertSeverity; explanation: string; components: ComponentId[];
  recommendations: string[];
  state: AlertState; first_seen_at: string; last_seen_at: string; acknowledged_at?: string; resolved_at?: string;
}
export interface ComponentHighlight { componentId: ComponentId; severity: AlertSeverity }
export type IdFactory = () => string;
export const ALERT_HISTORY_LIMIT = 200;

const faultComponents: Record<string, ComponentId[]> = {
  overheating_pattern: ['motor'], overheating: ['motor'],
  bearing_wear_pattern: ['bearing'], bearing_wear: ['bearing'],
  cavitation_pattern: ['casing', 'impeller'], cavitation: ['casing', 'impeller'],
  imbalance_pattern: ['shaft', 'impeller'], imbalance: ['shaft', 'impeller'],
};

export function mapAnomalyComponents(anomaly: Pick<Anomaly, 'metric'>, faults: string[] = []): ComponentId[] {
  const relevant = (fault: string) => {
    const f = fault.toLowerCase();
    if (anomaly.metric === 'temperature_c') return f.includes('overheat');
    if (anomaly.metric === 'vibration_mm_s') return f.includes('bearing') || f.includes('cavitation') || f.includes('imbalance');
    if (anomaly.metric === 'sound_db') return f.includes('bearing') || f.includes('cavitation');
    if (anomaly.metric === 'rpm') return f.includes('cavitation') || f.includes('imbalance');
    return false;
  };
  const fromFaults = faults.filter(relevant).flatMap((fault) => faultComponents[fault.toLowerCase()] ?? []);
  const byMetric: ComponentId[] = anomaly.metric === 'temperature_c' ? ['motor'] : anomaly.metric === 'rpm' ? ['shaft', 'motor'] : [];
  if (byMetric.length || fromFaults.length) return [...new Set([...byMetric, ...fromFaults])];
  return ['pump'];
}

export function reconcileAlerts(previous: AlertEvent[], assessment: Assessment, now: string, idFactory: IdFactory = () => globalThis.crypto?.randomUUID?.() ?? `alert-${Date.now()}-${Math.random()}`): AlertEvent[] {
  const incoming = assessment.anomalies.filter((a): a is Anomaly & { severity: AlertSeverity } => a.severity === 'warning' || a.severity === 'critical');
  // Severity describes the current intensity of a condition, not a new fault
  // episode. Keep the episode identity stable while the same pump/metric/range
  // remains out of range so acknowledgement survives warning/critical changes.
  const conditionKey = (pumpId: string, anomaly: Pick<Anomaly, 'metric' | 'expected_range'>) => `${pumpId}|${anomaly.metric}|${anomaly.expected_range}`;
  const active = new Map(previous.filter((event) => event.state !== 'resolved').map((event) => [conditionKey(event.pump_id, event), event]));
  const seen = new Set<string>();
  const updated = incoming.map((a) => {
    const k = conditionKey(assessment.pump_id, a); seen.add(k);
    const existing = active.get(k);
    return existing ? { ...existing, timestamp: assessment.timestamp, observed_value: a.observed_value, severity: a.severity, explanation: a.explanation, components: mapAnomalyComponents(a, assessment.detected_faults), recommendations: assessment.recommendations, last_seen_at: now }
      : { id: idFactory(), pump_id: assessment.pump_id, metric: a.metric, timestamp: assessment.timestamp, observed_value: a.observed_value, expected_range: a.expected_range, severity: a.severity, explanation: a.explanation, components: mapAnomalyComponents(a, assessment.detected_faults), recommendations: assessment.recommendations, state: 'active' as const, first_seen_at: now, last_seen_at: now };
  });
  const resolved = previous.map((event) => event.state !== 'resolved' && !seen.has(conditionKey(event.pump_id, event))
    ? { ...event, state: 'resolved' as const, resolved_at: now } : event);
  const knownIds = new Set(updated.map((e) => e.id));
  const events = [...updated, ...resolved.filter((e) => !knownIds.has(e.id))];
  if (events.length <= ALERT_HISTORY_LIMIT) return events;
  const retainedActive = events.filter((event) => event.state !== 'resolved');
  const retainedResolved = events.filter((event) => event.state === 'resolved')
    .sort((left, right) => Date.parse(right.resolved_at ?? right.last_seen_at) - Date.parse(left.resolved_at ?? left.last_seen_at));
  return [...retainedActive, ...retainedResolved.slice(0, Math.max(0, ALERT_HISTORY_LIMIT - retainedActive.length))];
}

export function acknowledgeAlert(events: AlertEvent[], id: string, at: string): AlertEvent[] {
  return events.map((event) => event.id === id && event.state === 'active' ? { ...event, state: 'acknowledged', acknowledged_at: at } : event);
}

export function getComponentHighlights(events: AlertEvent[], selected?: AlertEvent | null): ComponentHighlight[] {
  const byId = new Map<ComponentId, AlertSeverity>();
  for (const event of [...events.filter((e) => e.state !== 'resolved'), ...(selected ? [selected] : [])]) {
    for (const componentId of event.components) if (event.severity === 'critical' || byId.get(componentId) !== 'critical') byId.set(componentId, event.severity);
  }
  return [...byId].map(([componentId, severity]) => ({ componentId, severity }));
}
