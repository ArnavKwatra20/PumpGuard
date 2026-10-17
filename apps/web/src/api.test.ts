import { afterEach, describe, expect, it, vi } from 'vitest';
import { pumpApi, type DiagnosticRequest } from './api';

describe('API request timeouts', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('releases the Generate action when the backend does not answer', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));
    const request = pumpApi.generate({ pump_id: 'pump-01', scenario: 'normal', sample_count: 60, sampling_interval_seconds: 1 });
    const rejection = expect(request).rejects.toThrow('API request timed out after 8 seconds.');
    await vi.advanceTimersByTimeAsync(8_000);
    await rejection;
  });

  it('keeps AMD diagnostic requests alive beyond the former 60 second browser deadline', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));
    const request = pumpApi.diagnose!({} as DiagnosticRequest);
    let settled = false;
    void request.catch(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(60_001);
    expect(settled).toBe(false);
    const rejection = expect(request).rejects.toThrow('API request timed out after 260 seconds.');
    await vi.advanceTimersByTimeAsync(199_999);
    await rejection;
  });
});
