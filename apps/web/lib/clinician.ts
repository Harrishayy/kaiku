/**
 * Pure view-model helpers for the clinician pages (unit-tested). They only rearrange what the cloud decided:
 * the state, verdicts and evidence come from the consensus; numbers come from the timeline series.
 */

import type { Consensus, MetricSeries, SourceVerdict, TimelinePoint } from '../../../contracts/ts/models.ts';

type State = Consensus['state'];
type Agreement = Consensus['agreement'];
type Verdict = SourceVerdict['verdict'];

/** Consensus wording (root AGENTS.md): "Needs a call", "Worth a check-in", "Stable", "Not enough data". */
export function consensusChip(state: State, agreement: Agreement): { label: string; cls: string } {
  if (state === 'safety') return { label: 'Safety: call today', cls: 'safety' };
  if (state === 'needs_call') return { label: 'Needs a call', cls: 'call' };
  if (state === 'watch' && agreement === 'low_coverage') return { label: 'Not enough data', cls: 'ins' };
  if (state === 'watch') return { label: 'Worth a check-in', cls: 'watch' };
  return { label: 'Stable', cls: 'ok' };
}

export function verdictChip(v: Verdict | undefined): { label: string; cls: string } {
  if (v === 'worse') return { label: 'Change from usual', cls: 'watch' };
  if (v === 'better') return { label: 'Better than usual', cls: 'ok' };
  if (v === 'as_usual') return { label: 'As usual', cls: 'ok' };
  return { label: 'Not enough data', cls: 'ins' };
}

export const VERDICT_WORD: Record<Verdict, string> = {
  worse: 'change from usual',
  better: 'better',
  as_usual: 'as usual',
  insufficient: 'not enough data',
};

export function lastValue(points: TimelinePoint[]): TimelinePoint | null {
  for (let i = points.length - 1; i >= 0; i--) if (typeof points[i].value === 'number') return points[i];
  return null;
}

export function num(v: number | null | undefined): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  const s = a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
  return (s.includes('.') ? s.replace(/\.?0+$/, '') : s) || '0'; // 8900 stays 8900; 2.50 → 2.5
}

const UNITLESS = new Set(['', 'count', 'ratio', '0–1', '1–5']);
export function withUnit(v: number | null | undefined, unit: string | undefined): string {
  const n = num(v);
  if (n === '—' || !unit || UNITLESS.has(unit)) return n;
  return `${n} ${unit}`;
}

export interface EvidenceRow {
  metric: string;
  label: string;
  source: string;
  today: string;
  usual: string;
  z: string;
  direction: string;
  /** plain words for |z|: "a little", "clearly", "far" (from the usual day-to-day spread) */
  size: string;
  worse: boolean;
  absZ: number;
}

/** |z| in plain words: how many of the person's usual day-to-day spreads away from their usual. */
export function zWords(z: number | null | undefined): string {
  if (typeof z !== 'number') return '—';
  const a = Math.abs(z);
  return a >= 4 ? 'far from usual' : a >= 2.5 ? 'clearly different' : a >= 1.5 ? 'somewhat different' : 'a little';
}

/** Usual range "(low–high)", never below 0 for a metric that is never negative (minutes, counts, rates). */
export function usualRange(p: TimelinePoint, unit: string | undefined, nonNegative: boolean): string {
  if (typeof p.baseline_median !== 'number') return '—';
  const lo = typeof p.band_low === 'number' && nonNegative ? Math.max(0, p.band_low) : p.band_low;
  return `${withUnit(p.baseline_median, unit)} (${num(lo)}–${num(p.band_high)})`;
}

/** Evidence table: every drifting metric any source reports, joined with its timeline numbers, biggest |z| first. */
export function evidenceRows(c: Consensus, series: MetricSeries[]): EvidenceRow[] {
  const by = new Map(series.map((s) => [s.metric, s]));
  const rows: EvidenceRow[] = [];
  for (const v of c.sources) {
    for (const e of v.evidence ?? []) {
      const s = by.get(e.metric);
      const last = s ? lastValue(s.points) : null;
      const worse = s ? s.worse_when === e.direction : v.verdict === 'worse';
      // a [[rule]] (no series) carries its reading in the summary: "PHQ-9 ≥ 10: 16"
      const [ruleLabel, ruleValue] = (e.summary ?? '').split(/:\s*(.*)/s);
      rows.push({
        metric: e.metric,
        label: s?.label ?? (ruleLabel || e.metric.replace(/_/g, ' ')),
        source: v.source,
        today: last ? withUnit(last.value, s?.unit) : ruleValue || '—',
        usual: last && s ? usualRange(last, s.unit, s.points.every((p) => typeof p.value !== 'number' || p.value >= 0)) : '—',
        z: typeof e.z === 'number' ? `${e.z > 0 ? '+' : e.z < 0 ? '−' : ''}${Math.abs(e.z).toFixed(1)}` : '—',
        direction: `${e.direction === 'up' ? '↑ higher' : '↓ lower'}${e.days ? ` on ${e.days} of the last days` : ''}`,
        size: zWords(e.z),
        worse,
        absZ: typeof e.z === 'number' ? Math.abs(e.z) : 99,
      });
    }
  }
  return rows.sort((a, b) => Number(b.worse) - Number(a.worse) || b.absZ - a.absZ);
}

/** Up to n metric series for a source card: evidence metrics first, then the rest in criteria order. */
export function cardSeries(source: string, v: SourceVerdict | undefined, series: MetricSeries[], n = 3): MetricSeries[] {
  const mine = series.filter((s) => s.source === source && s.points.some((p) => typeof p.value === 'number'));
  const ev = (v?.evidence ?? []).map((e) => e.metric);
  const first = ev.map((m) => mine.find((s) => s.metric === m)).filter((s): s is MetricSeries => Boolean(s));
  const rest = mine.filter((s) => !ev.includes(s.metric));
  return [...first, ...rest].slice(0, n);
}

/** A source with no data at all (e.g. no watch paired) vs one with too little recent data. */
export function sourceMissing(v: SourceVerdict | undefined, series: MetricSeries[], source: string): boolean {
  if (!v) return true;
  if (v.last_data_at) return false;
  return !series.some((s) => s.source === source && s.points.some((p) => typeof p.value === 'number'));
}

/** "2 of 3 sources with data show a change from usual". */
export function consensusSentence(c: Consensus): string {
  const withData = c.sources.filter((s) => s.verdict !== 'insufficient');
  const worse = withData.filter((s) => s.verdict === 'worse').length;
  if (withData.length === 0) return 'No source has enough recent data yet';
  if (worse === 0) return `All ${withData.length} sources with data look as usual or better`;
  return `${worse} of ${withData.length} sources with data show a change from usual`;
}

/** Sparkline geometry over the last `days` points: value line, last-point band, last point. */
export function sparkline(points: TimelinePoint[], w = 72, h = 22, days = 14) {
  const pts = points.slice(-days);
  const vals = pts.map((p) => p.value).filter((v): v is number => typeof v === 'number');
  const last = lastValue(pts);
  if (vals.length < 2 || !last) return null;
  const band: [number, number] | null =
    typeof last.band_low === 'number' && typeof last.band_high === 'number' ? [last.band_low, last.band_high] : null;
  let lo = Math.min(...vals, ...(band ?? []));
  let hi = Math.max(...vals, ...(band ?? []));
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const X = (i: number) => 2 + (i * (w - 6)) / (pts.length - 1);
  const Y = (v: number) => h - 2 - ((v - lo) / (hi - lo)) * (h - 4);
  const line = pts
    .map((p, i) => (typeof p.value === 'number' ? `${X(i).toFixed(1)},${Y(p.value).toFixed(1)}` : null))
    .filter(Boolean)
    .join(' ');
  const li = pts.lastIndexOf(last);
  return {
    line,
    band: band ? { y: Y(band[1]), h: Math.max(1, Y(band[0]) - Y(band[1])) } : null,
    dot: { x: X(li), y: Y(last.value as number) },
    last,
  };
}
