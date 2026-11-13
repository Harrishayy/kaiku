/**
 * Pure feature math for the laptop session (unit-tested, no browser APIs).
 * Everything here runs on numbers already computed in memory; nothing is recorded.
 */

export function quantile(values: number[], q: number): number | null {
  if (values.length === 0) return null;
  const s = [...values].sort((a, b) => a - b);
  const pos = (s.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}

export function round(n: number | null, digits = 2): number | null {
  if (n === null || !Number.isFinite(n)) return null;
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}

// ----------------------------------------------------------------- reaction task (go / no-go)
export interface Trial {
  kind: 'go' | 'nogo';
  /** ms from stimulus to response; null = no response */
  rt: number | null;
}

export const LAPSE_MS = 500;
const ANTICIPATION_MS = 100;

/**
 * median and IQR over valid go responses (100 ms < rt); lapses = go trials missed or slower than 500 ms.
 * No-go false alarms are reported separately (not part of the contract).
 */
export function reactionStats(trials: Trial[]): {
  reaction_ms_median: number | null;
  reaction_ms_iqr: number | null;
  lapses: number;
  false_alarms: number;
  go_trials: number;
} {
  const go = trials.filter((t) => t.kind === 'go');
  const valid = go.map((t) => t.rt).filter((rt): rt is number => rt !== null && rt > ANTICIPATION_MS);
  const lapses = go.filter((t) => t.rt === null || t.rt > LAPSE_MS).length;
  const falseAlarms = trials.filter((t) => t.kind === 'nogo' && t.rt !== null).length;
  const q1 = quantile(valid, 0.25);
  const q3 = quantile(valid, 0.75);
  return {
    reaction_ms_median: round(quantile(valid, 0.5), 0),
    reaction_ms_iqr: q1 === null || q3 === null ? null : round(q3 - q1, 0),
    lapses,
    false_alarms: falseAlarms,
    go_trials: go.length,
  };
}

/** Random go/no-go schedule: ~20% no-go, never two no-go in a row, ISI 1.2–2.8 s. */
export function makeSchedule(n: number, rand: () => number = Math.random): { kind: Trial['kind']; isiMs: number }[] {
  const out: { kind: Trial['kind']; isiMs: number }[] = [];
  for (let i = 0; i < n; i++) {
    const prevNogo = out[i - 1]?.kind === 'nogo';
    const kind: Trial['kind'] = i > 1 && !prevNogo && rand() < 0.2 ? 'nogo' : 'go';
    out.push({ kind, isiMs: Math.round(1200 + rand() * 1600) });
  }
  return out;
}

// ----------------------------------------------------------------- facial expressivity
/**
 * Expressivity index 0..1 from per-frame blendshape scores (frames × blendshapes).
 * = mean over blendshapes of the score's standard deviation across frames, scaled ×4 and clipped.
 * Captures how much the face moves while talking — a rough, research-style proxy, not an emotion reading.
 */
export function expressivityIndex(frames: number[][]): number | null {
  if (frames.length < 10) return null;
  const k = frames[0].length;
  if (k === 0) return null;
  let sdSum = 0;
  for (let j = 0; j < k; j++) {
    let mean = 0;
    for (const f of frames) mean += f[j] ?? 0;
    mean /= frames.length;
    let v = 0;
    for (const f of frames) v += ((f[j] ?? 0) - mean) ** 2;
    sdSum += Math.sqrt(v / frames.length);
  }
  return round(Math.min(1, Math.max(0, (sdSum / k) * 4)), 3);
}

/** Blendshape names used for expressivity (MediaPipe FaceLandmarker categories). */
export const EXPRESSION_BLENDSHAPES = [
  'browDownLeft', 'browDownRight', 'browInnerUp', 'browOuterUpLeft', 'browOuterUpRight',
  'cheekSquintLeft', 'cheekSquintRight', 'eyeSquintLeft', 'eyeSquintRight', 'eyeWideLeft', 'eyeWideRight',
  'jawOpen', 'mouthFrownLeft', 'mouthFrownRight', 'mouthSmileLeft', 'mouthSmileRight',
  'mouthPressLeft', 'mouthPressRight', 'mouthStretchLeft', 'mouthStretchRight', 'noseSneerLeft', 'noseSneerRight',
];

// ----------------------------------------------------------------- voice pitch
/**
 * Autocorrelation pitch estimate for one frame of samples. Returns Hz in [70, 400] or null when the
 * frame is unvoiced / too quiet / not periodic enough.
 */
export function estimatePitch(buf: Float32Array | number[], sampleRate: number): number | null {
  const n = buf.length;
  let energy = 0;
  for (let i = 0; i < n; i++) energy += buf[i] * buf[i];
  if (Math.sqrt(energy / n) < 0.01) return null;
  const minLag = Math.floor(sampleRate / 400);
  const maxLag = Math.min(n - 1, Math.ceil(sampleRate / 70));
  let best = -1;
  let bestLag = -1;
  for (let lag = minLag; lag <= maxLag; lag++) {
    let c = 0;
    for (let i = 0; i < n - lag; i++) c += buf[i] * buf[i + lag];
    c /= n - lag;
    if (c > best) {
      best = c;
      bestLag = lag;
    }
  }
  const norm = energy / n;
  if (bestLag < 0 || best / norm < 0.3) return null;
  return sampleRate / bestLag;
}

/** Pitch variability = SD of pitch in semitones around the median (robust to voice range). */
export function semitoneSd(pitchesHz: number[]): number | null {
  if (pitchesHz.length < 10) return null;
  const med = quantile(pitchesHz, 0.5) as number;
  const st = pitchesHz.map((f) => 12 * Math.log2(f / med));
  const mean = st.reduce((a, b) => a + b, 0) / st.length;
  const sd = Math.sqrt(st.reduce((a, b) => a + (b - mean) ** 2, 0) / st.length);
  return round(sd, 2);
}
