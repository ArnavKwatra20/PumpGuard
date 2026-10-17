import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AiFeatureResponse, PumpApi } from './api';
import { AiFeaturePanel } from './AiFeaturePanel';

const response: AiFeatureResponse = {
  feature: 'maintenance_planner',
  assistant_message: '**Inspect first** using the synthetic rule evidence.',
  provider: 'mock',
  is_mock: true,
  latency_ms: 3,
  evidence_timestamp: '2026-10-15T00:00:00Z',
};

function setup(aiFeature: NonNullable<PumpApi['aiFeature']>) {
  const api = { aiFeature } as unknown as PumpApi;
  return { api, ...render(<AiFeaturePanel api={api} pumpId="pump-01" clientSessionId="session-01" contextAvailable contextKey="pump-01:normal" />) };
}

describe('AiFeaturePanel', () => {
  it('keeps feature actions disabled until authoritative telemetry context exists', () => {
    const request = vi.fn();
    const api = { aiFeature: request } as unknown as PumpApi;
    render(<AiFeaturePanel api={api} pumpId="pump-01" clientSessionId={null} contextAvailable={false} contextKey="pump-01:normal" />);
    expect(screen.getByRole('button', { name: 'Draft maintenance plan' })).toBeDisabled();
    expect(request).not.toHaveBeenCalled();
  });

  it('requests a selected feature and renders safe assistant content', async () => {
    const request = vi.fn().mockResolvedValue(response);
    setup(request);
    fireEvent.click(screen.getByRole('button', { name: 'Draft maintenance plan' }));
    expect(await screen.findByText('Inspect first')).toBeInTheDocument();
    expect(screen.getByText(/TEST MOCK — not AMD-generated/)).toBeInTheDocument();
    expect(screen.getByText('Inspect first').tagName).toBe('STRONG');
    expect(request).toHaveBeenCalledWith({ pump_id: 'pump-01', feature: 'maintenance_planner', client_session_id: 'session-01' });
  });

  it('labels a real provider response as AMD-generated only when provider metadata confirms it', async () => {
    const request = vi.fn().mockResolvedValue({ ...response, assistant_message: 'Vibration increased from 1.91 to 7.30 mm/s.', provider: 'amd', is_mock: false });
    setup(request);
    fireEvent.click(screen.getByRole('button', { name: 'Draft maintenance plan' }));
    expect(await screen.findByText(/AI-generated demo explanation · AMD/)).toBeInTheDocument();
    expect(screen.getByText('Vibration increased from 1.91 to 7.30 mm/s.')).toBeInTheDocument();
  });

  it('shows provider failures and retries without fabricating a result', async () => {
    const request = vi.fn().mockRejectedValueOnce(new Error('AMD unavailable')).mockResolvedValueOnce(response);
    setup(request);
    fireEvent.click(screen.getByRole('button', { name: 'Explain telemetry trends' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('AMD unavailable');
    expect(screen.queryByText(/AI-generated demo explanation · AMD/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Inspect first')).toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('does not render an older response after the simulation context changes', async () => {
    let resolveRequest!: (value: AiFeatureResponse) => void;
    const request = vi.fn().mockReturnValue(new Promise<AiFeatureResponse>((resolve) => { resolveRequest = resolve; }));
    const api = { aiFeature: request } as unknown as PumpApi;
    const view = render(<AiFeaturePanel api={api} pumpId="pump-01" clientSessionId="session-01" contextAvailable contextKey="pump-01:normal" />);
    fireEvent.click(screen.getByRole('button', { name: 'Draft maintenance plan' }));
    view.rerender(<AiFeaturePanel api={api} pumpId="pump-01" clientSessionId="session-02" contextAvailable contextKey="pump-01:normal:session-02" />);
    await act(async () => { resolveRequest(response); });
    expect(screen.queryByText('Inspect first')).not.toBeInTheDocument();
  });
});
