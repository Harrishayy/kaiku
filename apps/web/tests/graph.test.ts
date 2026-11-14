import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  type GraphIn,
  anchorOf,
  buildHoods,
  edgeWords,
  fillGraph,
  fitLabel,
  hoodCaption,
  hoodNotable,
  hoodOnDay,
  latestDay,
  layoutHood,
  layoutMap,
  linkLines,
  linkPath,
  neighboursOf,
  nodeOnDay,
  personPath,
  rowLabel,
  rowValue,
} from '../lib/graph-layout.ts';

type N = GraphIn['nodes'][number];
type E = GraphIn['edges'][number];

const day = (date: string, tone = 'unknown', value = '', text = value) => ({ date, tone, value, text }) as N['days'][number];
const node = (id: string, kind: N['kind'], domain: string, label = id, days: N['days'] = [], extra: Partial<N> = {}): N => ({ id, kind, domain, label, detail: null, evidence: 3, tone: 'unknown', layer: 'learned', days, ...extra });
const edge = (src: string, dst: string, rel: E['rel'], label: string = rel, extra: Partial<E> = {}): E => ({ src, dst, rel, label, weight: 0.7, evidence: 4, layer: 'learned', on: [], tag: '', ...extra });

const DOMAINS: NonNullable<GraphIn['domains']> = [
  { id: 'morning', label: 'Mornings and the ritual', short: 'Mornings', place: 'nw' },
  { id: 'mood', label: 'Mood and energy', short: 'Mood', place: 'n' },
  { id: 'movement', label: 'Movement and the outdoors', short: 'Movement', place: 'ne' },
  { id: 'people', label: 'People and contact', short: 'People', place: 'e' },
  { id: 'notebook', label: 'What they tell Kaiku', short: 'Notebook', place: 'se' },
  { id: 'care', label: 'Care', short: 'Care', place: 'sw' },
  { id: 'screens', label: 'Screens and games', short: 'Screens', place: 's' },
  { id: 'sleep', label: 'Sleep and body', short: 'Sleep', place: 'w' },
];

/** a record shaped like a full one: every neighbourhood filled, two days */
function record(): GraphIn {
  const d1 = '2026-11-08';
  const d2 = '2026-11-09';
  const nodes: N[] = [
    node('person', 'person', '', 'Aino'),
    node('group:robot', 'signal_group', '', 'Check-ins & robot'),
    node('activity:drum', 'activity', 'morning', 'Drum sessions (robot)', [day(d1, 'unknown', '07:24')]),
    node('routine:drum', 'routine', 'morning', 'Drum sessions · around 07:24', [day(d1, 'similar', '07:24', 'done at 07:24'), day(d2, 'worse', 'missed', 'not recorded on this day')]),
    node('activity:ritual', 'activity', 'morning', 'Morning ritual (robot)', [day(d1, 'unknown', '07:20'), day(d2, 'unknown', '08:57')]),
    node('routine:ritual', 'routine', 'morning', 'Morning ritual · around 07:22', [day(d1, 'similar', '07:20'), day(d2, 'similar', '08:57')]),
    node('measure:getup', 'measure', 'morning', 'First interaction time', [day(d1, 'similar', '07:18'), day(d2, 'worse', '08:49', '08:49, later than their usual 07:15')]),
    node('measure:drum_tempo', 'measure', 'morning', 'Drum tempo', [day(d1, 'similar', '104 bpm')]),
    node('talk:routine', 'shared_topic', 'morning', 'Talked about: routine', [day(d2, 'unknown', 'came up')]),
    node('activity:checkin', 'activity', 'mood', 'Self-report check-ins (apps)'),
    node('measure:mood', 'measure', 'mood', 'Mood dial', [day(d1, 'similar', '4 of 5'), day(d2, 'worse', '2 of 5', '2 of 5, below their usual 4 of 5')]),
    node('measure:energy', 'measure', 'mood', 'Energy dial', [day(d1, 'unknown', '4 of 5'), day(d2, 'better', '5 of 5')]),
    node('activity:walk', 'activity', 'movement', 'Walks and outings', [day(d1, 'unknown', '15:02')]),
    node('routine:walk', 'routine', 'movement', 'Walks and outings · around 15:00', [day(d1, 'similar', '15:02')]),
    node('measure:steps', 'measure', 'movement', 'Steps on walks', [day(d1, 'similar', '3,900 steps')]),
    node('measure:daily_steps', 'measure', 'movement', 'Daily steps (watch)', [day(d2, 'worse', '2,700 steps')]),
    node('talk:outdoors', 'shared_topic', 'movement', 'Talked about: outdoors'),
    node('measure:communication_min', 'measure', 'people', 'Time in messages & calls apps', [day(d2, 'worse', '4 min')]),
    node('talk:being alone', 'shared_topic', 'people', 'Talked about: being alone'),
    node('topic:people', 'shared_topic', 'people', 'People in their notebook'),
    node('topic:likes', 'shared_topic', 'notebook', 'Things they like'),
    node('care:0', 'care_action', 'care', 'Care team follow-up · 10 Nov'),
    node('activity:play', 'activity', 'screens', 'Games (apps)'),
    node('measure:late_night', 'measure', 'screens', 'Late-night screen time (00–05)', [day(d2, 'worse', '1 h 36 min')]),
    node('routine:sleep', 'routine', 'sleep', 'Asleep · around 23:33', [day(d1, 'unknown', '23:41')]),
    node('measure:watch_sleep', 'measure', 'sleep', 'Sleep (watch)', [day(d2, 'worse', '5 h 53 min')]),
    node('measure:sleep_midpoint', 'measure', 'sleep', "Middle of the night's sleep (later = up)", [day(d2, 'worse', '05:00')]),
    node('measure:hrv_sdnn', 'measure', 'sleep', 'Heart rate variability (watch, SDNN)', [day(d2, 'worse', '29 ms')]),
    node('measure:new_thing', 'measure', 'not-declared', 'A new measure'),
  ];
  const edges: E[] = [
    edge('routine:drum', 'activity:drum', 'of'),
    edge('routine:ritual', 'activity:ritual', 'of'),
    edge('routine:walk', 'activity:walk', 'of'),
    edge('activity:ritual', 'measure:getup', 'produces', 'recorded together on 15 days'),
    edge('activity:ritual', 'measure:mood', 'produces', 'recorded together on 15 days'),
    edge('activity:drum', 'measure:drum_tempo', 'produces', 'recorded together on 13 days'),
    edge('activity:checkin', 'measure:mood', 'produces', 'recorded together on 5 days'),
    edge('activity:walk', 'measure:steps', 'produces', 'recorded together on 15 days'),
    edge('routine:sleep', 'measure:watch_sleep', 'produces', 'recorded together on 15 days'),
    edge('talk:outdoors', 'activity:walk', 'about', 'about the same part of life'),
    edge('talk:routine', 'activity:ritual', 'about', 'about the same part of life'),
    edge('person', 'measure:late_night', 'moved_first', 'first to move, 6 Nov', { on: ['2026-11-06'], tag: 'first' }),
    edge('measure:late_night', 'measure:mood', 'followed', 'moved 1 day later (order, not cause)', { on: ['2026-11-07'], tag: '+1 day' }),
    edge('measure:late_night', 'measure:energy', 'followed', 'moved 1 day later (order, not cause)', { on: ['2026-11-07'], tag: '+1 day' }),
    edge('measure:mood', 'measure:daily_steps', 'moved_together', 'away from usual on the same 4 days', { tag: '4 days' }),
    edge('care:0', 'measure:mood', 'after', 'back within usual 2 days after', { on: ['2026-11-12'], tag: '+2 days' }),
    edge('activity:walk', 'person', 'helped', 'building reported response, 7 attempts', { evidence: 7 }),
    edge('person', 'routine:ritual', 'kept_through', '5 of 6 days while measures were away from usual'),
    edge('person', 'activity:walk', 'did', '15 days', { layer: 'structure' }),
  ];
  return { nodes, edges, domains: DOMAINS, days: [d1, d2].map((date) => ({ date, recorded: true, away: 0, changes: [] })) };
}

test('graph map: nodes sit in the neighbourhood the cloud declared, as a small tree', () => {
  const g = record();
  const { person, hoods } = buildHoods(g);
  assert.equal(person?.id, 'person');
  const by = new Map(hoods.map((h) => [h.id, h]));
  assert.deepEqual([...by.keys()], ['morning', 'mood', 'movement', 'people', 'notebook', 'care', 'screens', 'sleep', 'other']);
  assert.ok(!hoods.some((h) => h.nodes.some((n) => n.kind === 'person' || n.kind === 'signal_group')), 'who sent a record is not what it is about');

  // an activity with its routine on the same row, by the day's rhythm; what it produces under it, then its theme
  const morning = by.get('morning')!;
  assert.deepEqual(morning.rows.map((r) => [r.node.id, r.depth, r.parent, r.chip?.id ?? null]), [
    ['activity:ritual', 0, null, 'routine:ritual'],
    ['measure:getup', 1, 'activity:ritual', null],
    ['talk:routine', 1, 'activity:ritual', null],
    ['activity:drum', 0, null, 'routine:drum'],
    ['measure:drum_tempo', 1, 'activity:drum', null],
  ]);
  assert.equal(morning.nodes.length, 7, 'a routine on a row still belongs to the neighbourhood');
  // a measure hangs under the activity of its own neighbourhood only; the mood dial is produced in two places
  assert.deepEqual(by.get('mood')!.rows.map((r) => [r.node.id, r.depth]), [['activity:checkin', 0], ['measure:mood', 1], ['measure:energy', 0]]);
  // a routine without an activity node is a row of its own, with what it produces
  assert.deepEqual(by.get('sleep')!.rows.slice(0, 2).map((r) => [r.node.id, r.depth, r.parent]), [['routine:sleep', 0, null], ['measure:watch_sleep', 1, 'routine:sleep']]);
  assert.deepEqual(by.get('movement')!.rows.map((r) => r.node.id), ['activity:walk', 'measure:steps', 'talk:outdoors', 'measure:daily_steps']);
  // a node the cloud gave no known domain is kept on its own, never dropped and never put where it was not declared
  assert.deepEqual(by.get('other')!.rows.map((r) => r.node.id), ['measure:new_thing']);
  assert.equal(by.get('other')!.place, 'x', 'all eight places are taken: it sits under the person');
  assert.equal(buildHoods({ ...g, domains: DOMAINS.slice(0, 7) }).hoods.find((h) => h.id === 'other')!.place, 'w', 'otherwise in the free place');
  // every node is placed exactly once
  const placed = hoods.flatMap((h) => h.rows.flatMap((r) => [r.node.id, ...(r.chip ? [r.chip.id] : [])]));
  assert.equal(new Set(placed).size, placed.length);
  assert.equal(placed.length, g.nodes.length - 2);
});

test('graph map: without domains (the fallback view) nodes are grouped by kind, and every node shows', () => {
  const g = record();
  const { hoods } = buildHoods({ nodes: g.nodes.map((n) => ({ ...n, domain: '', days: [] })), edges: g.edges });
  assert.deepEqual(hoods.map((h) => h.id), ['doing', 'measures', 'told', 'care']);
  assert.equal(hoods.reduce((s, h) => s + h.nodes.length, 0), g.nodes.length - 2);
  assert.equal(nodeOnDay(hoods[1].nodes[0], null).lit, true, 'no day data: every node is shown with its overall tone');
  // a graph from a service that predates the map: the missing lists read as empty, a whole graph is left alone
  const old = { nodes: g.nodes.map(({ domain: _d, days: _y, ...n }) => n), edges: g.edges.map(({ on: _o, tag: _t, ...e }) => e) } as never;
  const filled = fillGraph(old) as GraphIn;
  assert.deepEqual([filled.domains, filled.days, filled.nodes[0].days, filled.nodes[0].domain, filled.edges[0].on, filled.edges[0].tag], [[], [], [], '', [], '']);
  assert.deepEqual(buildHoods(filled).hoods.map((h) => h.id), ['doing', 'measures', 'told', 'care']);
  const whole = { ...g, domains: g.domains!, days: g.days! };
  assert.equal(fillGraph(whole), whole);
});

const overlap = (a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

test('graph map: the same graph and size give the same picture, and nothing overlaps at any panel size', () => {
  const { hoods } = buildHoods(record());
  // the maximised panel at 1280 × 720 and 1440 × 900, the main panel, and a room too small for the rows
  for (const [w, h] of [[904, 420], [1060, 600], [660, 420], [640, 180]] as const) {
    const a = layoutMap(hoods, w, h);
    assert.deepEqual(layoutMap(buildHoods(record()).hoods, w, h), a, 'deterministic');
    assert.ok(a.pitch >= 16 && a.pitch <= 24);
    assert.ok(a.h >= h, 'the picture grows rather than squeeze rows together');
    assert.equal(a.rows.length, hoods.reduce((s, x) => s + x.rows.length, 0));
    for (const p of a.hoods) {
      assert.ok(p.x >= 0 && p.x + p.w <= a.w + 0.5 && p.y >= 0 && p.y + p.h <= a.h + 0.5, `${p.hood.id} is inside the picture`);
      for (const q of a.hoods) if (p !== q) assert.ok(!overlap(p, q), `${p.hood.id} and ${q.hood.id} do not overlap at ${w} × ${h}`);
      const rows = a.rows.filter((r) => r.hood === p.hood.id);
      rows.forEach((r, i) => {
        if (i) assert.ok(r.y - rows[i - 1].y >= a.pitch - 0.01, 'one row per node, a line apart');
        assert.ok(r.y - a.pitch / 2 >= p.y && r.y + a.pitch / 2 <= p.y + p.h + 0.5, 'rows are inside their neighbourhood');
        // label, value and mark are separate boxes inside the neighbourhood
        assert.ok(r.labelX >= p.x && r.labelX + r.labelW <= p.x + p.w, 'label inside');
        assert.ok(r.labelW >= 60, `a label keeps room to be read at ${w} wide (${r.labelW})`);
        if (r.valueW) {
          assert.ok(r.valueX >= r.labelX + r.labelW, 'the value follows the label');
          assert.ok(r.valueX + r.valueW <= p.x + p.w);
          assert.ok(r.markX < r.labelX || r.markX > r.valueX + r.valueW, 'the mark is outside both');
        }
      });
    }
    // the person sits in the middle column, between the neighbourhoods above and below
    const north = a.hoods.find((p) => p.hood.place === 'n')!;
    const south = a.hoods.find((p) => p.hood.place === 's')!;
    const extra = a.hoods.find((p) => p.hood.place === 'x')!;
    assert.ok(a.person && a.person.y > north.y + north.h && a.person.y < extra.y && extra.y + extra.h <= south.y);
    // left neighbourhoods face the person: their marks are on the inner edge
    const left = a.rows.find((r) => r.hood === 'sleep')!;
    assert.equal(left.side, 'left');
    assert.ok(left.markX > left.labelX + left.labelW);
  }
  // places mean the same thing in every record: west on the left, east on the right
  const wide = layoutMap(hoods, 1060, 600);
  const at = (id: string) => wide.hoods.find((p) => p.hood.id === id)!;
  assert.ok(at('sleep').x < at('mood').x && at('mood').x < at('people').x);
  assert.ok(at('morning').y < at('sleep').y && at('sleep').y < at('care').y);
  assert.ok(at('mood').y < wide.person!.y && wide.person!.y < at('screens').y);
  // one neighbourhood on its own: a single column
  const one = layoutHood(hoods[0], 276);
  assert.equal(one.rows.length, hoods[0].rows.length);
  assert.ok(one.rows.every((r) => r.labelW > 80 && r.valueX + r.valueW <= 276));
});

test('graph map: links attach at the mark facing the person and curve the same way every time', () => {
  const { hoods } = buildHoods(record());
  const lay = layoutMap(hoods, 1060, 600);
  const sleep = anchorOf(lay, 'measure:watch_sleep')!;
  const steps = anchorOf(lay, 'measure:daily_steps')!;
  assert.equal(sleep.out, 1);
  assert.equal(steps.out, -1);
  assert.equal(anchorOf(lay, 'routine:drum')!.y, anchorOf(lay, 'activity:drum')!.y, 'a routine shares its activity row');
  assert.notEqual(anchorOf(lay, 'routine:drum')!.x, anchorOf(lay, 'activity:drum')!.x);
  assert.equal(anchorOf(lay, 'person')!.out, 0);
  assert.equal(anchorOf(lay, 'nobody'), null);
  // a middle-column node linked to the right leaves from the far end of its row, not across its own label
  const mood = anchorOf(lay, 'measure:mood', steps)!;
  assert.equal(mood.out, 1);
  assert.ok(mood.x > anchorOf(lay, 'measure:mood')!.x);
  assert.equal(linkPath(sleep, steps), linkPath(sleep, steps));
  assert.match(linkPath(sleep, steps), /^M[\d.]+,[\d.]+C/);
});

/** points along a path made of M, H, C and L (absolute), as the panel draws them */
function along(d: string): { x: number; y: number }[] {
  const out: { x: number; y: number }[] = [];
  let at = { x: 0, y: 0 };
  for (const [, cmd, rest] of d.matchAll(/([MHCL])([^MHCL]*)/g)) {
    const n = rest.trim().split(/[ ,]+/).map(Number);
    const from = at;
    if (cmd === 'M') at = { x: n[0], y: n[1] };
    if (cmd === 'H') at = { x: n[0], y: from.y };
    if (cmd === 'L') at = { x: n[0], y: n[1] };
    if (cmd === 'C') at = { x: n[4], y: n[5] };
    for (let i = 0; i <= 24; i++) {
      const t = i / 24;
      const u = 1 - t;
      if (cmd === 'C') out.push({ x: u ** 3 * from.x + 3 * u * u * t * n[0] + 3 * u * t * t * n[2] + t ** 3 * n[4], y: u ** 3 * from.y + 3 * u * u * t * n[1] + 3 * u * t * t * n[3] + t ** 3 * n[5] });
      else if (cmd !== 'M') out.push({ x: from.x + (at.x - from.x) * t, y: from.y + (at.y - from.y) * t });
    }
  }
  return out;
}

test('graph map: a line to the person turns in the corridor and crosses no neighbourhood on its way', () => {
  const { hoods } = buildHoods(record());
  for (const [w, h] of [[904, 420], [1060, 600], [660, 420]] as const) {
    const lay = layoutMap(hoods, w, h);
    const person = lay.person!;
    const inside = (p: { x: number; y: number }, skip: string) => lay.hoods.find((q) => q.hood.id !== skip && p.x > q.x + 0.5 && p.x < q.x + q.w - 0.5 && p.y > q.y + 0.5 && p.y < q.y + q.h - 0.5);
    // every neighbourhood at the side, from where its trunk meets the spoke
    for (const p of lay.hoods.filter((q) => q.col !== 1)) {
      const d = personPath(lay, p.port);
      assert.equal(d, personPath(lay, p.port), 'the same every time');
      const pts = along(d);
      assert.deepEqual(pts.at(-1), { x: person.x, y: person.y });
      for (const pt of pts) assert.equal(inside(pt, p.hood.id), undefined, `${p.hood.id} at ${w} × ${h}: the spoke stays out of ${inside(pt, p.hood.id)?.hood.id}`);
    }
    // a node at the side (walks: reported to help) and one in the middle column (the mood dial, above the person)
    for (const id of ['activity:walk', 'measure:watch_sleep', 'measure:mood', 'measure:late_night']) {
      const a = anchorOf(lay, id)!;
      const own = lay.rows.find((r) => r.node.id === id)!.hood;
      for (const pt of along(personPath(lay, a))) assert.equal(inside(pt, own), undefined, `${id} at ${w} × ${h}`);
    }
  }
  assert.equal(personPath(layoutHood(hoods[0], 276), { x: 10, y: 10 }), '', 'no person in a single neighbourhood');
});

test('graph map: a caption never cuts a count, and a label has the room its values leave on every day', () => {
  const hood = { label: 'Mornings and the ritual', short: 'Mornings' };
  const s = { text: '1 of 3 away from usual · 1 missed', brief: '1 of 3 away' };
  assert.deepEqual(hoodCaption(hood, s, 420), { name: 'Mornings and the ritual', sum: '1 of 3 away from usual · 1 missed' });
  assert.deepEqual(hoodCaption(hood, s, 290), { name: 'Mornings', sum: '1 of 3 away from usual · 1 missed' });
  assert.deepEqual(hoodCaption(hood, s, 215), { name: 'Mornings', sum: '1 of 3 away · 1 missed' });
  assert.deepEqual(hoodCaption(hood, s, 150), { name: 'Mornings', sum: '1 of 3 away' });
  assert.equal(hoodCaption(hood, { text: 'within usual', brief: 'within usual' }, 250).name, 'Mornings and the ritual');
  // what a row prints beside its label
  const g = record();
  const by = new Map(g.nodes.map((n) => [n.id, n]));
  assert.equal(rowValue(by.get('topic:likes')!, ''), '3×', 'a theme or a notebook topic prints its count');
  assert.equal(rowValue(by.get('talk:routine')!, 'came up'), '3×');
  assert.equal(rowValue(by.get('measure:mood')!, '2 of 5'), '2 of 5');
  assert.equal(rowValue(by.get('care:0')!, 'logged'), '');
  const lay = layoutMap(buildHoods(g).hoods, 1060, 600);
  const row = (id: string) => lay.rows.find((r) => r.node.id === id)!;
  // a short value leaves its label more room than a long one; a node that never prints one gives it all
  assert.ok(row('measure:mood').valueW < row('measure:watch_sleep').valueW);
  assert.ok(row('measure:mood').valueW >= '2 of 5'.length * 6.4);
  assert.equal(row('activity:checkin').valueW, 0);
  assert.equal(row('care:0').valueW, 0);
  assert.ok(row('activity:checkin').labelW > row('measure:mood').labelW);
  assert.ok(row('activity:drum').valueW >= 52, 'a routine on the row keeps the whole value box');
});

test('graph map: a day lights what was recorded, tones measures and routines, and sums each neighbourhood', () => {
  const g = record();
  const { hoods } = buildHoods(g);
  const by = new Map(g.nodes.map((n) => [n.id, n]));
  assert.equal(latestDay(g.days!), '2026-11-09');
  assert.equal(latestDay([{ date: '2026-11-09', recorded: true }, { date: '2026-11-10', recorded: false }]), '2026-11-09', 'the latest day with data');
  assert.deepEqual(nodeOnDay(by.get('measure:mood')!, '2026-11-09'), { lit: true, look: 'worse', value: '2 of 5', text: '2 of 5, below their usual 4 of 5' });
  assert.equal(nodeOnDay(by.get('measure:mood')!, '2026-11-01').look, 'off');
  assert.equal(nodeOnDay(by.get('routine:drum')!, '2026-11-09').look, 'worse', 'a missed routine');
  assert.equal(nodeOnDay(by.get('routine:sleep')!, '2026-11-08').look, 'plain', "a night's onset is shown, not judged");
  assert.equal(nodeOnDay(by.get('activity:walk')!, '2026-11-08').look, 'plain');
  assert.equal(nodeOnDay(by.get('topic:likes')!, '2026-11-09').look, 'still', 'a notebook count is never dated');
  const sum = (id: string, date: string | null) => hoodOnDay(hoods.find((h) => h.id === id)!, date);
  assert.equal(sum('sleep', '2026-11-09').text, '3 of 3 away from usual');
  assert.equal(sum('sleep', '2026-11-09').brief, '3 of 3 away');
  assert.equal(sum('morning', '2026-11-09').text, '1 of 1 away from usual · 1 missed');
  assert.equal(sum('morning', '2026-11-08').text, 'within usual');
  assert.equal(sum('mood', '2026-11-09').text, '1 of 2 away from usual · 1 better');
  assert.equal(sum('mood', '2026-11-08').text, 'within usual', 'a reading without a usual is not counted as scored');
  assert.equal(sum('care', '2026-11-09').text, 'no action this day');
  // what came back after a care action is counted where the action lives, on the day it came back
  const care = hoods.find((h) => h.id === 'care')!;
  assert.deepEqual([hoodOnDay(care, '2026-11-12', g.edges).text, hoodOnDay(care, '2026-11-12', g.edges).brief], ['1 back within usual after it', '1 back after it']);
  assert.equal(hoodOnDay(care, '2026-11-09', g.edges).text, 'no action this day');
  assert.equal(sum('notebook', '2026-11-09').text, 'counts only');
  assert.equal(sum('screens', '2026-11-08').text, 'nothing recorded');
  // zoomed out: the telling nodes first, and an activity with its kept routine named once
  const morning = hoodNotable(hoods.find((h) => h.id === 'morning')!, '2026-11-09').map((x) => x.node.id);
  assert.deepEqual(morning, ['measure:getup', 'routine:drum', 'activity:ritual', 'talk:routine']);
  for (const h of hoods) for (const d of ['2026-11-08', '2026-11-09', null]) assert.ok(!/undefined|NaN/.test(hoodOnDay(h, d).text + hoodOnDay(h, d).brief));
});

test('graph map: links read as sentences, grouped, and order in time is never worded as cause', () => {
  const g = record();
  const lines = linkLines('measure:mood', g.edges);
  assert.deepEqual(lines.map((l) => l.rel), ['followed', 'moved_together', 'after', 'produces']);
  const said = (l: (typeof lines)[number]) => `${l.lead} ${l.others.join(', ')} ${l.tail}`.replace(/\s+/g, ' ').trim();
  assert.equal(said(lines[0]), 'Moved away 1 day later than measure:late_night (order, not cause)');
  assert.equal(said(lines[1]), 'Away from usual on the same 4 days as measure:daily_steps');
  assert.equal(said(lines[2]), 'Back within usual 2 days after care:0 (order in time, not proof of effect)');
  assert.deepEqual(lines[3].others, ['activity:ritual', 'activity:checkin'], 'the two activities that give readings of it, told once');
  // from the first mover: everything that followed, in one line
  const first = linkLines('measure:late_night', g.edges);
  assert.deepEqual(first.map((l) => [l.rel, l.others]), [['moved_first', []], ['followed', ['measure:mood', 'measure:energy']]]);
  assert.match(first[0].lead, /first to move away from usual, 6 Nov/);
  const walk = linkLines('activity:walk', g.edges).map(said).join(' | ');
  assert.match(walk, /Reported response: 7 tries · uncertain .*not proof of effect/);
  assert.match(walk, /Kept as a routine: routine:walk/);
  assert.match(walk, /They talk about it: talk:outdoors \(a theme count, never their words\)/);
  const everything = g.nodes.flatMap((n) => linkLines(n.id, g.edges).map(said)).join(' ');
  assert.ok(!/\b(because|caused|causes|due to|led to|predict\w*|diagnos\w*|relapse)\b/i.test(everything.replace(/not cause/g, '')));
  // focus keeps what a node is linked to by something learned or declared; how the record is organised does not count
  assert.deepEqual([...neighboursOf('measure:mood', g.edges)].sort(), ['activity:checkin', 'activity:ritual', 'care:0', 'measure:daily_steps', 'measure:late_night', 'measure:mood']);
  assert.ok(!neighboursOf('activity:walk', g.edges).has('person'));
  assert.equal(edgeWords({ rel: 'helped', label: 'helped', evidence: 8, weight: 0.7 } as never), 'helped · 8 tries · uncertain');
  assert.equal(edgeWords({ rel: 'followed', label: 'followed within a day', evidence: 4, weight: 1 } as never), 'followed within a day · 4 records');
});

test('graph map: labels are cut to their box, a bracket goes first, a theme is named as a theme', () => {
  assert.equal(fitLabel('Heart rate variability (watch, SDNN)', 140), 'Heart rate variabil…');
  assert.equal(fitLabel('Watch', 140), 'Watch');
  assert.equal(rowLabel('Sleep (watch)', 200), 'Sleep (watch)');
  assert.equal(rowLabel('Heart rate variability (watch, SDNN)', 160), 'Heart rate variability');
  assert.equal(rowLabel("Middle of the night's sleep (later = up)", 120), "Middle of the nig…");
  assert.equal(rowLabel('Talked about: being alone', 200), 'Theme: being alone');
  for (const px of [60, 90, 120, 200]) assert.ok(rowLabel("Middle of the night's sleep (later = up)", px).length * 6.6 <= px + 6.6);
});

test('graph map: the panel draws only what the cloud sent, in tokens, and keeps the privacy note', () => {
  const src = readFileSync(new URL('../components/dash/panels/GraphPanel.tsx', import.meta.url), 'utf8');
  assert.ok(src.includes('graph.note'), 'the privacy note from the cloud is shown');
  assert.ok(!/Aino|Riitta|2026-/.test(src), 'no person data in the panel');
  assert.ok(!/\b(caused|because of|predicts?|diagnos\w*|relapse)\b/i.test(src.replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, '')));
  assert.ok(/never cause/.test(src), 'the key says that links are never cause');
  assert.ok(/role="slider"/.test(src) && /aria-valuetext/.test(src), 'the day scrubber is one keyboard stop with a spoken value');
  const css = readFileSync(new URL('../app/dashboard.css', import.meta.url), 'utf8');
  for (const rel of ['helped', 'followed', 'moved_together', 'after', 'talked_about']) assert.ok(css.includes(`.d-glink-${rel}`), `${rel} has its own stroke`);
  for (const look of ['better', 'worse', 'similar', 'unknown', 'plain']) assert.ok(css.includes(`.d-look-${look} .d-gmark`), `${look} has its own mark`);
});
