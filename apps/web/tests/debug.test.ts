// Run: pnpm test. Pure helpers behind the team's /debug/ page, plus its scope guards.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import {
  METRIC_COLUMNS,
  NO_EVENT_FILTER,
  NO_METRIC_FILTER,
  anchorOf,
  askCost,
  callOutcome,
  callSummary,
  citeTarget,
  claimGroups,
  conversationSummary,
  dayFraction,
  debugPath,
  diffDay,
  diffEmpty,
  diffLine,
  countsElsewhere,
  eventsBehind,
  fallbackWords,
  filterEvents,
  filterMetrics,
  isDate,
  laneCounts,
  laneOf,
  latency,
  localClock,
  localStamp,
  metricCounts,
  modelTotals,
  num,
  orderCalls,
  payloadLine,
  pickRead,
  problemKind,
  rejectedTotal,
  resolveCites,
  shiftDate,
  signed,
  slowestCall,
  sortMetrics,
  stampedOutside,
  toolsInOrder,
  typeCounts,
  usableOf,
  usd,
} from '../lib/debug.ts';

const SOURCE_OF = { 'obs.self_report': 'robot', 'obs.drum_session': 'robot', 'obs.outing': 'glasses', 'obs.wearable_daily': 'wearable', 'obs.play_session': 'laptop' };

const metric = (name: string, extra: Record<string, unknown> = {}) =>
  ({
    id: `metric:${name}`, metric: name, label: name, unit: '', source: 'robot', obs: 'obs.self_report', value: 3, readings: 1,
    baseline: { median: 3, spread: 1, days: 10, early: false }, z: 0, worse_z: 0, direction: 'down', z_threshold: 1.5, beyond_today: false,
    status: 'normal', worse_days: 0, better_days: 0, scored_days: 5, drift_days_needed: 3, weight: 1, enabled: true, scored: true, flagged: false, event_ids: [],
    ...extra,
  }) as never;

const event = (id: string, source: string, type: string, extra: Record<string, unknown> = {}) =>
  ({ id, ts: '2026-11-09T08:00:00Z', local_time: '10:00:00', source, type, sim: false, quality: null, payload: {}, metrics: [], ...extra }) as never;

const day = (extra: Record<string, unknown> = {}) =>
  ({
    home_id: 'h', date: '2026-11-09', timezone: 'Europe/Helsinki', day_start: '2026-11-08T22:00:00Z', day_end: '2026-11-09T22:00:00Z', is_today: true, sim: false,
    events: [], events_total: 0, metrics: [], verdicts: [], consensus: { id: 'consensus:state', state: 'stable', raw_state: 'stable', agreement: 'agree', rule_version: 'v' },
    conversations: [], model_calls: [], facts: [], read: {}, computed_at: '2026-11-09T12:00:00Z',
    ...extra,
  }) as never;

test('debug day: dates step by calendar day, and Gemma is asked only when the request says so', () => {
  assert.equal(isDate('2026-11-09'), true);
  for (const bad of ['2026-02-30', '2026-11-9', 'today', '', null, undefined]) assert.equal(isDate(bad), false, String(bad));
  assert.equal(shiftDate('2026-11-01', -1), '2026-10-31');
  assert.equal(shiftDate('2026-12-31', 1), '2027-01-01');
  assert.equal(shiftDate('2028-02-28', 1), '2028-02-29');
  assert.equal(debugPath('demo aino', null, false), '/v1/debug/day?home_id=demo+aino&generate=false');
  assert.equal(debugPath('h', '2026-11-09', true), '/v1/debug/day?home_id=h&date=2026-11-09&generate=true');
});

test('debug day: a failed request is named for what a developer should do next', () => {
  assert.equal(problemKind(null, null), 'unreachable');
  assert.equal(problemKind(401, 'valid authorization required'), 'closed');
  assert.equal(problemKind(403, 'x'), 'closed');
  assert.equal(problemKind(404, 'Not Found'), 'no_route', 'the router’s own 404: this cloud has no such route');
  assert.equal(problemKind(404, 'unknown home demo-x'), 'unknown_home');
  assert.equal(problemKind(422, []), 'bad_request');
  assert.equal(problemKind(500, 'boom'), 'server');
});

test('debug numbers: empty stays empty, signs are kept, clocks are the home’s', () => {
  assert.equal(num(null), '—');
  assert.equal(num(3), '3');
  assert.equal(num(3.456), '3.46');
  assert.equal(num(-0.5), '−0.5');
  assert.equal(num(-0.001), '0');
  assert.equal(signed(2), '+2.00');
  assert.equal(signed(-1.234), '−1.23');
  assert.equal(signed(-0.001), '+0.00');
  assert.equal(signed(undefined), '—');
  assert.equal(usd(0.1), '$0.10');
  assert.equal(usd(0.0031), '$0.0031');
  assert.equal(usd(0), '$0.00');
  assert.equal(usd(null), '—');
  assert.equal(latency(812.4), '812 ms');
  assert.equal(latency(2310), '2.31 s');
  assert.equal(latency(41_200), '41.2 s');
  assert.equal(latency(null), '—');
  assert.equal(localClock('2026-11-09T08:15:30Z', 'Europe/Helsinki'), '10:15:30');
  assert.equal(localClock('2026-11-08T22:00:00Z', 'Europe/Helsinki', false), '00:00');
  assert.equal(localClock(null, 'Europe/Helsinki'), '—');
  assert.equal(localStamp('2026-11-08T22:30:00Z', 'Europe/Helsinki'), '2026-11-09 00:30');
  assert.equal(dayFraction('2026-11-09T10:00:00Z', '2026-11-08T22:00:00Z', '2026-11-09T22:00:00Z'), 0.5);
  assert.equal(dayFraction('2026-11-10T10:00:00Z', '2026-11-08T22:00:00Z', '2026-11-09T22:00:00Z'), 1);
  assert.equal(dayFraction('x', 'y', 'z'), 0);
});

test('debug events: lanes follow the envelope’s own source; silent devices stay listed with zero', () => {
  assert.equal(laneOf({ source: 'hub', type: 'obs.drum_session' }, SOURCE_OF), 'robot');
  assert.equal(laneOf({ source: 'head', type: 'raw.head.tap' }, SOURCE_OF), 'robot');
  assert.equal(laneOf({ source: 'laptop', type: 'obs.play_session' }, SOURCE_OF), 'mac');
  assert.equal(laneOf({ source: 'phone', type: 'obs.outing' }, SOURCE_OF), 'phone', 'a walk the phone sent is the phone’s, whatever group it votes in');
  assert.equal(laneOf({ source: 'phone', type: 'obs.wearable_daily' }, SOURCE_OF), 'watch');
  assert.equal(laneOf({ source: 'sim', type: 'obs.self_report' }, SOURCE_OF), 'sim');
  const events = [event('a', 'hub', 'obs.drum_session'), event('b', 'head', 'obs.self_report', { payload: { item: 'mood', value: 2 } }), event('c', 'phone', 'obs.wearable_daily'), event('d', 'sim', 'obs.outing')];
  const lanes = laneCounts(events, SOURCE_OF);
  assert.deepEqual(lanes.map((l) => [l.lane, l.count]), [['robot', 2], ['phone', 0], ['mac', 0], ['glasses', 0], ['watch', 1], ['cloud', 0], ['sim', 1]]);
  assert.deepEqual(lanes[0].senders, ['head', 'hub']);
  assert.deepEqual(lanes.filter((l) => l.count === 0).map((l) => l.label), ['Phone', 'Mac', 'Glasses', 'Cloud']);
  assert.deepEqual(typeCounts(events), [{ type: 'obs.drum_session', count: 1 }, { type: 'obs.outing', count: 1 }, { type: 'obs.self_report', count: 1 }, { type: 'obs.wearable_daily', count: 1 }]);
  assert.equal(filterEvents(events, NO_EVENT_FILTER, SOURCE_OF).length, 4);
  assert.deepEqual(filterEvents(events, { lane: 'robot', type: '', text: '' }, SOURCE_OF).map((e: { id: string }) => e.id), ['a', 'b']);
  assert.deepEqual(filterEvents(events, { lane: 'robot', type: 'obs.self_report', text: '' }, SOURCE_OF).map((e: { id: string }) => e.id), ['b']);
  assert.deepEqual(filterEvents(events, { lane: '', type: '', text: 'MOOD' }, SOURCE_OF).map((e: { id: string }) => e.id), ['b']);
  assert.equal(payloadLine({ item: 'mood', value: 2, ok: true, ratio: 0.33333, tags: ['a', 'b'], none: null }), 'item=mood value=2 ok=true ratio=0.333 tags=["a","b"] none=null');
  assert.equal(payloadLine({}), '{}');
  assert.equal(payloadLine({ long: 'x'.repeat(300) }, 20).length, 20);
});

test('debug metrics: flagged first by default; any column sorts both ways with empty rows last; filters combine', () => {
  const rows = [
    metric('calm'),
    metric('sleep', { value: null, baseline: null, z: null, worse_z: null, status: 'insufficient', source: 'wearable' }),
    metric('mood', { flagged: true, status: 'drifting', worse_z: 2.4, z: -2.4, value: 2, worse_days: 3 }),
    metric('energy', { beyond_today: true, worse_z: 1.8, z: -1.8, value: 2.5, worse_days: 1 }),
    metric('steps', { status: 'improved', worse_z: -2, z: 2, value: 9000, source: 'glasses', scored: false, weight: 0 }),
  ];
  const names = (list: { metric: string }[]) => list.map((m) => m.metric);
  assert.deepEqual(names(sortMetrics(rows, 'pipeline', 'asc')), ['mood', 'energy', 'steps', 'calm', 'sleep']);
  assert.deepEqual(names(sortMetrics(rows, 'worse_z', 'desc')), ['mood', 'energy', 'calm', 'steps', 'sleep']);
  assert.deepEqual(names(sortMetrics(rows, 'worse_z', 'asc')), ['steps', 'calm', 'energy', 'mood', 'sleep'], 'no value stays last either way');
  assert.deepEqual(names(sortMetrics(rows, 'label', 'asc')), ['calm', 'energy', 'mood', 'sleep', 'steps']);
  assert.deepEqual(names(sortMetrics(rows, 'value', 'desc')).slice(0, 2), ['steps', 'calm']);
  assert.equal(names(sortMetrics(rows, 'progress', 'desc'))[0], 'mood');
  assert.equal(rows.length, 5, 'sorting never mutates the response');
  assert.deepEqual(names(filterMetrics(rows, NO_METRIC_FILTER)), names(rows));
  assert.deepEqual(names(filterMetrics(rows, { ...NO_METRIC_FILTER, status: 'flagged' })), ['mood']);
  assert.deepEqual(names(filterMetrics(rows, { ...NO_METRIC_FILTER, source: 'robot', withData: true, role: 'scored' })), ['calm', 'mood', 'energy']);
  assert.deepEqual(names(filterMetrics(rows, { ...NO_METRIC_FILTER, role: 'observe' })), ['steps']);
  assert.deepEqual(names(filterMetrics(rows, { ...NO_METRIC_FILTER, text: ' SLE ' })), ['sleep']);
  assert.deepEqual(metricCounts(rows), { total: 5, flagged: 1, beyond: 1, drifting: 1, improved: 1, insufficient: 1, withData: 4, observeOnly: 1 });
  assert.deepEqual(usableOf('robot', rows), { usable: 3, scored: 3 });
  assert.deepEqual(usableOf('wearable', rows), { usable: 0, scored: 1 }, 'a group can clear its confidence and still have nothing to vote with');
  assert.deepEqual(usableOf('glasses', rows), { usable: 0, scored: 0 }, 'observe-only metrics are never counted');
  const keys = METRIC_COLUMNS.map((c) => c.key);
  assert.equal(new Set(keys).size, keys.length);
  for (const k of keys) assert.equal(sortMetrics(rows, k, 'asc').length, rows.length, k);
});

test('debug metrics: the envelopes behind a metric are the ids the cloud lists, never a guess from the name', () => {
  const events = [event('e1', 'phone', 'obs.wearable_daily', { metrics: ['sleep'] }), event('e2', 'hub', 'obs.self_report', { metrics: ['energy'] }), event('e3', 'phone', 'obs.wearable_daily', { metrics: ['sleep'] })];
  const behind = eventsBehind({ event_ids: ['e3', 'gone'] } as never, events);
  assert.deepEqual(behind.events.map((e: { id: string }) => e.id), ['e3'], 'e1 names the metric but measures another day');
  assert.equal(behind.unlisted, 1, 'an id that is not in the day’s list is counted, not dropped silently');
  const metrics = [{ metric: 'sleep', event_ids: ['e3'], readings: 1 }, { metric: 'energy', event_ids: ['e2'], readings: 1 }] as never;
  assert.equal(countsElsewhere(events[0], metrics), true);
  assert.equal(countsElsewhere(events[2], metrics), false);
  assert.equal(countsElsewhere(event('e9', 'hub', 'obs.ritual'), metrics), false, 'an envelope that counts toward nothing is not "elsewhere"');
  assert.equal(countsElsewhere(events[0], [{ metric: 'sleep', event_ids: ['e3'], readings: 25 }] as never), false, 'a cut id list proves nothing');
  const bounds = { day_start: '2026-11-08T22:00:00Z', day_end: '2026-11-09T22:00:00Z' };
  assert.equal(stampedOutside({ ts: '2026-11-09T08:00:00Z' }, bounds), null);
  assert.equal(stampedOutside({ ts: '2026-11-10T05:00:00Z' }, bounds), 'after');
  assert.equal(stampedOutside({ ts: '2026-11-08T21:59:59Z' }, bounds), 'before');
});

test('debug read: every citation resolves to its fact and to the row it names, or says that it cannot', () => {
  const d = day({
    metrics: [metric('mood'), metric('sleep', { source: 'wearable' })],
    verdicts: [{ source: 'robot', verdict: 'worse' }, { source: 'wearable', verdict: 'insufficient' }],
    events: [event('018f-aa', 'hub', 'obs.self_report')],
  });
  assert.deepEqual(citeTarget('metric:mood', d), { section: 'metrics', anchor: anchorOf.metric('mood') });
  assert.deepEqual(citeTarget('source:robot', d), { section: 'verdicts', anchor: anchorOf.verdict('robot') });
  assert.deepEqual(citeTarget('consensus:state', d), { section: 'result', anchor: 'dbg-consensus' });
  assert.deepEqual(citeTarget('event:018f-aa', d), { section: 'events', anchor: anchorOf.event('018f-aa') });
  assert.deepEqual(citeTarget('missing:wearable', d), { section: 'verdicts', anchor: anchorOf.verdict('wearable') });
  assert.deepEqual(citeTarget('missing:sleep', d), { section: 'metrics', anchor: anchorOf.metric('sleep') });
  assert.deepEqual(citeTarget('tomorrow:mood', d), { section: 'metrics', anchor: anchorOf.metric('mood') });
  assert.deepEqual(citeTarget('tomorrow:group_robot', d), { section: 'verdicts', anchor: anchorOf.verdict('robot') });
  assert.deepEqual(citeTarget('tomorrow:state', d), { section: 'result', anchor: 'dbg-consensus' });
  for (const nowhere of ['metric:ghost', 'event:nope', 'tomorrow:anything', 'tomorrow:group_ghost', 'weird', 'other:mood']) assert.equal(citeTarget(nowhere, d), null, nowhere);
  assert.match(anchorOf.metric('a b/c'), /^dbg-metric-[A-Za-z0-9_-]+$/);
  const facts = [{ id: 'metric:mood', kind: 'metric', label: 'Mood dial', detail: 'Mood dial 2 against a usual 4', numbers: [2, 4] }] as never;
  const cites = resolveCites({ cites: ['metric:mood', 'metric:mood', 'metric:ghost'] } as never, facts, d);
  assert.equal(cites.length, 2, 'a repeated citation is shown once');
  assert.equal(cites[0].fact?.label, 'Mood dial');
  assert.equal(cites[1].fact, null);
  assert.equal(cites[1].target, null);
  const groups = claimGroups({ moved: [{ text: 'a', cites: ['metric:mood'] }], rule_check: { text: 'b', cites: ['consensus:state'] } } as never);
  assert.deepEqual(groups.map((g) => [g.key, g.claims.length]), [['moved', 1], ['missing', 0], ['tomorrow', 0], ['rule_check', 1]]);
  assert.equal(rejectedTotal({ uncited_number: 2, unknown_fact: 1 }), 3);
  assert.equal(rejectedTotal(undefined), 0);
  assert.equal(fallbackWords('over_budget'), 'the spend cap is reached');
  assert.equal(fallbackWords('something_new'), 'something_new');
});

test('debug read: a poll never replaces Gemma’s read with the unasked fallback, and says when the data has moved on', () => {
  const gemma = { by: 'gemma', digest: 'd1', fallback_reason: null } as never;
  const polled = { by: 'deterministic', digest: 'd1', fallback_reason: 'not_requested' } as never;
  assert.deepEqual(pickRead(gemma, polled), { read: gemma, kept: true, current: true });
  const moved = { by: 'deterministic', digest: 'd2', fallback_reason: 'not_requested' } as never;
  assert.deepEqual(pickRead(gemma, moved), { read: gemma, kept: true, current: false });
  const failed = { by: 'deterministic', digest: 'd2', fallback_reason: 'over_budget' } as never;
  assert.equal(pickRead(gemma, failed).read, failed, 'a real fallback is shown, not hidden behind an older read');
  assert.equal(pickRead(null, polled).read, polled);
  const fresh = { by: 'gemma', digest: 'd2' } as never;
  assert.deepEqual(pickRead(gemma, fresh), { read: fresh, kept: false, current: true });
});

test('debug calls: failures on top, totals per model cover only what was recorded, the slowest call is found', () => {
  const call = (ts: string, model: string, extra: Record<string, unknown> = {}) => ({ ts, provider: 'gemini', model, task: 't', route: null, ok: true, fallback: false, latency_ms: 100, est_usd: 0.01, ...extra }) as never;
  const calls = [
    call('2026-11-09T08:00:00Z', 'live'),
    call('2026-11-09T09:00:00Z', 'gemma', { ok: false, latency_ms: 9000, est_usd: null }),
    call('2026-11-09T07:00:00Z', 'gemma', { fallback: true, latency_ms: null }),
    call('2026-11-09T06:00:00Z', 'live', { latency_ms: 300 }),
  ];
  assert.deepEqual(orderCalls(calls).map((c: { ts: string }) => c.ts.slice(11, 13)), ['09', '07', '06', '08']);
  assert.equal(callOutcome({ ok: false, fallback: true }), 'failed');
  const totals = modelTotals(calls);
  assert.deepEqual(totals.map((t) => t.model), ['live', 'gemma']);
  assert.deepEqual(totals[0], { provider: 'gemini', model: 'live', calls: 2, failed: 0, fallback: 0, timed: 2, costed: 2, latency_ms: 400, slowest_ms: 300, est_usd: 0.02 });
  assert.deepEqual([totals[1].failed, totals[1].fallback, totals[1].timed, totals[1].costed, totals[1].slowest_ms], [1, 1, 1, 1, 9000]);
  assert.equal((slowestCall(calls) as unknown as { latency_ms: number }).latency_ms, 9000);
  assert.equal(slowestCall([call('t', 'm', { latency_ms: null })]), null);
  assert.deepEqual(callSummary(calls), { calls: 4, failed: 1, fallback: 1, costed: 3, est_usd: 0.03 });
  const conv = [{ minutes: 4.5, billed_minutes: 5, outcome: 'completed', feel: [{}, {}] }, { minutes: null, billed_minutes: null, outcome: null, feel: [] }] as never;
  assert.deepEqual(conversationSummary(conv), { count: 2, minutes: 4.5, billed: 5, open: 1, feels: 2 });
  const since = Date.parse('2026-11-09T08:30:00Z');
  const wrote = (model: string | null, fallback_reason: string | null = null) => ({ by: model ? 'gemma' : 'deterministic', model, fallback_reason }) as never;
  assert.deepEqual(askCost(calls, wrote('gemma'), since), { calls: 1, latency_ms: 9000, est_usd: null }, 'only this model’s calls since the ask began');
  assert.deepEqual(askCost(calls, wrote('live'), Date.parse('2026-11-09T05:00:00Z')), { calls: 2, latency_ms: 400, est_usd: 0.02 });
  assert.equal(askCost(calls, wrote('gemma'), Date.parse('2026-11-09T10:00:00Z')), null);
  assert.equal(askCost(calls, wrote(null, 'not_requested'), 0), null, 'no ask, no cost');
  const failed = [
    call('2026-11-09T09:00:10Z', 'gemma', { task: 'debug_read', latency_ms: 10_000, est_usd: 0.005 }),
    call('2026-11-09T09:00:22Z', 'gemma', { task: 'debug_read', latency_ms: 12_000, est_usd: 0.005 }),
    call('2026-11-09T09:00:22Z', 'template', { provider: 'none', task: 'debug_read', route: 'no_valid_claims', fallback: true, latency_ms: null, est_usd: null }),
    call('2026-11-09T09:00:15Z', 'live', { task: 'live_session' }),
  ];
  assert.deepEqual(askCost(failed, wrote(null, 'no_valid_claims'), since), { calls: 2, latency_ms: 22_000, est_usd: 0.01 }, 'an ask that fell back after the model answered still cost its calls');
  assert.equal(toolsInOrder({ end: null }), true);
  assert.equal(toolsInOrder({ end: '2026-11-09T08:17:00Z' }), false, 'an uploaded conversation lists one of each tool: no order to draw');
});

test('debug live: a refresh reports what arrived and what it moved; another day is not a change', () => {
  const before = day({ events: [event('e1', 'hub', 'obs.self_report')], metrics: [metric('mood'), metric('energy')], verdicts: [{ source: 'robot', verdict: 'as_usual' }] });
  const after = day({
    events: [event('e1', 'hub', 'obs.self_report'), event('e2', 'hub', 'obs.drum_session')],
    metrics: [metric('mood', { value: 2, status: 'drifting', flagged: true }), metric('energy')],
    verdicts: [{ source: 'robot', verdict: 'worse' }],
    consensus: { id: 'consensus:state', state: 'watch', raw_state: 'watch', agreement: 'agree', rule_version: 'v' },
  });
  const d = diffDay(before, after);
  assert.deepEqual(d.events, ['e2']);
  assert.deepEqual(d.types, ['obs.drum_session']);
  assert.deepEqual(d.metrics.map((m) => [m.id, m.from, m.to, m.statusTo, m.flaggedTo]), [['metric:mood', 3, 2, 'drifting', true]]);
  assert.deepEqual(d.verdicts, [{ source: 'robot', from: 'as_usual', to: 'worse' }]);
  assert.deepEqual(d.state, { from: 'stable', to: 'watch' });
  assert.equal(diffLine(d), '1 new event (obs.drum_session) · state stable → watch · robot as_usual → worse · mood 3 → 2');
  assert.equal(diffEmpty(diffDay(before, before)), true);
  assert.equal(diffEmpty(diffDay(null, after)), true, 'the first load marks nothing as new');
  assert.equal(diffEmpty(diffDay(before, day({ date: '2026-11-10', events: [event('z', 'hub', 'obs.self_report')] }))), true);
});

test('debug page scope: a team page inside the team shell, linked from the dashboard footer, tokens only, no fixture shipped', () => {
  const app = new URL('../app/debug/', import.meta.url);
  assert.ok(existsSync(new URL('page.tsx', app)), 'route exists');
  assert.match(readFileSync(new URL('page.tsx', app), 'utf8'), /TeamShell/);
  assert.match(readFileSync(new URL('../components/dash/Dashboard.tsx', import.meta.url), 'utf8'), /href="\/debug\/"/);
  const dir = new URL('../components/debug/', import.meta.url);
  for (const f of readdirSync(dir)) {
    const src = readFileSync(new URL(f, dir), 'utf8').replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, '');
    assert.ok(!/diagnos|predicts|relapse/i.test(src), `${f} wording`);
    assert.ok(!/fixture|\.json['"]/i.test(src), `${f} reads the route, never a file`);
  }
  const css = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');
  const block = css.slice(css.indexOf('/debug/ (team)'));
  assert.ok(block.length > 200 && block.length < css.length, 'the page has its own rule block in the team stylesheet');
  const rules = block.replace(/\/\*[\s\S]*?\*\//g, '');
  assert.ok(!/#[0-9a-fA-F]{3,8}\b|rgba?\(/.test(rules), 'debug colours are tokens only');
  assert.ok(!/font-size:\s*[\d.]+(px|rem|em)/.test(rules), 'debug type sizes are tokens only');
  assert.ok(!/[^-\w]--(?!k-|d-|dbg-)[a-z]/.test(rules), 'only design tokens and the page’s own properties');
});
