import type { Telemetry } from './engineering';

export type Scenario = 'normal' | 'overheating' | 'bearing_wear' | 'cavitation' | 'imbalance';
export const SCENARIOS: Scenario[] = ['normal', 'overheating', 'bearing_wear', 'cavitation', 'imbalance'];

export interface Anomaly {
  metric: string;
  observed_value: number;
  expected_range: string;
  severity: 'normal' | 'warning' | 'critical';
  explanation: string;
}

export interface Assessment {
  pump_id: string;
  timestamp: string;
  health_score: number;
  status: 'normal' | 'warning' | 'critical';
  anomalies: Anomaly[];
  detected_faults: string[];
  recommendations: string[];
}

export interface SimulationResponse {
  scenario_label: Scenario;
  readings: Telemetry[];
  assessment: Assessment;
  simulation?: SimulationSnapshot;
}

export interface SimulationSnapshot {
  time_seconds: number;
  step: number;
  fault_level: number;
  fault_enabled: boolean;
  scenario: Scenario;
  config: { speed: number; rpm_setpoint?: number; load_percent: number; cooling_effectiveness: number; inlet_restriction_percent: number; fault_severity: number };
  events: { time_seconds: number; kind: string; scenario: Scenario }[];
}

export interface DiagnosticRequest {
  pump_id: string;
  client_session_id?: string;
  simulation_id?: string;
  alert_episode_id?: string;
  assessment_timestamp: string;
  telemetry: { timestamp: string; temperature_c: number; vibration_mm_s: number; sound_db: number; rpm: number; pressure_kpa?: number | null; load_percent?: number | null }[];
  trends: { metric: 'temperature_c' | 'vibration_mm_s' | 'sound_db' | 'rpm' | 'pressure_kpa'; initial_value: number; latest_value: number; delta: number; elapsed_seconds: number; samples: number }[];
  detector: { status: Assessment['status']; score: number; predicted_faults: string[]; confidence: number | null };
  assessment?: { status: Assessment['status']; health_score: number; anomalies: { metric: string; observed_value: number; expected_range: string; severity: 'normal' | 'warning' | 'critical'; explanation: string }[]; recommendations: string[] };
  is_synthetic: boolean;
  selected_scenario?: Scenario | null;
  injected_scenario?: Scenario | null;
  alert?: { episode_id: string; metric: string; severity: 'warning' | 'critical'; observed_value: number; expected_range: string; explanation: string } | null;
  events: { time_seconds: number; kind: string; scenario: Scenario }[];
  ml_prediction?: { label: Scenario; score: number; model_version: string; compute_provider: 'cpu' | 'amd_rocm' | 'cuda'; device: string; execution_path: string } | null;
}

export interface DiagnosticResult {
  summary: string;
  hypotheses: { cause: string; rank: number; uncertainty: 'low' | 'moderate' | 'high'; evidence: { source: 'telemetry' | 'trend' | 'detector' | 'alert' | 'event' | 'ml_prediction' | 'assessment'; field: string; metric?: string | null; reading_index?: number | null; event_index?: number | null; value: number | string }[]; missing_evidence: string[] }[];
  missing_evidence: string[];
  inspection_steps: string[];
  priority: 'routine' | 'soon' | 'urgent';
  priority_rationale: string;
  limitations: string[];
  human_review_required: true;
  provider: 'mock' | 'amd' | 'amd_unavailable';
  is_mock: boolean;
  latency_ms: number;
  correlation_id: string;
  cached: boolean;
  assessment_timestamp: string;
  ml_prediction?: { label: Scenario; score: number; model_version: string; compute_provider: 'cpu' | 'amd_rocm' | 'cuda'; device: string; execution_path: string } | null;
}

export interface DiagnosticProviderStatus { provider: 'mock' | 'amd' | 'amd_unavailable'; state?: 'mock_test_mode' | 'amd_configured' | 'amd_unconfigured'; available: boolean; is_mock: boolean; configured?: boolean; model?: string | null }
export interface DiagnosticChatMessage { role: 'user' | 'assistant'; content: string; timestamp?: string }
export interface DiagnosticChatRequest { pump_id: string; client_session_id?: string; question: string; history: Pick<DiagnosticChatMessage, 'role' | 'content'>[] }
export interface DiagnosticChatResponse { assistant_message: string; provider: 'mock' | 'amd' | 'amd_unavailable'; is_mock: boolean; latency_ms: number }
export type AiFeatureKind = 'maintenance_planner' | 'telemetry_explanation' | 'scenario_analyst';
export interface AiFeatureRequest { pump_id: string; feature: AiFeatureKind; client_session_id?: string | null }
export interface AiFeatureResponse { feature: AiFeatureKind; assistant_message: string; provider: 'mock' | 'amd' | 'amd_unavailable'; is_mock: boolean; latency_ms: number; evidence_timestamp: string }
export interface DiagnosticModelCatalog { configured: boolean; models: { id: string; capabilities: Record<string, unknown>; capabilities_verified: boolean }[]; capabilities_verified: boolean }
export interface MLComputeStatus { enabled: boolean; artifact_available: boolean; provider_available: boolean; model_version: string | null; requested_compute_provider: string; compute_provider: 'cpu' | 'amd_rocm' | 'cuda' | 'unavailable'; device: string; execution_path: string; classifier_loaded: boolean; pytorch_version: string | null; hip_version: string | null; devices: { index: number; name: string }[]; inference_error: string | null; interpretation: string }

export type TrendDirection = 'increasing' | 'decreasing' | 'stable' | 'insufficient_data';
export type Provenance = 'measured' | 'derived' | 'synthetic';

export interface ThresholdBand { low: number; high: number; critical_low: number; critical_high: number; unit: string }

export interface MetricTrend {
  metric: string; unit: string; provenance: Provenance;
  sample_count: number; valid_count: number; missing_count: number;
  first_timestamp: string | null; last_timestamp: string | null; elapsed_seconds: number | null;
  first_value: number | null; latest_value: number | null; minimum: number | null; maximum: number | null; mean: number | null;
  delta: number | null; rate_per_second: number | null; rate_unit: string; direction: TrendDirection;
  median_interval_seconds: number | null; sampling_regular: boolean; rolling_mean: number | null; rolling_std: number | null;
  threshold: ThresholdBand | null; excursions_high: number; excursions_low: number; critical_breaches: number; insufficient_samples: boolean;
}

export interface MetricAISummary { metric: string; unit: string; latest_value: number | null; mean: number | null; rate_per_second: number | null; direction: TrendDirection; excursions_high: number; excursions_low: number; critical_breaches: number }

export interface TelemetryAnalysis {
  asset_id: string; generator: 'deterministic_analysis'; provenance: Provenance; synthetic: boolean;
  window_start: string | null; window_end: string | null;
  sample_count: number; valid_sample_count: number; missing_sample_count: number;
  sampling_regular: boolean; median_interval_seconds: number | null;
  metrics: MetricTrend[]; limitations: string[]; ai_summary: MetricAISummary[];
}

export interface WindowComparison { metric: string; unit: string; comparable: boolean; reason: string | null; baseline_mean: number | null; current_mean: number | null; mean_delta: number | null; baseline_rate_per_second: number | null; current_rate_per_second: number | null; rate_delta_per_second: number | null; baseline_direction: TrendDirection | null; current_direction: TrendDirection | null }

export interface ComparisonResult { asset_id: string; generator: 'deterministic_analysis'; provenance: Provenance; synthetic: boolean; baseline_sample_count: number; current_sample_count: number; metrics: WindowComparison[]; limitations: string[] }

export interface SimulationRequest {
  pump_id: string;
  client_session_id?: string;
  scenario: Scenario;
  sample_count: number;
  sampling_interval_seconds: number;
  random_seed?: number;
  start_time?: string;
}

export interface LiveSampleRequest extends Pick<SimulationRequest, 'pump_id' | 'scenario' | 'random_seed'> {
  /** Isolates process-local live state when multiple dashboards monitor one pump. */
  client_session_id?: string;
  reset_session?: boolean;
  speed?: number;
  rpm_setpoint?: number;
  load_percent?: number;
  cooling_effectiveness?: number;
  inlet_restriction_percent?: number;
  fault_severity?: number;
  fault_enabled?: boolean;
}

export interface PumpApi {
  generate(request: SimulationRequest): Promise<SimulationResponse>;
  history(pumpId: string, limit?: number): Promise<Telemetry[]>;
  liveSample?(request: LiveSampleRequest): Promise<SimulationResponse>;
  diagnose?(request: DiagnosticRequest): Promise<DiagnosticResult>;
  diagnosticChat?(request: DiagnosticChatRequest): Promise<DiagnosticChatResponse>;
  aiFeature?(request: AiFeatureRequest): Promise<AiFeatureResponse>;
  diagnosticStatus?(): Promise<DiagnosticProviderStatus>;
  diagnosticModels?(): Promise<DiagnosticModelCatalog>;
  mlStatus?(): Promise<MLComputeStatus>;
  telemetryAnalysis?(pumpId: string, limit?: number, clientSessionId?: string): Promise<TelemetryAnalysis>;
  telemetryCompare?(pumpId: string, current?: number, baseline?: number, clientSessionId?: string): Promise<ComparisonResult>;
}

const apiBase = import.meta.env.VITE_API_BASE_URL ?? '';
const REQUEST_TIMEOUT_MS = 8_000;
// Diagnostic explanations call the AMD Token Factory and can legitimately take tens of seconds
// (the backend budget is PUMPGUARD_DIAGNOSTIC_TIMEOUT_SECONDS, default 50s). This deadline must stay
// above that backend budget so the UI surfaces the backend's authoritative, categorized result
// (success / 502 invalid response / 504 timeout / 429 rate limit) instead of aborting early and
// misreporting a generic client timeout while the backend is still working.
const DIAGNOSTIC_TIMEOUT_MS = Number(import.meta.env.VITE_DIAGNOSTIC_TIMEOUT_MS ?? 60_000);

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit = {}, timeoutMs: number = REQUEST_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) throw new Error(`API request timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json() as { detail?: string | { msg?: string }[] };
      if (typeof body.detail === 'string') detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((item) => item.msg ?? 'Invalid input').join('; ');
    } catch {
      // Keep the useful status message when the server did not return JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const pumpApi: PumpApi = {
  async generate(request) {
    const response = await fetchWithTimeout(`${apiBase}/api/v1/simulation/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    return readJson<SimulationResponse>(response);
  },
  async liveSample(request) {
    const response = await fetchWithTimeout(`${apiBase}/api/v1/simulation/live-sample`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    return readJson<SimulationResponse>(response);
  },
  async diagnose(request) {
    const response = await fetchWithTimeout(`${apiBase}/api/v1/diagnostics`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
    }, DIAGNOSTIC_TIMEOUT_MS);
    return readJson<DiagnosticResult>(response);
  },
  async diagnosticChat(request) {
    const response = await fetchWithTimeout(`${apiBase}/api/v1/diagnostics/chat`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
    }, DIAGNOSTIC_TIMEOUT_MS);
    return readJson<DiagnosticChatResponse>(response);
  },
  async aiFeature(request) {
    const response = await fetchWithTimeout(`${apiBase}/api/v1/diagnostics/ai-feature`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
    }, DIAGNOSTIC_TIMEOUT_MS);
    return readJson<AiFeatureResponse>(response);
  },
  async diagnosticStatus() {
    const response = await fetchWithTimeout(`${apiBase}/api/v1/diagnostics/status`);
    return readJson<DiagnosticProviderStatus>(response);
  },
  async diagnosticModels() {
    const response = await fetchWithTimeout(`${apiBase}/api/v1/diagnostics/models`);
    return readJson<DiagnosticModelCatalog>(response);
  },
  async mlStatus() {
    const response = await fetchWithTimeout(`${apiBase}/api/v1/ml/status`);
    return readJson<MLComputeStatus>(response);
  },
  async history(pumpId, limit = 120) {
    const response = await fetchWithTimeout(
      `${apiBase}/api/v1/pumps/${encodeURIComponent(pumpId)}/telemetry/history?limit=${limit}`,
    );
    return readJson<Telemetry[]>(response);
  },
  async telemetryAnalysis(pumpId, limit = 120, clientSessionId) {
    const session = clientSessionId ? `&client_session_id=${encodeURIComponent(clientSessionId)}` : '';
    const response = await fetchWithTimeout(
      `${apiBase}/api/v1/pumps/${encodeURIComponent(pumpId)}/telemetry/analysis?limit=${limit}${session}`,
    );
    return readJson<TelemetryAnalysis>(response);
  },
  async telemetryCompare(pumpId, current = 30, baseline = 30, clientSessionId) {
    const session = clientSessionId ? `&client_session_id=${encodeURIComponent(clientSessionId)}` : '';
    const response = await fetchWithTimeout(
      `${apiBase}/api/v1/pumps/${encodeURIComponent(pumpId)}/telemetry/analysis/compare?current=${current}&baseline=${baseline}${session}`,
    );
    return readJson<ComparisonResult>(response);
  },
};
