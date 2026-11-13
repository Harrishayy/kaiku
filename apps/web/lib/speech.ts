'use client';

import { estimatePitch, semitoneSd } from './metrics.ts';

/**
 * Spoken-prompt task. Audio is analysed in memory with Web Audio and never recorded,
 * stored or sent — only the derived numbers below leave the browser.
 */
export interface SpeechResult {
  speech_rate: number | null; // syllables per second (rough, from energy peaks)
  pause_ratio: number | null;
  pitch_variability: number | null; // semitones SD
  duration_s: number;
}

export interface SpeechSession {
  stop: () => void;
  done: Promise<SpeechResult | null>;
}

export const FRAME_MS = 50;

export async function startSpeechTask(opts: {
  durationS: number;
  onLevel: (level: number, elapsedS: number) => void;
}): Promise<SpeechSession> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const Ctx: typeof AudioContext =
    window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const ctx = new Ctx();
  const src = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 2048;
  src.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  const frames: number[] = [];
  const pitches: number[] = [];
  const started = performance.now();

  let resolve!: (f: SpeechResult | null) => void;
  const done = new Promise<SpeechResult | null>((r) => (resolve = r));
  let finished = false;

  const finish = () => {
    if (finished) return;
    finished = true;
    clearInterval(timer);
    stream.getTracks().forEach((t) => t.stop());
    ctx.close().catch(() => undefined);
    resolve(computeSpeech(frames, pitches, (performance.now() - started) / 1000));
  };

  const timer = setInterval(() => {
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    frames.push(rms);
    const f0 = estimatePitch(buf, ctx.sampleRate);
    if (f0 !== null) pitches.push(f0);
    const elapsed = (performance.now() - started) / 1000;
    opts.onLevel(Math.min(1, rms * 8), elapsed);
    if (elapsed >= opts.durationS) finish();
  }, FRAME_MS);

  return { stop: finish, done };
}

function percentile(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0;
  const i = Math.min(sorted.length - 1, Math.max(0, Math.floor(q * (sorted.length - 1))));
  return sorted[i];
}

/** Energy-based voice activity: pause ratio + rough syllable rate from energy peaks + pitch variability. */
export function computeSpeech(frames: number[], pitchesHz: number[], durationS: number): SpeechResult | null {
  if (frames.length < 20 || durationS < 5) return null;
  const sorted = [...frames].sort((a, b) => a - b);
  const floor = percentile(sorted, 0.1);
  const loud = percentile(sorted, 0.9);
  const threshold = Math.max(0.004, floor + 0.25 * (loud - floor));
  const voicedCount = frames.filter((r) => r > threshold).length;
  const pauseRatio = 1 - voicedCount / frames.length;

  const smooth = frames.map((_, i) => {
    const a = frames[Math.max(0, i - 1)];
    const c = frames[Math.min(frames.length - 1, i + 1)];
    return (a + frames[i] + c) / 3;
  });
  let peaks = 0;
  let lastPeak = -10;
  for (let i = 1; i < smooth.length - 1; i++) {
    if (smooth[i] > threshold && smooth[i] >= smooth[i - 1] && smooth[i] > smooth[i + 1] && i - lastPeak >= 3) {
      peaks += 1;
      lastPeak = i;
    }
  }
  const voicedS = (voicedCount * FRAME_MS) / 1000;
  return {
    speech_rate: voicedS >= 1 ? Math.round((peaks / voicedS) * 100) / 100 : null,
    pause_ratio: Math.round(pauseRatio * 1000) / 1000,
    pitch_variability: semitoneSd(pitchesHz),
    duration_s: Math.round(durationS * 10) / 10,
  };
}
