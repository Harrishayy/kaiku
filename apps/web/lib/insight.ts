/**
 * Pure view-model helpers for the practitioner dashboard (unit-tested). Two jobs:
 *  1. give every number its meaning against the person's own usual ("42 min later than their usual 23:10");
 *  2. when the cloud has no `GET /v1/patients/{id}/insight` yet, derive the same shapes from the older
 *     endpoints (consensus, timeline, week, graph, events) so every panel renders one contract shape.
 * Nothing here decides a state: state and verdicts always come from the consensus.
 */

import type {
  Consensus,
  DataCoverage,
  GroupComparison,
  InsightGraph,
  KnowledgeGraph,
  LearnedRoutine,
  MetricComparison,
  MetricSeries,
  ObsTypeCoverage,
  PatientInsight,
  PatientReview,
  PeriodComparison,
  RecordCitation,
  ReviewFinding,
  TimelinePoint,
  WeekSummary,
} from '../../../contracts/ts/models.ts';
import { clockMinutes, durationMinutes, num, withUnit } from './clinician.ts';

/**
 * The cloud serialises every field (pydantic defaults included), but the generated types mark defaulted fields
 * optional. `Deep<T>` is the as-served shape: same contract types, defaults present.
 */
export type Deep<T> = T extends (infer U)[] ? Deep<U>[] : T extends object ? { [K in keyof T]-?: Deep<T[K]> } : T;

export type Tone = 'better' | 'worse' | 'similar' | 'unknown';
type Src = MetricSeries['source'];

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/*
 * The browser fallback's own constants. They are used only when `GET /v1/patients/{id}/insight` is unavailable and
 * the shapes are derived here (the result is labelled `by: 'template'`); no endpoint serves them. They word a
 * comparison and a certainty label and never decide a state. The cloud's own review uses its config instead.
 */
/** this week counts as "similar" to the week before within half of the usual band's half-width ... */
const FALLBACK_TOLERANCE_BAND_SHARE = 0.5;
/** ... or, with no band yet, within 5 % of the usual value */
const FALLBACK_TOLERANCE_OF_USUAL = 0.05;
/** "what helps": fewer tries than this reads "early" ... */
const FALLBACK_HELP_EARLY_TRIES = 5;
/** ... and fewer than this reads "building"; from here on "consistent" */
const FALLBACK_HELP_BUILDING_TRIES = 12;
const isClock = (unit: string | undefined) => Boolean(unit && unit.includes('midnight'));

/** Value with its unit in reading form: clock times, durations, percentages, "4 of 5". */
export function valueText(v: number | null | undefined, unit: string | undefined): string {
  if (!isNum(v)) return 'Not recorded';
  if (unit === '1–5' || unit === '1-5') return `${num(v)} out of 5`;
  return withUnit(v, unit);
}

function amountText(diff: number, unit: string | undefined): string {
  const a = Math.abs(diff);
  if (isClock(unit) || unit === 'min') return durationMinutes(a);
  if (unit === 's') return a >= 60 ? durationMinutes(a / 60) : `${Math.round(a)} sec`;
  if (unit === '1–5' || unit === '1-5') return `${num(a)} ${a === 1 ? 'point' : 'points'}`;
  if (unit === 'ratio') return `${Math.round(a * 100)} ${Math.round(a * 100) === 1 ? 'point' : 'points'}`;
  return withUnit(a, unit);
}

function directionWord(up: boolean, unit: string | undefined): string {
  if (isClock(unit)) return up ? 'later' : 'earlier';
  if (unit === 'min' || unit === 's') return up ? 'longer' : 'shorter';
  if (unit === 'steps' || unit === 'count') return up ? 'more' : 'fewer';
  return up ? 'higher' : 'lower';
}

export interface Meaning {
  /** "42 min later than their usual 23:10" */
  text: string;
  /** where it sits against the usual range, in plain words */
  range: string;
  tone: Tone;
}

/** One number against the person's own usual. Tone uses the usual range when there is one. */
export function meaningOf(
  value: number | null | undefined,
  usual: number | null | undefined,
  unit: string | undefined,
  worseWhen: 'up' | 'down',
  bandLow?: number | null,
  bandHigh?: number | null,
): Meaning {
  if (!isNum(value)) return { text: 'Not recorded', range: 'No reading', tone: 'unknown' };
  if (!isNum(usual)) return { text: 'Still building their usual', range: 'No usual to compare with yet', tone: 'unknown' };
  const diff = value - usual;
  const usualStr = isClock(unit) ? clockMinutes(usual) : valueText(usual, unit);
  const same = amountText(diff, unit) === amountText(0, unit);
  const text = same
    ? `Same as their usual ${usualStr}`
    : `${amountText(diff, unit)} ${directionWord(diff > 0, unit)} than their usual ${usualStr}`;
  const hasBand = isNum(bandLow) && isNum(bandHigh);
  const inside = hasBand ? value >= (bandLow as number) && value <= (bandHigh as number) : same;
  if (inside) return { text, range: 'Within their usual range', tone: 'similar' };
  const worse = (diff > 0 ? 'up' : 'down') === worseWhen;
  return {
    text,
    range: worse ? 'Outside their usual range: a change from their usual' : 'Outside their usual range, on the better side',
    tone: hasBand ? (worse ? 'worse' : 'better') : 'unknown',
  };
}

export const pointMeaning = (s: Pick<MetricSeries, 'unit' | 'worse_when'>, p: TimelinePoint): Meaning =>
  meaningOf(p.value, p.baseline_median, s.unit, s.worse_when, p.band_low, p.band_high);

export interface DaySignal {
  date: string;
  /** measures with a reading that day */
  measured: number;
  /** of those, how many had a usual range to compare with */
  compared: number;
  /** outside the usual range on the change side / on the better side */
  changed: number;
  better: number;
  changedLabels: string[];
}

/**
 * Per day: how many measures sat outside the person's usual. Descriptive only; the state comes from the consensus.
 * A measure that is shown and not scored (`scored: false`: camera face signs, more of the day from Apple Health)
 * is charted but left out of these counts, so a day's count speaks of the measures the rule reads.
 */
export function daySignals(series: MetricSeries[]): DaySignal[] {
  const days = new Map<string, DaySignal>();
  for (const s of series) {
    if (s.scored === false) continue;
    for (const p of s.points) {
      const d = days.get(p.date) ?? { date: p.date, measured: 0, compared: 0, changed: 0, better: 0, changedLabels: [] };
      days.set(p.date, d);
      if (!isNum(p.value)) continue;
      d.measured += 1;
      if (!isNum(p.band_low) || !isNum(p.band_high)) continue;
      d.compared += 1;
      const tone = pointMeaning(s, p).tone;
      if (tone === 'worse') {
        d.changed += 1;
        d.changedLabels.push(s.label);
      } else if (tone === 'better') d.better += 1;
    }
  }
  return [...days.values()].sort((a, b) => a.date.localeCompare(b.date));
}

export interface RecordStage {
  /** day number of the record (first recorded day = 1) */
  day: number;
  /** scored against a provisional baseline: lower confidence */
  early: boolean;
  /** no measure has a usual yet */
  building: boolean;
  /** days needed before the rule allows a steady reading, when the server shares it */
  steadyAfter: number | null;
}

/** Where the record is in its calibration, read from the timeline alone (used when the cloud sends no insight). */
export function recordStage(series: MetricSeries[]): RecordStage {
  const rec = recordedDays(series);
  const building = !series.some((s) => s.points.some((p) => isNum(p.baseline_median)));
  const flagged = series.some((s) => s.points.some((p) => p.early));
  return { day: rec.span, building, early: building || flagged, steadyAfter: null };
}

export const TONE_WORD: Record<Tone, string> = {
  better: 'Better',
  worse: 'Change from usual',
  similar: 'As usual',
  unknown: 'Not enough data',
};

/** Days that have at least one reading, and the first / last of them. */
export function recordedDays(series: MetricSeries[]): { days: number; first: string | null; last: string | null; span: number } {
  const dates = new Set<string>();
  for (const s of series) for (const p of s.points) if (isNum(p.value)) dates.add(p.date);
  const sorted = [...dates].sort();
  const first = sorted[0] ?? null;
  const last = sorted.at(-1) ?? null;
  const span = first && last ? Math.round((Date.parse(last) - Date.parse(first)) / 86_400_000) + 1 : 0;
  return { days: sorted.length, first, last, span };
}

/** Drop the leading empty days so a 16-day record is not drawn as a 30-day chart with half of it blank. */
export function trimLeading(series: MetricSeries[]): MetricSeries[] {
  const { first } = recordedDays(series);
  if (!first) return series;
  return series.map((s) => ({ ...s, points: s.points.filter((p) => p.date >= first) }));
}

const median = (values: number[]): number | null => {
  const s = [...values].sort((a, b) => a - b);
  const n = s.length;
  return n ? (n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2) : null;
};

const addDays = (iso: string, n: number) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);

function trend(a: number | null, b: number | null, worseWhen: 'up' | 'down', tolerance: number): Tone {
  if (!isNum(a) || !isNum(b)) return 'unknown';
  const d = a - b;
  if (Math.abs(d) <= tolerance) return 'similar';
  return (d > 0 ? 'up' : 'down') === worseWhen ? 'worse' : 'better';
}

/** This week vs the week before vs usual for one series; weeks are calendar days ending on `end`. */
export function compareSeries(s: MetricSeries, end: string, sustained: MetricComparison['sustained']): Deep<MetricComparison> {
  const early = s.points.some((p) => p.early);
  const inRange = (lo: string, hi: string) =>
    s.points.filter((p) => p.date >= lo && p.date <= hi && isNum(p.value)).map((p) => p.value as number);
  const thisVals = inRange(addDays(end, -6), end);
  const prevVals = inRange(addDays(end, -13), addDays(end, -7));
  const last = [...s.points].reverse().find((p) => isNum(p.baseline_median)) ?? null;
  const usual = last?.baseline_median ?? null;
  const half = last && isNum(last.band_low) && isNum(last.band_high) ? (last.band_high - last.band_low) / 2 : null;
  const thisWeek = median(thisVals);
  const previous = median(prevVals);
  const tolerance = half !== null ? half * FALLBACK_TOLERANCE_BAND_SHARE : Math.abs(usual ?? previous ?? 0) * FALLBACK_TOLERANCE_OF_USUAL;
  const vsUsual: Tone =
    isNum(thisWeek) && last && isNum(last.band_low) && isNum(last.band_high)
      ? thisWeek >= last.band_low && thisWeek <= last.band_high
        ? 'similar'
        : trend(thisWeek, usual, s.worse_when, 0)
      : trend(thisWeek, usual, s.worse_when, tolerance);
  return {
    metric: s.metric,
    label: s.label,
    unit: s.unit ?? '',
    source: s.source,
    worse_when: s.worse_when,
    this_week: thisWeek,
    previous_week: previous,
    usual,
    this_week_text: isNum(thisWeek) ? valueText(thisWeek, s.unit) : null,
    previous_week_text: isNum(previous) ? valueText(previous, s.unit) : null,
    usual_text: isNum(usual) ? valueText(usual, s.unit) : null,
    days_this_week: thisVals.length,
    days_previous_week: prevVals.length,
    vs_previous: trend(thisWeek, previous, s.worse_when, tolerance),
    vs_usual: vsUsual,
    sustained,
    early_baseline: early,
    baseline_days: null,
    meaning: meaningOf(thisWeek, usual, s.unit, s.worse_when, last?.band_low, last?.band_high).text,
  };
}

function groupTrend(metrics: Deep<MetricComparison>[]): Tone {
  const known = metrics.map((m) => m.vs_previous).filter((t) => t !== 'unknown');
  if (!known.length) return 'unknown';
  const worse = known.filter((t) => t === 'worse').length;
  const better = known.filter((t) => t === 'better').length;
  return worse > better ? 'worse' : better > worse ? 'better' : 'similar';
}

export function deriveComparison(c: Consensus, series: MetricSeries[], labelOf: (s: string) => string, stage: RecordStage): Deep<PeriodComparison> | null {
  const { last } = recordedDays(series);
  if (!last) return null;
  const groups: Deep<GroupComparison>[] = c.sources.map((v) => {
    const ev = new Map((v.evidence ?? []).map((e) => [e.metric, e]));
    const metrics = series
      .filter((s) => s.source === v.source && s.points.some((p) => isNum(p.value)))
      .map((s) => {
        const e = ev.get(s.metric);
        const sustained: MetricComparison['sustained'] = e
          ? e.direction === s.worse_when
            ? 'change_from_usual'
            : 'better_than_usual'
          : v.verdict === 'insufficient'
            ? 'not_enough_data'
            : 'as_usual';
        return compareSeries(s, last, sustained);
      });
    const t = groupTrend(metrics);
    return {
      source: v.source,
      label: labelOf(v.source),
      verdict: v.verdict,
      confidence: v.confidence,
      days_this_week: Math.max(0, ...metrics.map((m) => m.days_this_week)),
      days_previous_week: Math.max(0, ...metrics.map((m) => m.days_previous_week)),
      trend: t,
      meaning:
        t === 'unknown'
          ? 'Too few recorded days to compare the two weeks.'
          : t === 'similar'
            ? 'About the same as the week before.'
            : t === 'better'
              ? 'More measures moved to the better side than the other way since the week before.'
              : 'More measures moved away from their usual than toward it since the week before.',
      metrics,
    };
  });
  const all = groups.flatMap((g) => g.metrics);
  const improved = all.filter((m) => m.vs_previous === 'better').map((m) => m.metric);
  const changed = all.filter((m) => m.vs_previous === 'worse').map((m) => m.metric);
  return {
    this_week_start: addDays(last, -6),
    this_week_end: last,
    previous_week_start: addDays(last, -13),
    previous_week_end: addDays(last, -7),
    summary: `${improved.length} ${improved.length === 1 ? 'measure is' : 'measures are'} better than the week before and ${changed.length} moved the other way, out of ${all.length} with readings.`,
    improved,
    changed,
    groups,
    day_of_record: stage.day,
    early_baseline: stage.early,
    since_low: '',
    back_in_range: [],
    still_away: [],
  };
}

export function deriveRoutine(week: WeekSummary | null, graph: KnowledgeGraph | null, stage: RecordStage): Deep<LearnedRoutine> {
  const routines = (week?.routines ?? []) as Deep<WeekSummary['routines']>;
  const count = (s: string) => routines.filter((r) => r.status === s).length;
  const byId = new Map((graph?.nodes ?? []).map((n) => [n.id, n]));
  const helps = (graph?.edges ?? [])
    .filter((e) => e.rel === 'helped' && byId.has(e.dst))
    .map((e) => {
      const label = byId.get(e.dst)!.label;
      const certainty = e.evidence < FALLBACK_HELP_EARLY_TRIES ? ('early' as const) : e.evidence < FALLBACK_HELP_BUILDING_TRIES ? ('building' as const) : ('consistent' as const);
      return {
        activity: label,
        label: label.replace(/^\w/, (ch) => ch.toUpperCase()),
        tries: e.evidence,
        mean_effect: Math.max(0, Math.min(1, e.weight)),
        low: null,
        high: null,
        certainty,
        text: `Reported response after ${e.evidence} ${e.evidence === 1 ? 'try' : 'tries'}. A response, not proof that it caused the change.`,
      };
    });
  return {
    routines,
    helps,
    kept: count('kept'),
    partly: count('partly'),
    slipped: count('slipped'),
    summary: routines.length
      ? `${count('kept')} of ${routines.length} usual routines kept this week${count('slipped') ? `, ${count('slipped')} slipped` : ''}.`
      : 'No routine has been seen often enough yet.',
    day_of_record: stage.day,
    early_record: stage.early,
    caveat: stage.early
      ? `Day ${stage.day} of the record. On a short record these responses are early preferences only, not proof that an activity helps.`
      : 'Responses are what the person reported around an activity, not proof that it helped.',
  };
}

const REL_LABEL: Record<string, string> = { did: 'did', keeps: 'keeps', of: 'routine of', helped: 'helped' };

/** Care-team view of the older knowledge graph: activities, routines and what helped only. */
export function deriveGraph(graph: KnowledgeGraph | null): Deep<InsightGraph> {
  if (!graph) return { nodes: [], edges: [], shared: false, basis: [], note: '', layers: [], domains: [], days: [] };
  const kind = (t: string) => (t === 'me' ? 'person' : t === 'routine' ? 'routine' : t === 'activity' || t === 'helper' ? 'activity' : null);
  const nodes = graph.nodes.flatMap((n) => {
    const k = kind(n.type);
    if (!k) return [];
    const routineName = k === 'routine' && n.detail?.includes(':') ? n.detail.split(':')[0] : null;
    return [{
      id: String(n.id),
      kind: k as 'person' | 'routine' | 'activity',
      label: routineName ? `${routineName} · ${n.label}` : n.label,
      detail: n.detail ?? null,
      evidence: n.evidence,
      tone: 'unknown' as const,
      layer: 'learned' as const,
      domain: '',
      days: [],
    }];
  });
  const ids = new Set(nodes.map((n) => n.id));
  const edges = graph.edges
    .filter((e) => e.rel in REL_LABEL && ids.has(String(e.src)) && ids.has(String(e.dst)))
    .map((e) => ({
      src: String(e.src),
      dst: String(e.dst),
      rel: e.rel as 'did' | 'keeps' | 'of' | 'helped',
      label: REL_LABEL[e.rel],
      weight: Math.max(0, Math.min(1, e.weight)),
      evidence: e.evidence,
      layer: 'learned' as const,
      on: [],
      tag: '',
    }));
  return {
    nodes,
    edges,
    layers: ['learned' as const],
    domains: [],
    days: [],
    shared: graph.shared,
    basis: graph.shared ? ['observations', 'shared_conversations'] : ['observations'],
    note: graph.shared
      ? 'Activities, routines and what helped. People, places and private notes are never shown here.'
      : 'Built from observations only: the person has not shared what Kaiku learned in conversations.',
  };
}

export interface ObsEvent {
  id: string;
  ts: string;
  source: string;
  type: string;
  payload: Record<string, unknown>;
  sim?: boolean;
}

const localDay = (ts: string) => {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.slice(0, 10);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export const OBS_LABEL: Record<string, string> = {
  'obs.self_report': 'Check-in ratings',
  'obs.ritual': 'Morning ritual steps',
  'obs.presence': 'First interaction',
  'obs.drum_session': 'Drum sessions',
  'obs.hrv_session': 'Breathing sessions',
  'obs.speech_features': 'Speech features',
  'obs.light_level': 'Room light',
  'obs.outing': 'Walks and outings',
  'obs.play_session': 'Games and tasks',
  'obs.laptop_session': 'Laptop sessions',
  'obs.screen_activity': 'Screen rhythm',
  'obs.wearable_daily': 'Watch daily summary',
  'obs.phq9': 'PHQ-9 questionnaire',
  'obs.nudge_offered': 'Suggestions offered',
  'obs.nudge_outcome': 'Suggestion outcomes',
  'obs.intervention_response': 'Before / after responses',
  'obs.friend_link': 'Friend lamp',
  'obs.safety_flag': 'Safety flags',
};
export const obsLabel = (type: string) =>
  OBS_LABEL[type] ?? type.replace(/^obs\./, '').replace(/_/g, ' ').replace(/^\w/, (ch) => ch.toUpperCase());

/** Per-source completeness from the raw observation feed. */
export function deriveCoverage(
  c: Consensus,
  events: ObsEvent[],
  series: MetricSeries[],
  sourceOf: Record<string, string>,
  labelOf: (s: string) => string,
  stage: RecordStage,
): Deep<DataCoverage> {
  const rec = recordedDays(series);
  const types = new Map<string, ObsEvent[]>();
  for (const e of events) types.set(e.type, [...(types.get(e.type) ?? []), e]);
  const cover = (type: string, list: ObsEvent[]): Deep<ObsTypeCoverage> => ({
    type,
    label: obsLabel(type),
    count: list.length,
    days: new Set(list.map((e) => localDay(e.ts))).size,
    last_at: list.map((e) => e.ts).sort().at(-1) ?? null,
    captured_by: [...new Set(list.map((e) => e.source))].sort(),
    simulated: list.filter((e) => e.sim).length,
  });
  const lastDay = rec.last ?? localDay(new Date().toISOString());
  const from14 = addDays(lastDay, -13);
  const groups = c.sources.map((v) => {
    const mine = [...types.entries()].filter(([t]) => sourceOf[t] === v.source);
    const days = new Set(mine.flatMap(([, l]) => l.map((e) => localDay(e.ts))).filter((d) => d >= from14));
    return {
      source: v.source,
      label: labelOf(v.source),
      sufficient: v.verdict !== 'insufficient',
      days_last_14: Math.min(14, days.size),
      last_at: v.last_data_at ?? null,
      types: mine.map(([t, l]) => cover(t, l)),
    };
  });
  const known = new Set(c.sources.map((v) => v.source as string));
  const other = [...types.entries()].filter(([t]) => !known.has(sourceOf[t])).map(([t, l]) => cover(t, l));
  const ready = groups.filter((g) => g.sufficient).length;
  return {
    first_day: rec.first,
    last_day: rec.last,
    span_days: rec.span,
    recorded_days: rec.days,
    observations: events.length,
    baseline_ready: series.some((s) => s.points.some((p) => isNum(p.baseline_median))),
    simulated: events.length > 0 && events.every((e) => e.sim),
    summary: `${rec.days} recorded ${rec.days === 1 ? 'day' : 'days'}; ${ready} of ${groups.length} signal groups have enough recent data for a verdict.`,
    groups,
    other,
    day_of_record: stage.day,
    early_baseline: stage.early,
  };
}

/** Deterministic review assembled from the consensus evidence and the weekly summary (no model involved). */
export function deriveReview(
  c: Consensus,
  series: MetricSeries[],
  week: WeekSummary | null,
  stage: RecordStage,
): { review: Deep<PatientReview>; evidence: RecordCitation[] } {
  const by = new Map(series.map((s) => [s.metric, s]));
  const evidence: RecordCitation[] = [];
  const cite = (metric: string): string | null => {
    const s = by.get(metric);
    const last = s ? [...s.points].reverse().find((p) => isNum(p.value)) : null;
    if (!s || !last) return null;
    const id = `metric:${metric}`;
    if (!evidence.some((e) => e.id === id))
      evidence.push({
        id,
        label: s.label,
        metric,
        source: s.source,
        unit: s.unit ?? null,
        value: last.value,
        baseline: last.baseline_median ?? null,
        observed_at: last.date,
        detail: pointMeaning(s, last).text,
      });
    return id;
  };
  const findings: Deep<ReviewFinding>[] = [];
  for (const v of c.sources)
    for (const e of v.evidence ?? []) {
      const s = by.get(e.metric);
      const id = cite(e.metric);
      const worse = s ? s.worse_when === e.direction : v.verdict === 'worse';
      const last = s ? [...s.points].reverse().find((p) => isNum(p.value)) : null;
      findings.push({
        theme: worse ? 'change' : 'improvement',
        title: s?.label ?? e.metric.replace(/_/g, ' '),
        meaning: worse
          ? `A change from their usual on ${e.days} recent ${e.days === 1 ? 'day' : 'days'}.`
          : `On the better side of their usual on ${e.days} recent ${e.days === 1 ? 'day' : 'days'}.`,
        consider: worse ? 'Worth asking about at the next contact.' : null,
        facts: s && last ? [`${valueText(last.value, s.unit)} on the latest day. ${pointMeaning(s, last).text}.`] : e.summary ? [e.summary] : [],
        cites: id ? [id] : [],
        by: 'template',
      });
    }
  for (const item of week?.going_well ?? []) {
    if (item.kind !== 'metric' || !item.metric || findings.some((f) => f.cites.includes(`metric:${item.metric}`))) continue;
    const id = cite(item.metric);
    findings.push({ theme: 'improvement', title: by.get(item.metric)?.label ?? item.metric, meaning: item.text, consider: null, facts: [], cites: id ? [id] : [], by: 'template' });
  }
  const routines = week?.routines ?? [];
  if (routines.length) {
    const slipped = routines.filter((r) => r.status === 'slipped');
    findings.push({
      theme: 'routine',
      title: slipped.length ? 'Some routines slipped' : 'Routines are holding',
      meaning: slipped.length
        ? `${slipped.map((r) => r.label).join(', ')} happened less often than usual this week.`
        : `${routines.filter((r) => r.status === 'kept').length} of ${routines.length} usual routines were kept this week.`,
      consider: slipped.length ? 'Ask what got in the way before reading it as a change.' : null,
      facts: routines.slice(0, 3).map((r) => `${r.label}: ${r.this_week} of 7 days this week.`),
      cites: [],
      by: 'template',
    });
  }
  const missing = c.sources.filter((v) => v.verdict === 'insufficient');
  if (missing.length)
    findings.push({
      theme: 'coverage',
      title: 'Not enough data from some signal groups',
      meaning: `${missing.length} of ${c.sources.length} signal groups cannot give a verdict yet, so this is not a confirmed steady picture.`,
      consider: 'Read the consensus as provisional until more days are recorded.',
      facts: [],
      cites: [],
      by: 'template',
    });
  return {
    review: {
      headline: cleanText(c.explanation?.text ?? c.explanation?.headline ?? 'No explanation has been generated yet.'),
      findings: findings.slice(0, 8),
      by: 'template',
      model: null,
      cached: false,
      fallback_reason: 'not_requested',
      overview: null,
      overview_cites: [],
      day_of_record: stage.day,
      early_record: stage.early,
      generated_at: c.explanation?.generated_at ?? c.computed_at,
    },
    evidence,
  };
}

/** Internal provenance tags never belong in a sentence about the person; the header carries the marker. */
export function cleanText(text: string): string {
  return text
    .replace(/\s*\((SIMULATED|simulated)\)/g, '')
    .replace(/\bSimulated data is labelled SIMULATED\.\s*/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

export interface InsightView {
  review: Deep<PatientReview>;
  evidence: RecordCitation[];
  trace: Deep<PatientInsight>['trace'];
  comparison: Deep<PeriodComparison> | null;
  routine: Deep<LearnedRoutine>;
  graph: Deep<InsightGraph>;
  coverage: Deep<DataCoverage>;
  /** the code-written arc of the record (null until the cloud sends it) */
  course: Deep<PatientInsight>['course'];
  /** the one code-built sentence that reconciles the rule state with the course ('' until the cloud sends it) */
  statusLine: string;
  /** one plain-language line per day, newest first (empty until the cloud sends it) */
  days: Deep<PatientInsight>['days'];
  /** reflection levels and themes, only when the person shares; never their words */
  reflections: Deep<PatientInsight>['reflections'];
  stage: RecordStage;
  /** the consensus replayed per day, oldest first (empty when the cloud does not send it) */
  stateHistory: Deep<PatientInsight>['state_history'];
  /** care-team action log, oldest first */
  actions: Deep<PatientInsight>['actions'];
  /** true when the cloud's insight payload was used, false when derived in the browser */
  fromCloud: boolean;
}

/** One shape for every panel: the cloud's insight when present, otherwise the derived view. */
export function insightView(
  insight: PatientInsight | null,
  c: Consensus,
  series: MetricSeries[],
  week: WeekSummary | null,
  graph: KnowledgeGraph | null,
  events: ObsEvent[],
  sourceOf: Record<string, string>,
  labelOf: (s: string) => string,
): InsightView {
  if (insight) {
    const full = insight as Deep<PatientInsight>;
    return {
      review: { ...full.review, headline: cleanText(full.review.headline) },
      evidence: full.evidence ?? [],
      trace: full.trace ?? [],
      comparison: full.comparison,
      routine: full.routine,
      graph: full.graph,
      coverage: full.coverage,
      course: full.course ?? null,
      statusLine: cleanText(full.status_line ?? ''),
      days: full.days ?? [],
      reflections: full.reflections ?? null,
      stage: {
        day: full.day_of_record,
        early: full.early_record,
        building: !full.coverage.baseline_ready,
        steadyAfter: full.min_history_days_for_stable || null,
      },
      stateHistory: full.state_history ?? [],
      actions: full.actions ?? [],
      fromCloud: true,
    };
  }
  const stage = recordStage(series);
  const r = deriveReview(c, series, week, stage);
  return {
    review: r.review,
    evidence: r.evidence,
    trace: [],
    comparison: deriveComparison(c, series, labelOf, stage),
    routine: deriveRoutine(week, graph, stage),
    graph: deriveGraph(graph),
    coverage: deriveCoverage(c, events, series, sourceOf, labelOf, stage),
    course: null,
    statusLine: '',
    days: [],
    reflections: null,
    stage,
    stateHistory: [],
    actions: [],
    fromCloud: false,
  };
}

export const FALLBACK_REASON: Record<string, string> = {
  not_requested: 'The model was not asked for this record, so the rule-based summary is shown.',
  provider_unavailable: 'The model could not be reached, so the rule-based summary is shown.',
  invalid_json: 'The model’s answer could not be read, so the rule-based summary is shown.',
  no_valid_findings: 'None of the model’s findings passed validation, so the rule-based summary is shown.',
  cooldown: 'The model is resting after recent errors, so the rule-based summary is shown.',
};

export type { Src };
