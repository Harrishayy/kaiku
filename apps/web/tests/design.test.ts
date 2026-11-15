// Run: pnpm test. Pure helpers behind the dashboard brand mark and the clinician view model.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { cssValue, glowAt, walkParts, type MascotSpec } from '../lib/mascot.ts';
import { consensusSentence, num } from '../lib/clinician.ts';

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

test('mascot: transforms render as CSS values; every animated part exists in the spec', () => {
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

test('clinician: numbers keep their precision; the consensus sentence counts only groups with data', () => {
  assert.equal(num(543.2), '543');
  assert.equal(num(0.3333), '0.33');
  const c = {
    home_id: 'h', state: 'needs_call', agreement: 'agree', rule_version: 'v', computed_at: '',
    sources: [verdict('robot', 'worse'), verdict('laptop', 'worse'), verdict('glasses', 'as_usual'), verdict('wearable', 'insufficient')],
  } as never;
  assert.equal(consensusSentence(c), '2 of 3 signal groups with data show a change from usual');
});
