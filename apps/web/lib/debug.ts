/**
 * Pure helpers for the team's /debug/ page (unit-tested). They only sort, filter, group, total and diff what
 * `GET /v1/debug/day` returned. Nothing here decides a state, a verdict, a reading or a sentence: those come
 * from the cloud, and the page shows them as served.
 */

import type {
  DebugClaim,
  DebugConversation,
  DebugDay,
  DebugEvent,
  DebugFact,
  DebugMetric,
  DebugModelCall,
  DebugRead,
} from '@contracts';

// ------------------------------------------------------------------ day and request
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** A real calendar day written YYYY-MM-DD. */
export function isDate(s: string | null | undefined): s is string {
  if (!s || !DATE.test(s)) return false;
  const d = new Date(`${s}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

export function shiftDate(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** `date: null` asks the cloud for the home's own today. Gemma is asked only when `generate` is true. */
export function debugPath(home: string, date: string | null, generate: boolean): string {
  const q = new URLSearchParams({ home_id: home });
  if (date) q.set('date', date);
  q.set('generate', generate ? 'true' : 'false');
  return `/v1/debug/day?${q.toString()}`;
}

export type ProblemKind = 'closed' | 'no_route' | 'unknown_home' | 'bad_request' | 'unreachable' | 'server';

/** What a failed request means for a developer. A bare 404 is the router's own: this cloud has no such route. */
export function problemKind(status: number | null, detail: unknown): ProblemKind {
  if (status === null) return 'unreachable';
  if (status === 401 || status === 403) return 'closed';
  if (status === 404) return typeof detail === 'string' && /^not found$/i.test(detail.trim()) ? 'no_route' : 'unknown_home';
  if (status === 400 || status === 422) return 'bad_request';
  return 'server';
}

// ------------------------------------------------------------------ numbers and clocks
const MINUS = '−';

/** Up to `digits` decimals, trailing zeros dropped; null stays visibly empty. */
export function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const s = v.toFixed(digits).replace(/\.?0+$/, '');
  return (s === '-0' ? '0' : s).replace('-', MINUS);
}

/** A z-score keeps its sign and two decimals so columns line up. */
export function signed(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const s = Math.abs(v).toFixed(digits);
  return `${v < 0 && Number(s) !== 0 ? MINUS : '+'}${s}`;
}

export function usd(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `$${v.toFixed(v !== 0 && Math.abs(v) < 0.01 ? 4 : 2)}`;
}

export function latency(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v >= 10_000 ? `${(v / 1000).toFixed(1)} s` : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;
}

/** Wall clock in the home's timezone (the page never uses the browser's), 24 h. */
export function localClock(iso: string | null | undefined, timeZone: string, seconds = true): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat('en-GB', {
      timeZone,
      hour: '2-digit',
      minute: '2-digit',
      ...(seconds ? { second: '2-digit' } : {}),
      hourCycle: 'h23',
    }).format(d);
  } catch {
    return d.toISOString().slice(11, seconds ? 19 : 16) + 'Z';
  }
}

/** Day and clock in the home's timezone, for instants that may fall on another day (last data, since). */
export function localStamp(iso: string | null | undefined, timeZone: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  try {
    const day = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
    return `${day} ${localClock(iso, timeZone, false)}`;
  } catch {
    return d.toISOString().slice(0, 16).replace('T', ' ') + 'Z';
  }
}

/** Where an instant falls in the local day, 0 to 1 (clamped), for the events strip. */
export function dayFraction(ts: string, dayStart: string, dayEnd: string): number {
  const [t, a, b] = [Date.parse(ts), Date.parse(dayStart), Date.parse(dayEnd)];
  if (Number.isNaN(t) || Number.isNaN(a) || Number.isNaN(b) || b <= a) return 0;
  return Math.min(1, Math.max(0, (t - a) / (b - a)));
}

// ------------------------------------------------------------------ events: who sent what
/** The devices a developer wires, in pipeline order. Extra senders (simulator, new nodes) get their own lane. */
export const LANES = ['robot', 'phone', 'mac', 'glasses', 'watch', 'cloud'] as const;

const LANE_LABEL: Record<string, string> = {
  robot: 'Robot',
  phone: 'Phone',
  mac: 'Mac',
  glasses: 'Glasses',
  watch: 'Watch',
  cloud: 'Cloud',
  sim: 'Simulator',
};
export const laneLabel = (lane: string): string => LANE_LABEL[lane] ?? lane;

const ROBOT_NODES = new Set(['head', 'sensors', 'hub', 'friendlink']);

/**
 * The lane of one envelope. It follows the envelope's own `source`; watch records have no sender of their own
 * (they travel through the phone), so they are recognised by their type's signal group.
 */
export function laneOf(e: Pick<DebugEvent, 'source' | 'type'>, sourceOf: Record<string, string>): string {
  if (sourceOf[e.type] === 'wearable') return 'watch';
  if (ROBOT_NODES.has(e.source)) return 'robot';
  if (e.source === 'laptop') return 'mac';
  return e.source;
}

export interface LaneCount {
  lane: string;
  label: string;
  count: number;
  /** the envelope sources seen in this lane, e.g. hub + head */
  senders: string[];
}

/** Every expected lane (silent ones with count 0), then any other sender that showed up. */
export function laneCounts(events: Pick<DebugEvent, 'source' | 'type'>[], sourceOf: Record<string, string>): LaneCount[] {
  const by = new Map<string, { count: number; senders: Set<string> }>(LANES.map((l) => [l, { count: 0, senders: new Set<string>() }]));
  for (const e of events) {
    const lane = laneOf(e, sourceOf);
    const row = by.get(lane) ?? { count: 0, senders: new Set<string>() };
    row.count += 1;
    row.senders.add(e.source);
    by.set(lane, row);
  }
  return [...by].map(([lane, r]) => ({ lane, label: laneLabel(lane), count: r.count, senders: [...r.senders].sort() }));
}

export function typeCounts(events: Pick<DebugEvent, 'type'>[]): { type: string; count: number }[] {
  const by = new Map<string, number>();
  for (const e of events) by.set(e.type, (by.get(e.type) ?? 0) + 1);
  return [...by].map(([type, count]) => ({ type, count })).sort((a, b) => a.type.localeCompare(b.type));
}

export interface EventFilter {
  lane: string;
  type: string;
  text: string;
}
export const NO_EVENT_FILTER: EventFilter = { lane: '', type: '', text: '' };

export function filterEvents<E extends Pick<DebugEvent, 'source' | 'type' | 'payload' | 'id'>>(events: E[], f: EventFilter, sourceOf: Record<string, string>): E[] {
  const needle = f.text.trim().toLowerCase();
  return events.filter(
    (e) =>
      (!f.lane || laneOf(e, sourceOf) === f.lane) &&
      (!f.type || e.type === f.type) &&
      (!needle || `${e.type} ${e.source} ${e.id} ${JSON.stringify(e.payload)}`.toLowerCase().includes(needle)),
  );
}

function scalar(v: unknown): string {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  if (typeof v === 'string' || typeof v === 'boolean') return String(v);
  return JSON.stringify(v);
}

/** One line a developer can scan: `item=mood value=2 context=ritual`, cut to `max` characters. */
export function payloadLine(payload: Record<string, unknown> | null | undefined, max = 140): string {
  const line = Object.entries(payload ?? {})
    .map(([k, v]) => `${k}=${scalar(v)}`)
    .join(' ');
  if (!line) return '{}';
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

/** Column heads of the events table, named after the envelope's own fields. */
export const EVENT_COLUMNS = [
  { key: 'local_time', label: 'Local time', title: 'Wall clock in the home’s timezone' },
  { key: 'lane', label: 'From', title: 'Device lane, with the envelope’s own source' },
  { key: 'type', label: 'Type', title: 'Fully qualified message type' },
  { key: 'quality', label: 'Quality', title: 'The envelope’s quality, 0 to 1, when the sender gave one' },
  { key: 'sim', label: 'Sim', title: 'Sent by a simulated source, not a connected device' },
  { key: 'payload', label: 'Payload', title: 'Compact payload: long lists are cut to their first items plus a count' },
  { key: 'metrics', label: 'Counted toward', title: 'Metrics this envelope counted toward' },
] as const;

// ------------------------------------------------------------------ metrics table
export type MetricSortKey =
  | 'pipeline'
  | 'label'
  | 'source'
  | 'value'
  | 'readings'
  | 'median'
  | 'spread'
  | 'days'
  | 'z'
  | 'worse_z'
  | 'direction'
  | 'status'
  | 'progress'
  | 'weight'
  | 'scored';

const STATUS_RANK: Record<DebugMetric['status'], number> = { drifting: 0, improved: 1, normal: 2, insufficient: 3 };

const SORT_VALUE: Record<Exclude<MetricSortKey, 'pipeline'>, (m: DebugMetric) => number | string | null> = {
  label: (m) => m.metric.toLowerCase(),
  source: (m) => m.source,
  value: (m) => m.value ?? null,
  readings: (m) => m.readings ?? 0,
  median: (m) => m.baseline?.median ?? null,
  spread: (m) => m.baseline?.spread ?? null,
  days: (m) => m.baseline?.days ?? null,
  z: (m) => m.z ?? null,
  worse_z: (m) => m.worse_z ?? null,
  direction: (m) => m.direction,
  status: (m) => STATUS_RANK[m.status],
  progress: (m) => (m.worse_days ?? 0) / Math.max(1, m.drift_days_needed),
  weight: (m) => m.weight,
  scored: (m) => (m.scored ? 0 : 1),
};

export interface MetricColumn {
  key: Exclude<MetricSortKey, 'pipeline'>;
  label: string;
  title: string;
  numeric: boolean;
  /** first click on a numeric column shows the largest first */
  first: 'asc' | 'desc';
}

export const METRIC_COLUMNS: MetricColumn[] = [
  { key: 'label', label: 'Metric', title: 'Criteria name, then its label and unit', numeric: false, first: 'asc' },
  { key: 'source', label: 'Group', title: 'Signal group it votes in', numeric: false, first: 'asc' },
  { key: 'value', label: 'Value', title: 'The day’s value; empty = no data that day', numeric: true, first: 'desc' },
  { key: 'readings', label: 'n', title: 'Envelopes that day that counted toward it', numeric: true, first: 'desc' },
  { key: 'median', label: 'Median', title: 'Baseline median', numeric: true, first: 'desc' },
  { key: 'spread', label: 'Spread', title: 'max(1.4826 × MAD, min_mad): what one z unit is', numeric: true, first: 'desc' },
  { key: 'days', label: 'Base d', title: 'Days the baseline is made from', numeric: true, first: 'desc' },
  { key: 'z', label: 'z', title: '(value − median) / spread, as measured', numeric: true, first: 'desc' },
  { key: 'worse_z', label: 'Worse z / thr', title: 'z signed so that positive is the worse direction, against its threshold', numeric: true, first: 'desc' },
  { key: 'direction', label: 'Worse if', title: 'Direction the criteria count as worse', numeric: false, first: 'asc' },
  { key: 'status', label: 'Status', title: 'drifting, improved, normal or insufficient over the drift window', numeric: false, first: 'asc' },
  { key: 'progress', label: 'Toward flag', title: 'Worse days in the drift window / worse days that flag it', numeric: true, first: 'desc' },
  { key: 'weight', label: 'Weight', title: 'Weight in its group’s worse and better sums', numeric: true, first: 'desc' },
  { key: 'scored', label: 'Role', title: 'scored = a vote; observe-only = charted, never a vote', numeric: false, first: 'asc' },
];

/** Flagged first, then beyond the threshold today, then by status and by how far the worse way; no data last. */
export function pipelineOrder(a: DebugMetric, b: DebugMetric): number {
  const rank = (m: DebugMetric) => (m.flagged ? 0 : m.beyond_today ? 1 : 2 + STATUS_RANK[m.status] + (m.value === null || m.value === undefined ? 4 : 0));
  return rank(a) - rank(b) || (b.worse_z ?? -Infinity) - (a.worse_z ?? -Infinity) || a.label.localeCompare(b.label);
}

/** Stable sort; rows without a value for the column always sink, whichever way the column is sorted. */
export function sortMetrics(metrics: DebugMetric[], key: MetricSortKey, dir: 'asc' | 'desc'): DebugMetric[] {
  if (key === 'pipeline') return [...metrics].sort(pipelineOrder);
  const get = SORT_VALUE[key];
  const sign = dir === 'asc' ? 1 : -1;
  return [...metrics].sort((a, b) => {
    const [x, y] = [get(a), get(b)];
    if (x === null || y === null) return x === y ? pipelineOrder(a, b) : x === null ? 1 : -1;
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
    return c * sign || pipelineOrder(a, b);
  });
}

export interface MetricFilter {
  text: string;
  source: string;
  status: string;
  /** '' = all, 'scored' = votes only, 'observe' = observe-only */
  role: '' | 'scored' | 'observe';
  /** only metrics with a value that day */
  withData: boolean;
}
export const NO_METRIC_FILTER: MetricFilter = { text: '', source: '', status: '', role: '', withData: false };

export function filterMetrics(metrics: DebugMetric[], f: MetricFilter): DebugMetric[] {
  const needle = f.text.trim().toLowerCase();
  return metrics.filter(
    (m) =>
      (!needle || `${m.label} ${m.metric} ${m.obs}`.toLowerCase().includes(needle)) &&
      (!f.source || m.source === f.source) &&
      (!f.status || (f.status === 'flagged' ? Boolean(m.flagged) : m.status === f.status)) &&
      (!f.role || (f.role === 'scored' ? m.scored : !m.scored)) &&
      (!f.withData || (m.value !== null && m.value !== undefined)),
  );
}

export function metricCounts(metrics: DebugMetric[]) {
  const n = (p: (m: DebugMetric) => boolean) => metrics.filter(p).length;
  return {
    total: metrics.length,
    flagged: n((m) => Boolean(m.flagged)),
    beyond: n((m) => Boolean(m.beyond_today)),
    drifting: n((m) => m.status === 'drifting'),
    improved: n((m) => m.status === 'improved'),
    insufficient: n((m) => m.status === 'insufficient'),
    withData: n((m) => m.value !== null && m.value !== undefined),
    observeOnly: n((m) => !m.scored),
  };
}

/**
 * A count for the verdicts table, not a decision: of a group's scored metrics, how many have a status other than
 * insufficient that day. It is what a developer looks for when a verdict is insufficient although its confidence
 * clears the minimum.
 */
export function usableOf(source: string, metrics: Pick<DebugMetric, 'source' | 'scored' | 'status'>[]): { usable: number; scored: number } {
  const scored = metrics.filter((m) => m.source === source && m.scored);
  return { usable: scored.filter((m) => m.status !== 'insufficient').length, scored: scored.length };
}

/**
 * The envelopes behind one metric that day, oldest first: exactly the ids the cloud lists for it. An envelope can
 * name a metric and still count on another day (a daily summary), so the name alone is never used.
 */
export function eventsBehind<E extends Pick<DebugEvent, 'id'>>(metric: Pick<DebugMetric, 'event_ids'>, events: E[]): { events: E[]; unlisted: number } {
  const ids = new Set<string>(metric.event_ids ?? []);
  const found = events.filter((e) => ids.has(e.id));
  return { events: found, unlisted: ids.size - found.length };
}

/** An envelope listed for this day although it is stamped before or after it (a summary that arrived later). */
export function stampedOutside(e: Pick<DebugEvent, 'ts'>, day: Pick<DebugDay, 'day_start' | 'day_end'>): 'before' | 'after' | null {
  const [t, a, b] = [Date.parse(e.ts), Date.parse(day.day_start), Date.parse(day.day_end)];
  if (Number.isNaN(t) || Number.isNaN(a) || Number.isNaN(b)) return null;
  return t < a ? 'before' : t >= b ? 'after' : null;
}

/**
 * True when an envelope names metrics but none of them lists it for this day: it is stamped here and measures
 * another day. Only said when every named metric's id list is complete (as many ids as readings).
 */
export function countsElsewhere(e: Pick<DebugEvent, 'id' | 'metrics'>, metrics: Pick<DebugMetric, 'metric' | 'event_ids' | 'readings'>[]): boolean {
  const named = metrics.filter((m) => (e.metrics ?? []).includes(m.metric));
  if (!named.length) return false;
  return named.every((m) => {
    const ids: readonly string[] = m.event_ids ?? [];
    return !ids.includes(e.id) && ids.length >= (m.readings ?? 0);
  });
}

// ------------------------------------------------------------------ the read and its citations
export const READING_LABEL: Record<DebugRead['reading'], string> = {
  as_usual: 'As usual',
  slight_shift: 'Slight shift',
  clear_shift: 'Clear shift',
  not_enough_data: 'Not enough data',
};

export const READING_TONE: Record<DebugRead['reading'], 'neutral' | 'warn' | 'call' | 'ins'> = {
  as_usual: 'neutral',
  slight_shift: 'warn',
  clear_shift: 'call',
  not_enough_data: 'ins',
};

const FALLBACK_WORDS: Record<string, string> = {
  not_requested: 'Gemma was not asked',
  provider_unavailable: 'the model provider did not answer',
  over_budget: 'the spend cap is reached',
  invalid_json: 'the model’s answer was not valid JSON',
  no_valid_claims: 'the model answered, but nothing usable was left after the validators',
  cooldown: 'a read of this day was generated moments ago and its data has changed since; ask again after the cooldown',
};
export const fallbackWords = (reason: string | null | undefined): string => (reason ? (FALLBACK_WORDS[reason] ?? reason) : 'no reason given');

export const rejectedTotal = (rejected: Record<string, number> | null | undefined): number =>
  Object.values(rejected ?? {}).reduce((a, b) => a + b, 0);

export type SectionId = 'result' | 'verdicts' | 'metrics' | 'events' | 'conversations' | 'calls';

export interface CiteTarget {
  section: SectionId;
  /** DOM id of the row or block the citation names */
  anchor: string;
}

const slug = (s: string) => s.replace(/[^A-Za-z0-9_-]+/g, '-');
export const anchorOf = {
  metric: (name: string) => `dbg-metric-${slug(name)}`,
  verdict: (source: string) => `dbg-verdict-${slug(source)}`,
  event: (id: string) => `dbg-event-${slug(id)}`,
  consensus: () => 'dbg-consensus',
};

type Citable = Pick<DebugDay, 'metrics' | 'verdicts' | 'events'>;

/**
 * Where a fact id points on the page: `metric:<name>` to its metric row, `source:<name>` to its verdict,
 * `event:<id>` to its envelope, `consensus:state` to the result. `missing:<group or metric>` and
 * `tomorrow:<metric>` / `tomorrow:group_<group>` / `tomorrow:state` point at the group, the metric or the result.
 * Null when the day holds nothing by that name, so the page can say so instead of jumping nowhere.
 */
export function citeTarget(id: string, day: Citable): CiteTarget | null {
  const cut = id.indexOf(':');
  const [kind, name] = cut < 0 ? [id, ''] : [id.slice(0, cut), id.slice(cut + 1)];
  const metric = (n = name) => (day.metrics.some((m) => m.metric === n) ? { section: 'metrics' as const, anchor: anchorOf.metric(n) } : null);
  const verdict = (n = name) => (day.verdicts.some((v) => v.source === n) ? { section: 'verdicts' as const, anchor: anchorOf.verdict(n) } : null);
  const consensus = { section: 'result' as const, anchor: anchorOf.consensus() };
  if (kind === 'consensus') return consensus;
  if (kind === 'metric') return metric();
  if (kind === 'source') return verdict();
  if (kind === 'event') return day.events.some((e) => e.id === name) ? { section: 'events', anchor: anchorOf.event(name) } : null;
  if (kind === 'missing') return verdict() ?? metric();
  if (kind === 'tomorrow') return name === 'state' ? consensus : name.startsWith('group_') ? verdict(name.slice(6)) : (metric() ?? verdict());
  return null;
}

export interface ResolvedCite {
  id: string;
  /** null = the claim cites a fact the day does not list */
  fact: DebugFact | null;
  target: CiteTarget | null;
}

export function resolveCites(claim: Pick<DebugClaim, 'cites'>, facts: DebugFact[], day: Citable): ResolvedCite[] {
  const byId = new Map(facts.map((f) => [f.id, f]));
  return [...new Set<string>(claim.cites)].map((id) => ({ id, fact: byId.get(id) ?? null, target: citeTarget(id, day) }));
}

export interface ClaimGroup {
  key: 'moved' | 'missing' | 'tomorrow' | 'rule_check';
  title: string;
  empty: string;
  claims: DebugClaim[];
}

/** The read's parts in reading order. An empty part stays listed, so "nothing moved" is visible, not absent. */
export function claimGroups(read: Pick<DebugRead, 'moved' | 'missing' | 'tomorrow' | 'rule_check'>): ClaimGroup[] {
  return [
    { key: 'moved', title: 'What moved', empty: 'No claim about a measure that moved.', claims: read.moved ?? [] },
    { key: 'missing', title: 'What is missing', empty: 'No claim about missing data.', claims: read.missing ?? [] },
    { key: 'tomorrow', title: 'What would change tomorrow', empty: 'No claim about tomorrow.', claims: read.tomorrow ?? [] },
    { key: 'rule_check', title: 'Does the rule’s answer look right', empty: 'No rule check in this read.', claims: read.rule_check ? [read.rule_check] : [] },
  ];
}

/**
 * Which read to show after a refresh. A poll never asks Gemma, so its read is the deterministic one with
 * `not_requested`; a Gemma read already on screen for the same day is kept, and `current` says whether the
 * day's data is still what Gemma read (same digest).
 */
export function pickRead(held: DebugRead | null, next: DebugRead): { read: DebugRead; kept: boolean; current: boolean } {
  if (held && held.by === 'gemma' && next.by === 'deterministic' && next.fallback_reason === 'not_requested')
    return { read: held, kept: true, current: held.digest === next.digest };
  return { read: next, kept: false, current: true };
}

// ------------------------------------------------------------------ conversations and model calls
export type CallOutcome = 'failed' | 'fallback' | 'ok';
export const callOutcome = (c: Pick<DebugModelCall, 'ok' | 'fallback'>): CallOutcome => (!c.ok ? 'failed' : c.fallback ? 'fallback' : 'ok');

const OUTCOME_RANK: Record<CallOutcome, number> = { failed: 0, fallback: 1, ok: 2 };

/** Failures on top, then fallbacks, then the rest, each oldest first. */
export function orderCalls<C extends Pick<DebugModelCall, 'ok' | 'fallback' | 'ts'>>(calls: C[]): C[] {
  return [...calls].sort((a, b) => OUTCOME_RANK[callOutcome(a)] - OUTCOME_RANK[callOutcome(b)] || a.ts.localeCompare(b.ts));
}

export interface ModelTotal {
  provider: string;
  model: string;
  calls: number;
  failed: number;
  fallback: number;
  /** calls that carry a latency / an estimate: the sums below cover only those */
  timed: number;
  costed: number;
  latency_ms: number;
  slowest_ms: number | null;
  est_usd: number;
}

export function modelTotals(calls: DebugModelCall[]): ModelTotal[] {
  const by = new Map<string, ModelTotal>();
  for (const c of calls) {
    const key = `${c.provider}\u0000${c.model}`;
    const t = by.get(key) ?? { provider: c.provider, model: c.model, calls: 0, failed: 0, fallback: 0, timed: 0, costed: 0, latency_ms: 0, slowest_ms: null, est_usd: 0 };
    t.calls += 1;
    const o = callOutcome(c);
    if (o === 'failed') t.failed += 1;
    if (o === 'fallback') t.fallback += 1;
    if (typeof c.latency_ms === 'number') {
      t.timed += 1;
      t.latency_ms += c.latency_ms;
      t.slowest_ms = Math.max(t.slowest_ms ?? 0, c.latency_ms);
    }
    if (typeof c.est_usd === 'number') {
      t.costed += 1;
      t.est_usd += c.est_usd;
    }
    by.set(key, t);
  }
  return [...by.values()].sort((a, b) => b.est_usd - a.est_usd || b.calls - a.calls || a.model.localeCompare(b.model));
}

export function slowestCall<C extends Pick<DebugModelCall, 'latency_ms'>>(calls: C[]): C | null {
  let best: C | null = null;
  for (const c of calls) if (typeof c.latency_ms === 'number' && (best === null || c.latency_ms > (best.latency_ms as number))) best = c;
  return best;
}

export function callSummary(calls: DebugModelCall[]) {
  const totals = modelTotals(calls);
  return {
    calls: calls.length,
    failed: totals.reduce((a, t) => a + t.failed, 0),
    fallback: totals.reduce((a, t) => a + t.fallback, 0),
    costed: totals.reduce((a, t) => a + t.costed, 0),
    est_usd: totals.reduce((a, t) => a + t.est_usd, 0),
  };
}

/**
 * Tool names are in call order only while the conversation is still open; once the device has uploaded it the
 * cloud keeps one of each, so no order may be drawn.
 */
export const toolsInOrder = (c: Pick<DebugConversation, 'end'>): boolean => !c.end;

export interface AskCost {
  calls: number;
  /** null when no matching call recorded one */
  latency_ms: number | null;
  est_usd: number | null;
}

/**
 * What one ask cost, read from the ledger rather than assumed. The calls are logged under the home's today,
 * whichever day was read. A read Gemma wrote names its model: its calls since the ask began are the ask. A read
 * that fell back after the model answered names no model, so the ask is found through the ledger's own fallback
 * row (provider none, route = the fallback reason): the model calls of that same task. Null when none is found.
 */
export function askCost(calls: DebugModelCall[], read: Pick<DebugRead, 'model' | 'fallback_reason' | 'by'>, sinceMs: number): AskCost | null {
  const since = calls.filter((c) => Date.parse(c.ts) >= sinceMs);
  const marker = since.find((c) => c.provider === 'none' && c.route === read.fallback_reason);
  const mine =
    read.by === 'gemma' && read.model
      ? since.filter((c) => c.model === read.model)
      : marker
        ? since.filter((c) => c.task === marker.task && c.provider !== 'none')
        : [];
  if (!mine.length) return null;
  const sum = (get: (c: DebugModelCall) => number | null | undefined) => {
    const known = mine.map(get).filter((v): v is number => typeof v === 'number');
    return known.length ? known.reduce((a, b) => a + b, 0) : null;
  };
  return { calls: mine.length, latency_ms: sum((c) => c.latency_ms), est_usd: sum((c) => c.est_usd) };
}

export function conversationSummary(list: DebugConversation[]) {
  const sum = (get: (c: DebugConversation) => number | null | undefined) => list.reduce((a, c) => a + (get(c) ?? 0), 0);
  return {
    count: list.length,
    minutes: sum((c) => c.minutes),
    billed: sum((c) => c.billed_minutes),
    open: list.filter((c) => !c.outcome).length,
    feels: sum((c) => (c.feel ?? []).length),
  };
}

// ------------------------------------------------------------------ live: what a refresh brought
export interface MetricMove {
  id: string;
  label: string;
  from: number | null;
  to: number | null;
  statusFrom: DebugMetric['status'];
  statusTo: DebugMetric['status'];
  flaggedFrom: boolean;
  flaggedTo: boolean;
}

export interface DayDiff {
  /** ids of envelopes that were not in the previous response */
  events: string[];
  /** their message types, each once, in arrival order */
  types: string[];
  metrics: MetricMove[];
  verdicts: { source: string; from: string; to: string }[];
  state: { from: string; to: string } | null;
}

export const NO_DIFF: DayDiff = { events: [], types: [], metrics: [], verdicts: [], state: null };

/** What changed between two responses for the same home and day. Another day or home is not a change: empty. */
export function diffDay(prev: DebugDay | null, next: DebugDay): DayDiff {
  if (!prev || prev.home_id !== next.home_id || prev.date !== next.date) return NO_DIFF;
  const had = new Set(prev.events.map((e) => e.id));
  const before = new Map(prev.metrics.map((m) => [m.id, m]));
  const verdictBefore = new Map(prev.verdicts.map((v) => [v.source, v.verdict]));
  const metrics: MetricMove[] = [];
  for (const m of next.metrics) {
    const p = before.get(m.id);
    const [from, to] = [p?.value ?? null, m.value ?? null];
    if (!p || from !== to || p.status !== m.status || Boolean(p.flagged) !== Boolean(m.flagged))
      metrics.push({ id: m.id, label: m.label, from, to, statusFrom: p?.status ?? 'insufficient', statusTo: m.status, flaggedFrom: Boolean(p?.flagged), flaggedTo: Boolean(m.flagged) });
  }
  const arrived = next.events.filter((e) => !had.has(e.id));
  return {
    events: arrived.map((e) => e.id),
    types: [...new Set(arrived.map((e) => e.type))],
    metrics,
    verdicts: next.verdicts
      .filter((v) => verdictBefore.has(v.source) && verdictBefore.get(v.source) !== v.verdict)
      .map((v) => ({ source: v.source, from: String(verdictBefore.get(v.source)), to: v.verdict })),
    state: prev.consensus.state !== next.consensus.state ? { from: prev.consensus.state, to: next.consensus.state } : null,
  };
}

export const diffEmpty = (d: DayDiff): boolean => !d.events.length && !d.metrics.length && !d.verdicts.length && !d.state;

/** One line for the live bar: "1 new event (obs.drum_session) · Mood dial 3 → 2 · robot as_usual → worse". */
export function diffLine(d: DayDiff, max = 3): string {
  const parts: string[] = [];
  if (d.events.length) {
    const types = d.types.length > max ? `${d.types.slice(0, max).join(', ')}, +${d.types.length - max} more types` : d.types.join(', ');
    parts.push(`${d.events.length} new ${d.events.length === 1 ? 'event' : 'events'}${types ? ` (${types})` : ''}`);
  }
  if (d.state) parts.push(`state ${d.state.from} → ${d.state.to}`);
  for (const v of d.verdicts) parts.push(`${v.source} ${v.from} → ${v.to}`);
  for (const m of d.metrics.slice(0, max))
    parts.push(m.from !== m.to ? `${m.label} ${num(m.from)} → ${num(m.to)}` : m.statusFrom !== m.statusTo ? `${m.label} ${m.statusFrom} → ${m.statusTo}` : `${m.label} ${m.flaggedTo ? 'now flagged' : 'no longer flagged'}`);
  if (d.metrics.length > max) parts.push(`+${d.metrics.length - max} more metrics`);
  return parts.join(' · ');
}
