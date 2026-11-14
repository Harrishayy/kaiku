'use client';

import { useMemo } from 'react';
import { CONSENSUS_SOURCES } from '@contracts';
import { shortDay } from '@/lib/clinician';
import { GROUP_LABEL, byDay, dayChips, dayValence, localDate, type DayChip, type Valence } from '@/lib/evidence';
import { sourceLabel } from '@/lib/format';
import { pointMeaning, valueText } from '@/lib/insight';
import { stateChip, type ChipTone } from '@/lib/labels';
import type { DashData } from '../data';
import { Chip, EmptyState, SimMark, ToneMark, captureLabel } from '../kit';

const CHIP_TONE: Record<DayChip['kind'], ChipTone> = { did: 'neutral', mood: 'neutral', away: 'warn', reflection: 'info', care: 'call', questionnaire: 'neutral', other: 'neutral' };
const VALENCE_WORD: Record<Valence | 'none', string> = { low: 'Low', neutral: 'Ordinary', bright: 'Bright', declined: 'Declined', none: 'No reflection' };

/**
 * Daily account: one readable line per day (written by the cloud from every source), newest first, with its parts
 * as small chips. Days in a flagged spell carry the state's tone; the care-action day is marked. Opening a day
 * shows every measure against their usual and the underlying records. Conversation words never appear here.
 */
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
  const records = useMemo(() => byDay(data.events), [data.events]);
  const accounts = data.view.days;
  const dates = useMemo(() => {
    const all = new Set<string>([...records.map((d) => d.date), ...accounts.map((d) => d.date)]);
    for (const s of data.series) for (const p of s.points) if (typeof p.value === 'number') all.add(p.date);
    return [...all].sort().reverse();
  }, [records, accounts, data.series]);
  if (!dates.length) return <EmptyState title="No days recorded yet">Each day’s account appears here once the first check-in, outing or watch data arrives.</EmptyState>;

  const stateOf = new Map(data.view.stateHistory.map((d) => [d.date, stateChip(d.state, d.agreement)]));
  const careDays = new Set(data.view.actions.map((a) => localDate(a.ts)));
  const refl = data.view.reflections;
  const strip = [...dates].slice(0, 14).reverse();
  // the cloud's per-day reflection levels when it sends them; otherwise the level named in the day's account
  const valenceOf = (d: string): Valence | 'none' => {
    const entries = (refl?.days ?? []).filter((x) => x.date === d);
    if (entries.length) {
      if (entries.some((x) => x.valence === 'low')) return 'low';
      const v = entries.find((x) => x.valence)?.valence;
      return v ?? (entries.some((x) => x.declined) ? 'declined' : 'none');
    }
    return dayValence(accounts.find((x) => x.date === d)?.parts ?? []) ?? 'none';
  };

  return (
    <div className="d-stack">
      <section aria-label="Reflections with Kaiku" className="d-refl">
        {refl ? (
          <details>
            <summary>
              <span className="d-strong">Reflections</span>
              <span className="d-refl-strip" role="img" aria-label={`Reflection level by day: ${strip.map((d) => `${shortDay(d)} ${VALENCE_WORD[valenceOf(d)].toLowerCase()}`).join(', ')}`}>
                {strip.map((d) => (
                  <span key={d} className={`d-refl-cell d-refl-${valenceOf(d)}`} title={`${shortDay(d)}: ${VALENCE_WORD[valenceOf(d)]}`} />
                ))}
              </span>
              <span className="d-meta">
                {refl.reflections} this week: {refl.low} low, {refl.neutral} ordinary, {refl.bright} bright{refl.declined ? `, ${refl.declined} declined` : ''}
              </span>
            </summary>
            <p>{refl.summary}</p>
            <ul className="d-legend" aria-label="Reflection key">
              {(['low', 'neutral', 'bright', 'declined', 'none'] as const).map((v) => (
                <li key={v}>
                  <span className={`d-refl-cell d-refl-${v}`} aria-hidden="true" />
                  {VALENCE_WORD[v]}
                </li>
              ))}
            </ul>
            {refl.themes.length > 0 && (
              <div className="d-chips" aria-label="What reflections were about">
                <span className="d-meta">Came up</span>
                {refl.themes.map((t) => (
                  <Chip key={t.label}>
                    {t.label} · {Math.round(t.value)}
                  </Chip>
                ))}
              </div>
            )}
          </details>
        ) : (
          <p className="d-muted">Reflections stay with the person unless they choose to share summaries.</p>
        )}
      </section>

      <ol className="d-days" aria-label="Days, newest first">
        {dates.map((d) => {
          const account = accounts.find((a) => a.date === d);
          const rec = records.find((r) => r.date === d);
          const st = stateOf.get(d);
          const flagged = st && (st.tone === 'call' || st.tone === 'warn' || st.tone === 'crisis');
          const open = day === d;
          const chips = account ? dayChips(account.parts) : [];
          const did = chips.filter((c) => c.kind === 'did');
          // what stands out first: care team, reflection level, mood, then what was away from usual
          const rank = { care: 0, reflection: 1, mood: 2, questionnaire: 3, away: 4, other: 5, did: 6 };
          const notable = chips.filter((c) => c.kind !== 'did').sort((x, y) => rank[x.kind] - rank[y.kind]);
          const weekday = new Date(`${d}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'short' });
          return (
            <li key={d} className={`d-day${flagged ? ` is-flagged d-day-${st.tone}` : ''}${open ? ' is-open' : ''}`}>
              <button type="button" className="d-day-head" aria-expanded={open} onClick={() => onDay(open ? '' : d)}>
                <span className="d-day-date">
                  <span className="d-day-wd">{weekday}</span> {shortDay(d)}
                </span>
                <span className="d-day-body">
                  {chips.length > 0 ? (
                    <>
                      {did.length > 0 && <span className="d-day-did">{did.map((c) => c.label).join(' · ')}</span>}
                      <span className="d-day-chips">
                        {notable.slice(0, open ? notable.length : 4).map((c, i) => (
                            <Chip key={`${c.label}-${i}`} tone={c.kind === 'reflection' && c.valence === 'low' ? 'warn' : CHIP_TONE[c.kind]}>
                              {c.label}
                            </Chip>
                        ))}
                        {!open && notable.length > 4 && <Chip tone="ins">+{notable.length - 4} more</Chip>}
                        {careDays.has(d) && !chips.some((c) => c.kind === 'care') && <Chip tone="call">Care team action</Chip>}
                      </span>
                    </>
                  ) : (
                    <span className="d-muted">{rec ? `${rec.count} ${rec.count === 1 ? 'record' : 'records'}` : 'Measures only'}</span>
                  )}
                </span>
                {flagged && <span className="d-day-state">{st.label}</span>}
              </button>
              {account && <span className="d-sr">{account.text}</span>}
              {open && <DayDetail data={data} date={d} onMetric={onMetric} />}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function DayDetail({ data, date, onMetric }: { data: DashData; date: string; onMetric: (m: string) => void }) {
  const records = useMemo(() => byDay(data.events).find((d) => d.date === date), [data.events, date]);
  const measures = [...CONSENSUS_SOURCES]
    .map((src) => ({
      src,
      list: data.series
        .filter((s) => s.source === src)
        .map((s) => ({ s, p: s.points.find((p) => p.date === date && typeof p.value === 'number') }))
        .filter((x) => x.p),
    }))
    .filter((g) => g.list.length);
  return (
    <div className="d-day-detail">
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
      {records ? (
        records.groups.map((g) => (
          <div key={g.group} className="d-daypart">
            <h4 className="d-h4">{GROUP_LABEL[g.group]}</h4>
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
          </div>
        ))
      ) : (
        <p className="d-muted">No individual records are listed for this day.</p>
      )}
    </div>
  );
}
