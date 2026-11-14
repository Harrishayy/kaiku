import { SOURCE_LABELS as CONTRACT_SOURCE_LABELS, type Envelope } from '@contracts';
import { label } from './labels';

/** Consensus states (handoff §6.4). Wording per §12: never diagnostic. */
export type State = 'stable' | 'watch' | 'needs_call' | 'safety';
export type Verdict = 'better' | 'as_usual' | 'worse' | 'insufficient';
export type Agreement = 'agree' | 'disagree' | 'low_coverage';

export const STATE_LABEL: Record<State, string> = {
  safety: label('state.safety'),
  needs_call: label('state.needs_call'),
  watch: label('state.watch'),
  stable: label('state.stable'),
};

export const STATE_HINT: Record<State, string> = {
  safety: 'A safety flag is recorded. Prioritise review and direct contact.',
  needs_call: 'Multiple signal groups show a change from this person’s usual.',
  watch: 'Check recent coverage and the person’s usual before interpreting changes.',
  stable: 'Sources with enough data look as usual or better.',
};

/** Ranking for "who needs a call": safety first. Mirrors kaiku_contracts.api.STATE_RANK. */
export const STATE_RANK: Record<State, number> = { safety: 0, needs_call: 1, watch: 2, stable: 3 };

export const VERDICT_LABEL: Record<Verdict, string> = {
  worse: label('verdict.worse'),
  as_usual: label('verdict.as_usual'),
  better: label('verdict.better'),
  insufficient: label('verdict.insufficient'),
};

export const AGREEMENT_LABEL: Record<Agreement, string> = {
  agree: 'Sources agree',
  disagree: 'Sources disagree',
  low_coverage: 'Low coverage',
};

/** Display names for consensus sources. Unknown (future) sources fall back to a prettified id. */
const SOURCE_LABELS: Record<string, string> = CONTRACT_SOURCE_LABELS;
const SOURCE_BLURB: Record<string, string> = {
  robot: 'Check-in ratings, knock timing and first interaction',
  glasses: 'Recorded outings: duration and phone steps',
  laptop: 'Native games, Mac activity rhythm and PHQ-9',
  wearable: 'Watch: sleep, resting heart rate, HRV, steps',
};
export const sourceLabel = (s: string) => SOURCE_LABELS[s] ?? prettify(s);
export const sourceBlurb = (s: string) => SOURCE_BLURB[s] ?? '';

export const ACTION_LABEL: Record<string, string> = {
  flag_booster: 'Flag for booster TMS',
  flag_icbt_referral: 'Flag for iCBT referral (Mielenterveystalo)',
  acknowledge: 'Acknowledge',
  send_message: 'Send a message',
  check_in_call: 'Check-in call',
  none: 'No action needed',
};

const ACTIVITY_LABEL: Record<string, string> = {
  breathe: 'Paced breathing',
  drum: 'Drumming',
  walk: 'Walk',
  daylight_walk: 'Daylight walk',
  friend_ping: 'Friend ping',
  icbt: 'iCBT exercise',
  icbt_exercise: 'iCBT exercise',
};
export const activityLabel = (a: string) => ACTIVITY_LABEL[a] ?? prettify(a);

export function prettify(name: string): string {
  return name.replace(/[._]/g, ' ').replace(/\s+/g, ' ').trim().replace(/^\w/, (c) => c.toUpperCase());
}

export function sortByState<T extends { state: State; display_name: string }>(list: T[]): T[] {
  return [...list].sort((a, b) => STATE_RANK[a.state] - STATE_RANK[b.state] || a.display_name.localeCompare(b.display_name));
}

export function relTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return 'not recorded';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 'date unavailable';
  const s = Math.round((now - t) / 1000);
  if (s < 0) return 'just now';
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

export function clockTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return 'not recorded';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function fmt(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return n.toFixed(digits);
}

export function pct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return `${Math.round(n * 100)}%`;
}

/** One human sentence for an observation (used on /live). Neutral, non-diagnostic wording. */
export function describe(env: Envelope<Record<string, unknown>>): { title: string; detail: string } {
  const p = env.payload ?? {};
  const n = (k: string, d = 0, obj: Record<string, unknown> = p) => fmt(typeof obj[k] === 'number' ? (obj[k] as number) : null, d);
  switch (env.type) {
    case 'obs.presence':
      return {
        title: p.first_of_day ? 'First interaction of the day' : 'Someone is near Kaiku',
        detail: `${n('distance_cm')} cm away · stayed ${n('dwell_s')} s`,
      };
    case 'obs.self_report':
      return {
        title: `${prettify(String(p.item ?? 'dial'))} dial turned to ${n('value')} / 5`,
        detail: `context: ${String(p.context ?? 'ritual').replace('_', ' ')}`,
      };
    case 'obs.hrv_session':
      return {
        title: 'Breathing together finished',
        detail: `HR ${n('hr_bpm')} bpm · HRV ${n('rmssd_pre_ms')} → ${n('rmssd_post_ms')} ms · ${n('breath_bpm')} breaths/min`,
      };
    case 'obs.drum_session':
      return {
        title: 'Drummed on Kaiku’s head',
        detail: `${n('taps')} taps · ${n('tempo_bpm')} bpm · regularity ${n('regularity', 2)}` + (typeof p.force_mean === 'number' ? ` · recorded force ${n('force_mean', 2)}` : ''),
      };
    case 'obs.light_level':
      return { title: 'Room light', detail: `≈${n('lux_est')} lux over ${n('window_min')} min` };
    case 'obs.speech_features':
      return { title: 'Speech features (no audio kept)', detail: `pauses ${pct(p.pause_ratio as number)}` };
    case 'obs.ritual':
      return { title: `Ritual · ${String(p.step)} ${String(p.status)}`, detail: p.duration_s ? `${n('duration_s')} s` : '' };
    case 'obs.nudge_offered':
      return { title: `Suggested: ${activityLabel(String(p.arm))}`, detail: String(p.reason ?? '') };
    case 'obs.nudge_outcome': {
      const nd = (p.next_day ?? {}) as Record<string, unknown>;
      return {
        title: `Suggestion ${p.accepted ? 'taken up' : 'passed on'}: ${activityLabel(String(p.arm))}`,
        detail: typeof nd.mood === 'number' ? `next-day mood ${n('mood', 0, nd)}` : '',
      };
    }
    case 'obs.outing':
      return {
        title: 'Recorded outing',
        detail:
          `${n('minutes')} min` +
          (typeof p.steps === 'number' ? ` · ${n('steps')} steps` : '') +
          (typeof p.daylight_min === 'number' ? ` · ${n('daylight_min')} min daylight` : '') +
          ` · via ${String(p.method)}`,
      };
    case 'obs.friend_link':
      return { title: `Friend lamp ${String(p.direction)}`, detail: p.ack ? 'acknowledged' : 'waiting for ack' };
    case 'obs.laptop_session':
      return {
        title: 'Laptop session completed (nothing recorded)',
        detail:
          `${n('duration_s')} s` +
          (typeof p.reaction_ms_median === 'number' ? ` · reaction ${n('reaction_ms_median')} ms` : '') +
          (typeof p.pause_ratio === 'number' ? ` · pauses ${pct(p.pause_ratio as number)}` : ''),
      };
    case 'obs.phq9':
      return { title: 'PHQ-9 completed', detail: `total ${n('total')} / 27 · ${String(p.mode)}` };
    case 'obs.intervention_response':
      return { title: `${activityLabel(String(p.activity))} — before vs after`, detail: describeDelta(p.delta) };
    case 'obs.safety_flag':
      return {
        title: 'Safety flag raised',
        detail: `trigger: ${String(p.trigger)} · ${p.handled_locally ? 'crisis script shown locally' : 'not handled locally'}`,
      };
    default:
      return { title: env.type, detail: JSON.stringify(p).slice(0, 120) };
  }
}

function describeDelta(delta: unknown): string {
  if (!delta || typeof delta !== 'object') return '';
  return Object.entries(delta as Record<string, unknown>)
    .filter(([, v]) => typeof v === 'number')
    .map(([k, v]) => `${prettify(k)} ${(v as number) > 0 ? '+' : ''}${fmt(v as number, 1)}`)
    .join(' · ');
}
