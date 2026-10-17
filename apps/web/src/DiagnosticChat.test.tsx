import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { DiagnosticChatRequest, DiagnosticChatResponse, PumpApi } from './api';
import { DiagnosticChat } from './DiagnosticChat';

const defaultChat = vi.fn((_request: DiagnosticChatRequest): Promise<DiagnosticChatResponse> => Promise.resolve({
  assistant_message: 'Inspect the measured vibration and follow the rule assessment.',
  provider: 'mock', is_mock: true, latency_ms: 4,
}));

function setup(diagnosticChat: NonNullable<PumpApi['diagnosticChat']> = defaultChat, clientSessionId?: string) {
  const api = { diagnosticChat } as unknown as PumpApi;
  return { api, ...render(<DiagnosticChat api={api} pumpId="pump-01" clientSessionId={clientSessionId} contextAvailable />) };
}

describe('DiagnosticChat', () => {
  it('sends a question and renders the assistant response', async () => {
    const { api } = setup();
    fireEvent.change(screen.getByLabelText('Ask about this pump'), { target: { value: 'Why is it warning?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByText('Why is it warning?')).toBeInTheDocument();
    expect(await screen.findByText(/Inspect the measured vibration/)).toBeInTheDocument();
    expect(screen.getByText(/TEST MOCK — not AMD-generated/)).toBeInTheDocument();
    expect(api.diagnosticChat).toHaveBeenCalledWith({ pump_id: 'pump-01', question: 'Why is it warning?', history: [] });
  });

  it('shows loading and disables input while sending', async () => {
    let resolve!: (value: { assistant_message: string; provider: 'mock'; is_mock: true; latency_ms: number }) => void;
    const request = vi.fn((_request) => new Promise<DiagnosticChatResponse>((r) => { resolve = r; }));
    setup(request);
    fireEvent.change(screen.getByLabelText('Ask about this pump'), { target: { value: 'What changed?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(screen.getByText(/consulting the configured diagnostic provider/i)).toBeInTheDocument();
    expect(screen.getByLabelText('Ask about this pump')).toBeDisabled();
    resolve({ assistant_message: 'The current evidence is synthetic.', provider: 'mock', is_mock: true, latency_ms: 1 });
    await screen.findByText(/current evidence is synthetic/);
  });

  it('sends the active client session with chat evidence requests', async () => {
    const request = vi.fn().mockResolvedValue({ assistant_message: 'Vibration increased from 1.91 to 7.30 mm/s.', provider: 'amd', is_mock: false, latency_ms: 1 });
    setup(request, 'session-current');
    fireEvent.change(screen.getByLabelText('Ask about this pump'), { target: { value: 'What changed?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByText('Vibration increased from 1.91 to 7.30 mm/s.')).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith({ pump_id: 'pump-01', client_session_id: 'session-current', question: 'What changed?', history: [] });
    expect(screen.getByText(/AI-generated demo explanation · AMD/)).toBeInTheDocument();
  });

  it('never labels contradictory AMD mock provenance as an AMD response', async () => {
    const request = vi.fn().mockResolvedValue({ assistant_message: 'Unverified answer.', provider: 'amd', is_mock: true, latency_ms: 1 });
    setup(request);
    fireEvent.change(screen.getByLabelText('Ask about this pump'), { target: { value: 'Summarize' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await screen.findByText('Unverified answer.');
    expect(screen.getByText(/TEST MOCK — not AMD-generated/)).toBeInTheDocument();
    expect(screen.queryByText(/AI-generated demo explanation · AMD/)).not.toBeInTheDocument();
  });

  it('shows an error and retries the failed question', async () => {
    const request = vi.fn()
      .mockRejectedValueOnce(new Error('AMD gateway unavailable'))
      .mockResolvedValueOnce({ assistant_message: 'Retry succeeded.', provider: 'mock', is_mock: true, latency_ms: 2 });
    setup(request);
    fireEvent.change(screen.getByLabelText('Ask about this pump'), { target: { value: 'What should I inspect?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('AMD gateway unavailable');
    expect(screen.queryByText(/AI-generated demo explanation · AMD/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Retry succeeded.')).toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('renders escaped bold Markdown safely without interpreting HTML', async () => {
    const request = vi.fn().mockResolvedValue({
      assistant_message: String.raw`\*\*warning\*\* is based on the current rule.

<script>alert(1)</script>`,
      provider: 'amd', is_mock: false, latency_ms: 3,
    });
    setup(request);
    fireEvent.change(screen.getByLabelText('Ask about this pump'), { target: { value: 'Summarize the status' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByText('warning')).toBeInTheDocument();
    expect(screen.getByText('warning').tagName).toBe('STRONG');
    expect(screen.getByText(/AI-generated demo explanation · AMD/)).toBeInTheDocument();
    expect(screen.queryByRole('script')).not.toBeInTheDocument();
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
  });

  it('keeps the input editable when provider status is unavailable and reports send failures', async () => {
    const request = vi.fn().mockRejectedValue(new Error('Provider status unavailable'));
    setup(request);
    const input = screen.getByLabelText('Ask about this pump');
    expect(input).toBeEnabled();
    fireEvent.change(input, { target: { value: 'Can you inspect this pump?' } });
    expect(input).toHaveValue('Can you inspect this pump?');
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', shiftKey: false });
    expect(await screen.findByRole('alert')).toHaveTextContent('Provider status unavailable');
    expect(request).toHaveBeenCalledWith({ pump_id: 'pump-01', question: 'Can you inspect this pump?', history: [] });
    expect(screen.queryByText(/AI-generated demo explanation · AMD/)).not.toBeInTheDocument();
  });

  it('keeps Enter as submit and Shift+Enter as newline while provider status is unavailable', async () => {
    const request = vi.fn().mockResolvedValue({ assistant_message: 'Answer', provider: 'mock', is_mock: true, latency_ms: 1 });
    setup(request);
    const input = screen.getByLabelText('Ask about this pump');
    fireEvent.change(input, { target: { value: 'First line' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', shiftKey: true });
    expect(input).toHaveValue('First line');
    fireEvent.change(input, { target: { value: 'First line\nSecond line' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', shiftKey: false });
    expect(await screen.findByText('Answer')).toBeInTheDocument();
  });

  it('uses suggested questions and clears only after confirmation', async () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'Which telemetry signals support this assessment?' }));
    expect(screen.getByLabelText('Ask about this pump')).toHaveValue('Which telemetry signals support this assessment?');
    fireEvent.change(screen.getByLabelText('Ask about this pump'), { target: { value: 'A question' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByText('A question')).toBeInTheDocument();
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    fireEvent.click(screen.getByRole('button', { name: 'Clear conversation' }));
    expect(screen.getByText('A question')).toBeInTheDocument();
    vi.mocked(window.confirm).mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'Clear conversation' }));
    await waitFor(() => expect(screen.queryByText('A question')).not.toBeInTheDocument());
  });

  it('separates conversation when the selected pump changes', async () => {
    const api = { diagnosticChat: vi.fn().mockResolvedValue({ assistant_message: 'Answer', provider: 'mock', is_mock: true, latency_ms: 1 }) } as unknown as PumpApi;
    const view = render(<DiagnosticChat api={api} pumpId="pump-01" contextAvailable />);
    fireEvent.change(screen.getByLabelText('Ask about this pump'), { target: { value: 'Question for one pump' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByText('Question for one pump')).toBeInTheDocument();
    view.rerender(<DiagnosticChat api={api} pumpId="pump-02" contextAvailable />);
    await waitFor(() => expect(screen.queryByText('Question for one pump')).not.toBeInTheDocument());
    expect(screen.getByText('Ask a focused question about the current evidence.')).toBeInTheDocument();
  });
});

