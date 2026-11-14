// Run: pnpm test  (Node >= 22.18 strips TS types natively)
import { test } from 'node:test';
import assert from 'node:assert/strict';

// ------------------------------------------------------------------ /tune/ helpers
import { criteriaToToml, diffPaths, groupBySource, normalizeCriteria, setIn } from '../lib/criteria.ts';
import type { Criteria } from '@contracts';

const C: Criteria = {
  name: 'consensus-v1',
  defaults: { z_threshold: 1.5, min_mad: 0 },
  sources: { robot: { enabled: true, worse_min_weight: 2 }, glasses: { enabled: true, worse_min_weight: 1 } },
  state: { needs_call_min_worse: 2, correlated_families: ['self_report'], count_correlated_as_one: false },
  metric: [
    { name: 'rmssd', label: 'HRV', obs: 'obs.hrv_session', field: 'rmssd_pre_ms', worse_when: 'down' as const, min_mad: 3 },
    { name: 'mood', label: 'Mood "dial"', obs: 'obs.self_report', field: 'value', worse_when: 'down' as const, where: { item: 'mood', context: 'ritual' } },
    { name: 'outing', label: 'Out', obs: 'obs.outing', field: 'minutes', worse_when: 'down' as const, weight: 0.5 },
    { name: 'mystery', label: 'X', obs: 'obs.unknown', field: 'v', worse_when: 'up' as const },
  ],
  rule: [{ name: 'phq9_high', label: 'PHQ-9 ≥ 10', obs: 'obs.phq9', field: 'total', kind: 'at_least' as const, threshold: 10 }],
};
const SRC = { 'obs.hrv_session': 'robot', 'obs.self_report': 'robot', 'obs.outing': 'glasses', 'obs.phq9': 'laptop' };

test('groupBySource: by SOURCE_OF[obs], keeps empty known sources, unknown obs → other', () => {
  const g = Object.fromEntries(groupBySource(C, SRC, ['robot', 'glasses', 'laptop']).map(([s, x]) => [s, x]));
  assert.deepEqual(g.robot.metrics.map((x) => x.m.name), ['rmssd', 'mood']);
  assert.deepEqual(g.glasses.metrics.map((x) => x.i), [2]);
  assert.deepEqual(g.laptop.rules.map((x) => x.r.name), ['phq9_high']);
  assert.deepEqual(g.other.metrics.map((x) => x.m.name), ['mystery']);
});

test('setIn is immutable and blank removes the key; diffPaths names metrics', () => {
  const d1 = setIn(C, ['metric', 0, 'z_threshold'], 2);
  assert.equal(C.metric![0].z_threshold, undefined);
  assert.equal(d1.metric![0].z_threshold, 2);
  const d2 = setIn(d1, ['metric', 0, 'min_mad'], null);
  assert.equal('min_mad' in d2.metric![0], false);
  const d3 = setIn(d2, ['sources', 'robot', 'worse_min_weight'], 1.5);
  assert.deepEqual(diffPaths(C, d3).sort(), ['metric.rmssd.min_mad', 'metric.rmssd.z_threshold', 'sources.robot.worse_min_weight']);
  assert.deepEqual(diffPaths(C, JSON.parse(JSON.stringify(C))), []);
});

test('criteriaToToml: tables, arrays of tables, inline where, escaped strings', () => {
  const t = criteriaToToml(C, ['hello']);
  assert.ok(t.startsWith('# hello\n'));
  assert.match(t, /^name = "consensus-v1"$/m);
  assert.match(t, /^\[sources\.robot\]$/m);
  assert.match(t, /^correlated_families = \["self_report"\]$/m);
  assert.equal(t.match(/^\[\[metric\]\]$/gm)?.length, 4);
  assert.match(t, /^where = \{ item = "mood", context = "ritual" \}$/m);
  assert.match(t, /^label = "Mood \\"dial\\""$/m);
  assert.match(t, /^weight = 0\.5$/m);
});

test('normalizeCriteria accepts metrics/rules and emits the contract keys metric/rule', () => {
  const n = normalizeCriteria({ sources: {}, metrics: [C.metric![0]], rules: [] } as unknown as Criteria);
  assert.equal(n.metric!.length, 1);
  assert.deepEqual(n.rule, []);
  assert.equal('metrics' in n, false);
  assert.equal(normalizeCriteria(C).metric!.length, 4);
});
