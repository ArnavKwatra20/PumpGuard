import { afterEach, describe, expect, it, vi } from 'vitest';
import { pumpApi } from './api';

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
});
