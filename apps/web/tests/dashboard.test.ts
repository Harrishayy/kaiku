import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { PANEL_IDS, defaultLayout, dropPanel, promotePanel, readLayout, shiftPanel, slots, togglePanel } from '../lib/layout.ts';
import { cleanText, compareSeries, daySignals, deriveReview, insightView, meaningOf, recordStage, recordedDays, trimLeading } from '../lib/insight.ts';
import { byDay, describeObs } from '../lib/evidence.ts';

test('layout: every panel count tiles the 12 × 12 grid exactly, so panels can never overlap or leave holes', () => {
  for (let n = 1; n <= PANEL_IDS.length; n++) {
    const cells = new Map<string, number>();
    const rects = slots(n);
    assert.equal(rects.length, n);
    for (const s of rects) {
      assert.ok(Number.isInteger(s.c[0]) && Number.isInteger(s.c[1]) && Number.isInteger(s.r[0]) && Number.isInteger(s.r[1]), `integer lines for ${n}`);
      for (let c = s.c[0]; c < s.c[1]; c++) for (let r = s.r[0]; r < s.r[1]; r++) cells.set(`${c},${r}`, (cells.get(`${c},${r}`) ?? 0) + 1);
    }
    assert.equal(cells.size, 144, `holes with ${n} panels`);
    assert.ok([...cells.values()].every((v) => v === 1), `overlap with ${n} panels`);
    const area = (s: (typeof rects)[number]) => (s.c[1] - s.c[0]) * (s.r[1] - s.r[0]);
    assert.ok(rects.every((s) => area(rects[0]) >= area(s)), 'the main panel is the largest');
  }
});

test('layout: saved layouts recover from junk, stale ids, duplicates and missing panels', () => {
  const full = (l: { order: string[]; docked: string[] }) => assert.deepEqual([...l.order, ...l.docked].sort(), [...PANEL_IDS].sort());
  for (const raw of [null, '', '{', '[]', '{"order":1}', '{"order":["trends","nope","trends"],"docked":["trends","care"]}', '{"order":[],"docked":[]}']) full(readLayout(raw));
  assert.deepEqual(readLayout('{"order":["care","nope","care"],"docked":[]}').order, ['care']);
  assert.equal(defaultLayout(1280, 720).order.length, 3);
  assert.equal(defaultLayout(1920, 1080).order.length, 5);
  assert.deepEqual(defaultLayout(1280, 720).order, ['trends', 'consensus', 'review'], 'the review is always open by default');
  assert.deepEqual(defaultLayout(1440, 900).order.slice(3), ['evidence', 'graph'], 'the map of the record is open where there is room');
  assert.equal(defaultLayout(1440, 900).docked[0], 'routine', 'Routine is the first chip in the dock');
  assert.equal(defaultLayout(1280, 720).order[0], 'trends');
});

test('layout: collapse, expand, keyboard shift, drag-drop and promote keep the complete panel set', () => {
  let l = defaultLayout(1920, 1080);
  const full = () => assert.deepEqual([...l.order, ...l.docked].sort(), [...PANEL_IDS].sort());
  l = togglePanel(l, 'trends');
  assert.ok(l.docked.includes('trends') && !l.order.includes('trends'));
  l = togglePanel(l, 'trends');
  assert.equal(l.order.at(-1), 'trends');
  full();
  const before = l.order.indexOf('review');
  l = shiftPanel(l, 'review', 1);
  assert.equal(l.order.indexOf('review'), before + 1);
  assert.equal(shiftPanel(l, l.order[0], -1), l, 'moving past the edge changes nothing');
  const [a, b] = [l.order[0], l.order[2]];
  l = dropPanel(l, a, b);
  assert.deepEqual([l.order[0], l.order[2]], [b, a]);
  l = dropPanel(l, 'coverage', l.order[1]);
  assert.equal(l.order[1], 'coverage');
  assert.ok(!l.docked.includes('coverage'));
  l = promotePanel(l, 'ask');
  assert.equal(l.order[0], 'ask');
  full();
});

const pt = (date: string, value: number | null, usual: number | null = null, lo: number | null = null, hi: number | null = null, early = false) => ({ date, value, baseline_median: usual, band_low: lo, band_high: hi, early });

test('meaning: every number is worded against the person’s own usual, in the unit’s language', () => {
  assert.equal(meaningOf(1412, 1370, 'min after midnight', 'up', 1350, 1395).text, '42 min later than their usual 22:50');
  assert.equal(meaningOf(1412, 1370, 'min after midnight', 'up', 1350, 1395).tone, 'worse');
  assert.equal(meaningOf(26, 15, 'min', 'down', 3, 27).text, '11 min longer than their usual 15 min');
  assert.equal(meaningOf(26, 15, 'min', 'down', 3, 27).tone, 'similar');
  assert.equal(meaningOf(2, 4, '1–5', 'down', 3.25, 4.75).text, '2 points lower than their usual 4 out of 5');
  assert.equal(meaningOf(2, 4, '1–5', 'down', 3.25, 4.75).range, 'Outside their usual range: a change from their usual');
  assert.equal(meaningOf(332, 390, 'ms', 'up', 360, 420).tone, 'better');
  assert.equal(meaningOf(4, 4, '1–5', 'down', 3, 5).text, 'Same as their usual 4 out of 5');
  assert.equal(meaningOf(null, 4, '1–5', 'down').text, 'Not recorded');
  assert.equal(meaningOf(0, null, 'min', 'down').text, 'Still building their usual');
  assert.equal(meaningOf(0, 20, 'min', 'down', 10, 30).tone, 'worse', 'zero is a recorded value');
});

const mood = {
  metric: 'mood', label: 'Mood dial', unit: '1–5', source: 'robot' as const, worse_when: 'down' as const,
  points: [
    pt('2026-10-28', null), pt('2026-10-29', 4), pt('2026-10-30', 4), pt('2026-10-31', 4), pt('2026-11-01', 4), pt('2026-11-02', 4), pt('2026-11-03', 4), pt('2026-11-04', 4),
    pt('2026-11-05', 4, 4, 3.25, 4.75, true), pt('2026-11-06', null, 4, 3.25, 4.75, true), pt('2026-11-07', 2, 4, 3.25, 4.75, true), pt('2026-11-08', 2, 4, 3.25, 4.75, true),
    pt('2026-11-09', 2, 4, 3.25, 4.75, true), pt('2026-11-10', 3, 4, 3.25, 4.75, true), pt('2026-11-11', 5, 4, 3.25, 4.75, true),
  ],
};
const consensus = (verdicts: Record<string, string>, state = 'watch', agreement = 'low_coverage') => ({
  home_id: 'h', state, agreement, rule_version: 'v', computed_at: '2026-11-11T08:00:00Z',
  sources: Object.entries(verdicts).map(([source, verdict]) => ({ home_id: 'h', source, verdict, confidence: 0.9, computed_at: '', last_data_at: verdict === 'insufficient' ? null : '2026-11-11T07:00:00Z', evidence: source === 'robot' && verdict === 'worse' ? [{ metric: 'mood', z: -2, direction: 'down', days: 4 }] : [] })),
  explanation: { headline: 'Aino (SIMULATED): watching', text: 'Aino (SIMULATED) shows change. Simulated data is labelled SIMULATED. Read on.', caveats: '', suggested_actions: [], by: 'template' },
}) as never;

test('record: leading empty days are trimmed, gaps kept, and the calibration stage is read from the data', () => {
  const s = trimLeading([mood as never]);
  assert.equal(s[0].points[0].date, '2026-10-29');
  assert.deepEqual(recordedDays(s), { days: 13, first: '2026-10-29', last: '2026-11-11', span: 14 });
  assert.deepEqual(recordStage(s), { day: 14, building: false, early: true, steadyAfter: null });
  const young = [{ ...mood, points: mood.points.slice(1, 5) }] as never;
  assert.equal(recordStage(young).building, true);
  assert.equal(recordStage(young).early, true);
});

test('day signals and period comparison: counts of measures outside their usual, calendar weeks, missing days visible', () => {
  const sig = daySignals([mood as never]);
  assert.deepEqual(sig.find((d) => d.date === '2026-11-07'), { date: '2026-11-07', measured: 1, compared: 1, changed: 1, better: 0, changedLabels: ['Mood dial'] });
  assert.equal(sig.find((d) => d.date === '2026-11-06')?.measured, 0);
  assert.equal(sig.find((d) => d.date === '2026-10-30')?.compared, 0, 'no usual yet: nothing to compare');
  assert.equal(sig.find((d) => d.date === '2026-11-11')?.better, 1);
  // a measure that is shown and not scored (face signs, more of the day from Apple Health) is charted, never counted
  const beside = { ...(mood as object), metric: 'deep_sleep', label: 'Deep sleep (watch)', scored: false };
  assert.deepEqual(daySignals([mood as never, beside as never]), sig);
  const c = compareSeries(mood as never, '2026-11-11', 'change_from_usual');
  assert.equal(c.days_this_week, 6);
  assert.equal(c.days_previous_week, 7);
  assert.equal(c.this_week, 2.5);
  assert.equal(c.previous_week, 4);
  assert.equal(c.vs_previous, 'worse');
  assert.equal(c.vs_usual, 'worse');
  assert.equal(c.early_baseline, true);
});

test('review fallback: cites real records, never claims a steady picture on thin data, strips provenance tags from prose', () => {
  const c = consensus({ robot: 'worse', glasses: 'insufficient', laptop: 'insufficient', wearable: 'insufficient' });
  const { review, evidence } = deriveReview(c, [mood as never], null, recordStage([mood as never]));
  assert.equal(review.by, 'template');
  assert.ok(!/SIMULATED/.test(review.headline));
  assert.equal(review.findings[0].theme, 'change');
  assert.deepEqual(review.findings[0].cites, ['metric:mood']);
  assert.equal(evidence[0].value, 5);
  assert.equal(evidence[0].observed_at, '2026-11-11');
  const coverage = review.findings.find((f) => f.theme === 'coverage');
  assert.match(coverage?.meaning ?? '', /3 of 4 signal groups cannot give a verdict/);
  assert.ok(!review.findings.some((f) => /\bstable\b/i.test(`${f.title} ${f.meaning}`)));
  assert.equal(cleanText('Aino (SIMULATED): too little data'), 'Aino: too little data');
  const view = insightView(null, c, [mood as never], null, null, [], {}, (s) => s);
  assert.equal(view.fromCloud, false);
  assert.deepEqual(view.trace, []);
  assert.equal(view.stage.early, true);
  assert.equal(view.coverage.groups.filter((g) => g.sufficient).length, 1);
});

test('evidence by day: plain sentences, envelope source kept, newest day first, fixed group order', () => {
  assert.deepEqual(describeObs({ type: 'obs.outing', payload: { minutes: 26, steps: 2600, method: 'steps' } }), { group: 'outing', title: 'Outing of 26 min', detail: '2,600 steps · measured by steps' });
  assert.equal(describeObs({ type: 'obs.phq9', payload: { total: 6, item9_positive: false } }).title, 'PHQ-9 questionnaire: 6 of 27');
  assert.equal(describeObs({ type: 'obs.wearable_daily', payload: { sleep_min: 440 } }).title, 'Slept 7 h 20 min');
  assert.equal(describeObs({ type: 'obs.something_new', payload: {} }).group, 'other');
  for (const type of ['obs.self_report', 'obs.play_session', 'obs.safety_flag', 'obs.nudge_outcome', 'obs.intervention_response'])
    assert.ok(!/payload|obs\.|undefined|null/.test(JSON.stringify(describeObs({ type, payload: {} }))), type);
  const days = byDay([
    { id: 'a', ts: '2026-11-12T12:00:00Z', source: 'phone', type: 'obs.outing', payload: { minutes: 10 }, sim: true },
    { id: 'b', ts: '2026-11-13T12:00:00Z', source: 'hub', type: 'obs.drum_session', payload: {} },
    { id: 'c', ts: '2026-11-13T12:05:00Z', source: 'phone', type: 'obs.safety_flag', payload: { trigger: 'manual' } },
  ]);
  assert.deepEqual(days.map((d) => d.count), [2, 1]);
  assert.deepEqual(days[0].groups.map((g) => g.group), ['safety', 'checkin']);
  assert.equal(days[1].groups[0].items[0].source, 'phone');
  assert.equal(days[1].groups[0].items[0].sim, true);
});

test('website scope: practitioner dashboard only; no person-facing routes, internal ids or banned words in the UI', () => {
  const app = new URL('../app/', import.meta.url);
  for (const gone of ['me', 'checkin', 'session', 'play', 'phq9', 'consent', 'live', 'clinician']) assert.ok(!existsSync(new URL(gone, app)), `${gone} route removed`);
  for (const kept of ['health', 'eval', 'tune']) assert.ok(existsSync(new URL(kept, app)), kept);
  const dir = new URL('../components/dash/', import.meta.url);
  const files = [...readdirSync(dir).filter((f) => f.endsWith('.tsx')).map((f) => new URL(f, dir)), ...readdirSync(new URL('panels/', dir)).map((f) => new URL(`panels/${f}`, dir))];
  for (const f of files) {
    const src = readFileSync(f, 'utf8').replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, '');
    assert.ok(!/monitoring|\bdemo\b|synthetic|diagnos|relapse|Worse than usual/i.test(src), `${f.pathname.split('/').pop()} wording`);
    assert.ok(!/patient\.id\}<|home_id\}</.test(src), 'no internal id rendered');
  }
  const css = readFileSync(new URL('../app/dashboard.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.ok(!/#[0-9a-fA-F]{3,8}\b|rgba?\(/.test(css), 'dashboard colours are tokens only');
  assert.ok(!/font-size:\s*[\d.]+(px|rem|em)/.test(css), 'dashboard type sizes are tokens only');
});

import { dayChips, dayValence } from '../lib/evidence.ts';

test('daily account: parts become typed chips; reflection level only, unknown phrases stay neutral', () => {
  const chips = dayChips(['morning ritual, drum session, game, walk (21 min), weather check', 'mood 3 of 5', "away from usual: mood dial, energy dial, last night's sleep and 14 more", 'evening reflection bright (outdoors)', 'care team follow-up']);
  assert.deepEqual(chips.filter((c) => c.kind === 'did').map((c) => c.label), ['Morning ritual', 'Drum session', 'Game', 'Walk (21 min)', 'Weather check']);
  assert.deepEqual(chips.filter((c) => c.kind !== 'did').map((c) => c.kind), ['mood', 'away', 'reflection', 'care']);
  assert.equal(chips.find((c) => c.kind === 'reflection')?.label, 'Reflection bright (outdoors)');
  assert.equal(dayValence(['evening reflection low (sleep)']), 'low');
  assert.equal(dayValence(['evening reflection ordinary (routine)']), 'neutral');
  assert.equal(dayValence(['reflection declined']), 'declined');
  assert.equal(dayValence(['mood 4 of 5']), null);
  assert.deepEqual(dayChips(['Morning ritual done, Out for 28 min, Energy dial below usual, 4 more measures away']).map((c) => c.kind), ['did', 'did', 'away', 'away']);
  assert.deepEqual(dayChips(['something new: the cloud said this']), [{ kind: 'other', label: 'Something new: the cloud said this' }]);
});
