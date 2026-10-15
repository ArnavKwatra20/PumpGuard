import { useState } from 'react';
import type { MetricTrend, TelemetryAnalysis, TrendDirection } from './api';

const METRIC_LABELS: Record<string, string> = {
  temperature_c: 'Temperature',
  vibration_mm_s: 'Vibration',
  sound_db: 'Sound',
  rpm: 'Motor speed',
};

const directionLabel = (direction: TrendDirection) => direction.replaceAll('_', ' ');
const signed = (value: number | null, digits = 3) => (value === null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(digits)}`);

function TrendRow({ metric }: { metric: MetricTrend }) {
  const label = METRIC_LABELS[metric.metric] ?? metric.metric;
  const excursions = metric.excursions_high + metric.excursions_low;
  return (
    <div className={`analysis-row ${metric.critical_breaches ? 'is-critical' : excursions ? 'is-warning' : ''}`}>
      <div className="analysis-row-head">
        <b>{label}</b>
        <span className="analysis-direction">{directionLabel(metric.direction)}</span>
      </div>
      <div className="analysis-row-values">
        <span>latest <b>{metric.latest_value === null ? '—' : metric.latest_value.toFixed(1)} {metric.unit}</b></span>
        <span>mean <b>{metric.mean === null ? '—' : metric.mean.toFixed(1)}</b></span>
        <span>rate <b>{signed(metric.rate_per_second)} {metric.unit}/s</b></span>
      </div>
      <div className="analysis-row-excursions">
        {metric.threshold
          ? <small>Expected {metric.threshold.low}–{metric.threshold.high} {metric.threshold.unit} · excursions {excursions} · critical {metric.critical_breaches}</small>
          : <small>No authoritative threshold configured for this metric.</small>}
        {metric.insufficient_samples && <small>Insufficient samples for a trend.</small>}
      </div>
    </div>
  );
}

export function TelemetryAnalysisPanel({ analysis, loading, error, onAnalyze, available }: {
  analysis: TelemetryAnalysis | null;
  loading: boolean;
  error: string | null;
  onAnalyze: () => void;
  available: boolean;
}) {
  const [closed, setClosed] = useState(false);

  if (closed) {
    return (
      <section className="analysis-panel analysis-panel-closed panel" aria-label="Telemetry intelligence">
        <button type="button" className="analysis-reopen-button" onClick={() => setClosed(false)}>
          Show trend &amp; excursion analysis
        </button>
      </section>
    );
  }

  return (
    <section className="analysis-panel panel" aria-label="Telemetry intelligence">
      <div className="section-title">
        <div><span className="panel-kicker">DETERMINISTIC TELEMETRY INTELLIGENCE</span><h3>Trend &amp; excursion analysis</h3></div>
        <button type="button" className="analysis-close-button" aria-label="Close trend and excursion analysis" onClick={() => setClosed(true)}>×</button>
      </div>
      <p className="analysis-intro">Locally computed rate-of-change, rolling statistics, and threshold excursions. Deterministic; no hosted model is contacted.</p>
      <button type="button" className="diagnosis-request-button" onClick={onAnalyze} disabled={!available || loading}>
        {loading ? 'Analyzing telemetry…' : analysis ? 'Refresh analysis' : 'Analyze telemetry window'}
      </button>
      {!available && <p className="diagnosis-error" role="status">Analysis unavailable until a simulation has generated telemetry.</p>}
      {error && <p className="diagnosis-error" role="alert">{error}</p>}
      {analysis && !error && (
        <div className="analysis-result" aria-live="polite">
          <div className="analysis-meta">
            <span className="diagnosis-source">DETERMINISTIC ANALYSIS · {analysis.sample_count} samples · {analysis.sampling_regular ? 'regular' : 'irregular'} sampling{analysis.median_interval_seconds !== null ? ` · median ${analysis.median_interval_seconds.toFixed(1)}s` : ''}</span>
            {analysis.synthetic && <span className="analysis-synthetic-tag">SYNTHETIC TELEMETRY</span>}
          </div>
          {analysis.metrics.map((metric) => <TrendRow key={metric.metric} metric={metric} />)}
          <ul className="analysis-limitations">
            {analysis.limitations.map((item, index) => <li key={index}>{item}</li>)}
          </ul>
        </div>
      )}
    </section>
  );
}
