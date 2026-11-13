/**
 * Pure helpers for the mascot renderer (unit-tested). The spec itself is design/mascot.spec.json; this file only
 * interprets it: part tree walking, CSS values for spec props, glow by hour, ambient mood → state.
 */

export type Vec = [number, number];
export type PropName = 'translate' | 'rotate' | 'scale' | 'opacity';
export type PropValue = number | Vec;
export type Pose = Record<string, Partial<Record<PropName, PropValue>>>;

export interface Shape {
  type: 'path' | 'ellipse' | 'circle';
  d?: string;
  cx?: number;
  cy?: number;
  rx?: number;
  ry?: number;
  r?: number;
  fill?: string;
  stroke?: string;
  'stroke-width'?: number;
  'stroke-linecap'?: string;
  'stroke-linejoin'?: string;
  opacity?: number;
  gradient?: string;
}
export interface Part {
  id: string;
  pivot: Vec;
  shapes?: Shape[];
  children?: Part[];
  clip?: string;
  default?: { opacity?: number };
}
export interface Track {
  part: string;
  prop: PropName;
  easing: string;
  keys: [number, PropValue][];
}
export interface StateSpec {
  duration: number;
  loop: boolean;
  blink: 'normal' | 'slow' | 'none';
  pose: Pose;
  tracks: Track[];
  composes?: boolean;
  events?: Record<string, { interval: Vec; duration: number; tracks: Track[] }>;
}
export interface BlinkMode {
  duration: number;
  interval: Vec;
  double_chance?: number;
  double_gap?: number;
}
export interface MascotSpec {
  viewBox: number[];
  clips: Record<string, { cx: number; cy: number; rx: number; ry: number }>;
  parts: Part[];
  blink: { parts: string[]; closed: Vec; easing: string; modes: Record<string, BlinkMode | null> };
  states: Record<string, StateSpec>;
  interactions: {
    tap: { duration: number; part: string; easing: string; keys: [number, number][] };
  };
  ambient_mood: Record<string, string | null>;
}

export const MASCOT_STATES = [
  'idle', 'listening', 'thinking', 'happy', 'cheering', 'breathing', 'sleepy', 'walking', 'cozy', 'speaking', 'peek',
] as const;
export type MascotState = (typeof MASCOT_STATES)[number];

export function cssValue(prop: PropName, v: PropValue): string {
  if (prop === 'translate') return `${(v as Vec)[0]}px ${(v as Vec)[1]}px`;
  if (prop === 'rotate') return `${v}deg`;
  if (prop === 'scale') return Array.isArray(v) ? `${v[0]} ${v[1]}` : `${v}`;
  return `${v}`;
}

export function walkParts(parts: Part[], fn: (p: Part) => void): void {
  for (const p of parts) {
    fn(p);
    if (p.children) walkParts(p.children, fn);
  }
}

/** Paint reference → CSS (token name → var(--k-…); 'glow' radial → the per-instance gradient). */
export function paint(ref: string, s: Shape, uid: string): string {
  if (ref === 'none') return 'none';
  if (ref === 'glow') return s.gradient === 'radial' ? `url(#${uid}-g)` : 'var(--k-glow)';
  return `var(--k-${ref})`;
}

/**
 * GET /v1/me mascot.mood → state via mascot.spec.json ambient_mood. `crisis` (safety) → null: no mascot,
 * the crisis screen replaces everything. `happy` is the "stable + did something together" mood.
 */
export function ambientState(spec: Pick<MascotSpec, 'ambient_mood'>, mood: string | null | undefined): MascotState | null {
  if (mood === 'crisis' || mood === 'safety') return null;
  if (mood === 'happy') return (spec.ambient_mood.stable_after_interaction as MascotState) ?? 'happy';
  if (mood === 'cozy') return (spec.ambient_mood.watch as MascotState) ?? 'cozy';
  return (spec.ambient_mood.stable as MascotState) ?? 'idle';
}

export interface GlowStop {
  hour: number;
  color: string;
  intensity: number;
}
const hex2rgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const rgb2hex = (c: number[]) => '#' + c.map((x) => Math.round(x).toString(16).padStart(2, '0')).join('');

/** Chest glow colour + intensity at a local hour (linear between tokens.json glow.stops, wraps at 24). */
export function glowAt(stops: GlowStop[], hour: number): { color: string; intensity: number } {
  let i = stops.length - 1;
  for (let k = 0; k < stops.length; k++) if (stops[k].hour <= hour) i = k;
  const a = stops[i];
  const b = i + 1 < stops.length ? stops[i + 1] : { ...stops[0], hour: stops[0].hour + 24 };
  const f = b.hour === a.hour ? 0 : (hour - a.hour) / (b.hour - a.hour);
  const ca = hex2rgb(a.color);
  const cb = hex2rgb(b.color);
  return { color: rgb2hex(ca.map((x, j) => x + (cb[j] - x) * f)), intensity: a.intensity + (b.intensity - a.intensity) * f };
}
