// Run: pnpm test  (Node >= 22.18 strips TS types natively)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isoMs, makeEnvelope, uuidv7 } from '../lib/envelope.ts';
import { computeSpeech } from '../lib/speech.ts';
import { estimatePitch, expressivityIndex, makeSchedule, reactionStats, semitoneSd } from '../lib/metrics.ts';
import { parsePairing } from '../lib/pairing.ts';

test('uuidv7 has version 7, RFC variant and current ms timestamp', () => {
  const before = Date.now();
  const id = uuidv7();
  assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  const ms = parseInt(id.replace(/-/g, '').slice(0, 12), 16);
  assert.ok(ms >= before && ms <= Date.now());
});

test('envelope matches the contract shape (laptop source)', () => {
  const env = makeEnvelope('obs.safety_flag', { trigger: 'phq9_item9', severity: 'high', handled_locally: true }, {
    source: 'laptop',
    homeId: 'demo-aino',
  });
  assert.equal(env.v, 1);
  assert.equal(env.source, 'laptop');
  assert.match(env.ts, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  assert.equal(env.sim, false);
  assert.match(isoMs(new Date(Date.UTC(2026, 10, 14, 8, 12, 3, 120))), /2026-11-14T08:12:03\.120Z/);
});

test('speech: half silence gives ~0.5 pause ratio; too short returns null', () => {
  const frames: number[] = [];
  for (let i = 0; i < 400; i++) frames.push(i % 40 < 20 ? 0.001 : 0.1 + 0.05 * Math.sin(i));
  const f = computeSpeech(frames, [], 20);
  assert.ok(f);
  assert.ok(f.pause_ratio! > 0.4 && f.pause_ratio! < 0.6, `pause_ratio ${f.pause_ratio}`);
  assert.equal(f.duration_s, 20);
  assert.equal(f.pitch_variability, null); // not enough pitched frames
  assert.equal(computeSpeech([0.1, 0.2], [], 1), null);
});

test('pitch: 200 Hz sine is detected; semitone SD grows with variation', () => {
  const sr = 48000;
  const buf = Float32Array.from({ length: 2048 }, (_, i) => 0.3 * Math.sin((2 * Math.PI * 200 * i) / sr));
  const f0 = estimatePitch(buf, sr);
  assert.ok(f0 && Math.abs(f0 - 200) < 6, `f0 ${f0}`);
  assert.equal(estimatePitch(new Float32Array(2048), sr), null);
  const flat = Array(30).fill(200);
  const lively = Array.from({ length: 30 }, (_, i) => 200 * 2 ** ((i % 6) / 12));
  assert.equal(semitoneSd(flat), 0);
  assert.ok((semitoneSd(lively) ?? 0) > 1);
});

test('reaction stats: median, IQR, lapses; anticipations ignored; no-go false alarms separate', () => {
  const r = reactionStats([
    { kind: 'go', rt: 300 },
    { kind: 'go', rt: 320 },
    { kind: 'go', rt: 340 },
    { kind: 'go', rt: 360 },
    { kind: 'go', rt: 600 }, // lapse (slow) but still a valid RT
    { kind: 'go', rt: null }, // lapse (miss)
    { kind: 'go', rt: 50 }, // anticipation, excluded
    { kind: 'nogo', rt: 250 }, // false alarm
    { kind: 'nogo', rt: null },
  ]);
  assert.equal(r.reaction_ms_median, 340);
  assert.equal(r.reaction_ms_iqr, 40);
  assert.equal(r.lapses, 2);
  assert.equal(r.false_alarms, 1);
  assert.equal(reactionStats([]).reaction_ms_median, null);
});

test('schedule: ~20% no-go, never two in a row, first two always go', () => {
  let seed = 1;
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const s = makeSchedule(200, rand);
  assert.equal(s[0].kind, 'go');
  assert.equal(s[1].kind, 'go');
  for (let i = 1; i < s.length; i++) assert.ok(!(s[i].kind === 'nogo' && s[i - 1].kind === 'nogo'));
  const share = s.filter((t) => t.kind === 'nogo').length / s.length;
  assert.ok(share > 0.08 && share < 0.3, `share ${share}`);
  assert.ok(s.every((t) => t.isiMs >= 1200 && t.isiMs <= 2800));
});

test('expressivity: still face ~0, moving face higher, too few frames null', () => {
  const still = Array.from({ length: 40 }, () => [0.1, 0.2, 0.3]);
  const moving = Array.from({ length: 40 }, (_, i) => [i % 2 ? 0.8 : 0.1, i % 3 ? 0.6 : 0.0, 0.3]);
  assert.equal(expressivityIndex(still), 0);
  const m = expressivityIndex(moving)!;
  assert.ok(m > 0.5 && m <= 1, `m ${m}`);
  assert.equal(expressivityIndex(still.slice(0, 5)), null);
});

test('pairing: URL wins over storage, invalid values ignored, default home', () => {
  const p = parsePairing('?home=demo-aino&t=abcDEF123456', { home: 'other', token: 'storedtoken99' }, 'def');
  assert.deepEqual(p, { homeId: 'demo-aino', token: 'abcDEF123456', paired: true, fromUrl: { home: true, token: true } });
  const q = parsePairing('?home=Bad Home&t=x', { home: null, token: 'storedtoken99' }, 'def');
  assert.equal(q.homeId, 'def');
  assert.equal(q.token, 'storedtoken99');
  assert.deepEqual(q.fromUrl, { home: false, token: false });
  assert.equal(parsePairing('', { home: null, token: null }, 'def').paired, false);
});

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
