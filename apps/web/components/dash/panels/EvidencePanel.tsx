'use client';

import { useMemo } from 'react';
import { CONSENSUS_SOURCES } from '@contracts';
import { shortDay } from '@/lib/clinician';
import { GROUP_LABEL, byDay } from '@/lib/evidence';
import { sourceLabel } from '@/lib/format';
import { pointMeaning, valueText } from '@/lib/insight';
import type { DashData } from '../data';
import { EmptyState, SimMark, ToneMark, captureLabel } from '../kit';

export function EvidencePanel({
  data,
  day,
  onDay,
  onMetric,
}: {
  data: DashData;
  day: string | null;
  onDay: (d: string) => void;
  onMetric: (m: string) => void;
}) {
  const days = useMemo(() => byDay(data.events), [data.events]);
  const dates = useMemo(() => {
    const all = new Set(days.map((d) => d.date));
    for (const s of data.series) for (const p of s.points) if (typeof p.value === 'number') all.add(p.date);
    return [...all].sort().reverse();
  }, [days, data.series]);
  if (!dates.length) return <EmptyState title="No records yet">Each day’s check-ins, outings, tasks and watch data will be listed here.</EmptyState>;

  const current = day && dates.includes(day) ? day : dates[0];
  const i = dates.indexOf(current);
  const records = days.find((d) => d.date === current);
  const measures = [...CONSENSUS_SOURCES]
    .map((src) => ({
      src,
      list: data.series
        .filter((s) => s.source === src)
        .map((s) => ({ s, p: s.points.find((p) => p.date === current && typeof p.value === 'number') }))
        .filter((x) => x.p),
    }))
    .filter((g) => g.list.length);
  const weekday = new Date(`${current}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'long' });

  return (
    <div className="d-stack">
      <div className="d-toolbar">
        <div className="d-seg" role="group" aria-label="Change day">
          <button type="button" disabled={i >= dates.length - 1} onClick={() => onDay(dates[i + 1])} aria-label="Earlier day">
            ‹ Earlier
          </button>
          <button type="button" disabled={i <= 0} onClick={() => onDay(dates[i - 1])} aria-label="Later day">
            Later ›
          </button>
        </div>
        <label className="d-field">
          <span className="d-field-k">Day</span>
          <select value={current} onChange={(e) => onDay(e.target.value)}>
            {dates.map((d) => (
              <option key={d} value={d}>
                {shortDay(d)} ({days.find((x) => x.date === d)?.count ?? 0} records)
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="d-strong">
        {weekday} {shortDay(current)}: {records?.count ?? 0} {records?.count === 1 ? 'record' : 'records'}
      </p>

      {measures.length > 0 && (
        <section aria-label="Measures that day">
          <h3 className="d-h3">Measures against their usual</h3>
          {measures.map((g) => (
            <div key={g.src} className="d-daypart">
              <h4 className="d-h4">{sourceLabel(g.src)}</h4>
              <ul className="d-rows">
                {g.list.map(({ s, p }) => {
                  const m = pointMeaning(s, p!);
                  return (
                    <li key={s.metric} className="d-measure">
                      <button type="button" className="d-link" onClick={() => onMetric(s.metric)}>
                        {s.label}
                      </button>
                      <span className="d-measure-v">{valueText(p!.value, s.unit)}</span>
                      <span className="d-measure-m">
                        {m.text}. <ToneMark tone={m.tone}>{m.range}</ToneMark>
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </section>
      )}

      {records ? (
        records.groups.map((g) => (
          <section key={g.group} aria-label={GROUP_LABEL[g.group]}>
            <h3 className="d-h3">{GROUP_LABEL[g.group]}</h3>
            <ul className="d-rows">
              {g.items.map((it) => (
                <li key={it.id} className="d-record">
                  <span className="d-record-time">{it.time}</span>
                  <div className="d-record-body">
                    <span className="d-row-title">{it.title}</span>
                    {it.detail && <span>{it.detail}</span>}
                    <span className="d-prov">
                      Sent by {captureLabel(it.source)}
                      {it.sim && <SimMark />}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))
      ) : (
        <p className="d-muted">No individual records are listed for this day.</p>
      )}

      <p className="d-callout">
        Conversations with Kaiku stay with the person. The care team sees activities, routines and what helped, never the words of a conversation.
      </p>
    </div>
  );
}
