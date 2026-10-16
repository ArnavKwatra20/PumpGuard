import { useEffect, useRef, useState } from 'react';
import type { AiFeatureKind, AiFeatureResponse, PumpApi } from './api';
import { renderAssistantContent } from './DiagnosticChat';

interface Props {
  api: PumpApi;
  pumpId: string | null;
  clientSessionId: string | null;
  contextAvailable: boolean;
  contextKey: string;
}

const FEATURES: { kind: AiFeatureKind; label: string; description: string }[] = [
  { kind: 'maintenance_planner', label: 'Draft maintenance plan', description: 'Evidence-bounded inspection draft' },
  { kind: 'telemetry_explanation', label: 'Explain telemetry trends', description: 'Interpret computed signal changes' },
  { kind: 'scenario_analyst', label: 'Analyze active scenario', description: 'Explain recorded simulator events' },
];

export function AiFeaturePanel({ api, pumpId, clientSessionId, contextAvailable, contextKey }: Props) {
  const [selected, setSelected] = useState<AiFeatureKind>('maintenance_planner');
  const [result, setResult] = useState<AiFeatureResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestVersionRef = useRef(0);

  useEffect(() => {
    requestVersionRef.current += 1;
    setResult(null);
    setError(null);
  }, [contextKey]);

  const requestFeature = async (feature: AiFeatureKind = selected) => {
    if (!api.aiFeature || !pumpId || !contextAvailable || loading) return;
    setSelected(feature);
    setLoading(true);
    setError(null);
    const requestVersion = ++requestVersionRef.current;
    try {
      const nextResult = await api.aiFeature({ pump_id: pumpId, feature, client_session_id: clientSessionId });
      if (requestVersion === requestVersionRef.current) setResult(nextResult);
    } catch (reason) {
      if (requestVersion === requestVersionRef.current) {
        setResult(null);
        setError(reason instanceof Error ? reason.message : 'AI feature request failed.');
      }
    } finally {
      if (requestVersion === requestVersionRef.current) setLoading(false);
    }
  };

  return <section className="ai-feature-panel" aria-label="AI engineering tools">
    <div className="ai-feature-heading">
      <div><span className="panel-kicker">OPTIONAL AI INTERPRETATION</span><h3>Engineering tools</h3></div>
      <small>Rule engine remains authoritative</small>
    </div>
    <p className="ai-feature-note">AMD or the configured offline provider receives only server-owned synthetic telemetry, deterministic analysis, and simulator context. Output is a draft, not a confirmed diagnosis.</p>
    <div className="ai-feature-actions">
      {FEATURES.map((feature) => <button type="button" key={feature.kind} onClick={() => void requestFeature(feature.kind)} disabled={!api.aiFeature || !pumpId || !contextAvailable || loading} aria-label={feature.label}>
        <b>{feature.label}</b><small>{feature.description}</small>
      </button>)}
    </div>
    {loading && <p className="ai-feature-status" role="status">Generating a bounded, evidence-grounded draft…</p>}
    {error && <div className="ai-feature-error" role="alert"><span>{error}</span><button type="button" onClick={() => void requestFeature()} disabled={loading}>Retry</button></div>}
    {result && <article className="ai-feature-result">
      <div className="ai-feature-result-meta"><b>{FEATURES.find((feature) => feature.kind === result.feature)?.label}</b><span>{result.provider === 'amd' && !result.is_mock ? 'AMD-generated response' : result.is_mock ? 'TEST MOCK — not AMD-generated' : 'Provider unavailable — not an AMD diagnosis'} · {Math.round(result.latency_ms)} ms · evidence {new Date(result.evidence_timestamp).toLocaleTimeString()}</span></div>
      <div className="chat-message-content">{renderAssistantContent(result.assistant_message)}</div>
    </article>}
  </section>;
}
