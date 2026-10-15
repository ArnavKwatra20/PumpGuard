export interface AlarmAudio {
  activate(): Promise<void>;
  /** Start (or retain) one repeating warning pattern. Idempotent while active. */
  start(): Promise<void>;
  /** Stop every tone immediately. */
  stop(): void;
  /** Observe failures in later cadence cycles without leaking timer exceptions. */
  setErrorHandler(handler: () => void): void;
  close(): void;
}

/** One reusable Web Audio context for a controlled, repeating industrial siren. */
export function createAlarmAudio(): AlarmAudio {
  const AudioContextConstructor = window.AudioContext;
  if (!AudioContextConstructor) throw new Error('Web Audio is unavailable in this browser.');

  const context = new AudioContextConstructor();
  let active = false;
  let closed = false;
  let starting: Promise<void> | null = null;
  let generation = 0;
  let requested = false;
  let errorHandler: () => void = () => {};
  let timer: ReturnType<typeof setTimeout> | null = null;
  const oscillators = new Set<OscillatorNode>();
  let toneIndex = 0;

  const resume = async () => {
    if (closed) throw new Error('Alarm audio is closed.');
    if (context.state !== 'running') await context.resume();
    if (context.state !== 'running') throw new Error('Browser audio playback is blocked.');
  };

  const scheduleTone = () => {
    if (!active || closed) return;
    // Two alternating pairs followed by a quiet gap: recognizable warning cadence
    // without a continuous or excessively loud tone.
    const cadence = [740, 520, 740, 520, 0];
    const frequency = cadence[toneIndex % cadence.length];
    toneIndex += 1;
    if (frequency > 0) {
      try {
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        const now = context.currentTime;
        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(frequency, now);
        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.exponentialRampToValueAtTime(0.09, now + 0.025);
        gain.gain.setValueAtTime(0.09, now + 0.22);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.28);
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.onended = () => {
          oscillators.delete(oscillator);
          try { oscillator.disconnect(); gain.disconnect(); } catch { /* Already disconnected. */ }
        };
        oscillators.add(oscillator);
        oscillator.start(now);
        oscillator.stop(now + 0.3);
      } catch {
        stop();
        throw new Error('Unable to create alarm tone.');
      }
    }
    timer = setTimeout(() => {
      try { scheduleTone(); }
      catch { stop(); errorHandler(); }
    }, frequency === 0 ? 520 : 420);
  };

  const stop = () => {
    generation += 1;
    requested = false;
    active = false;
    if (timer !== null) clearTimeout(timer);
    timer = null;
    for (const oscillator of oscillators) {
      try { oscillator.stop(); } catch { /* It may already have ended. */ }
      try { oscillator.disconnect(); } catch { /* Already disconnected. */ }
    }
    oscillators.clear();
  };

  const start = (): Promise<void> => {
    if (active) return Promise.resolve();
    requested = true;
    if (starting) return starting.then(() => requested && !active && !closed ? start() : undefined);
    const requestedGeneration = generation;
    starting = (async () => {
      await resume();
      if (closed || active || generation !== requestedGeneration) return;
      active = true;
      toneIndex = 0;
      scheduleTone();
    })().catch((error) => {
      if (generation === requestedGeneration) requested = false;
      throw error;
    }).finally(() => { starting = null; });
    return starting;
  };

  return {
    activate: resume,
    start,
    stop,
    setErrorHandler(handler) { errorHandler = handler; },
    close() {
      closed = true;
      stop();
      if (context.state !== 'closed') void context.close();
    },
  };
}
