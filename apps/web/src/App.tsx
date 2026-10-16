import { lazy, Suspense, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { pumpApi, SCENARIOS, type Assessment, type DiagnosticProviderStatus, type DiagnosticRequest, type DiagnosticResult, type PumpApi, type Scenario, type SimulationSnapshot, type TelemetryAnalysis } from './api';
import { calculateEngineeringMetrics, type Telemetry } from './engineering';
import { acknowledgeAlert, getComponentHighlights, mapAnomalyComponents, reconcileAlerts, type AlertEvent } from './alerts';
import { prependReadingWindow } from './telemetry-window';
import { isTelemetryReading, validateSimulationResponse } from './response-validation';
import { DiagnosticExplorer } from './DiagnosticExplorer';
import { TelemetryAnalysisPanel } from './TelemetryAnalysisPanel';
import { AiFeaturePanel } from './AiFeaturePanel';
import { calculateMetricTrend, MEASUREMENTS, type MetricKey } from './diagnostics';
import { createAlarmAudio, type AlarmAudio } from './alarm-audio';

const PumpScene = lazy(() => import('./PumpScene').then((module) => ({ default: module.PumpScene })));

const METRIC_COLORS: Record<MetricKey, string> = {
  temperature_c: '#E3AD4C',
  vibration_mm_s: '#E87932',
  rpm: '#A2ABB2',
  sound_db: '#B7A48B',
  pressure_kpa: '#C98562',
};

const SCENARIO_NAMES: Record<Scenario, string> = {
  normal: 'Normal operation',
  overheating: 'Overheating',
  bearing_wear: 'Bearing wear',
  cavitation: 'Cavitation',
  imbalance: 'Rotor imbalance',
};

const SCENARIO_HELP: Record<Scenario, string> = {
  normal: 'Synthetic baseline with bounded sensor variation',
  overheating: 'Temperature-channel increase; not a component-specific sensor',
  bearing_wear: 'Synthetic vibration and sound pattern with gradual temperature drift',
  cavitation: 'Synthetic pressure reduction and irregular vibration/sound changes',
  imbalance: 'Synthetic vibration oscillation; no phase spectrum is modeled',
};

interface Props { api?: PumpApi }
type MonitoringState = 'stopped' | 'live' | 'paused';
type AlarmSoundStatus = 'ready' | 'blocked' | 'muted' | 'audible' | 'unavailable';
const LIVE_INTERVAL_MS = 1000;
const LIVE_MAX_AGE_MS = 30_000;
const CHART_HISTORY_LIMIT = 120;

function valueText(value: number | undefined, digits = 1) {
  return value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function Sparkline({ readings, field, color }: { readings: Telemetry[]; field: keyof Telemetry; color: string }) {
  const series = [...readings].filter((reading) => Number.isFinite(reading[field]) && Number.isFinite(Date.parse(reading.timestamp)))
    .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp)).slice(-48);
  const points = series.map((reading) => Number(reading[field]));
  if (!points.length) {
    return <div className="spark-empty">Waiting for telemetry</div>;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const coordinates = points.map((point, index) => `${39 + (index / Math.max(points.length - 1, 1)) * 177},${40 - ((point - min) / span) * 30}`).join(' ');
  const start = series[0].timestamp, end = series.at(-1)!.timestamp;
  const fmtTime = (stamp: string) => new Date(stamp).toLocaleTimeString();
  const unit = MEASUREMENTS[field as MetricKey]?.unit ?? '';
  return <svg className="sparkline" viewBox="0 0 224 62" preserveAspectRatio="none" role="img" aria-label={`${String(field).replaceAll('_', ' ')} trend from ${fmtTime(start)} to ${fmtTime(end)}, ${points.length} measured samples`}>
    <line x1="37" x2="218" y1="10" y2="10" /><line x1="37" x2="218" y1="40" y2="40" />
    <text x="0" y="12">{max.toFixed(1)} {unit}</text><text x="0" y="42">{min.toFixed(1)} {unit}</text>
    <polyline points={coordinates} fill="none" stroke={color} strokeWidth="1.7" vectorEffect="non-scaling-stroke" />
    <text x="28" y="58">{fmtTime(start)}</text><text x="218" y="58" textAnchor="end">{fmtTime(end)}</text>
  </svg>;
}

function HealthBadge({ assessment }: { assessment: Assessment | null }) {
  const status = assessment?.status ?? 'waiting';
  return <span className={`health-badge ${status}`}><i />{status === 'waiting' ? 'AWAITING DATA' : status.toUpperCase()}</span>;
}

function MetricCard({ field, telemetry, readings, assessment, freshness, monitoring }: {
  field: MetricKey; telemetry: Telemetry | null; readings: Telemetry[]; assessment: Assessment | null;
  freshness: string; monitoring: MonitoringState;
}) {
  const definition = MEASUREMENTS[field];
  const anomaly = assessment?.anomalies.find((item) => item.metric === field);
  const freshnessLabel = !telemetry ? 'NO SAMPLE' : freshness === 'Unavailable' ? 'UNAVAILABLE' : freshness === 'Stale' ? 'STALE' : monitoring === 'live' ? 'LIVE SAMPLE' : 'LAST SAMPLE';
  const color = METRIC_COLORS[field];
  return <article className="metric-card panel">
    <div className="metric-top"><span>{definition.label.toUpperCase()}</span><span className="measurement-state">{anomaly?.severity.toUpperCase() ?? (assessment ? (definition.thresholded ? 'NO FINDING' : 'NOT THRESHOLDED') : 'AWAITING')}</span></div>
    <div className="metric-reading">{valueText(telemetry?.[field])}<small className="metric-unit">{definition.unit}</small></div>
    <div className="metric-reference">{anomaly ? `Expected ${anomaly.expected_range}` : assessment && definition.thresholded ? 'No active threshold finding' : definition.thresholded ? 'Awaiting backend assessment' : 'No configured backend threshold'}</div>
    <Sparkline readings={readings} field={field} color={color} />
    <div className="metric-foot"><span>{definition.location}</span><span>{freshnessLabel}</span></div>
  </article>;
}

type DashboardField = 'vibration_mm_s' | 'bearing_temperature_c' | 'motor_temperature_c' | 'current_a' | 'flow_rate_m3_h' | 'inlet_pressure_kpa' | 'outlet_pressure_kpa' | 'rpm';
const DASHBOARD_CHARTS: { field: DashboardField; title: string; unit: string; color: string }[] = [
  { field: 'vibration_mm_s', title: 'Vibration RMS', unit: 'mm/s', color: '#e87932' },
  { field: 'bearing_temperature_c', title: 'Bearing temperature', unit: '°C', color: '#e3ad4c' },
  { field: 'motor_temperature_c', title: 'Motor temperature', unit: '°C', color: '#e87932' },
  { field: 'current_a', title: 'Motor current', unit: 'A', color: '#4db8e8' },
  { field: 'flow_rate_m3_h', title: 'Flow rate', unit: 'm³/h', color: '#54a878' },
  { field: 'inlet_pressure_kpa', title: 'Inlet pressure', unit: 'kPa', color: '#6bb5e8' },
  { field: 'rpm', title: 'Motor speed', unit: 'rpm', color: '#bb8ee8' },
];

function TelemetryChart({ field, title, unit, color, readings, telemetry }: {
  field: DashboardField; title: string; unit: string; color: string; readings: Telemetry[]; telemetry: Telemetry | null;
}) {
  const samples = [...readings].filter((item) => Number.isFinite(item[field]) && Number.isFinite(Date.parse(item.timestamp)))
    .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp)).slice(-48);
  const values = samples.map((item) => item[field] as number);
  const latest = telemetry?.[field];
  const available = typeof latest === 'number' && Number.isFinite(latest);
  if (!available) return <article className="dash-chart"><div className="dash-chart-head"><b>{title}</b><span>— {unit}</span></div><div className="chart-unavailable">Awaiting supported telemetry</div></article>;
  const min = Math.min(...values, latest as number), max = Math.max(...values, latest as number), span = max - min || 1;
  const points = values.map((value, index) => `${8 + (index / Math.max(values.length - 1, 1)) * 184},${39 - ((value - min) / span) * 29}`).join(' ');
  return <article className="dash-chart"><div className="dash-chart-head"><b>{title}</b><span style={{ color }}>{(latest as number).toFixed(1)} {unit}</span></div>
    {values.length > 1 ? <svg viewBox="0 0 200 54" role="img" aria-label={`${title} actual telemetry trend, ${values.length} samples, ${min.toFixed(1)} to ${max.toFixed(1)} ${unit}`}><line x1="6" x2="194" y1="10" y2="10"/><line x1="6" x2="194" y1="39" y2="39"/><polyline points={points} fill="none" stroke={color} strokeWidth="1.8" vectorEffect="non-scaling-stroke"/><text x="6" y="52">{new Date(samples[0].timestamp).toLocaleTimeString()}</text><text x="194" y="52" textAnchor="end">{new Date(samples.at(-1)!.timestamp).toLocaleTimeString()}</text></svg> : <div className="chart-unavailable">Collecting samples for trend</div>}
  </article>;
}

function StatusMetric({ label, value, unit, stale }: { label: string; value: number | null | undefined; unit: string; stale: boolean }) {
  return <div className="status-metric"><span>{label}</span><b>{typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '—'}<small>{typeof value === 'number' && Number.isFinite(value) ? ` ${unit}` : ''}</small></b><i className={stale ? 'is-stale' : typeof value === 'number' ? 'is-live' : ''}>{stale ? 'STALE' : typeof value === 'number' ? 'CURRENT' : 'UNAVAILABLE'}</i></div>;
}

function SystemStatus({ telemetry, assessment, stale }: { telemetry: Telemetry | null; assessment: Assessment | null; stale: boolean }) {
  const status = assessment?.status ?? 'waiting';
  const hasSample = Boolean(telemetry);
  return <section className={`system-status panel status-${status}`} aria-label="System status and operating measurements">
    <div className="status-title"><div><span className="panel-kicker">SYSTEM STATUS</span><h2>{!hasSample ? 'Awaiting telemetry' : status === 'normal' ? 'Operating normally' : `${status === 'critical' ? 'Critical' : 'Warning'} condition`}</h2></div><div className="health-chip"><b>{assessment?.health_score ?? '—'}</b><small>/100</small></div></div>
    {assessment?.detected_faults.length ? <div className="status-fault">{assessment.detected_faults.map((fault) => fault.replaceAll('_', ' ')).join(' · ')} <span>{assessment.anomalies.length} finding{assessment.anomalies.length === 1 ? '' : 's'}</span></div> : <div className="status-fault">{!hasSample ? 'Start a simulation to populate measurements' : stale ? 'Last assessment is stale' : 'No configured threshold findings'}</div>}
    <div className="status-metrics">
      <StatusMetric label="RPM" value={telemetry?.rpm} unit="rpm" stale={stale}/><StatusMetric label="Flow rate" value={telemetry?.flow_rate_m3_h} unit="m³/h" stale={stale}/>
      <StatusMetric label="Inlet pressure" value={telemetry?.inlet_pressure_kpa} unit="kPa" stale={stale}/><StatusMetric label="Outlet pressure" value={telemetry?.outlet_pressure_kpa} unit="kPa" stale={stale}/>
      <StatusMetric label="Motor current" value={telemetry?.current_a} unit="A" stale={stale}/><StatusMetric label="Motor temp" value={telemetry?.motor_temperature_c ?? telemetry?.temperature_c} unit="°C" stale={stale}/>
      <StatusMetric label="Bearing temp" value={telemetry?.bearing_temperature_c} unit="°C" stale={stale}/><StatusMetric label="Vibration RMS" value={telemetry?.vibration_mm_s} unit="mm/s" stale={stale}/>
    </div>
  </section>;
}

function EventTimeline({ monitoring, snapshot, alerts, diagnosis, sessionEvents }: { monitoring: MonitoringState; snapshot: SimulationSnapshot | null; alerts: AlertEvent[]; diagnosis: DiagnosticResult | null; sessionEvents: { id: string; label: string; time: string; tone: string }[] }) {
  const items: { id: string; label: string; time: string; tone: string }[] = [];
  if (monitoring === 'live') items.push({ id: 'simulation-running', label: 'Simulation running', time: 'Live session', tone: 'good' });
  for (const event of snapshot?.events ?? []) items.push({ id: `${event.kind}-${event.time_seconds}-${event.scenario}`, label: event.kind.replaceAll('_', ' '), time: `${event.time_seconds.toFixed(1)} s`, tone: event.kind.includes('fault') ? 'alert' : 'info' });
  for (const alert of alerts) items.push({ id: alert.id, label: `${alert.state === 'resolved' ? 'Fault resolved' : 'Alert'} · ${alert.metric.replaceAll('_', ' ')}`, time: new Date(alert.timestamp).toLocaleTimeString(), tone: alert.severity === 'critical' ? 'alert' : 'warn' });
  items.push(...sessionEvents);
  if (diagnosis) items.push({ id: `diagnosis-${diagnosis.correlation_id}`, label: `Diagnostic generated · ${diagnosis.provider === 'mock' ? 'mock' : 'provider'}`, time: new Date(diagnosis.assessment_timestamp).toLocaleTimeString(), tone: 'info' });
  const unique = [...new Map(items.map((item) => [item.id, item])).values()].slice(-8);
  return <section className="event-timeline panel" aria-label="Session event timeline"><div className="timeline-heading"><div><span className="panel-kicker">SESSION HISTORY</span><h2>Event timeline</h2></div><span>IN-MEMORY SESSION</span></div>{unique.length ? <ol>{unique.map((item) => <li key={item.id} className={item.tone}><i/><time>{item.time}</time><b>{item.label}</b></li>)}</ol> : <p>No simulation events yet. Start a simulation to record session events.</p>}</section>;
}

export function PumpTwinApp({ api = pumpApi }: Props) {
  const [pumpId, setPumpId] = useState('pump-01');
  const [scenario, setScenario] = useState<Scenario>('normal');
  const [sampleCount, setSampleCount] = useState(60);
  const [intervalSeconds, setIntervalSeconds] = useState(1);
  const [seed, setSeed] = useState(42);
  const [speed, setSpeed] = useState(1);
  const [rpmSetpoint, setRpmSetpoint] = useState(1780);
  const [loadPercent, setLoadPercent] = useState(65);
  const [cooling, setCooling] = useState(0.8);
  const [inletRestriction, setInletRestriction] = useState(0);
  const [faultSeverity, setFaultSeverity] = useState(1);
  const [faultEnabled, setFaultEnabled] = useState(false);
  const [simulationSnapshot, setSimulationSnapshot] = useState<SimulationSnapshot | null>(null);
  const [diagnosticResult, setDiagnosticResult] = useState<DiagnosticResult | null>(null);
  const [diagnosticResultKey, setDiagnosticResultKey] = useState<string | null>(null);
  const [diagnosticLoading, setDiagnosticLoading] = useState(false);
  const [diagnosticError, setDiagnosticError] = useState<string | null>(null);
  const [providerStatus, setProviderStatus] = useState<DiagnosticProviderStatus | null>(null);
  const [telemetryAnalysis, setTelemetryAnalysis] = useState<TelemetryAnalysis | null>(null);
  const [telemetryAnalysisLoading, setTelemetryAnalysisLoading] = useState(false);
  const [telemetryAnalysisError, setTelemetryAnalysisError] = useState<string | null>(null);
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [readings, setReadings] = useState<Telemetry[]>([]);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [returnedScenario, setReturnedScenario] = useState<Scenario | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(true);
  const [resetToken, setResetToken] = useState(0);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [sessionEvents, setSessionEvents] = useState<{ id: string; label: string; time: string; tone: string }[]>([]);
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [selectedMetric, setSelectedMetric] = useState<string | null>(null);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [soundStatus, setSoundStatus] = useState<AlarmSoundStatus>('ready');
  const [lastFreshAssessment, setLastFreshAssessment] = useState<string | null>(null);
  const [monitoring, setMonitoring] = useState<MonitoringState>('stopped');
  const inFlight = useRef(false);
  const latestReadingRef = useRef<Telemetry | null>(null);
  const alertsRef = useRef(alerts);
  const soundEnabledRef = useRef(soundEnabled);
  const soundStatusRef = useRef(soundStatus);
  const audioRef = useRef<AlarmAudio | null>(null);
  const sirenRequestedRef = useRef(false);
  const liveClientSessionIdRef = useRef<string | null>(null);
  const diagnosticRequestVersionRef = useRef(0);
  const resetSessionNextRef = useRef(false);
  if (liveClientSessionIdRef.current === null) {
    liveClientSessionIdRef.current = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `session-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
  }
  alertsRef.current = alerts;
  soundEnabledRef.current = soundEnabled;
  soundStatusRef.current = soundStatus;

  const updateSoundStatus = (status: AlarmSoundStatus) => {
    soundStatusRef.current = status;
    setSoundStatus(status);
  };

  const recordSessionEvent = (label: string, tone = 'info') => {
    const timestamp = new Date();
    const id = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${timestamp.getTime()}-${Math.random()}`;
    setSessionEvents((current) => [...current, { id, label, tone, time: timestamp.toLocaleTimeString() }].slice(-32));
  };

  useEffect(() => {
    try {
      const audio = createAlarmAudio();
      audioRef.current = audio;
      audio.setErrorHandler(() => {
        sirenRequestedRef.current = false;
        updateSoundStatus('unavailable');
      });
      updateSoundStatus('ready');
      return () => {
        audio.close();
        if (audioRef.current === audio) audioRef.current = null;
      };
    } catch {
      updateSoundStatus('unavailable');
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!api.diagnosticStatus) return;
    void api.diagnosticStatus().then((status) => { if (!cancelled) setProviderStatus(status); })
      .catch(() => { if (!cancelled) setProviderStatus(null); });
    return () => { cancelled = true; };
  }, [api]);

  useEffect(() => {
    const needsAlarm = alerts.some((event) => event.state === 'active');
    const audio = audioRef.current;
    const currentSoundStatus = soundStatusRef.current;
    if (!needsAlarm || !soundEnabled || currentSoundStatus === 'blocked' || currentSoundStatus === 'unavailable') {
      if (sirenRequestedRef.current) audio?.stop();
      sirenRequestedRef.current = false;
      if (currentSoundStatus === 'audible') updateSoundStatus(soundEnabled ? 'ready' : 'muted');
      return;
    }
    if (!audio) {
      updateSoundStatus('unavailable');
      return;
    }
    if (sirenRequestedRef.current) return;
    sirenRequestedRef.current = true;
    void audio.start().then(() => {
      if (soundEnabledRef.current && alertsRef.current.some((event) => event.state === 'active')) updateSoundStatus('audible');
    }).catch((error: unknown) => {
      sirenRequestedRef.current = false;
      const blocked = Boolean(error && typeof error === 'object' && 'name' in error && error.name === 'NotAllowedError');
      updateSoundStatus(blocked ? 'blocked' : 'unavailable');
    });
  }, [alerts, soundEnabled]);

  const enableSoundAlerts = () => {
    soundEnabledRef.current = true;
    setSoundEnabled(true);
    const audio = audioRef.current;
    if (!audio) {
      updateSoundStatus('unavailable');
      return;
    }
    // This is the only user-gesture path; it unlocks playback but never sounds
    // the alarm itself. Future newly detected episodes play automatically.
    void audio.activate().then(() => {
      if (alertsRef.current.some((event) => event.state === 'active')) {
        if (sirenRequestedRef.current) return;
        sirenRequestedRef.current = true;
        return audio.start().then(() => updateSoundStatus('audible')).catch(() => { sirenRequestedRef.current = false; updateSoundStatus('blocked'); });
      }
      updateSoundStatus('ready');
    }).catch(() => updateSoundStatus('blocked'));
  };

  const toggleSoundAlerts = () => {
    if (soundEnabledRef.current && soundStatusRef.current !== 'blocked') {
      soundEnabledRef.current = false;
      setSoundEnabled(false);
      updateSoundStatus('muted');
      return;
    }
    enableSoundAlerts();
  };
  const selectedAlert = alerts.find((item) => item.id === selectedAlertId) ?? null;
  const activeDiagnosticAlert = (selectedAlert?.state !== 'resolved' ? selectedAlert : null)
    ?? [...alerts].reverse().find((item) => item.state !== 'resolved') ?? null;
  const diagnosticKey = activeDiagnosticAlert?.id ?? (telemetry ? `${telemetry.pump_id}:${liveClientSessionIdRef.current}` : null);
  const visibleDiagnosis = diagnosticResultKey === diagnosticKey ? diagnosticResult : null;
  const activeCount = alerts.filter((item) => item.state !== 'resolved').length;
  const unacknowledgedAlerts = alerts.filter((item) => item.state === 'active');
  const componentHighlights = useMemo(() => {
    const highlights = getComponentHighlights(alerts, selectedAlert);
    const selectedAnomaly = assessment?.anomalies.find((item) => item.metric === selectedMetric);
    if (!selectedAnomaly) return highlights;
    const byComponent = new Map(highlights.map((item) => [item.componentId, item.severity]));
    const severity = selectedAnomaly.severity === 'critical' ? 'critical' : 'warning';
    for (const component of mapAnomalyComponents(selectedAnomaly, assessment?.detected_faults ?? [])) {
      if (severity === 'critical' || byComponent.get(component) !== 'critical') byComponent.set(component, severity);
    }
    return [...byComponent].map(([componentId, severity]) => ({ componentId, severity }));
  }, [alerts, selectedAlert, assessment, selectedMetric]);

  const sampleAgeMs = telemetry ? Date.now() - Date.parse(telemetry.timestamp) : Infinity;
  const isFresh = Boolean(telemetry && Math.abs(sampleAgeMs) <= LIVE_MAX_AGE_MS && apiOnline !== false);
  const monitoringLabel = isFresh && monitoring === 'live' ? 'LIVE' : apiOnline === false ? 'DISCONNECTED' : telemetry && sampleAgeMs > LIVE_MAX_AGE_MS ? 'STALE' : monitoring === 'live' ? 'CONNECTING' : 'READY';
  const diagnosticFreshness = !telemetry ? 'Awaiting sample' : !isFresh ? (apiOnline === false ? 'Unavailable' : 'Stale') : 'Fresh';

  const metrics = useMemo(
    () => calculateEngineeringMetrics(telemetry ?? {}),
    [telemetry],
  );

  const submit = async (event?: FormEvent, nextScenario = scenario, force = false) => {
    event?.preventDefault();
    if (pending || (inFlight.current && !force)) return;
    liveClientSessionIdRef.current = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID() : `session-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    diagnosticRequestVersionRef.current += 1;
    setDiagnosticLoading(false);
    setDiagnosticError(null);
    setMonitoring('stopped');
    setPending(true);
    setError(null);
    try {
      const requestStartedAt = Date.now();
      const response = validateSimulationResponse(await api.generate({
        pump_id: pumpId.trim(),
        client_session_id: liveClientSessionIdRef.current ?? undefined,
        scenario: nextScenario,
        sample_count: sampleCount,
        sampling_interval_seconds: intervalSeconds,
        random_seed: seed,
        start_time: new Date(requestStartedAt - Math.max(0, sampleCount - 1) * intervalSeconds * 1000).toISOString(),
      }), { pumpId: pumpId.trim(), scenario: nextScenario, maxAgeMs: LIVE_MAX_AGE_MS });
      const latest = response.readings.at(-1)!;
      setDiagnosticResult(null);
      setDiagnosticResultKey(null);
      latestReadingRef.current = latest;
      setReturnedScenario(response.scenario_label);
      setTelemetry(latest);
      setAssessment(response.assessment);
      setSimulationSnapshot(null);
      setLastFreshAssessment(response.assessment.timestamp);
      const previousAlerts = alertsRef.current;
      const nextAlerts = reconcileAlerts(previousAlerts, response.assessment, new Date().toISOString());
      alertsRef.current = nextAlerts;
      setAlerts(nextAlerts);
      setPumpId(latest?.pump_id ?? response.assessment.pump_id);
      setApiOnline(true);
      // The history endpoint has no scenario label and can mix older runs for
      // this pump. Seed this scenario's graphs only from the validated response.
      setReadings([...response.readings].filter(isTelemetryReading)
        .sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp))
        .slice(0, CHART_HISTORY_LIMIT));
      // A successful Generate action begins continuous backend telemetry.
      setMonitoring('live');
      recordSessionEvent('Simulation started', 'good');
    } catch (reason) {
      setApiOnline(false);
      setError(reason instanceof Error ? reason.message : 'Unable to reach the PumpGuard API.');
    } finally {
      setPending(false);
    }
  };

  useEffect(() => {
    if (monitoring !== 'live') return;
    let cancelled = false;
    let timer: number | undefined;
    const tick = async () => {
      if (cancelled) return;
      if (inFlight.current) {
        timer = window.setTimeout(() => void tick(), LIVE_INTERVAL_MS);
        return;
      }
      inFlight.current = true;
      try {
        const rawResponse = api.liveSample
          ? await api.liveSample({ pump_id: pumpId.trim(), scenario, random_seed: seed, client_session_id: liveClientSessionIdRef.current!,
            reset_session: resetSessionNextRef.current, speed, rpm_setpoint: rpmSetpoint, load_percent: loadPercent, cooling_effectiveness: cooling,
            inlet_restriction_percent: inletRestriction, fault_severity: faultSeverity, fault_enabled: faultEnabled })
          : await api.generate({ pump_id: pumpId.trim(), scenario, sample_count: 1, sampling_interval_seconds: 1, random_seed: seed });
        if (cancelled) return;
        const response = validateSimulationResponse(rawResponse, {
          pumpId: pumpId.trim(), scenario, maxAgeMs: LIVE_MAX_AGE_MS, newerThan: latestReadingRef.current?.timestamp,
        });
        const latest = response.readings.at(-1)!;
        resetSessionNextRef.current = false;
        latestReadingRef.current = latest;
        setTelemetry(latest);
        setAssessment(response.assessment);
        setReturnedScenario(response.scenario_label);
        setLastFreshAssessment(response.assessment.timestamp);
        setSimulationSnapshot(response.simulation ?? null);
        setApiOnline(true);
        setError(null);
        setReadings((current) => prependReadingWindow(current, latest, CHART_HISTORY_LIMIT));
        const previousAlerts = alertsRef.current;
        const nextAlerts = reconcileAlerts(previousAlerts, response.assessment, new Date().toISOString());
        alertsRef.current = nextAlerts;
        setAlerts(nextAlerts);
      } catch (reason) {
        if (!cancelled) {
          setApiOnline(false);
          setError(reason instanceof Error ? reason.message : 'Unable to reach the PumpGuard API.');
        }
      } finally {
        inFlight.current = false;
        if (!cancelled) timer = window.setTimeout(() => void tick(), LIVE_INTERVAL_MS);
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [api, monitoring, pumpId, scenario, seed, speed, rpmSetpoint, loadPercent, cooling, inletRestriction, faultSeverity, faultEnabled]);

  const changeScenario = (nextScenario: Scenario) => {
    if (nextScenario === scenario) return;
    diagnosticRequestVersionRef.current += 1;
    setDiagnosticLoading(false);
    setDiagnosticError(null);
    setScenario(nextScenario);
    recordSessionEvent(`Scenario selected · ${SCENARIO_NAMES[nextScenario]}`, 'info');
    setFaultEnabled(nextScenario !== 'normal');
    setSimulationSnapshot(null);
    setDiagnosticResult(null);
    setDiagnosticResultKey(null);
    if (monitoring !== 'stopped') {
      setReadings([]);
      setTelemetry(null);
      latestReadingRef.current = null;
      setAssessment(null);
      setReturnedScenario(null);
      setLastFreshAssessment(null);
      setApiOnline(null);
    }
  };

  const handleReset = () => {
    if (pending) return;
    setScenario('normal');
    setFaultEnabled(false);
    setSimulationSnapshot(null);
    resetSessionNextRef.current = true;
    setResetToken((value) => value + 1);
    void submit(undefined, 'normal', true);
  };

  const requestDiagnosis = async () => {
    if (!assessment || !telemetry || !api.diagnose || diagnosticLoading) return;
    const samples = [...readings].sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp)).slice(-12);
    if (!samples.length) samples.push(telemetry);
    const trends = (Object.keys(MEASUREMENTS) as MetricKey[]).flatMap((metric) => {
      const trend = calculateMetricTrend(samples, metric);
      return trend ? [{ metric, initial_value: trend.initialValue, latest_value: trend.latestValue, delta: trend.delta,
        elapsed_seconds: trend.elapsedSeconds, samples: trend.samples }] : [];
    });
    const alertContext = activeDiagnosticAlert ? {
      episode_id: activeDiagnosticAlert.id, metric: activeDiagnosticAlert.metric, severity: activeDiagnosticAlert.severity,
      observed_value: activeDiagnosticAlert.observed_value, expected_range: activeDiagnosticAlert.expected_range,
      explanation: activeDiagnosticAlert.explanation,
    } : null;
    const request: DiagnosticRequest = {
      pump_id: telemetry.pump_id, simulation_id: liveClientSessionIdRef.current ?? undefined,
      alert_episode_id: activeDiagnosticAlert?.id, assessment_timestamp: assessment.timestamp,
      telemetry: samples.map((reading) => ({ timestamp: reading.timestamp, temperature_c: reading.temperature_c,
        vibration_mm_s: reading.vibration_mm_s, sound_db: reading.sound_db, rpm: reading.rpm,
        pressure_kpa: reading.pressure_kpa, load_percent: reading.load_percent })),
      trends, detector: { status: assessment.status, score: assessment.health_score,
        predicted_faults: assessment.detected_faults, confidence: null }, is_synthetic: true,
      assessment: { status: assessment.status, health_score: assessment.health_score,
        anomalies: assessment.anomalies, recommendations: assessment.recommendations },
      selected_scenario: returnedScenario ?? scenario,
      injected_scenario: simulationSnapshot?.fault_enabled ? (returnedScenario ?? scenario) : null,
      alert: alertContext,
      events: simulationSnapshot?.events.slice(-12) ?? [],
    };
    setDiagnosticLoading(true);
    setDiagnosticError(null);
    setDiagnosticResult(null);
    const requestVersion = ++diagnosticRequestVersionRef.current;
    try {
      const result = await api.diagnose(request);
      if (requestVersion === diagnosticRequestVersionRef.current) {
        setDiagnosticResult(result);
        setDiagnosticResultKey(diagnosticKey);
        recordSessionEvent('Diagnostic explanation generated', 'info');
      }
    } catch (reason) {
      if (requestVersion === diagnosticRequestVersionRef.current) setDiagnosticError(reason instanceof Error ? reason.message : 'Diagnostic provider request failed.');
    } finally {
      if (requestVersion === diagnosticRequestVersionRef.current) setDiagnosticLoading(false);
    }
  };

  const requestTelemetryAnalysis = async () => {
    if (!api.telemetryAnalysis || telemetryAnalysisLoading) return;
    setTelemetryAnalysisLoading(true);
    setTelemetryAnalysisError(null);
    try {
      // The backend requires limit >= 2; request a bounded window of the recent history.
      const limit = Math.min(Math.max(readings.length, 2), 200);
      const result = await api.telemetryAnalysis(telemetry?.pump_id ?? pumpId, limit);
      setTelemetryAnalysis(result);
      recordSessionEvent('Telemetry intelligence analysis refreshed', 'info');
    } catch (reason) {
      setTelemetryAnalysis(null);
      setTelemetryAnalysisError(reason instanceof Error ? reason.message : 'Telemetry analysis request failed.');
    } finally {
      setTelemetryAnalysisLoading(false);
    }
  };

  const latestTime = telemetry ? new Date(telemetry.timestamp).toLocaleString() : 'No sample yet';

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="PumpGuard workspace navigation">
        <a className="brand" href="#top" aria-label="PumpGuard home">
          <span className="brand-mark"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M7 25h5l3-11 6 18 4-13 3 6h5" /><circle cx="20" cy="20" r="17" /></svg></span>
          <span><b>PUMPGUARD</b><small>CONDITION MONITOR</small></span>
        </a>
        <div className="sidebar-section">MONITOR</div>
        <button className="nav-item active" aria-current="page" aria-label="Overview" title="Overview"><span className="nav-icon">◈</span><span className="nav-label">Overview</span><span className="nav-current" /></button>
        <button className="nav-item" aria-label="Sensor trends" title="Sensor trends" onClick={() => document.getElementById('sensor-panel')?.scrollIntoView({ behavior: 'smooth' })}><span className="nav-icon">⌁</span><span className="nav-label">Sensor trends</span></button>
        <button className="nav-item" aria-label="Diagnostics and alerts" title="Diagnostics and alerts" onClick={() => document.getElementById('alert-history')?.scrollIntoView({ behavior: 'smooth' })}><span className="nav-icon">▤</span><span className="nav-label">Diagnostics / alerts</span></button>
        <button className="nav-item" aria-label="Health assessment" title="Health assessment" onClick={() => document.getElementById('assessment-panel')?.scrollIntoView({ behavior: 'smooth' })}><span className="nav-icon">⌖</span><span className="nav-label">Health assessment</span></button>
        <div className="sidebar-bottom">
          <div className="connection-card" role="status" aria-label={apiOnline === false ? 'API unreachable' : isFresh ? 'API connected and telemetry fresh' : apiOnline ? 'API connected; sample not current' : 'API status unknown'} title={apiOnline === false ? 'API unreachable' : isFresh ? 'API connected and telemetry fresh' : apiOnline ? 'API connected; sample not current' : 'API status unknown'}><span className={`connection-indicator ${apiOnline === false ? 'offline' : isFresh ? 'online' : ''}`} /><div><b>{apiOnline === false ? 'API unreachable' : isFresh ? 'API connected' : apiOnline ? 'Sample not current' : 'API status'}</b><small>{apiOnline === false ? 'Check local service' : 'Local simulation service'}</small></div><span className="connection-menu">···</span></div>
          <div className="sidebar-foot">SYNTHETIC DEMONSTRATION <span>v0.4.1</span></div>
        </div>
      </aside>

      <main className="main-content" id="top">
        <header className="topbar">
          <a className="dashboard-brand" href="#top" aria-label="PumpGuard dashboard"><span className="brand-mark"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M7 25h5l3-11 6 18 4-13 3 6h5"/><circle cx="20" cy="20" r="17"/></svg></span><span><b>PumpGuard</b><small>Industrial Simulation</small></span></a>
          <nav className="dashboard-tabs" aria-label="Dashboard sections">
            <button onClick={() => document.getElementById('top')?.scrollIntoView({ behavior: 'smooth' })}>Live Monitor</button>
            <button className="active" aria-current="page" onClick={() => document.getElementById('simulation-controls')?.scrollIntoView({ behavior: 'smooth' })}>Simulation</button>
            <button onClick={() => document.getElementById('diagnostic-inspector')?.scrollIntoView({ behavior: 'smooth' })}>Diagnostics</button>
            <button onClick={() => document.getElementById('assessment-panel')?.scrollIntoView({ behavior: 'smooth' })}>Maintenance</button>
            <button onClick={() => document.getElementById('alert-history')?.scrollIntoView({ behavior: 'smooth' })}>History</button>
            <button disabled title="Fleet view is not implemented">Fleet View</button>
          </nav>
          <div className="topbar-right"><span className="synthetic-tag"><i /> SYNTHETIC DATA</span><span className="topbar-divider" /><span className="pump-chip">PUMP <b>{telemetry?.pump_id ?? pumpId}</b></span><span className="pump-chip">SCENARIO <b>{SCENARIO_NAMES[returnedScenario ?? scenario]}</b></span><div className={`connection-masthead ${monitoringLabel.toLowerCase()}`}>{monitoringLabel}</div></div>
        </header>

        <section className="page-heading">
          <div><div className="eyebrow">PUMPGUARD <span>/</span> CENTRIFUGAL PUMP</div><h1>Pump monitoring</h1><p>Telemetry, threshold assessments, and inspectable diagnostic evidence.</p></div>
          <div className="heading-actions"><span className="last-updated">{telemetry ? `UPDATED ${new Date(telemetry.timestamp).toLocaleTimeString()}` : 'NO LIVE SAMPLE'}</span><button className="icon-button" aria-label="Reset 3D camera" onClick={() => setResetToken((value) => value + 1)}>⟲</button></div>
        </section>

        <section className="alarm-strip panel" aria-label="Alert controls">
          <button className="alarm-indicator" onClick={() => document.getElementById('alert-history')?.scrollIntoView({ behavior: 'smooth' })}>
            <span className={`alarm-light ${alerts.some((item) => item.state !== 'resolved' && item.severity === 'critical') ? 'critical' : activeCount ? 'warning' : ''}`} />
            <b>{activeCount} active alert{activeCount === 1 ? '' : 's'}</b>
            {alerts.some((item) => item.state === 'acknowledged') && <small>· acknowledged</small>}
          </button>
          <span className={`freshness-note state-${monitoringLabel.toLowerCase()}`}>{monitoringLabel === 'LIVE' ? 'LIVE · fresh backend samples expected each second' : monitoringLabel === 'STALE' ? 'STALE · last sample is outside the freshness window' : monitoringLabel === 'DISCONNECTED' ? 'DISCONNECTED · telemetry unavailable' : monitoringLabel === 'CONNECTING' ? 'CONNECTING · awaiting first live sample' : 'READY · generate a simulation to start live telemetry'}{lastFreshAssessment ? ` · last successful assessment ${new Date(lastFreshAssessment).toLocaleTimeString()}` : ''}</span>
          {assessment && <div className="operational-assessment"><span className={`health-badge ${assessment.status}`}><i />{assessment.status.toUpperCase()}</span><b>{assessment.health_score}<small>/100</small></b><span>{assessment.anomalies.length} threshold finding{assessment.anomalies.length === 1 ? '' : 's'}</span></div>}
          {soundStatus === 'blocked' && <span className="sound-status blocked" role="status">Browser blocked sound · enable once</span>}
          {soundStatus === 'unavailable' && <span className="sound-status" role="status">Sound unavailable · visual alarms active</span>}
          {unacknowledgedAlerts.map((item) => <div className="active-alarm-control" key={item.id}>
            <span className={`alarm-state-label ${item.severity}`}>{soundStatus === 'audible' && soundEnabled ? 'UNACKNOWLEDGED — AUDIBLE ALARM' : 'UNACKNOWLEDGED — SOUND NOT ACTIVE'}</span>
            <small>{item.metric.replaceAll('_', ' ')} · {item.components.join(', ') || 'pump'} · {item.severity.toUpperCase()}</small>
            <button className="alarm-control acknowledge-button" onClick={() => { setAlerts((current) => { const next = acknowledgeAlert(current, item.id, new Date().toISOString()); alertsRef.current = next; return next; }); recordSessionEvent(`Alarm acknowledged · ${item.metric.replaceAll('_', ' ')}`, 'warn'); }}>ACKNOWLEDGE ALARM — SILENCE SIREN</button>
          </div>)}
          {alerts.some((item) => item.state === 'acknowledged') && <span className="alarm-state-label acknowledged-state">ACKNOWLEDGED — FAULT ACTIVE</span>}
          {!alerts.some((item) => item.state !== 'resolved') && alerts.some((item) => item.state === 'resolved') && <span className="alarm-state-label resolved-state">FAULT CLEARED</span>}
          <button className="alarm-control" aria-pressed={soundEnabled && soundStatus !== 'blocked'} disabled={soundStatus === 'unavailable'} onClick={toggleSoundAlerts}>{soundStatus === 'unavailable' ? 'Sound unavailable' : soundEnabled && soundStatus !== 'blocked' ? 'Mute alarms' : 'Enable sound alerts'}</button>
        </section>

        {error && <div className="error-banner" role="alert"><span>!</span><div><b>{monitoring === 'live' ? 'Live telemetry unavailable' : 'Simulation request failed'}</b><small>{error}</small></div><button aria-label="Dismiss error" onClick={() => setError(null)}>×</button></div>}

        <div className="overview-grid">
        <section className="twin-card panel">
            <div className="panel-heading twin-panel-heading"><div><span className="panel-kicker">3D DIGITAL TWIN — LIVE SIMULATION</span><h2>{SCENARIO_NAMES[returnedScenario ?? scenario]} <span className="model-pill">LIVE MODEL</span></h2></div><div className="scene-actions"><button className={`scene-action ${playing ? 'selected' : ''}`} onClick={() => setPlaying((value) => !value)} title={playing ? 'Pause 3D animation only' : 'Resume 3D animation only'}>{playing ? 'Ⅱ' : '▶'} <span>{playing ? 'Pause animation' : 'Play animation'}</span></button><button className="scene-action" onClick={() => setResetToken((value) => value + 1)} title="Reset view">⟲ <span>Reset view</span></button></div></div>
            <Suspense fallback={<div className="scene-loading" role="status">Preparing 3D pump model…</div>}><PumpScene scenario={returnedScenario ?? 'normal'} telemetry={telemetry} metrics={metrics} playing={playing} resetToken={resetToken} componentHighlights={componentHighlights} onComponentClick={(componentId) => { const match = [...alerts].reverse().find((item) => item.components.includes(componentId) && item.state !== 'resolved') ?? [...alerts].reverse().find((item) => item.components.includes(componentId)); if (match) { setSelectedAlertId(match.id); setSelectedMetric(null); } else { const anomaly = assessment?.anomalies.find((item) => mapAnomalyComponents(item, assessment.detected_faults).includes(componentId)); setSelectedAlertId(null); setSelectedMetric(anomaly?.metric ?? null); } }} /></Suspense>
          <div className="pump-callouts" aria-label="Current pump telemetry callouts">
            {[['Inlet pressure', telemetry?.inlet_pressure_kpa, 'kPa'], ['Outlet pressure', telemetry?.outlet_pressure_kpa, 'kPa'], ['Impeller speed', telemetry?.rpm, 'rpm'], ['Bearing temperature', telemetry?.bearing_temperature_c, '°C'], ['Flow rate', telemetry?.flow_rate_m3_h, 'm³/h'], ['Vibration', telemetry?.vibration_mm_s, 'mm/s'], ['Motor current', telemetry?.current_a, 'A']].map(([label, value, unit]) => <div key={String(label)}><small>{label}</small><b>{typeof value === 'number' ? `${value.toFixed(1)} ${unit}` : '—'}</b></div>)}
          </div>
          <div className="twin-foot"><span><i className="green-dot" /> {telemetry ? 'MODEL SYNCHRONIZED' : 'MODEL READY'}</span><span>VISUAL MOTION ONLY · GENERATE STARTS LIVE TELEMETRY</span></div>
          </section>

          <section className="controls-card panel" id="simulation-controls">
            <div className="panel-heading"><div><span className="panel-kicker">SIMULATION CONTROL</span><h2>Operating scenario</h2></div><span className="control-glyph">⌘</span></div>
            <form onSubmit={(event) => void submit(event)}>
              <label className="field-label" htmlFor="scenario">Scenario</label>
              <div className="select-wrap"><select id="scenario" value={scenario} onChange={(event) => changeScenario(event.target.value as Scenario)} disabled={pending}>{SCENARIOS.map((item) => <option key={item} value={item}>{SCENARIO_NAMES[item]}</option>)}</select><span>⌄</span></div>
              <div className="scenario-note"><i />{SCENARIO_HELP[scenario]}</div>
              <div className="field-row"><label className="field-group"><span className="field-label">Pump identity</span><input value={pumpId} onChange={(event) => setPumpId(event.target.value)} maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9_.\-]*" required disabled={pending || monitoring !== 'stopped'} /></label><label className="field-group"><span className="field-label">Samples</span><input type="number" min="1" max="10000" value={sampleCount} onChange={(event) => setSampleCount(Number(event.target.value))} required disabled={pending || monitoring !== 'stopped'} /></label></div>
              <div className="field-row"><label className="field-group"><span className="field-label">Interval <small>seconds</small></span><input type="number" min="0.1" max="86400" step="0.1" value={intervalSeconds} onChange={(event) => setIntervalSeconds(Number(event.target.value))} required disabled={pending || monitoring !== 'stopped'} /></label><label className="field-group"><span className="field-label">Random seed</span><input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} disabled={pending || monitoring !== 'stopped'} /></label></div>
              <label className="simulation-slider"><span>Simulation speed <b>{speed.toFixed(2)}×</b></span><input aria-label="Simulation speed" type="range" min="0.25" max="4" step="0.25" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} /><small>× simulation time per live sample</small></label>
              <label className="simulation-slider"><span>Motor speed <b>{rpmSetpoint} rpm</b></span><input aria-label="Motor speed" type="range" min="1200" max="2500" step="10" value={rpmSetpoint} onChange={(event) => setRpmSetpoint(Number(event.target.value))} /></label>
              <label className="simulation-slider"><span>Motor load <b>{loadPercent}%</b></span><input aria-label="Motor load" type="range" min="10" max="100" step="1" value={loadPercent} onChange={(event) => setLoadPercent(Number(event.target.value))} /></label>
              <label className="simulation-slider"><span>Cooling effectiveness <b>{Math.round(cooling * 100)}%</b></span><input aria-label="Cooling effectiveness" type="range" min="0.2" max="1" step="0.05" value={cooling} onChange={(event) => setCooling(Number(event.target.value))} /></label>
              <label className="simulation-slider"><span>Inlet restriction <b>{inletRestriction}%</b></span><input aria-label="Inlet restriction" type="range" min="0" max="70" step="1" value={inletRestriction} onChange={(event) => setInletRestriction(Number(event.target.value))} /></label>
              <label className="simulation-slider"><span>Fault severity <b>{Math.round(faultSeverity * 100)}%</b></span><input aria-label="Fault severity" type="range" min="0" max="1" step="0.05" value={faultSeverity} onChange={(event) => setFaultSeverity(Number(event.target.value))} /></label>
              <label className="fault-toggle"><input type="checkbox" aria-label="Inject selected fault" checked={faultEnabled} disabled={scenario === 'normal'} onChange={(event) => { setFaultEnabled(event.target.checked); recordSessionEvent(event.target.checked ? `Fault injected · ${SCENARIO_NAMES[scenario]}` : 'Fault recovery requested', event.target.checked ? 'alert' : 'warn'); }} /><span>Inject selected fault</span><small>{scenario === 'normal' ? 'SELECT A FAULT SCENARIO' : faultEnabled ? 'ACTIVE' : 'CLEARED / DISABLED'}</small></label>
              <div className="simulation-state" role="status"><span>SIM TIME <b>{(simulationSnapshot?.time_seconds ?? 0).toFixed(1)} s</b></span><span>STATE <b>{monitoring === 'live' ? 'RUNNING' : monitoring === 'paused' ? 'PAUSED' : 'STOPPED'}</b></span><span>FAULT <b>{simulationSnapshot?.fault_enabled ? 'INJECTED' : assessment?.anomalies.length ? 'DETECTED' : 'NONE DETECTED'}</b></span></div>
              {simulationSnapshot?.events.length ? <div className="simulation-events" aria-label="Simulation event markers">{simulationSnapshot.events.slice(-4).map((item, index) => <span key={`${item.kind}-${item.time_seconds}-${index}`}>{item.time_seconds.toFixed(1)}s · {item.kind.replaceAll('_', ' ')}</span>)}</div> : null}
              <div className="form-hint"><span className="info-dot">i</span>Same seed and inputs reproduce the same synthetic readings.</div>
              {monitoring === 'stopped' && <button className="primary-button" type="submit" disabled={pending || !pumpId.trim()}>{pending ? <><span className="spinner" /> Generating telemetry…</> : <>Generate simulation <span>→</span></>}</button>}
              {monitoring === 'live' && <button className="primary-button" type="button" onClick={() => { setMonitoring('paused'); recordSessionEvent('Simulation paused', 'warn'); }}>Pause simulation <span>Ⅱ</span></button>}
              {monitoring === 'paused' && <button className="primary-button" type="button" onClick={() => { setMonitoring('live'); recordSessionEvent('Simulation resumed', 'good'); }}>Resume simulation <span>▶</span></button>}
              {monitoring !== 'stopped' && <button className="stop-button" type="button" onClick={() => { setMonitoring('stopped'); recordSessionEvent('Live telemetry stopped', 'warn'); }}>Stop live simulation</button>}
              <button className="reset-button" type="button" onClick={handleReset} disabled={pending}>Reset to normal operation</button>
            </form>
            <div className="control-divider" />
            <div className="scenario-key"><span className="panel-kicker">AVAILABLE SCENARIOS</span>{SCENARIOS.map((item, index) => <button key={item} onClick={() => changeScenario(item)} disabled={pending} className={scenario === item ? 'scenario-option active' : 'scenario-option'}><i className={`scenario-mark mark-${item}`} /><span>{SCENARIO_NAMES[item]}</span><kbd>{index + 1}</kbd></button>)}</div>
          </section>
        </div>

        <SystemStatus telemetry={telemetry} assessment={assessment} stale={Boolean(telemetry && !isFresh)} />
        <section className="metrics-section panel" id="sensor-panel" data-layout-slot="diagnostic">
          <div className="section-title"><div><span className="panel-kicker">LIVE TELEMETRY — TIME SERIES</span><h2>Operating parameters</h2></div><div className="sample-time"><span className={isFresh ? 'green-dot' : 'stale-dot'} />{latestTime}</div></div>
          <div className="dashboard-chart-grid">{DASHBOARD_CHARTS.map((chart) => <TelemetryChart key={chart.field} {...chart} readings={readings} telemetry={telemetry}/>)}</div>
          <div className="analysis-panels"><article><header><b>Vibration spectrum (FFT)</b><small>Unavailable</small></header><p>Frequency-domain data is not supplied by the current simulator. No spectrum has been inferred from insufficient samples.</p></article><article><header><b>Flow & pressure dynamics</b><small>Measured telemetry</small></header><TelemetryChart field="flow_rate_m3_h" title="Flow" unit="m³/h" color="#54a878" readings={readings} telemetry={telemetry}/><TelemetryChart field="outlet_pressure_kpa" title="Outlet" unit="kPa" color="#e87932" readings={readings} telemetry={telemetry}/></article><article><header><b>Temperature trend</b><small>Measured telemetry</small></header><TelemetryChart field="motor_temperature_c" title="Motor temperature" unit="°C" color="#e87932" readings={readings} telemetry={telemetry}/><TelemetryChart field="bearing_temperature_c" title="Bearing temperature" unit="°C" color="#e3ad4c" readings={readings} telemetry={telemetry}/></article></div>
          <div className="legacy-metrics">
          <div className="section-title"><div><span className="panel-kicker">RULE THRESHOLDED SENSOR CHANNELS</span><h2>Assessment details</h2></div></div>
          <div className="metrics-grid">
            {(['temperature_c', 'vibration_mm_s', 'rpm', 'sound_db', 'pressure_kpa'] as MetricKey[]).map((field) => <MetricCard key={field} field={field} telemetry={telemetry} readings={readings} assessment={assessment} freshness={diagnosticFreshness} monitoring={monitoring} />)}
          </div>
          <details className="engineering-details"><summary>Engineering calculations and display references</summary><div className="engineering-detail-grid"><p><b>Frequency</b><code>f = RPM / 60</code><span>Revolutions per second, shown in Hz.</span></p><p><b>Angular velocity</b><code>ω = 2π × RPM / 60</code><span>Drives visual shaft rotation in rad/s.</span></p><p><b>RPM deviation</b><code>(RPM − 1,780) / 1,780 × 100</code><span>Relative to an illustrative reference, not a validated equipment limit.</span></p><p><b>Temperature deviation</b><code>temperature − 68 °C</code><span>Illustrative reference only; backend thresholds appear in the assessment.</span></p><p><b>Vibration indicator</b><code>min(vibration / 8 mm/s, 1)</code><span>Normalized visualization scale, not a certified severity standard.</span></p></div></details>
          </div>
        </section>

        <section className="alert-section panel" id="alert-history" aria-label="Alert history">
          <div className="alert-list">
            <div className="alert-section-heading"><div><span className="panel-kicker">SESSION EVENT HISTORY</span><h2>Alerts</h2></div><span className="session-label">THIS SESSION ONLY</span></div>
            {!alerts.length ? <p className="alert-empty">No warning or critical findings have been reported.</p> : [...alerts].reverse().map((item) => <button className={`alert-event ${selectedAlertId === item.id ? 'selected' : ''}`} key={item.id} onClick={() => { setSelectedAlertId(item.id); setSelectedMetric(null); }}>
              <span className={`finding-indicator ${item.severity}`} /><span className="alert-event-main"><b>{item.metric.replaceAll('_', ' ')}</b><small>{item.observed_value.toFixed(1)} · {item.expected_range} · {item.components.join(', ')} · {new Date(item.timestamp).toLocaleString()} · {item.pump_id}</small></span><span className={`severity-pill ${item.severity}`}>{item.severity}</span><span className={`state-pill ${item.state}`}>{item.state}</span>
            </button>)}
          </div>
          <section className="diagnostic-panel panel" id="diagnostic-inspector" data-layout-slot="inspector" aria-label="Diagnostic inspector">
            <DiagnosticExplorer assessment={assessment} telemetry={telemetry} readings={readings} scenario={returnedScenario ?? scenario} freshness={diagnosticFreshness} selectedMetric={selectedMetric} selectedAlert={selectedAlert} onSelectMetric={(metric) => { setSelectedMetric(metric); const matching = [...alerts].reverse().find((item) => item.metric === metric && item.state !== 'resolved'); setSelectedAlertId(matching?.id ?? null); }} diagnosis={visibleDiagnosis} diagnosisLoading={diagnosticLoading} diagnosisError={diagnosticError} providerStatus={providerStatus} diagnosticAvailable={Boolean(api.diagnose)} onRequestDiagnosis={() => void requestDiagnosis()} api={api} pumpId={telemetry?.pump_id ?? pumpId} clientSessionId={liveClientSessionIdRef.current ?? undefined} />
          </section>
          <TelemetryAnalysisPanel analysis={telemetryAnalysis} loading={telemetryAnalysisLoading} error={telemetryAnalysisError} onAnalyze={() => void requestTelemetryAnalysis()} available={Boolean(api.telemetryAnalysis) && Boolean(telemetry)} />
          <AiFeaturePanel api={api} pumpId={telemetry?.pump_id ?? pumpId} clientSessionId={liveClientSessionIdRef.current} contextAvailable={Boolean(telemetry && assessment)} contextKey={`${telemetry?.pump_id ?? pumpId}:${returnedScenario ?? scenario}`} />
        </section>

        <EventTimeline monitoring={monitoring} snapshot={simulationSnapshot} alerts={alerts} diagnosis={visibleDiagnosis} sessionEvents={sessionEvents} />

        <section className="assessment-section panel" id="assessment-panel">
          <div className="assessment-main"><div className="section-title assessment-title"><div><span className="panel-kicker">RULE-BASED HEALTH ENGINE</span><h2>Latest assessment</h2></div><HealthBadge assessment={assessment} /></div>
            <div className="assessment-score"><div className="score-ring" style={{ '--score': assessment?.health_score ?? 0 } as React.CSSProperties}><div><b>{assessment?.health_score ?? '—'}</b><small>/ 100</small></div></div><div className="score-copy"><b>{assessment ? `${assessment.status[0].toUpperCase()}${assessment.status.slice(1)} condition` : 'Awaiting simulation'}</b><p>{assessment ? `${assessment.anomalies.length} threshold finding${assessment.anomalies.length === 1 ? '' : 's'} from the latest generated sample.` : 'Generate a scenario to view the rule-based assessment.'}</p></div></div>
            <div className="assessment-findings"><div className="finding-heading"><span>THRESHOLD FINDINGS</span><span>{assessment?.anomalies.length ?? 0} ITEMS</span></div>{assessment?.anomalies.length ? assessment.anomalies.map((item, index) => <div className="finding-row" key={`${item.metric}-${index}`}><span className={`finding-indicator ${item.severity}`} /><b>{item.metric.replaceAll('_', ' ')}</b><span>{item.observed_value.toFixed(1)}</span><small>{item.expected_range}</small><em>{item.severity}</em></div>) : <div className="empty-findings">{assessment ? 'No threshold findings in the latest sample.' : 'No assessment available yet.'}</div>}</div>
          </div>
          <div className="recommendations"><div className="recommendation-heading"><span className="panel-kicker">RULE ENGINE OUTPUT</span><span className="shield-icon">◇</span></div><h3>Recommendations</h3>{assessment?.recommendations.length ? <ul>{assessment.recommendations.map((item, index) => <li key={index}><span>{String(index + 1).padStart(2, '0')}</span>{item}</li>)}</ul> : <div className="recommendation-empty">{assessment ? 'No action recommended by the current rules.' : 'Recommendations will appear after a simulation.'}</div>}<div className="assessment-caveat"><span>ⓘ</span><p>This score reflects configured sensor thresholds. It is not a failure probability or prediction.</p></div></div>
        </section>

        <footer className="disclaimer"><span className="disclaimer-icon">ⓘ</span><p><b>Simulation environment.</b> All readings are synthetic. The 3D model and engineering references are illustrative and not to scale. Scenario classification and rule-based health status do not establish real-world pump condition or failure risk.</p><span>LOCAL DEMO</span></footer>
      </main>
    </div>
  );
}
