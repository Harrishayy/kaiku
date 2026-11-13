/**
 * Pure helpers for the /tune/ page (unit-tested). Data-driven: nothing here knows metric or source names.
 * Ground truth for the criteria is config/criteria.toml; these only edit / diff / serialise a candidate.
 */
import type { Criteria, MetricSpec, RuleSpec } from '@contracts';

export type SourceOf = Record<string, string>;

/** Group metrics and rules by consensus source (via SOURCE_OF[obs]); unknown obs → "other". */
export function groupBySource(c: Criteria, sourceOf: SourceOf, knownSources: readonly string[]) {
  const groups = new Map<string, { metrics: { m: MetricSpec; i: number }[]; rules: { r: RuleSpec; i: number }[] }>();
  const get = (s: string) => {
    if (!groups.has(s)) groups.set(s, { metrics: [], rules: [] });
    return groups.get(s)!;
  };
  for (const s of [...knownSources, ...Object.keys(c.sources ?? {})]) get(s);
  (c.metric ?? []).forEach((m, i) => get(sourceOf[m.obs] ?? 'other').metrics.push({ m, i }));
  (c.rule ?? []).forEach((r, i) => get(sourceOf[r.obs] ?? 'other').rules.push({ r, i }));
  return [...groups.entries()].filter(([s, g]) => s in (c.sources ?? {}) || g.metrics.length || g.rules.length);
}

/**
 * The contract key is `metric` / `rule` (TOML array-of-tables names = pydantic aliases; FastAPI serialises by
 * alias). A Python `model_dump()` without by_alias would send `metrics` / `rules` — accept both, emit the contract.
 */
export function normalizeCriteria(raw: Criteria): Criteria {
  const r = raw as Criteria & { metrics?: Criteria['metric']; rules?: Criteria['rule'] };
  const { metrics, rules, ...rest } = r;
  return { ...rest, metric: r.metric ?? metrics ?? [], rule: r.rule ?? rules ?? [] };
}

export function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x)) as T;
}

/** Set a value at a path; `undefined`/null/'' removes the key (= "use the default"). Returns a new object. */
export function setIn<T>(obj: T, path: (string | number)[], value: unknown): T {
  const out = clone(obj) as unknown as Record<string | number, unknown>;
  let cur = out;
  for (let k = 0; k < path.length - 1; k++) {
    const key = path[k];
    if (cur[key] === undefined || cur[key] === null) cur[key] = typeof path[k + 1] === 'number' ? [] : {};
    cur = cur[key] as Record<string | number, unknown>;
  }
  const last = path[path.length - 1];
  if (value === undefined || value === null || value === '') delete cur[last];
  else cur[last] = value;
  return out as unknown as T;
}

/** Paths ("metric.rmssd.weight", "sources.robot.min_confidence", …) where b differs from a. */
export function diffPaths(a: unknown, b: unknown, prefix = ''): string[] {
  const keyFor = (x: unknown, idx: number) =>
    x && typeof x === 'object' && 'name' in (x as object) ? String((x as { name: unknown }).name) : String(idx);
  if (Array.isArray(a) && Array.isArray(b)) {
    const out: string[] = [];
    const n = Math.max(a.length, b.length);
    for (let i = 0; i < n; i++) out.push(...diffPaths(a[i], b[i], `${prefix}${prefix ? '.' : ''}${keyFor(b[i] ?? a[i], i)}`));
    return out;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const keys = new Set([...Object.keys(a as object), ...Object.keys(b as object)]);
    return [...keys].flatMap((k) =>
      diffPaths((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k], `${prefix}${prefix ? '.' : ''}${k}`),
    );
  }
  const norm = (v: unknown) => (v === undefined ? null : v);
  return JSON.stringify(norm(a)) === JSON.stringify(norm(b)) ? [] : [prefix];
}

// ------------------------------------------------------------------------------------------ TOML export
type Scalar = string | number | boolean;

function tomlKey(k: string): string {
  return /^[A-Za-z0-9_-]+$/.test(k) ? k : JSON.stringify(k);
}

function tomlValue(v: unknown): string {
  if (typeof v === 'string') return JSON.stringify(v); // TOML basic strings share JSON escaping for our content
  if (typeof v === 'number') return String(v);
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (Array.isArray(v)) return `[${v.map(tomlValue).join(', ')}]`;
  if (v && typeof v === 'object')
    return `{ ${Object.entries(v as Record<string, unknown>)
      .filter(([, x]) => x !== undefined && x !== null)
      .map(([k, x]) => `${tomlKey(k)} = ${tomlValue(x)}`)
      .join(', ')} }`;
  throw new Error(`cannot serialise ${String(v)}`);
}

function scalarLines(obj: Record<string, unknown>, skip: string[] = []): string[] {
  return Object.entries(obj)
    .filter(([k, v]) => !skip.includes(k) && v !== undefined && v !== null)
    .map(([k, v]) => `${tomlKey(k)} = ${tomlValue(v as Scalar)}`);
}

/**
 * Serialise a Criteria object as TOML that config/criteria.toml (and kaiku_contracts/criteria.py) accepts.
 * Comments from the original file are not preserved — keep the file's header when pasting.
 */
export function criteriaToToml(c: Criteria, header: string[] = []): string {
  const out: string[] = header.map((h) => `# ${h}`);
  if (header.length) out.push('');
  const top = c as unknown as Record<string, unknown>;
  const tables = new Set(['defaults', 'state', 'sources', 'metric', 'rule']);
  out.push(...scalarLines(Object.fromEntries(Object.entries(top).filter(([k]) => !tables.has(k)))));
  if (c.defaults && Object.keys(c.defaults).length) out.push('', '[defaults]', ...scalarLines(c.defaults as Record<string, unknown>));
  for (const [name, spec] of Object.entries(c.sources ?? {}))
    out.push('', `[sources.${tomlKey(name)}]`, ...scalarLines(spec as Record<string, unknown>));
  if (c.state && Object.keys(c.state).length) out.push('', '[state]', ...scalarLines(c.state as Record<string, unknown>));
  for (const m of c.metric ?? []) out.push('', '[[metric]]', ...scalarLines(m as unknown as Record<string, unknown>));
  for (const r of c.rule ?? []) out.push('', '[[rule]]', ...scalarLines(r as unknown as Record<string, unknown>));
  return out.join('\n') + '\n';
}
