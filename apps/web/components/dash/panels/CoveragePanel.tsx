'use client';

import { CONSENSUS_SOURCES } from '@contracts';
import { shortDay } from '@/lib/clinician';
import { relTime, sourceLabel } from '@/lib/format';
import type { DashData } from '../data';
import { Chip, EmptyState, Provenance } from '../kit';

const LEVEL = (share: number) => (share <= 0 ? 0 : share < 0.5 ? 1 : share < 1 ? 2 : 3);
const LEVEL_WORD = ['no readings', 'some measures', 'most measures', 'all measures'];

export function CoveragePanel({ data, onDay }: { data: DashData; onDay: (d: string) => void }) {
  const cov = data.view.coverage;
  const dates = [...new Set(data.series.flatMap((s) => s.points.map((p) => p.date)))].sort().slice(-21);
  if (!dates.length) return <EmptyState title="No data received yet">Coverage fills in as each signal group sends its first day.</EmptyState>;
  const rows = [...CONSENSUS_SOURCES].map((src) => {
    const mine = data.series.filter((s) => s.source === src);
    return {
      src,
      cells: dates.map((d) => {
        const have = mine.filter((s) => s.points.some((p) => p.date === d && typeof p.value === 'number')).length;
        return { d, have, of: mine.length, level: mine.length ? LEVEL(have / mine.length) : 0 };
      }),
    };
  });

  return (
    <div className="d-stack">
      <div className="d-verdict">
        <p className="d-strong">{cov.summary}</p>
        <p className="d-meta">
          {cov.first_day && cov.last_day ? `${shortDay(cov.first_day)} to ${shortDay(cov.last_day)} · ` : ''}
          {cov.recorded_days} of {cov.span_days} days recorded · {cov.observations.toLocaleString('en-GB')} records ·{' '}
          {cov.baseline_ready ? 'personal usual established' : 'personal usual still forming'}
        </p>
      </div>

      <section aria-label="Completeness by day">
        <h3 className="d-h3">Completeness by day</h3>
        <div className="d-heat-scroll">
          <table className="d-heat">
            <thead>
              <tr>
                <th scope="col">Signal group</th>
                {dates.map((d, i) => (
                  <th key={d} scope="col" title={shortDay(d)}>
                    {i % 7 === (dates.length - 1) % 7 ? shortDay(d).split(' ')[0] : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.src}>
                  <th scope="row">{sourceLabel(r.src)}</th>
                  {r.cells.map((c) => (
                    <td key={c.d}>
                      <button
                        type="button"
                        className={`d-heat-cell lvl-${c.level}`}
                        title={`${shortDay(c.d)}: ${c.have} of ${c.of} measures`}
                        aria-label={`${sourceLabel(r.src)}, ${shortDay(c.d)}: ${LEVEL_WORD[c.level]} (${c.have} of ${c.of})`}
                        onClick={() => onDay(c.d)}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="d-legend" aria-label="Completeness key">
          {LEVEL_WORD.map((wd, i) => (
            <li key={wd}>
              <span className={`d-heat-cell lvl-${i}`} aria-hidden="true" />
              {wd.replace(/^\w/, (ch) => ch.toUpperCase())}
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="What each group sent">
        <h3 className="d-h3">What each group sent</h3>
        <ul className="d-rows">
          {cov.groups.map((g) => (
            <li key={g.source} className="d-row-item">
              <div className="d-row-head">
                <span className="d-row-title">{g.label}</span>
                <Chip tone={g.sufficient ? 'ok' : 'neutral'}>{g.sufficient ? 'Enough for a verdict' : 'Not enough data'}</Chip>
              </div>
              <p className="d-meta">
                {g.days_last_14} of the last 14 days · {g.last_at ? `last data ${relTime(g.last_at)}` : 'nothing received'}
              </p>
              {g.types.length > 0 ? (
                <ul className="d-types">
                  {g.types.map((t) => (
                    <li key={t.type}>
                      <span>{t.label}</span>
                      <span className="d-types-n">
                        {t.count} on {t.days} {t.days === 1 ? 'day' : 'days'}
                      </span>
                      <Provenance sources={t.captured_by ?? []} simulated={t.simulated > 0} />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="d-muted">No records from this group.</p>
              )}
            </li>
          ))}
          {(cov.other ?? []).length > 0 && (
            <li className="d-row-item">
              <div className="d-row-head">
                <span className="d-row-title">Other records</span>
              </div>
              <ul className="d-types">
                {(cov.other ?? []).map((t) => (
                  <li key={t.type}>
                    <span>{t.label}</span>
                    <span className="d-types-n">
                      {t.count} on {t.days} {t.days === 1 ? 'day' : 'days'}
                    </span>
                    <Provenance sources={t.captured_by ?? []} simulated={t.simulated > 0} />
                  </li>
                ))}
              </ul>
            </li>
          )}
        </ul>
      </section>
    </div>
  );
}
