// Run: pnpm test. Pure helpers behind the person + clinician pages (copy, mascot, receipt, QR, clinician view model).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fill, greetKey, mergeTables, nameFromHome, parseLang, translate } from '../lib/copy.ts';
import { ambientState, cssValue, glowAt, walkParts, type MascotSpec } from '../lib/mascot.ts';
import { localMidnightIso, sawToday, togetherDays } from '../lib/saw.ts';
import { pairingUrl, qrPath } from '../lib/qr.ts';
import { consensusChip, consensusSentence, evidenceRows, num, sourceMissing, sparkline, verdictChip } from '../lib/clinician.ts';

const json = (p: string) => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const design = json('../../../design/copy.json');
const web = json('../lib/copy-web.json');
const spec = json('../../../design/mascot.spec.json') as MascotSpec;
const tokens = json('../../../design/tokens.json');

test('web copy: en and fi have the same keys and placeholders, no clinical words, no dev text', () => {
  assert.deepEqual(Object.keys(web.en).sort(), Object.keys(web.fi).sort());
  const ph = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join();
  const banned = /diagnos|relapse|predict|disorder|symptom|patient|depression|masennus|obs\.|config\/|\.toml|TODO|VERIFY/i;
  for (const k of Object.keys(web.en)) {
    assert.equal(ph(web.en[k]), ph(web.fi[k]), k);
    assert.ok(!banned.test(web.en[k]) && !banned.test(web.fi[k]), k);
  }
});

test('copy: design wins over web, fi falls back to en, a missing key never shows its name', () => {
  const t = mergeTables({ en: { a: 'design' }, fi: {} }, { en: { a: 'web', b: 'B {n}' }, fi: { b: 'Bfi {n}' } });
  assert.equal(translate(t, 'en', 'a'), 'design');
  assert.equal(translate(t, 'fi', 'a'), 'design');
  assert.equal(translate(t, 'fi', 'b', { n: 3 }), 'Bfi 3');
  assert.equal(translate(t, 'en', 'nope'), '');
  assert.equal(fill('{x} {y}', { x: 1 }), '1 {y}');
  const all = mergeTables(design, web);
  for (const k of ['me.hi', 'today.card.weather.t', 'mem.forgetall', 'saw.never', 'me.together.n', 'game.firefly.t'])
    assert.ok(translate(all, 'fi', k), k);
});

test('copy: language parsing, greeting by hour, name from home id', () => {
  assert.equal(parseLang('fi-FI'), 'fi');
  assert.equal(parseLang('sv'), null);
  assert.equal(greetKey(8), 'today.greet.morning');
  assert.equal(greetKey(23), 'today.greet.late');
  assert.equal(greetKey(3), 'today.greet.late');
  assert.equal(nameFromHome('demo-aino'), 'Aino');
});

test('mascot: ambient mood maps through the spec; crisis has no mascot', () => {
  assert.equal(ambientState(spec, 'idle'), 'idle');
  assert.equal(ambientState(spec, 'happy'), 'happy');
  assert.equal(ambientState(spec, 'cozy'), 'cozy');
  assert.equal(ambientState(spec, 'crisis'), null);
  assert.equal(cssValue('translate', [0, 28]), '0px 28px');
  assert.equal(cssValue('scale', [1, 1.025]), '1 1.025');
  const ids: string[] = [];
  walkParts(spec.parts, (p) => ids.push(p.id));
  for (const id of ['body', 'ear', 'lid-l', 'lid-r', 'glow', 'scarf']) assert.ok(ids.includes(id), id);
  for (const st of Object.values(spec.states)) for (const tr of st.tracks) assert.ok(ids.includes(tr.part), tr.part);
});

test('mascot: glow interpolates between tokens.json stops and wraps at 24 h', () => {
  const stops = tokens.glow.stops;
  assert.equal(glowAt(stops, 12).color.toLowerCase(), '#ffd98f');
  assert.equal(glowAt(stops, 2).color.toLowerCase(), '#6f82ba');
  const late = glowAt(stops, 23);
  assert.ok(late.intensity < 0.55 && late.intensity > 0.45);
});

test('saw today: counts and minutes only, stable order', () => {
  const lines = sawToday([
    { type: 'obs.outing', payload: { minutes: 20.4 } },
    { type: 'obs.outing', payload: { minutes: 10 } },
    { type: 'obs.self_report', payload: {} },
    { type: 'obs.self_report', payload: {} },
    { type: 'obs.ritual', payload: { step: 'close', status: 'completed' } },
    { type: 'obs.ritual', payload: { step: 'dial', status: 'completed' } },
    { type: 'obs.screen_activity', payload: {} },
    { type: 'obs.nudge_offered', payload: {} },
  ]);
  assert.deepEqual(lines, [
    { key: 'saw.l.ritual' },
    { key: 'saw.l.dial', vars: { n: 2 } },
    { key: 'saw.l.walk', vars: { n: 30 } },
    { key: 'saw.mac' },
  ]);
  assert.match(localMidnightIso(), /Z$/);
  assert.equal(togetherDays([{ date: 'a', kind: 'good' }, { date: 'a', kind: 'good' }, { date: 'b', kind: 'hard' }]), 1);
});

test('qr: a pairing link encodes to a square module path', () => {
  const url = pairingUrl('https://kaiku.example', 'demo-aino', 'tok');
  assert.equal(url, 'https://kaiku.example/me/?home=demo-aino&t=tok');
  const { size, d } = qrPath(url);
  assert.ok(size >= 25 && d.startsWith('M'));
});

const verdict = (source: 'robot' | 'glasses' | 'laptop' | 'wearable', v: 'better' | 'as_usual' | 'worse' | 'insufficient', extra = {}) => ({
  home_id: 'h', source, verdict: v, confidence: 0.8, computed_at: '', last_data_at: v === 'insufficient' ? null : '2026-11-13T10:00:00Z', ...extra,
});

test('clinician: consensus wording, never "fine" for missing data', () => {
  assert.equal(consensusChip('needs_call', 'agree').label, 'Needs a call');
  assert.equal(consensusChip('watch', 'agree').label, 'Worth a check-in');
  assert.equal(consensusChip('watch', 'low_coverage').label, 'Not enough data');
  assert.equal(consensusChip('stable', 'agree').label, 'Stable');
  assert.equal(verdictChip('insufficient').label, 'Not enough data');
  assert.equal(verdictChip(undefined).cls, 'ins');
  assert.equal(sourceMissing(verdict('wearable', 'insufficient') as never, [], 'wearable'), true);
  assert.equal(num(543.2), '543');
  assert.equal(num(0.3333), '0.33');
});

test('clinician: evidence rows join timeline numbers and rule readings, worse first', () => {
  const c = {
    home_id: 'h', state: 'needs_call', agreement: 'agree', rule_version: 'v', computed_at: '',
    sources: [
      verdict('robot', 'worse', { evidence: [{ metric: 'energy', z: -4, direction: 'down', days: 5 }] }),
      verdict('laptop', 'worse', { evidence: [{ metric: 'phq9_high', z: null, direction: 'up', days: 1, summary: 'PHQ-9 ≥ 10: 16' }] }),
      verdict('glasses', 'as_usual', { evidence: [{ metric: 'cadence', z: -3, direction: 'up', days: 5 }] }),
      verdict('wearable', 'insufficient'),
    ],
  } as never;
  const series = [
    { metric: 'energy', label: 'Energy dial', unit: '1–5', source: 'robot', worse_when: 'down',
      points: [{ date: 'd1', value: 4 }, { date: 'd2', value: 2, baseline_median: 3.5, band_low: 2.4, band_high: 4.6 }, { date: 'd3', value: null }] },
    { metric: 'cadence', label: 'Walking cadence', unit: 'steps/min', source: 'glasses', worse_when: 'down', points: [] },
  ] as never;
  const rows = evidenceRows(c, series);
  // rule triggers (no z) first, then the biggest drift in the worse direction
  assert.equal(rows[0].label, 'PHQ-9 ≥ 10');
  assert.equal(rows[0].today, '16');
  assert.equal(rows[1].label, 'Energy dial');
  assert.equal(rows[1].today, '2');
  assert.equal(rows[1].usual, '3.5 (2.4–4.6)');
  assert.equal(rows[1].z, '−4.0');
  assert.equal(rows[2].worse, false);
  assert.equal(consensusSentence(c), '2 of 3 sources with data show a change from usual');
  const sp = sparkline((series as { points: never[] }[])[0].points);
  assert.ok(sp && sp.band && sp.line.split(' ').length === 2);
});
