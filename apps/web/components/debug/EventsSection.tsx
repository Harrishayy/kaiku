'use client';

import { useEffect, useMemo, useState } from 'react';
import type { DebugDay } from '@contracts';
import { SOURCE_OF } from '@contracts';
import { EVENT_COLUMNS, NO_EVENT_FILTER, anchorOf, dayFraction, filterEvents, laneCounts, laneOf, typeCounts, type EventFilter } from '@/lib/debug';
import { Empty, EventRows, type EventMarks, type Nav } from './bits';

const HOURS = [0, 3, 6, 9, 12, 15, 18, 21, 24];
/** Rows drawn before a developer asks for the rest: a day with thousands of envelopes stays scrollable. */
const FIRST_ROWS = 400;

/** The day's envelopes: a strip by local time and device, then every envelope as a row. */
export function EventsBody({
  day,
  nav,
  filter,
  onFilter,
  marks,
  now,
}: {
  day: DebugDay;
  nav: Nav;
  filter: EventFilter;
  onFilter: (f: EventFilter) => void;
  marks: EventMarks;
  /** the developer's clock, for the "now" line on today's strip */
  now: number;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [all, setAll] = useState(false);
  const lanes = useMemo(() => laneCounts(day.events, SOURCE_OF), [day.events]);
  const types = useMemo(() => typeCounts(day.events), [day.events]);
  const rows = useMemo(() => filterEvents(day.events, filter, SOURCE_OF), [day.events, filter]);
  const shown = all ? rows : rows.slice(0, FIRST_ROWS);
  // a jump to an envelope past the first rows draws them all, so its row exists to land on
  useEffect(() => {
    if (nav.hit && !all && rows.findIndex((e) => anchorOf.event(e.id) === nav.hit) >= FIRST_ROWS) setAll(true);
  }, [nav.hit, all, rows]);
  const when = day.is_today ? 'today' : 'on this day';
  const filtered = Boolean(filter.lane || filter.type || filter.text);
  const nowAt = day.is_today ? dayFraction(new Date(now).toISOString(), day.day_start, day.day_end) : null;
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  return (
    <>
      <div className="dbg-strip" role="group" aria-label="Envelopes by local time and device">
        {lanes.map((l) => {
          const mine = day.events.filter((e) => laneOf(e, SOURCE_OF) === l.lane);
          const on = filter.lane === l.lane;
          return (
            <div key={l.lane} className={`dbg-lane${l.count ? '' : ' is-silent'}`}>
              <button
                type="button"
                className="dbg-lane-name"
                aria-pressed={on}
                disabled={!l.count}
                title={l.count ? `Show only ${l.label} (${l.senders.join(', ')})` : undefined}
                onClick={() => onFilter({ ...filter, lane: on ? '' : l.lane })}
              >
                {l.label}
                <span className="dbg-count">{l.count}</span>
              </button>
              <div className="dbg-lane-track">
                {l.count === 0 && (
                  <span className="dbg-lane-silent">
                    nothing arrived from {l.label} {when}
                  </span>
                )}
                {mine.map((e) => (
                  <button
                    key={e.id}
                    type="button"
                    tabIndex={-1}
                    className={`dbg-tick${marks.fresh.has(e.id) ? ' is-new' : marks.arrived.has(e.id) ? ' is-arrived' : ''}${e.sim ? ' is-sim' : ''}`}
                    style={{ left: `${(dayFraction(e.ts, day.day_start, day.day_end) * 100).toFixed(2)}%` }}
                    title={`${e.local_time} ${e.type} (${e.source})`}
                    aria-label={`${e.local_time} ${e.type}: go to its row`}
                    onClick={() => nav.jump({ section: 'events', anchor: anchorOf.event(e.id) })}
                  />
                ))}
                {nowAt !== null && <span className="dbg-now" style={{ left: `${(nowAt * 100).toFixed(2)}%` }} aria-hidden="true" />}
              </div>
            </div>
          );
        })}
        <div className="dbg-lane dbg-lane-axis" aria-hidden="true">
          <span className="dbg-lane-name">{day.timezone}</span>
          <div className="dbg-lane-track">
            {HOURS.map((h) => (
              <span key={h} className="dbg-hour" style={{ left: `${(h / 24) * 100}%` }}>
                {String(h).padStart(2, '0')}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="dbg-filters" role="group" aria-label="Filter the envelopes">
        <label className="dbg-field">
          From
          <select className="dbg-input" value={filter.lane} onChange={(e) => onFilter({ ...filter, lane: e.target.value })}>
            <option value="">every device</option>
            {lanes
              .filter((l) => l.count)
              .map((l) => (
                <option key={l.lane} value={l.lane}>
                  {l.label} ({l.count})
                </option>
              ))}
          </select>
        </label>
        <label className="dbg-field">
          Type
          <select className="dbg-input" value={filter.type} onChange={(e) => onFilter({ ...filter, type: e.target.value })}>
            <option value="">every type</option>
            {types.map((t) => (
              <option key={t.type} value={t.type}>
                {t.type} ({t.count})
              </option>
            ))}
          </select>
        </label>
        <input
          type="search"
          className="dbg-input"
          aria-label="Find envelopes by type, source, id or any field"
          placeholder="Find in any field"
          value={filter.text}
          onChange={(e) => onFilter({ ...filter, text: e.target.value })}
        />
        <span className="dbg-dim" role="status">
          {rows.length} of {day.events.length} shown
          {day.events_total !== day.events.length ? ` · ${day.events_total} stored for the day, ${day.events.length} sent to this page` : ''}
        </span>
        {filtered && (
          <button type="button" className="d-btn d-btn-quiet dbg-small" onClick={() => onFilter(NO_EVENT_FILTER)}>
            Clear filters
          </button>
        )}
      </div>

      {day.events.length === 0 ? (
        <Empty>No envelope arrived {when}. Every device lane above is silent.</Empty>
      ) : (
        <div className="dbg-scroll">
          <table className="dbg-table dbg-events" aria-label="Envelopes of this day, oldest first">
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
              <EventRows day={day} events={shown} nav={nav} marks={marks} open={open} onToggle={toggle} anchors />
              {!rows.length && (
                <tr>
                  <td colSpan={EVENT_COLUMNS.length}>
                    <Empty>No envelope matches these filters.</Empty>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > shown.length && (
        <button type="button" className="d-btn dbg-small" onClick={() => setAll(true)}>
          Show all {rows.length} rows
        </button>
      )}
    </>
  );
}
