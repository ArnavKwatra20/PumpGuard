import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAlarmAudio } from './alarm-audio';

class FakeAudioContext {
  state: AudioContextState = 'suspended';
  currentTime = 1;
  destination = {} as AudioNode;
  oscillatorCreations = 0;
  resume = vi.fn(async () => { this.state = 'running'; });
  close = vi.fn(async () => { this.state = 'closed'; });
  oscillators: Array<{ type: OscillatorType; frequency: { value: number; setValueAtTime: ReturnType<typeof vi.fn> }; connect: ReturnType<typeof vi.fn>; start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn>; onended: (() => void) | null }> = [];
  oscillator = {
    type: 'sine' as OscillatorType,
    frequency: { value: 0, setValueAtTime: vi.fn() },
    connect: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(() => queueMicrotask(() => this.oscillator.onended?.())),
    disconnect: vi.fn(),
    onended: null as (() => void) | null,
  };
  gain = {
    gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
    connect: vi.fn(),
  };

  createOscillator() {
    this.oscillatorCreations += 1;
    const oscillator = { ...this.oscillator, frequency: { ...this.oscillator.frequency }, onended: null as (() => void) | null };
    oscillator.stop = vi.fn(() => queueMicrotask(() => oscillator.onended?.()));
    this.oscillators.push(oscillator);
    return oscillator as unknown as OscillatorNode;
  }
  createGain() { return this.gain as unknown as GainNode; }
}

const originalAudioContext = window.AudioContext;

afterEach(() => {
  vi.useRealTimers();
  Object.defineProperty(window, 'AudioContext', { configurable: true, value: originalAudioContext });
  vi.restoreAllMocks();
});

describe('automatic alarm audio', () => {
  it('starts one repeating alternating siren and stops it cleanly', async () => {
    const contexts: FakeAudioContext[] = [];
    class ContextFactory extends FakeAudioContext {
      constructor() { super(); contexts.push(this); }
    }
    Object.defineProperty(window, 'AudioContext', { configurable: true, value: ContextFactory });

    const audio = createAlarmAudio();
    vi.useFakeTimers();
    const first = audio.start();
    const second = audio.start();
    await Promise.all([first, second]);

    expect(contexts).toHaveLength(1);
    expect(contexts[0].oscillatorCreations).toBe(1);
    expect(contexts[0].oscillator.start).toHaveBeenCalledTimes(1);
    expect(contexts[0].oscillators[0].frequency.setValueAtTime).toHaveBeenCalledWith(740, 1);
    await vi.advanceTimersByTimeAsync(420);
    expect(contexts[0].oscillatorCreations).toBe(2);
    expect(contexts[0].oscillators[1].frequency.setValueAtTime).toHaveBeenCalledWith(520, 1);
    audio.stop();
    expect(contexts[0].oscillators.at(-1)?.stop).toHaveBeenCalled();
    audio.close();
    expect(contexts[0].close).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('surfaces rejected autoplay and does not create a tone until playback is allowed', async () => {
    class BlockedContext extends FakeAudioContext {
      resume = vi.fn(async () => { throw new DOMException('Blocked', 'NotAllowedError'); });
    }
    Object.defineProperty(window, 'AudioContext', { configurable: true, value: BlockedContext });
    const audio = createAlarmAudio();

    await expect(audio.start()).rejects.toHaveProperty('name', 'NotAllowedError');
    audio.close();
  });

  it('does not start after an immediate stop, and honors a newer start request during context resume', async () => {
    let releaseResume!: () => void;
    let contextInstance: DelayedContext | undefined;
    class DelayedContext extends FakeAudioContext {
      constructor() { super(); contextInstance = this; }
      resume = vi.fn(async () => { await new Promise<void>((resolve) => { releaseResume = resolve; }); this.state = 'running'; });
    }
    Object.defineProperty(window, 'AudioContext', { configurable: true, value: DelayedContext });
    const audio = createAlarmAudio();
    const firstStart = audio.start();
    audio.stop();
    const restarted = audio.start();
    releaseResume();
    await Promise.all([firstStart, restarted]);
    expect(contextInstance?.oscillatorCreations).toBe(1);
    audio.stop();
    audio.close();
  });

  it('reports a later oscillator failure without throwing from the cadence timer', async () => {
    class IntermittentContext extends FakeAudioContext {
      createOscillator() {
        if (this.oscillatorCreations > 0) throw new Error('Audio node unavailable');
        return super.createOscillator();
      }
    }
    Object.defineProperty(window, 'AudioContext', { configurable: true, value: IntermittentContext });
    vi.useFakeTimers();
    const audio = createAlarmAudio();
    const onError = vi.fn();
    audio.setErrorHandler(onError);
    await audio.start();
    await vi.advanceTimersByTimeAsync(420);
    expect(onError).toHaveBeenCalledTimes(1);
    audio.close();
  });

  it('reports unsupported Web Audio instead of failing silently', () => {
    Object.defineProperty(window, 'AudioContext', { configurable: true, value: undefined });
    expect(() => createAlarmAudio()).toThrow('Web Audio is unavailable in this browser.');
  });
});
