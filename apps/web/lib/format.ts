import { SOURCE_LABELS as CONTRACT_SOURCE_LABELS } from '@contracts';
import { label } from './labels';

/** Consensus states (handoff §6.4). Wording per §12: never diagnostic. */
export type State = 'stable' | 'watch' | 'needs_call' | 'safety';
export type Verdict = 'better' | 'as_usual' | 'worse' | 'insufficient';

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

/** Display names for consensus sources. Unknown (future) sources fall back to a prettified id. */
const SOURCE_LABELS: Record<string, string> = CONTRACT_SOURCE_LABELS;
export const sourceLabel = (s: string) => SOURCE_LABELS[s] ?? prettify(s);

export const ACTION_LABEL: Record<string, string> = {
  flag_booster: 'Flag for booster TMS',
  flag_icbt_referral: 'Flag for iCBT referral (Mielenterveystalo)',
  acknowledge: 'Acknowledge',
  send_message: 'Send a message',
  check_in_call: 'Check-in call',
  none: 'No action needed',
};

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
