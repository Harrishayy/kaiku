// Run: pnpm test. Pure helpers behind the dashboard brand mark and the clinician view model.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ambientState, cssValue, glowAt, walkParts, type MascotSpec } from '../lib/mascot.ts';
import { consensusSentence, evidenceRows, num, sourceMissing, sparkline } from '../lib/clinician.ts';

const json = (p: string) => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const design = json('../../../design/copy.json');
const spec = json('../../../design/mascot.spec.json') as MascotSpec;
const tokens = json('../../../design/tokens.json');

test('labels: every state and verdict the dashboard shows comes from design/copy.json, approved wording only', () => {
  for (const k of ['state.stable', 'state.watch', 'state.needs_call', 'state.safety', 'state.insufficient', 'verdict.better', 'verdict.as_usual', 'verdict.worse', 'verdict.insufficient', 'common.simulated'])
    assert.equal(typeof design.en[k], 'string', k);
  assert.equal(design.en['verdict.worse'], 'Change from usual');
  const labels = readFileSync(new URL('../lib/labels.ts', import.meta.url), 'utf8');
  assert.ok(!/Worse than usual|relapse|diagnos/i.test(labels));
  assert.match(labels, /agreement === 'low_coverage'\) return \{ label: label\('state.insufficient'\)/);
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

const verdict = (source: 'robot' | 'glasses' | 'laptop' | 'wearable', v: 'better' | 'as_usual' | 'worse' | 'insufficient', extra = {}) => ({
  home_id: 'h', source, verdict: v, confidence: 0.8, computed_at: '', last_data_at: v === 'insufficient' ? null : '2026-11-13T10:00:00Z', ...extra,
});

test('clinician: missing data is never read as fine; numbers keep their precision', () => {
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
  assert.equal(rows[1].usual, '3.5 (2.4 to 4.6)');
  assert.equal(rows[1].z, '−4.0');
  assert.equal(rows[2].worse, false);
  assert.equal(consensusSentence(c), '2 of 3 signal groups with data show a change from usual');
  const sp = sparkline((series as { points: never[] }[])[0].points);
  assert.ok(sp && sp.band && sp.line.split(' ').length === 2);
});
