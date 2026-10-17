import type { Assessment, DiagnosticProviderStatus, DiagnosticResult, PumpApi, Scenario } from './api';
import { mapAnomalyComponents, type AlertEvent } from './alerts';
import type { Telemetry } from './engineering';
import { anomalyForMetric, calculateMetricTrend, MEASUREMENTS, possibleContributors, relatedAnomalies, SCENARIO_BEHAVIOR, type MetricKey } from './diagnostics';
import { DiagnosticChat } from './DiagnosticChat';

interface Props {
  assessment: Assessment | null;
  telemetry: Telemetry | null;
  readings: Telemetry[];
  scenario: Scenario | null;
  freshness: string;
  selectedMetric: string | null;
  selectedAlert: AlertEvent | null;
  onSelectMetric: (metric: string) => void;
  diagnosis: DiagnosticResult | null;
  diagnosisLoading: boolean;
  diagnosisError: string | null;
  providerStatus: DiagnosticProviderStatus | null;
  diagnosticAvailable: boolean;
  onRequestDiagnosis: () => void;
  api: PumpApi;
  pumpId: string | null;
  clientSessionId?: string;
}

const METRIC_KEYS = Object.keys(MEASUREMENTS) as MetricKey[];
const pretty = (text: string) => text.replaceAll('_', ' ');
const value = (number: number | undefined) => typeof number === 'number' && Number.isFinite(number) ? number.toFixed(1) : '—';
const time = (timestamp?: string) => timestamp && Number.isFinite(Date.parse(timestamp)) ? new Date(timestamp).toLocaleString() : '—';

export function DiagnosticExplorer({ assessment, telemetry, readings, scenario, freshness, selectedMetric, selectedAlert, onSelectMetric,
  diagnosis, diagnosisLoading, diagnosisError, providerStatus, diagnosticAvailable, onRequestDiagnosis,
  api, pumpId, clientSessionId }: Props) {
  const primaryMetric = selectedAlert?.metric ?? selectedMetric ?? assessment?.anomalies[0]?.metric ?? null;
  const evidenceWindow = [...readings].sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp)).slice(-12);
  const primary = primaryMetric ? MEASUREMENTS[primaryMetric as MetricKey] : null;
  const currentAnomaly = primaryMetric ? anomalyForMetric(assessment, primaryMetric) : undefined;
  const historicalMatch = selectedAlert?.metric === primaryMetric ? selectedAlert : null;
  const related = relatedAnomalies(assessment, primaryMetric);
  const contributors = possibleContributors(assessment);
  const trend = primaryMetric && primaryMetric in MEASUREMENTS ? calculateMetricTrend(evidenceWindow, primaryMetric as MetricKey) : null;
  const suspectedRegions = currentAnomaly && assessment ? mapAnomalyComponents(currentAnomaly, assessment.detected_faults) : [];

  return <div className="diagnostic-explorer" aria-live="polite">
    <span className="panel-kicker">EVIDENCE &amp; FAULT RELATIONSHIPS</span>
    <section className="explorer-block ai-diagnosis" aria-label="AI diagnostic explanation">
      <h4>Diagnostic explanation <small>AI-generated demo text; not a confirmed diagnosis</small></h4>
      <button type="button" className="diagnosis-request-button" onClick={onRequestDiagnosis} disabled={!assessment || !diagnosticAvailable || diagnosisLoading || Boolean(providerStatus && providerStatus.provider !== 'mock' && !providerStatus.configured)}>
        {diagnosisLoading ? 'Preparing diagnostic…' : diagnosisError ? 'Retry diagnostic request' : diagnosis ? 'Refresh diagnostic explanation' : 'Request diagnostic explanation'}
      </button>
      {diagnosisError && <p className="diagnosis-error" role="alert">{diagnosisError}</p>}
      {diagnosis && <div className="diagnosis-result" aria-label="Diagnostic result">
        <span className="diagnosis-source">{diagnosis.provider === 'amd' && !diagnosis.is_mock ? 'AI-GENERATED DEMO EXPLANATION · AMD' : diagnosis.is_mock ? 'TEST MOCK · NOT AN AMD MODEL' : 'PROVIDER UNAVAILABLE'} · {diagnosis.latency_ms.toFixed(0)} ms · backend evidence snapshot {time(diagnosis.assessment_timestamp)}{diagnosis.cached ? ' · cached offline result' : ''}</span>
        {diagnosis.ml_prediction && <p><b>ML scenario classifier:</b> {diagnosis.ml_prediction.label} · uncalibrated score {diagnosis.ml_prediction.score.toFixed(2)} · {diagnosis.ml_prediction.compute_provider} / {diagnosis.ml_prediction.device} · {diagnosis.ml_prediction.model_version}. This is not a fault probability or degradation forecast.</p>}
        <p>{diagnosis.summary}</p>
        <p><b>Priority: {diagnosis.priority}</b> · {diagnosis.priority_rationale}</p>
        <h5>Ranked hypotheses</h5>
        {diagnosis.hypotheses.length ? diagnosis.hypotheses.map((hypothesis) => <article className="diagnosis-hypothesis" key={`${hypothesis.rank}-${hypothesis.cause}`}>
          <b>{hypothesis.rank}. {hypothesis.cause}</b><span>Uncertainty: {hypothesis.uncertainty} — not a calibrated probability.</span>
          <ul>{hypothesis.evidence.map((item, index) => { const unit = item.source === 'telemetry' ? MEASUREMENTS[item.field as MetricKey]?.unit : ''; return <li key={`${item.source}-${item.field}-${index}`}>{item.source} · {item.field.replaceAll('_', ' ')}{item.metric ? ` (${item.metric.replaceAll('_', ' ')})` : ''}{item.reading_index !== undefined && item.reading_index !== null ? ` · sample ${item.reading_index + 1}` : ''}: {String(item.value)}{unit ? ` ${unit}` : ''}</li>; })}</ul>
          {hypothesis.missing_evidence.length > 0 && <small>Missing: {hypothesis.missing_evidence.join('; ')}</small>}
        </article>) : <p>No ranked cause is supported by this result.</p>}
        {diagnosis.missing_evidence.length > 0 && <p><b>Evidence gaps:</b> {diagnosis.missing_evidence.join('; ')}</p>}
        <h5>Human inspection steps</h5><ul>{diagnosis.inspection_steps.map((step, index) => <li key={index}>{step}</li>)}</ul>
        <small>Human review required. This explanation cannot alter measured telemetry, detector outputs, alarms, or equipment controls.</small>
      </div>}
      <DiagnosticChat api={api} pumpId={pumpId} clientSessionId={clientSessionId} contextAvailable={Boolean(telemetry && assessment)} />
    </section>
    {primary ? <>
      <h3 className="explorer-title">{primary.label}{currentAnomaly && <span className={`severity-pill ${currentAnomaly.severity}`}>{currentAnomaly.severity}</span>}{historicalMatch && <span className={`state-pill ${historicalMatch.state}`}>{historicalMatch.state}</span>}</h3>
      <p className="diagnostic-state">{freshness === 'Unavailable' || freshness === 'Stale' ? 'Last received assessment; current telemetry is unavailable or stale.' : currentAnomaly ? 'Observed condition from the latest backend assessment.' : 'No active finding for this measurement in the latest assessment.'} Component localization is a suspected region, separate from sensor location.</p>

      <section className="explorer-block">
        <h4>Measurement evidence</h4>
        <dl className="evidence-grid">
          <dt>Latest value</dt><dd>{telemetry ? `${value(telemetry[primaryMetric as MetricKey])} ${primary.unit}` : 'Unavailable'}</dd>
          <dt>Sensor location</dt><dd>{primary.location}</dd>
          <dt>Assessment status</dt><dd>{freshness === 'Unavailable' || freshness === 'Stale' ? `${freshness}; last retained assessment is not current` : currentAnomaly ? currentAnomaly.severity : primary.thresholded ? 'No active threshold finding' : 'No configured rule threshold'}</dd>
          {(currentAnomaly || historicalMatch) && <><dt>Expected range</dt><dd>{currentAnomaly?.expected_range ?? historicalMatch?.expected_range}{!currentAnomaly && historicalMatch && ' (recorded with alert)'}</dd></>}
          {currentAnomaly?.explanation && <><dt>Rule evidence</dt><dd>{currentAnomaly.explanation}</dd></>}
          {historicalMatch && <><dt>Alert observed</dt><dd>{value(historicalMatch.observed_value)} ({historicalMatch.expected_range}) at {time(historicalMatch.timestamp)}</dd><dt>First assessment reported</dt><dd>{time(historicalMatch.first_seen_at)} (recorded by this UI; not physical onset)</dd></>}
          <dt>Sample time</dt><dd>{time(telemetry?.timestamp)} · {freshness}</dd>
          <dt>Suspected region</dt><dd>{historicalMatch?.components.join(', ') ?? (suspectedRegions.length ? suspectedRegions.join(', ') : 'No component localized')}</dd>
        </dl>
        {historicalMatch?.state === 'active' && <small className="ack-note">Use the episode control in Alert Controls to acknowledge and silence this alarm.</small>}
        {historicalMatch?.state === 'acknowledged' && <p className="ack-note">ACKNOWLEDGED — FAULT ACTIVE. The alarm is silenced for this episode; the assessment still reports the condition. Acknowledgement does not indicate repair.</p>}
        {historicalMatch?.state === 'resolved' && <p className="ack-note">FAULT CLEARED — the backend assessment no longer reports this condition.</p>}
      </section>

      <section className="explorer-block">
        <h4>Observed conditions <small>backend threshold findings</small></h4>
        {assessment?.anomalies.length ? <div className="observed-condition-list">{assessment.anomalies.map((anomaly) => <button type="button" aria-label={`Inspect ${MEASUREMENTS[anomaly.metric as MetricKey]?.label ?? pretty(anomaly.metric)} finding`} key={`${anomaly.metric}-${anomaly.severity}`} className={`observed-condition ${anomaly.metric === primaryMetric ? 'selected' : ''}`} onClick={() => onSelectMetric(anomaly.metric)}><span className={`finding-indicator ${anomaly.severity}`} /><span><b>{MEASUREMENTS[anomaly.metric as MetricKey]?.label ?? pretty(anomaly.metric)}</b><small>{value(anomaly.observed_value)} · {anomaly.expected_range}</small></span><span className={`severity-pill ${anomaly.severity}`}>{anomaly.severity}</span></button>)}</div> : <p className="explorer-empty">{assessment ? 'No configured threshold findings in the latest assessment.' : 'No assessment available.'}</p>}
      </section>

      <section className="explorer-block">
        <h4>Related symptoms <small>co-occurrence only</small></h4>
        {related.length ? <ul className="relationship-list">{related.map((anomaly) => <li key={anomaly.metric}><b>{pretty(anomaly.metric)} · {value(anomaly.observed_value)} {MEASUREMENTS[anomaly.metric as MetricKey]?.unit ?? ''}</b><span>{anomaly.expected_range} · {anomaly.severity}</span><small>Present in the same backend assessment; this does not establish a causal relationship.</small><button type="button" onClick={() => onSelectMetric(anomaly.metric)}>Inspect measurement and suspected region</button></li>)}</ul> : <p className="explorer-empty">No other configured threshold findings are present in the latest assessment.</p>}
      </section>

      <section className="explorer-block">
        <h4>Progression in the latest diagnostic window</h4>
        {trend ? <p className="trend-summary">{primary.label}: <b>{value(trend.initialValue)} → {value(trend.latestValue)} {primary.unit}</b>, {trend.direction} by {value(Math.abs(trend.delta))} {primary.unit} across {trend.elapsedSeconds.toFixed(0)} s ({trend.samples} recorded samples). {time(trend.startTimestamp)} to {time(trend.endTimestamp)}.</p> : <p className="explorer-empty">No valid samples are available for this measurement.</p>}
        <details className="trend-details"><summary>Other measured changes in this window</summary><div className="trend-table">{METRIC_KEYS.map((metric) => {
          const item = calculateMetricTrend(evidenceWindow, metric);
          return <div key={metric}><span>{MEASUREMENTS[metric].label}</span>{item ? <b>{item.direction} {item.delta > 0 ? '+' : ''}{value(item.delta)} {MEASUREMENTS[metric].unit}</b> : <b>Insufficient history</b>}</div>;
        })}</div><small>These are differences between recorded samples, not inferred causes. No measurement is synthesized to fill gaps.</small></details>
      </section>

      <section className="explorer-block">
        <h4>Possible contributors <small>unconfirmed hypotheses</small></h4>
        {contributors.length ? <ul className="hypothesis-list">{contributors.map((item) => <li key={item.title}><b>{item.title}</b><span>{item.rationale}</span><em>UNCONFIRMED · INVESTIGATE</em></li>)}</ul> : <p className="explorer-empty">No specific contributing hypothesis is supported by the current rule indicators.</p>}
      </section>

      <section className="explorer-block">
        <h4>Next checks <small>backend recommendations</small></h4>
        {assessment?.recommendations.length ? <ul className="recommendation-list">{assessment.recommendations.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <p className="explorer-empty">No backend recommendations available.</p>}
      </section>
      {scenario && <p className="scenario-evidence"><b>Modeled scenario · {scenario.replaceAll('_', ' ')}</b><span>{SCENARIO_BEHAVIOR[scenario]} Scenario selection describes simulator configuration; measurements above show observed output.</span></p>}
    </> : <p className="explorer-empty">Generate a simulation to inspect backend readings, assessment evidence, and recorded progression.</p>}
  </div>;
}
