'use client';

import { Fragment, useMemo, useState } from 'react';
import type { DebugDay, DebugMetric } from '@contracts';
import {
  METRIC_COLUMNS,
  NO_METRIC_FILTER,
  anchorOf,
  eventsBehind,
  filterMetrics,
  num,
  signed,
  sortMetrics,
  EVENT_COLUMNS,
  type MetricFilter,
  type MetricMove,
  type MetricSortKey,
} from '@/lib/debug';
import { Chevron, Empty, EventRows, Mono, Tag, type EventMarks, type Nav } from './bits';

const STATUS_TONE: Record<DebugMetric['status'], 'warn' | 'ok' | undefined> = { drifting: 'warn', improved: 'ok', normal: undefined, insufficient: undefined };

/** Every criteria metric on this day beside its baseline; a row opens the envelopes that made its value. */
export function MetricsBody({
  day,
  nav,
  filter,
  onFilter,
  marks,
  moved,
}: {
  day: DebugDay;
  nav: Nav;
  filter: MetricFilter;
  onFilter: (f: MetricFilter) => void;
  marks: EventMarks;
  moved: Map<string, MetricMove>;
}) {
  const [sort, setSort] = useState<{ key: MetricSortKey; dir: 'asc' | 'desc' }>({ key: 'pipeline', dir: 'asc' });
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [openEvents, setOpenEvents] = useState<Set<string>>(new Set());
  const rows = useMemo(() => sortMetrics(filterMetrics(day.metrics, filter), sort.key, sort.dir), [day.metrics, filter, sort]);
  const sources = useMemo(() => [...new Set(day.metrics.map((m) => m.source))], [day.metrics]);
  const filtered = JSON.stringify(filter) !== JSON.stringify(NO_METRIC_FILTER);

  const flip = (set: (f: (prev: Set<string>) => Set<string>) => void, id: string) =>
    set((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  if (!day.metrics.length) return <Empty>The criteria list no metric for this home.</Empty>;

  return (
    <>
      <div className="dbg-filters" role="group" aria-label="Filter the metrics">
        <input
          type="search"
          className="dbg-input"
          aria-label="Find a metric by label, name or message type"
          placeholder="Find a metric"
          value={filter.text}
          onChange={(e) => onFilter({ ...filter, text: e.target.value })}
        />
        <label className="dbg-field">
          Group
          <select className="dbg-input" value={filter.source} onChange={(e) => onFilter({ ...filter, source: e.target.value })}>
            <option value="">all</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="dbg-field">
          Status
          <select className="dbg-input" value={filter.status} onChange={(e) => onFilter({ ...filter, status: e.target.value })}>
            <option value="">all</option>
            <option value="flagged">flagged</option>
            <option value="drifting">drifting</option>
            <option value="improved">improved</option>
            <option value="normal">normal</option>
            <option value="insufficient">insufficient</option>
          </select>
        </label>
        <label className="dbg-field">
          Role
          <select className="dbg-input" value={filter.role} onChange={(e) => onFilter({ ...filter, role: e.target.value as MetricFilter['role'] })}>
            <option value="">all</option>
            <option value="scored">scored</option>
            <option value="observe">observe-only</option>
          </select>
        </label>
        <label className="dbg-check">
          <input type="checkbox" checked={filter.withData} onChange={(e) => onFilter({ ...filter, withData: e.target.checked })} />
          with a value this day
        </label>
        <span className="dbg-dim" role="status">
          {rows.length} of {day.metrics.length}
        </span>
        {filtered && (
          <button type="button" className="d-btn d-btn-quiet dbg-small" onClick={() => onFilter(NO_METRIC_FILTER)}>
            Clear filters
          </button>
        )}
        {sort.key !== 'pipeline' && (
          <button type="button" className="d-btn d-btn-quiet dbg-small" onClick={() => setSort({ key: 'pipeline', dir: 'asc' })}>
            Flagged first
          </button>
        )}
      </div>
      <div className="dbg-scroll">
        <table className="dbg-table dbg-metrics" aria-label="Metrics of this day beside their baselines">
          <thead>
            <tr>
              {METRIC_COLUMNS.map((c) => {
                const active = sort.key === c.key;
                return (
                  <th key={c.key} scope="col" className={c.numeric ? 'dbg-num' : undefined} aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'} title={c.title}>
                    <button
                      type="button"
                      className="dbg-sort"
                      onClick={() => setSort(active ? { key: c.key, dir: sort.dir === 'asc' ? 'desc' : 'asc' } : { key: c.key, dir: c.first })}
                    >
                      {c.label}
                      <span className="dbg-sort-mark" aria-hidden="true">
                        {active ? (sort.dir === 'asc' ? '▲' : '▼') : ''}
                      </span>
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => {
              const anchor = anchorOf.metric(m.metric);
              const isOpen = open.has(m.id);
              const move = moved.get(m.id);
              const has = m.value !== null && m.value !== undefined;
              const cls = [m.flagged ? 'is-flagged' : '', !has ? 'is-empty' : '', move ? 'is-moved' : '', nav.hit === anchor ? 'is-hit' : ''].filter(Boolean).join(' ');
              return (
                <Fragment key={m.id}>
                  <tr id={anchor} tabIndex={-1} className={cls || undefined}>
                    <th scope="row">
                      <div className="dbg-metric">
                        <button type="button" className="dbg-rowbtn" aria-expanded={isOpen} aria-label={`${isOpen ? 'Hide' : 'Show'} the envelopes behind ${m.label}`} onClick={() => flip(setOpen, m.id)}>
                          <Chevron open={isOpen} />
                          <span className="dbg-mono dbg-metric-name">{m.metric}</span>
                        </button>
                        <span className="dbg-metric-label" title={m.unit ? `${m.label} (${m.unit})` : m.label}>
                          {m.label}
                          {m.unit ? <span className="dbg-unit"> · {m.unit}</span> : null}
                        </span>
                        {m.flagged && <Tag tone="warn" title="Counted toward its group’s worse weight this day">flagged</Tag>}
                        {move && (
                          <Tag tone="new" title="Changed while this page was watching">
                            {move.from !== move.to ? `${num(move.from)} → ${num(move.to)}` : `${move.statusFrom} → ${move.statusTo}`}
                          </Tag>
                        )}
                      </div>
                    </th>
                    <td className="dbg-mono">{m.source}</td>
                    <td className="dbg-num">
                      {m.partial && <Tag title="Today’s running total of a summed or counted measure: shown, but not compared or scored until the day is over">partial</Tag>}{' '}
                      {has ? num(m.value) : <span className="dbg-dim">no data</span>}
                    </td>
                    <td className="dbg-num">{m.readings ?? 0}</td>
                    <td className="dbg-num">{num(m.baseline?.median)}</td>
                    <td className="dbg-num">{num(m.baseline?.spread)}</td>
                    <td className="dbg-num">
                      {m.baseline ? m.baseline.days : '—'}
                      {m.baseline?.early && <Tag title="Provisional baseline of a young record">early</Tag>}
                    </td>
                    <td className="dbg-num">{signed(m.z)}</td>
                    <td className={`dbg-num${m.beyond_today ? ' is-beyond' : ''}`} title={m.beyond_today ? 'This day alone is beyond the threshold in the worse direction' : undefined}>
                      {signed(m.worse_z)} <span className="dbg-dim">/ {num(m.z_threshold)}</span>
                    </td>
                    <td className="dbg-mono">{m.direction === 'up' ? '↑ up' : '↓ down'}</td>
                    <td>
                      <Tag tone={STATUS_TONE[m.status]}>{m.status}</Tag>
                    </td>
                    <td className="dbg-num" title={`${m.worse_days ?? 0} worse and ${m.better_days ?? 0} better of ${m.scored_days ?? 0} days that had a baseline; ${m.drift_days_needed} worse days flag it`}>
                      <span className="dbg-pips" aria-hidden="true">
                        {Array.from({ length: m.drift_days_needed }, (_, i) => (
                          <span key={i} className={i < (m.worse_days ?? 0) ? 'is-on' : undefined} />
                        ))}
                      </span>
                      {m.worse_days ?? 0}/{m.drift_days_needed}
                    </td>
                    <td className="dbg-num">{num(m.weight)}</td>
                    <td className="dbg-nowrap">{m.scored ? 'scored' : <Tag title={m.enabled ? 'Observe-only (weight 0): charted, never a vote' : 'Observe-only (disabled in the criteria): charted, never a vote'}>observe</Tag>}</td>
                  </tr>
                  {isOpen && <Behind metric={m} day={day} nav={nav} marks={marks} open={openEvents} onToggle={(id) => flip(setOpenEvents, id)} />}
                </Fragment>
              );
            })}
            {!rows.length && (
              <tr>
                <td colSpan={METRIC_COLUMNS.length}>
                  <Empty>No metric matches these filters.</Empty>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Behind({ metric, day, nav, marks, open, onToggle }: { metric: DebugMetric; day: DebugDay; nav: Nav; marks: EventMarks; open: Set<string>; onToggle: (id: string) => void }) {
  const behind = eventsBehind(metric, day.events);
  return (
    <tr className="dbg-sub">
      <td colSpan={METRIC_COLUMNS.length}>
        <p className="dbg-sub-line">
          Reads <Mono>{metric.obs}</Mono> · {metric.worse_days ?? 0} worse and {metric.better_days ?? 0} better of {metric.scored_days ?? 0} days that had a baseline ·{' '}
          {metric.enabled ? 'enabled' : 'disabled'} · weight {num(metric.weight)}
        </p>
        {behind.events.length ? (
          <table className="dbg-table dbg-table-inner">
            <caption className="dbg-caption">
              Envelopes behind this value ({behind.events.length}
              {behind.unlisted ? `, ${behind.unlisted} more not in this day’s list` : ''})
            </caption>
            <thead>
              <tr>
                {EVENT_COLUMNS.map((c) => (
                  <th key={c.key} scope="col" className={c.key === 'quality' ? 'dbg-num' : undefined} title={c.title}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <EventRows day={day} events={behind.events} nav={nav} marks={marks} open={open} onToggle={onToggle} anchors={false} />
            </tbody>
          </table>
        ) : (
          <Empty>
            No envelope counted toward this metric on this day
            {behind.unlisted ? ` (${behind.unlisted} named by the metric are not in the day’s list)` : ''}.
          </Empty>
        )}
        {behind.events.length > 0 && (
          <button type="button" className="d-btn d-btn-quiet dbg-small" onClick={() => nav.jump({ section: 'events', anchor: anchorOf.event(behind.events[0].id) })}>
            Show the first one in the timeline
          </button>
        )}
      </td>
    </tr>
  );
}
