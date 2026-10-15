import { describe, expect, it } from 'vitest';
import type { Assessment } from './api';
import { acknowledgeAlert, ALERT_HISTORY_LIMIT, getComponentHighlights, mapAnomalyComponents, reconcileAlerts } from './alerts';

const assessment = (anomalies: Assessment['anomalies'], faults: string[] = []): Assessment => ({
  pump_id: 'pump-01', timestamp: '2026-02-02T00:00:00Z', health_score: 70, status: anomalies.length ? 'warning' : 'normal',
  anomalies, detected_faults: faults, recommendations: ['Inspect equipment'],
});
const anomaly = (metric: string, severity: 'warning' | 'critical' = 'warning') => ({ metric, observed_value: 6.2, expected_range: '0–4.5 mm/s', severity, explanation: 'Measured above configured range' });

describe('alert episodes and localization', () => {
  it('maps metric and supported fault evidence, falling back to generic pump for ambiguous readings', () => {
    expect(mapAnomalyComponents(anomaly('temperature_c'))).toEqual(['motor']);
    expect(mapAnomalyComponents(anomaly('vibration_mm_s'), ['bearing_wear_pattern'])).toEqual(['bearing']);
    expect(mapAnomalyComponents(anomaly('sound_db'))).toEqual(['pump']);
  });
  it('deduplicates repeated observations but starts a new ID after resolution', () => {
    let ids = 0;
    const makeId = () => `event-${++ids}`;
    const first = reconcileAlerts([], assessment([anomaly('vibration_mm_s')], ['bearing_wear']), 'now', makeId);
    const repeated = reconcileAlerts(first, assessment([{ ...anomaly('vibration_mm_s'), observed_value: 7 }], ['bearing_wear']), 'later', makeId);
    expect(repeated).toHaveLength(1);
    expect(repeated[0].id).toBe(first[0].id);
    expect(repeated[0].observed_value).toBe(7);
    const resolved = reconcileAlerts(repeated, assessment([]), 'resolved', makeId);
    expect(resolved[0].state).toBe('resolved');
    const restarted = reconcileAlerts(resolved, assessment([anomaly('vibration_mm_s')], ['bearing_wear']), 'again', makeId);
    expect(restarted.find((item) => item.state === 'active')?.id).not.toBe(first[0].id);
  });
  it('retains multiple anomalies, critical severity and critical priority on shared components', () => {
    const events = reconcileAlerts([], assessment([anomaly('temperature_c', 'critical'), anomaly('vibration_mm_s')], ['bearing_wear']), 'now', () => Math.random().toString());
    expect(events).toHaveLength(2);
    expect(getComponentHighlights(events)).toEqual(expect.arrayContaining([
      { componentId: 'motor', severity: 'critical' }, { componentId: 'bearing', severity: 'warning' },
    ]));
  });
  it('acknowledges without resolving and keeps acknowledged state on repeated observations', () => {
    const first = reconcileAlerts([], assessment([anomaly('vibration_mm_s')]), 'now', () => 'id');
    const ack = acknowledgeAlert(first, 'id', 'ack-time');
    expect(ack[0]).toMatchObject({ state: 'acknowledged', acknowledged_at: 'ack-time' });
    expect(reconcileAlerts(ack, assessment([anomaly('vibration_mm_s')]), 'later', () => 'new')[0].state).toBe('acknowledged');
  });
  it('keeps one acknowledged episode when severity and sensor values fluctuate', () => {
    let nextId = 0;
    let events = reconcileAlerts([], assessment([anomaly('vibration_mm_s')]), 't0', () => `event-${++nextId}`);
    const episodeId = events[0].id;
    events = acknowledgeAlert(events, episodeId, 'ack-time');
    for (let index = 0; index < 12; index += 1) {
      const severity = index % 2 ? 'warning' : 'critical';
      events = reconcileAlerts(events, assessment([{ ...anomaly('vibration_mm_s', severity), observed_value: index % 2 ? 7.8 : 8.2 }]), `t${index + 1}`, () => `event-${++nextId}`);
      expect(events).toHaveLength(1);
      expect(events[0]).toMatchObject({ id: episodeId, state: 'acknowledged', severity });
    }
    expect(nextId).toBe(1);
  });
  it('bounds long-running resolved event history while retaining current active events', () => {
    let events = [] as ReturnType<typeof reconcileAlerts>;
    let sequence = 0;
    for (let index = 0; index < ALERT_HISTORY_LIMIT + 25; index += 1) {
      events = reconcileAlerts(events, assessment([anomaly(`sensor_${index}`)]), new Date(Date.UTC(2026, 0, 1, 0, 0, index)).toISOString(), () => `event-${++sequence}`);
    }
    expect(events).toHaveLength(ALERT_HISTORY_LIMIT);
    expect(events.filter((event) => event.state !== 'resolved')).toHaveLength(1);
    expect(events.find((event) => event.state !== 'resolved')?.metric).toBe(`sensor_${ALERT_HISTORY_LIMIT + 24}`);
  });
});
