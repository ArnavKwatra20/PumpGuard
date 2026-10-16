import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PumpTwinApp } from './App';
import type { DiagnosticRequest, DiagnosticResult, PumpApi, SimulationResponse } from './api';

const audioMock = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), setErrorHandler: vi.fn(), activate: vi.fn(), close: vi.fn() }));
vi.mock('./alarm-audio', () => ({ createAlarmAudio: () => audioMock }));

vi.mock('./PumpScene', () => ({
  PumpScene: ({ scenario, componentHighlights, onComponentClick }: { scenario: string; componentHighlights?: { componentId: string; severity: string }[]; onComponentClick?: (componentId: string) => void }) => <div data-testid="pump-scene" data-scenario={scenario} data-highlights={componentHighlights?.map((item) => `${item.componentId}:${item.severity}`).join(',')}><button onClick={() => onComponentClick?.('bearing')}>Mock bearing component</button></div>,
}));

function createFixture(): SimulationResponse {
  const timestamp = new Date().toISOString();
  return {
    scenario_label: 'bearing_wear',
    readings: [{ timestamp, pump_id: 'pump-01', temperature_c: 69.5, vibration_mm_s: 7.1, sound_db: 79, rpm: 1762, operating_mode: 'steady' }],
    assessment: { pump_id: 'pump-01', timestamp, health_score: 65, status: 'warning', anomalies: [{ metric: 'vibration_mm_s', observed_value: 7.1, expected_range: '0–4.5 mm/s', severity: 'warning', explanation: 'High vibration' }], detected_faults: ['bearing_wear'], recommendations: ['Inspect bearing assembly'] },
  };
}

let fixture = createFixture();
const fixtureTimestamp = fixture.readings[0].timestamp;

function atOffset(offsetMs: number, scenario: SimulationResponse['scenario_label'] = fixture.scenario_label): SimulationResponse {
  const timestamp = new Date(Date.now() + offsetMs).toISOString();
  return { ...fixture, scenario_label: scenario, readings: [{ ...fixture.readings[0], timestamp }], assessment: { ...fixture.assessment, timestamp } };
}

function normalAtOffset(offsetMs: number, scenario: SimulationResponse['scenario_label'] = 'bearing_wear'): SimulationResponse {
  const timestamp = new Date(Date.now() + offsetMs).toISOString();
  return { ...fixture, scenario_label: scenario, readings: [{ ...fixture.readings[0], timestamp, temperature_c: 68, vibration_mm_s: 2, sound_db: 68, rpm: 1780 }],
    assessment: { ...fixture.assessment, timestamp, health_score: 100, status: 'normal', anomalies: [], detected_faults: [] } };
}

function setup(api: PumpApi = { generate: vi.fn().mockResolvedValue(fixture), history: vi.fn().mockResolvedValue(fixture.readings) }) {
  render(<PumpTwinApp api={api} />);
  return api;
}

beforeEach(() => {
  fixture = createFixture();
  vi.clearAllMocks();
  audioMock.start.mockResolvedValue(undefined);
  audioMock.activate.mockResolvedValue(undefined);
});

function selectScenario(scenario: SimulationResponse['scenario_label'] = 'bearing_wear') {
  fireEvent.change(screen.getByLabelText('Scenario'), { target: { value: scenario } });
}

describe('digital twin dashboard', () => {
  it('renders the monitoring overview with accessible in-page navigation and no invented live readings', () => {
    setup();
    expect(screen.getByRole('heading', { name: 'Pump monitoring' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('button', { name: 'Sensor trends' })).toHaveAttribute('title', 'Sensor trends');
    expect(screen.getByRole('button', { name: 'Diagnostics and alerts' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Operating parameters' })).toBeInTheDocument();
    expect(document.getElementById('sensor-panel')).toHaveAttribute('data-layout-slot', 'diagnostic');
    expect(document.getElementById('alert-history')).not.toBeNull();
    expect(document.getElementById('diagnostic-inspector')).toHaveAttribute('data-layout-slot', 'inspector');
    expect(screen.getByText(/READY · generate a simulation to start live telemetry/)).toBeInTheDocument();
    expect(screen.getAllByText('Waiting for telemetry')).toHaveLength(5);
    expect(screen.getByLabelText('Inject selected fault')).toBeDisabled();
    expect(screen.getByRole('navigation', { name: 'Dashboard sections' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Fleet View' })).toBeDisabled();
    expect(screen.getByRole('heading', { name: 'Event timeline' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'System status and operating measurements' })).toBeInTheDocument();
    expect(screen.getByText(/Frequency-domain data is not supplied/)).toBeInTheDocument();
    expect(screen.getByLabelText('Motor speed')).toBeInTheDocument();
    expect(screen.getByLabelText('Pump identity')).toHaveAttribute('pattern', '[A-Za-z0-9][A-Za-z0-9_.\\-]*');
  });

  it('displays actual returned sensor values and assessment separately from the model label', async () => {
    const api = setup();
    fireEvent.change(screen.getByLabelText('Scenario'), { target: { value: 'bearing_wear' } });
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    expect(await screen.findAllByText('69.5')).toHaveLength(2);
    expect(screen.getAllByText('7.1').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('65')).toHaveLength(3); // Status chip, alarm strip and detailed rule assessment.
    expect(screen.getAllByText('Inspect bearing assembly')).toHaveLength(2);
    expect(screen.getByTestId('pump-scene')).toHaveAttribute('data-scenario', 'bearing_wear');
    expect(api.generate).toHaveBeenCalledWith(expect.objectContaining({ scenario: 'bearing_wear', pump_id: 'pump-01' }));
  });

  it('sends the selected motor RPM setpoint through the live simulator contract', async () => {
    const liveSample = vi.fn().mockRejectedValue(new Error('poll stopped for test'));
    const api = setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn(), liveSample });
    fireEvent.change(screen.getByLabelText('Motor speed'), { target: { value: '2050' } });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    await waitFor(() => expect(liveSample).toHaveBeenCalledWith(expect.objectContaining({ rpm_setpoint: 2050, scenario: 'bearing_wear' })));
    expect(api.generate).toHaveBeenCalledWith(expect.objectContaining({ scenario: 'bearing_wear' }));
  });

  it('seeds a scenario graph only from its response, not unlabelled mixed-pump history', async () => {
    const oldScenarioHistory = [{ ...fixture.readings[0], timestamp: new Date(Date.now() - 60_000).toISOString(), temperature_c: 123 }];
    const history = vi.fn().mockResolvedValue(oldScenarioHistory);
    const api = setup({ generate: vi.fn().mockResolvedValue(fixture), history });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    expect(await screen.findAllByText('69.5')).toHaveLength(2);
    expect(api.history).not.toHaveBeenCalled();
    expect(screen.getByRole('img', { name: /vibration mm s trend.*1 measured samples/i })).toBeInTheDocument();
    expect(screen.queryByText('123.0')).not.toBeInTheDocument();
  });

  it.each([
    ['normal', 67, 2, 66, 1780, 320],
    ['overheating', 94, 2.1, 68, 1780, 320],
    ['bearing_wear', 69, 7, 78, 1770, 320],
    ['cavitation', 68, 5.2, 86, 1730, 275],
    ['imbalance', 70, 8.1, 72, 1780, 320],
  ] as const)('plots the returned telemetry for the %s scenario', async (scenario, temperature, vibration, sound, rpm, pressure) => {
    const response = normalAtOffset(0, scenario);
    response.readings = [{ ...response.readings[0], temperature_c: temperature, vibration_mm_s: vibration, sound_db: sound, rpm, pressure_kpa: pressure }];
    const api = setup({ generate: vi.fn().mockResolvedValue(response), history: vi.fn().mockResolvedValue([]), liveSample: vi.fn().mockRejectedValue(new Error('stop polling')) });
    selectScenario(scenario);
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));

    await waitFor(() => expect(api.generate).toHaveBeenCalledTimes(1));
    expect(await screen.findByTestId('pump-scene')).toHaveAttribute('data-scenario', scenario);
    expect([...document.querySelectorAll('.metric-reading')].map((item) => item.firstChild?.textContent?.trim())).toEqual([
      temperature.toFixed(1), vibration.toFixed(1), rpm.toFixed(1), sound.toFixed(1), pressure.toFixed(1),
    ]);
    expect(screen.getAllByRole('img', { name: /trend.*1 measured samples/i })).toHaveLength(5);
    expect(api.history).not.toHaveBeenCalled();
  });

  it('shows sensor provenance, evidence relationships, unconfirmed contributors, and mapped scene selection', async () => {
    setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn().mockResolvedValue(fixture.readings), liveSample: vi.fn().mockRejectedValue(new Error('offline after batch')) });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    expect(await screen.findByText(/Bearing condition, lubrication, or alignment/)).toBeInTheDocument();
    expect(screen.getAllByText(/Physical sensor location not specified/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/No configured backend threshold/)).toBeInTheDocument();
    expect(screen.getByText(/No other configured threshold findings/)).toBeInTheDocument();
    expect(screen.getByText(/UNCONFIRMED · INVESTIGATE/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Vibration finding' }));
    expect(screen.getByTestId('pump-scene')).toHaveAttribute('data-highlights', 'bearing:warning');
  });

  it('does not show a live state when telemetry is unavailable', async () => {
    setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn(), liveSample: vi.fn().mockRejectedValue(new Error('disconnected')) });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/disconnected/i);
    expect(document.querySelector('.freshness-note')).toHaveTextContent(/^DISCONNECTED/);
    expect(document.querySelector('.connection-masthead')).not.toHaveTextContent('LIVE');
  });

  it('shows an API error without inventing telemetry', async () => {
    setup({ generate: vi.fn().mockRejectedValue(new Error('API offline')), history: vi.fn() });
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('API offline');
    expect(screen.getAllByText('Waiting for telemetry')).toHaveLength(5);
    expect(screen.getByText('Awaiting simulation')).toBeInTheDocument();
  });

  it('renders backend diagnostics, acknowledges without repair, and keeps alerts active when live API is unavailable', async () => {
    const api: PumpApi = {
      generate: vi.fn().mockResolvedValue(fixture),
      history: vi.fn().mockResolvedValue(fixture.readings),
      liveSample: vi.fn().mockRejectedValue(new Error('API offline')),
    };
    setup(api);
    selectScenario();
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    expect(await screen.findByRole('button', { name: /vibration mm s/i })).toHaveTextContent('warning');
    fireEvent.click(screen.getByRole('button', { name: /vibration mm s/i }));
    expect(screen.getByText('High vibration')).toBeInTheDocument();
    expect(screen.getAllByText(/Inspect bearing assembly/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: /acknowledge alarm — silence siren/i }));
    expect(screen.getAllByText('acknowledged', { exact: true })).toHaveLength(2); // Alert log and diagnostic inspector.
    expect(await screen.findByRole('alert')).toHaveTextContent('API offline');
    expect(screen.getAllByText('acknowledged', { exact: true })).toHaveLength(2);
    expect(document.querySelector('.freshness-note')).toHaveTextContent(/telemetry unavailable/i);
  });

  it('starts sound alerts enabled and lets the user mute or activate them without ringing manually', async () => {
    setup();
    const control = screen.getByRole('button', { name: /mute alarms/i });
    expect(control).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(control);
    const enable = screen.getByRole('button', { name: /enable sound alerts/i });
    expect(enable).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(enable);
    expect(audioMock.activate).toHaveBeenCalledTimes(1);
    expect(audioMock.start).not.toHaveBeenCalled();
  });

  it.each(['warning', 'critical'] as const)('automatically requests audio for a new %s fault episode', async (severity) => {
    const response = severity === 'warning' ? fixture : {
      ...fixture,
      assessment: { ...fixture.assessment, health_score: 35, status: 'critical' as const,
        anomalies: fixture.assessment.anomalies.map((item) => ({ ...item, severity: 'critical' as const })) },
    };
    setup({ generate: vi.fn().mockResolvedValue(response), history: vi.fn() });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    await screen.findAllByText('69.5');
    await waitFor(() => expect(audioMock.start).toHaveBeenCalledTimes(1));
  });

  it('does not play for initial empty state or normal telemetry', async () => {
    const normal = normalAtOffset(0, 'normal');
    const api = setup({ generate: vi.fn().mockResolvedValue(normal), history: vi.fn(), liveSample: vi.fn().mockResolvedValue(normal) });
    expect(audioMock.start).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    await screen.findAllByText('68.0');
    expect(api.generate).toHaveBeenCalledTimes(1);
    expect(audioMock.start).not.toHaveBeenCalled();
  });

  it('sounds once for an episode across repeated polls and again only after a resolved new episode', async () => {
    vi.useFakeTimers();
    try {
      let call = 0;
      const liveSample = vi.fn().mockImplementation(() => {
        call += 1;
        if (call === 1) return Promise.resolve(atOffset(1000)); // Same episode as batch.
        if (call === 2) return Promise.resolve(normalAtOffset(2000));
        return Promise.resolve(atOffset(3000)); // A fresh episode after the condition cleared.
      });
      setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn(), liveSample });
      selectScenario('bearing_wear');
      fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
      await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
      expect(audioMock.start).toHaveBeenCalledTimes(1);
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      expect(audioMock.start).toHaveBeenCalledTimes(1);
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      expect(audioMock.start).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows blocked autoplay and a user gesture starts the still-active siren', async () => {
    const blocked = Object.assign(new Error('Not allowed'), { name: 'NotAllowedError' });
    audioMock.start.mockRejectedValueOnce(blocked);
    setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn() });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    expect(await screen.findByText('Browser blocked sound · enable once')).toBeInTheDocument();
    const enable = await screen.findByRole('button', { name: /enable sound alerts/i });
    fireEvent.click(enable);
    await waitFor(() => expect(audioMock.activate).toHaveBeenCalledTimes(1));
    expect(audioMock.start).toHaveBeenCalledTimes(2); // Blocked attempt, then the gesture-authorized active siren.
  });

  it('does not replay a fault after acknowledgement while its episode remains active', async () => {
    setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn(), liveSample: vi.fn().mockResolvedValue(atOffset(1000)) });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    fireEvent.click(await screen.findByRole('button', { name: /vibration mm s/i }));
    fireEvent.click(await screen.findByRole('button', { name: /acknowledge alarm — silence siren/i }));
    await waitFor(() => expect(audioMock.start).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(audioMock.stop).toHaveBeenCalled());
    expect(screen.getAllByText('acknowledged', { exact: true })).toHaveLength(2);
  });

  it('keeps the alarm action and acknowledgement state stable across repeated live value and severity changes', async () => {
    vi.useFakeTimers();
    try {
      let sampleNumber = 0;
      const liveSample = vi.fn().mockImplementation(() => {
        sampleNumber += 1;
        const timestamp = new Date(Date.now() + 1).toISOString();
        const critical = sampleNumber % 2 === 0;
        const observedValue = critical ? 8.2 : 7.6;
        return Promise.resolve({
          ...fixture,
          readings: [{ ...fixture.readings[0], timestamp, vibration_mm_s: observedValue }],
          assessment: { ...fixture.assessment, timestamp, anomalies: [{ ...fixture.assessment.anomalies[0], observed_value: observedValue, severity: critical ? 'critical' as const : 'warning' as const }] },
        });
      });
      setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn(), liveSample });
      selectScenario('bearing_wear');
      fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
      const actionName = /acknowledge alarm — silence siren/i;
      await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
      expect(screen.getByRole('button', { name: actionName })).toBeInTheDocument();
      for (let index = 0; index < 8; index += 1) {
        await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
        expect(screen.getByRole('button', { name: actionName })).toBeInTheDocument();
      }
      fireEvent.click(screen.getByRole('button', { name: actionName }));
      expect(screen.queryByRole('button', { name: actionName })).not.toBeInTheDocument();
      expect(screen.getByText('ACKNOWLEDGED — FAULT ACTIVE')).toBeInTheDocument();
      for (let index = 0; index < 6; index += 1) {
        await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
        expect(screen.queryByRole('button', { name: actionName })).not.toBeInTheDocument();
        expect(screen.getByText('ACKNOWLEDGED — FAULT ACTIVE')).toBeInTheDocument();
      }
      expect(screen.getByRole('button', { name: /vibration mm s/i })).toHaveTextContent('acknowledged');
      expect(audioMock.start).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('mute stops the siren without acknowledging the fault and unmute resumes it', async () => {
    setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn() });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    await screen.findByRole('button', { name: /acknowledge alarm — silence siren/i });
    await waitFor(() => expect(audioMock.start).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: /mute alarms/i }));
    expect(audioMock.stop).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /acknowledge alarm — silence siren/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /enable sound alerts/i }));
    await waitFor(() => expect(audioMock.start).toHaveBeenCalledTimes(2));
    expect(audioMock.activate).toHaveBeenCalledTimes(1);
  });

  it('acknowledges simultaneous fault episodes independently and keeps the siren for the remaining episode', async () => {
    const multiple = { ...fixture, assessment: { ...fixture.assessment, anomalies: [
      ...fixture.assessment.anomalies,
      { metric: 'temperature_c', observed_value: 96, expected_range: '20–85 °C', severity: 'warning' as const, explanation: 'High temperature' },
    ] } };
    setup({ generate: vi.fn().mockResolvedValue(multiple), history: vi.fn() });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    const acknowledgeControls = await screen.findAllByRole('button', { name: /acknowledge alarm — silence siren/i });
    expect(acknowledgeControls).toHaveLength(2);
    fireEvent.click(acknowledgeControls[0]);
    expect(screen.getAllByRole('button', { name: /acknowledge alarm — silence siren/i })).toHaveLength(1);
    expect(audioMock.stop).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /acknowledge alarm — silence siren/i }));
    await waitFor(() => expect(audioMock.stop).toHaveBeenCalled());
  });

  it('highlights mapped components and opens their diagnostic from a component selection', async () => {
    setup();
    selectScenario();
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    const scene = await screen.findByTestId('pump-scene');
    await waitFor(() => expect(scene).toHaveAttribute('data-highlights', 'bearing:warning'));
    fireEvent.click(screen.getByRole('button', { name: 'Mock bearing component' }));
    expect(screen.getByText('High vibration')).toBeInTheDocument();
  });

  it('starts continuous backend sampling automatically after Generate, without a pause control', async () => {
    vi.useFakeTimers();
    try {
      let index = 0;
      const liveSample = vi.fn().mockImplementation(({ scenario }) => Promise.resolve(atOffset(++index, scenario)));
      setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn(), liveSample });
      selectScenario();
      fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      expect(liveSample).toHaveBeenCalledTimes(1);
      const clientSessionId = liveSample.mock.calls[0][0].client_session_id;
      expect(clientSessionId).toEqual(expect.any(String));
      expect(screen.getByText(/LIVE · fresh backend samples expected each second/)).toBeInTheDocument();
      await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
      expect(liveSample).toHaveBeenCalledTimes(4);
      expect(liveSample.mock.calls.every(([request]) => request.client_session_id === clientSessionId)).toBe(true);
      expect(screen.getByRole('button', { name: /pause simulation/i })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('switches live scenarios through fresh backend samples and clears mixed chart history', async () => {
    vi.useFakeTimers();
    try {
      let index = 0;
      const liveSample = vi.fn().mockImplementation(({ scenario }) => Promise.resolve(atOffset(++index, scenario)));
      setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn(), liveSample });
      selectScenario();
      fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      fireEvent.change(screen.getByLabelText('Scenario'), { target: { value: 'cavitation' } });
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      expect(liveSample).toHaveBeenLastCalledWith(expect.objectContaining({ scenario: 'cavitation' }));
      expect(screen.getByLabelText('Scenario')).toHaveValue('cavitation');
    } finally {
      vi.useRealTimers();
    }
  });

  it('clears the previous scenario graph and resolves its alarm only after a fresh normal assessment', async () => {
    vi.useFakeTimers();
    try {
      let index = 0;
      let resolveNormal!: (response: SimulationResponse) => void;
      const liveSample = vi.fn().mockImplementation(({ scenario }) => {
        index += 1;
        return scenario === 'normal'
          ? new Promise<SimulationResponse>((resolve) => { resolveNormal = resolve; })
          : Promise.resolve(atOffset(index, scenario));
      });
      setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn(), liveSample });
      selectScenario('bearing_wear');
      fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      expect(screen.getByRole('button', { name: /vibration mm s/i })).toHaveTextContent('active');
      expect(screen.getByRole('img', { name: /vibration mm s trend.*2 measured samples/i })).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText('Scenario'), { target: { value: 'normal' } });
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });

      expect(liveSample).toHaveBeenLastCalledWith(expect.objectContaining({ scenario: 'normal' }));
      expect(screen.getByRole('button', { name: /vibration mm s/i })).toHaveTextContent('active');
      expect(screen.queryByRole('img', { name: /vibration mm s trend/i })).not.toBeInTheDocument();
      expect(screen.getByText('Awaiting simulation')).toBeInTheDocument();

      await act(async () => { resolveNormal(normalAtOffset(index, 'normal')); await Promise.resolve(); await Promise.resolve(); });
      expect(screen.getByTestId('pump-scene')).toHaveAttribute('data-scenario', 'normal');
      expect(screen.getByRole('img', { name: /vibration mm s trend.*1 measured samples/i })).toBeInTheDocument();
      expect(screen.queryByText('69.5')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /vibration mm s/i })).toHaveTextContent('resolved');
      expect(screen.queryByRole('button', { name: /acknowledge alarm/i })).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('ignores a late response from the previous scenario and serializes the replacement request', async () => {
    vi.useFakeTimers();
    try {
      let resolveOld: ((value: SimulationResponse) => void) | undefined;
      let calls = 0;
      const liveSample = vi.fn(({ scenario }: { scenario: SimulationResponse['scenario_label'] }) => {
        calls += 1;
        if (calls === 1) return new Promise<SimulationResponse>((resolve) => { resolveOld = resolve; });
        return Promise.resolve(atOffset(calls, scenario));
      });
      setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn().mockResolvedValue(fixture.readings), liveSample });
      selectScenario();
      fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
      await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
      expect(liveSample).toHaveBeenCalledTimes(1);
      selectScenario('cavitation');
      await act(async () => { await Promise.resolve(); });
      expect(liveSample).toHaveBeenCalledTimes(1);
      await act(async () => { resolveOld?.(atOffset(2, 'bearing_wear')); await Promise.resolve(); await Promise.resolve(); });
      expect(screen.getByText('Awaiting simulation')).toBeInTheDocument();
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); await Promise.resolve(); await Promise.resolve(); });
      expect(liveSample).toHaveBeenCalledTimes(2);
      expect(screen.getByTestId('pump-scene')).toHaveAttribute('data-scenario', 'cavitation');
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps alert episodes and marks the last sample unavailable after a live API failure', async () => {
    const api: PumpApi = {
      generate: vi.fn().mockResolvedValue(fixture), history: vi.fn().mockResolvedValue(fixture.readings),
      liveSample: vi.fn().mockRejectedValue(new Error('Live API offline')),
    };
    setup(api);
    selectScenario();
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    expect(await screen.findByRole('button', { name: /vibration mm s/i })).toHaveTextContent('active');
    expect(await screen.findByRole('alert')).toHaveTextContent('Live API offline');
    expect(document.querySelector('.freshness-note')).toHaveTextContent(/telemetry unavailable/i);
    expect(screen.getByText('active', { exact: true })).toBeInTheDocument();
  });

  it('recovers after a live API failure without duplicating an unchanged alert episode', async () => {
    vi.useFakeTimers();
    try {
      let calls = 0;
      const api: PumpApi = {
        generate: vi.fn().mockResolvedValue(fixture),
        history: vi.fn().mockResolvedValue(fixture.readings),
        liveSample: vi.fn().mockImplementation(() => {
          calls += 1;
          return calls === 1 ? Promise.reject(new Error('API offline')) : Promise.resolve(atOffset(calls));
        }),
      };
      setup(api);
      selectScenario();
      fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
      await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
      expect(screen.getByRole('alert')).toHaveTextContent('API offline');
      expect(document.querySelector('.freshness-note')).toHaveTextContent(/telemetry unavailable/i);
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); await Promise.resolve(); await Promise.resolve(); });
      expect(document.querySelector('.freshness-note')).toHaveTextContent(/LIVE · fresh backend samples expected each second/);
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.getAllByRole('button', { name: /vibration mm s/i })).toHaveLength(1);
      expect(screen.getByRole('button', { name: /vibration mm s/i })).toHaveTextContent('active');
    } finally {
      vi.useRealTimers();
    }
  });

  it('cleans up the scheduled poll when the monitoring view unmounts', async () => {
    vi.useFakeTimers();
    try {
      let index = 0;
      const liveSample = vi.fn().mockImplementation(() => Promise.resolve(atOffset(++index)));
      const api: PumpApi = { generate: vi.fn().mockResolvedValue(fixture), history: vi.fn().mockResolvedValue(fixture.readings), liveSample };
      const view = render(<PumpTwinApp api={api} />);
      selectScenario();
      fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
      await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
      expect(liveSample).toHaveBeenCalledTimes(1);
      view.unmount();
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(liveSample).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('prevents a second request while the first request is pending', async () => {
    let resolveRequest: ((value: SimulationResponse) => void) | undefined;
    const api: PumpApi = {
      generate: vi.fn(() => new Promise<SimulationResponse>((resolve) => { resolveRequest = resolve; })),
      history: vi.fn().mockResolvedValue(fixture.readings),
    };
    setup(api);
    const button = screen.getByRole('button', { name: /generate simulation/i });
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    fireEvent.click(button);
    expect(api.generate).toHaveBeenCalledTimes(1);
    resolveRequest?.(fixture);
  });

  it('reset action requests the normal simulator scenario', async () => {
    const api = setup();
    fireEvent.click(screen.getByRole('button', { name: /reset to normal operation/i }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledWith(expect.objectContaining({ scenario: 'normal' })));
  });

  it('pauses and resumes simulation polling without discarding the active sample', async () => {
    let index = 0;
    const fresh = atOffset(0);
    const liveSample = vi.fn().mockImplementation(() => Promise.resolve(atOffset(++index + 1)));
    setup({ generate: vi.fn().mockResolvedValue(fresh), history: vi.fn(), liveSample });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    await waitFor(() => expect(liveSample).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: /pause simulation/i }));
    expect(screen.getByText('PAUSED')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /resume simulation/i }));
    await waitFor(() => expect(liveSample).toHaveBeenCalledTimes(2));
  });

  it('sends operating controls and fault injection to the backend live engine', async () => {
    const liveSample = vi.fn().mockResolvedValue(atOffset(1000));
    setup({ generate: vi.fn().mockResolvedValue(atOffset(0)), history: vi.fn(), liveSample });
    fireEvent.change(screen.getByLabelText('Scenario'), { target: { value: 'bearing_wear' } });
    fireEvent.change(screen.getByLabelText('Simulation speed'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Motor load'), { target: { value: '80' } });
    fireEvent.change(screen.getByLabelText('Inlet restriction'), { target: { value: '25' } });
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    await waitFor(() => expect(liveSample).toHaveBeenCalledWith(expect.objectContaining({
      scenario: 'bearing_wear', speed: 2, load_percent: 80, inlet_restriction_percent: 25,
      fault_enabled: true, fault_severity: 1,
    })));
  });

  it('requests a bounded diagnosis explicitly and labels mock output clearly', async () => {
    const diagnostic: DiagnosticResult = {
      summary: 'Mock diagnostic only. Bearing condition remains an unconfirmed hypothesis.',
      hypotheses: [{ cause: 'bearing wear', rank: 1, uncertainty: 'high', evidence: [{ source: 'telemetry', field: 'vibration_mm_s', reading_index: 0, value: 7.1 }], missing_evidence: ['Direct inspection'] }],
      missing_evidence: ['Independent sensor verification'], inspection_steps: ['Verify sensor readings.'], priority: 'soon',
      priority_rationale: 'Rule warning only.', limitations: ['Synthetic data.'], human_review_required: true,
      provider: 'mock', is_mock: true, latency_ms: 2, correlation_id: 'test-id', cached: false, assessment_timestamp: new Date().toISOString(),
    };
    const diagnose = vi.fn().mockResolvedValue(diagnostic);
    setup({ generate: vi.fn().mockResolvedValue(atOffset(0)), history: vi.fn(), liveSample: vi.fn().mockRejectedValue(new Error('stop')), diagnose });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    await screen.findByText(/LIVE · fresh backend samples expected each second/);
    const requestButton = await screen.findByRole('button', { name: /request diagnostic explanation/i });
    await waitFor(() => expect(requestButton).toBeEnabled());
    fireEvent.click(requestButton);
    expect(await screen.findByText(/MOCK RESULT · NOT AN AMD MODEL/)).toBeInTheDocument();
    expect(diagnose).toHaveBeenCalledWith(expect.objectContaining({
      is_synthetic: true, alert_episode_id: expect.any(String), telemetry: [expect.objectContaining({ vibration_mm_s: 7.1 })],
      detector: expect.objectContaining({ status: 'warning', confidence: null }),
    }));
  });

  it('labels a successfully parsed AMD diagnosis with its real provider provenance', async () => {
    const diagnostic: DiagnosticResult = {
      summary: 'AMD explanation based on this evidence.', hypotheses: [], missing_evidence: [], inspection_steps: ['Inspect safely.'],
      priority: 'soon', priority_rationale: 'Rule warning.', limitations: ['Synthetic data.'], human_review_required: true,
      provider: 'amd', is_mock: false, latency_ms: 3, correlation_id: 'amd-success', cached: false,
      assessment_timestamp: new Date().toISOString(),
    };
    const diagnose = vi.fn().mockResolvedValue(diagnostic);
    setup({ generate: vi.fn().mockResolvedValue(atOffset(0)), history: vi.fn(), liveSample: vi.fn().mockRejectedValue(new Error('stop')), diagnose });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    await screen.findByText(/LIVE · fresh backend samples expected each second/);
    const requestButton = await screen.findByRole('button', { name: /request diagnostic explanation/i });
    await waitFor(() => expect(requestButton).toBeEnabled());
    fireEvent.click(requestButton);
    expect(await screen.findByText(/AMD · 3 ms/)).toBeInTheDocument();
  });

  it('derives diagnostic trends from the exact telemetry window sent to the provider', async () => {
    const base = Date.now() - 12_000;
    const readings = Array.from({ length: 13 }, (_, index) => ({
      ...fixture.readings[0], timestamp: new Date(base + index * 1000).toISOString(),
      vibration_mm_s: index === 0 ? 1.91 : 6 + (index - 1) * (1.5 / 11),
    }));
    readings[12].vibration_mm_s = 7.5;
    const response = { ...fixture, readings, assessment: { ...fixture.assessment, timestamp: readings.at(-1)!.timestamp } };
    const diagnostic: DiagnosticResult = {
      summary: 'Evidence-based summary.', hypotheses: [], missing_evidence: [], inspection_steps: ['Inspect safely.'],
      priority: 'soon', priority_rationale: 'Rule warning.', limitations: ['Synthetic data.'], human_review_required: true,
      provider: 'mock', is_mock: true, latency_ms: 1, correlation_id: 'window-test', cached: false,
      assessment_timestamp: fixtureTimestamp,
    };
    const diagnose = vi.fn().mockResolvedValue(diagnostic);
    setup({ generate: vi.fn().mockResolvedValue(response), history: vi.fn(), liveSample: vi.fn().mockRejectedValue(new Error('stop')), diagnose });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    await screen.findByText(/LIVE · fresh backend samples expected each second/);
    const requestButton = await screen.findByRole('button', { name: /request diagnostic explanation/i });
    await waitFor(() => expect(requestButton).toBeEnabled());
    fireEvent.click(requestButton);
    await waitFor(() => expect(diagnose).toHaveBeenCalledTimes(1));
    const request = diagnose.mock.calls[0][0] as DiagnosticRequest;
    const vibrationTrend = request.trends.find((item) => item.metric === 'vibration_mm_s');
    expect(request.telemetry).toHaveLength(12);
    expect(request.telemetry[0].vibration_mm_s).toBe(6);
    expect(request.telemetry.at(-1)?.vibration_mm_s).toBe(7.5);
    expect(vibrationTrend).toMatchObject({ initial_value: 6, latest_value: 7.5, delta: 1.5, samples: 12 });
  });

  it('keeps deterministic alert controls available when a diagnostic provider fails', async () => {
    const diagnose = vi.fn().mockRejectedValue(new Error('Diagnostic provider unavailable'));
    setup({ generate: vi.fn().mockResolvedValue(atOffset(0)), history: vi.fn(), liveSample: vi.fn().mockRejectedValue(new Error('stop')), diagnose });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    const acknowledge = await screen.findByRole('button', { name: /acknowledge alarm/i });
    fireEvent.click(screen.getByRole('button', { name: /request diagnostic explanation/i }));
    expect(await screen.findByText('Diagnostic provider unavailable')).toBeInTheDocument();
    expect(acknowledge).toBeInTheDocument();
    expect(screen.getByText('High vibration')).toBeInTheDocument();
  });

  it('renders deterministic telemetry intelligence on demand and labels it synthetic', async () => {
    const analysis = {
      asset_id: 'pump-01', generator: 'deterministic_analysis', provenance: 'synthetic', synthetic: true,
      window_start: fixtureTimestamp, window_end: fixtureTimestamp, sample_count: 40, valid_sample_count: 40,
      missing_sample_count: 0, sampling_regular: true, median_interval_seconds: 1,
      metrics: [
        { metric: 'vibration_mm_s', unit: 'mm/s', provenance: 'synthetic', sample_count: 40, valid_count: 40, missing_count: 0, first_timestamp: fixtureTimestamp, last_timestamp: fixtureTimestamp, elapsed_seconds: 39, first_value: 6.1, latest_value: 7.1, minimum: 6.0, maximum: 7.2, mean: 6.6, delta: 1.0, rate_per_second: 0.005, rate_unit: 'per_second', direction: 'stable', median_interval_seconds: 1, sampling_regular: true, rolling_mean: 7.0, rolling_std: 0.2, threshold: { low: 0, high: 4.5, critical_low: 0, critical_high: 8, unit: 'mm/s' }, excursions_high: 40, excursions_low: 0, critical_breaches: 1, insufficient_samples: false },
      ],
      limitations: ['Telemetry is synthetic simulator output; it does not represent a real machine.'],
      ai_summary: [],
    };
    const telemetryAnalysis = vi.fn().mockResolvedValue(analysis);
    setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn(), telemetryAnalysis });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    const analyzeButton = await screen.findByRole('button', { name: /analyze telemetry window/i });
    await waitFor(() => expect(analyzeButton).toBeEnabled());
    await act(async () => { fireEvent.click(analyzeButton); });
    expect(await screen.findByText(/DETERMINISTIC ANALYSIS · 40 samples · regular sampling/)).toBeInTheDocument();
    expect(screen.getByText('SYNTHETIC TELEMETRY')).toBeInTheDocument();
    expect(screen.getByText(/excursions 40 · critical 1/)).toBeInTheDocument();
    expect(telemetryAnalysis).toHaveBeenCalledWith('pump-01', expect.any(Number));
  });

  it('surfaces a telemetry-analysis failure without blocking the dashboard', async () => {
    const telemetryAnalysis = vi.fn().mockRejectedValue(new Error('Unknown pump_id: pump-01'));
    setup({ generate: vi.fn().mockResolvedValue(fixture), history: vi.fn(), telemetryAnalysis });
    selectScenario('bearing_wear');
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    const analyzeButton = await screen.findByRole('button', { name: /analyze telemetry window/i });
    await waitFor(() => expect(analyzeButton).toBeEnabled());
    await act(async () => { fireEvent.click(analyzeButton); });
    expect(await screen.findByText('Unknown pump_id: pump-01')).toBeInTheDocument();
    // The rule-based assessment remains available.
    expect(screen.getByText('High vibration')).toBeInTheDocument();
  });


  it.each(['normal', 'overheating', 'bearing_wear', 'cavitation', 'imbalance'] as const)(
    'synchronizes the %s visual state from the API response', async (scenario) => {
      const result = { ...fixture, scenario_label: scenario };
      setup({ generate: vi.fn().mockResolvedValue(result), history: vi.fn().mockResolvedValue(result.readings) });
      fireEvent.change(screen.getByLabelText('Scenario'), { target: { value: scenario } });
      fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
      expect(await screen.findByTestId('pump-scene')).toHaveAttribute('data-scenario', scenario);
    },
  );

  it('keeps panels empty when the backend response contains no readings', async () => {
    setup({ generate: vi.fn().mockResolvedValue({ ...fixture, readings: [] }), history: vi.fn() });
    selectScenario();
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/malformed telemetry/i);
    expect(screen.queryByText('69.5')).not.toBeInTheDocument();
    expect(screen.getByText('Awaiting simulation')).toBeInTheDocument();
  });

  it('rejects stale live samples without replacing or unacknowledging the current alarm', async () => {
    const stale = { ...fixture, readings: [{ ...fixture.readings[0], timestamp: new Date(Date.now() - 60_000).toISOString() }], assessment: { ...fixture.assessment, timestamp: new Date(Date.now() - 60_000).toISOString() } };
    let releaseLive!: (response: SimulationResponse) => void;
    const api: PumpApi = { generate: vi.fn().mockResolvedValue(fixture), history: vi.fn().mockResolvedValue(fixture.readings), liveSample: vi.fn(() => new Promise<SimulationResponse>((resolve) => { releaseLive = resolve; })) };
    setup(api);
    selectScenario();
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    fireEvent.click(await screen.findByRole('button', { name: /acknowledge alarm/i }));
    await waitFor(() => expect(api.liveSample).toHaveBeenCalled());
    await act(async () => { releaseLive(stale); await Promise.resolve(); });
    expect(await screen.findByRole('alert')).toHaveTextContent(/stale telemetry/i);
    expect(screen.getAllByText('69.5')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: /acknowledge alarm/i })).not.toBeInTheDocument();
    expect(screen.getByText('ACKNOWLEDGED — FAULT ACTIVE')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /vibration mm s/i })).toHaveTextContent('acknowledged');
    expect(document.querySelector('.freshness-note')).toHaveTextContent(/telemetry unavailable/i);
  });

  it('anchors the generated batch so its newest sample is not future-dated', async () => {
    const api = setup();
    selectScenario();
    fireEvent.click(screen.getByRole('button', { name: /generate simulation/i }));
    await screen.findAllByText('69.5');
    const request = vi.mocked(api.generate).mock.calls[0][0];
    const newest = Date.parse(request.start_time!) + (request.sample_count - 1) * request.sampling_interval_seconds * 1000;
    expect(Math.abs(newest - Date.now())).toBeLessThan(1000);
  });
});
