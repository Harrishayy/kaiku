'use client';

/**
 * The one record (WeekSummary.sources): what each source added in the last 7 days — a bar per day and a few plain
 * counts — so anyone can see that robot, phone/Mac, glasses and watch feed one consistent record, which in turn
 * feeds the rhythms, going well / worth a look and the learned map. Counts only.
 */

import type { WeekSummary } from '@contracts';

export type RecordWords = {
  source: (s: string) => string;
  days: (n: number) => string;
  none: string;
  flow: string;
  dayLetters: string[];
};

const ORDER = ['robot', 'laptop', 'glasses', 'wearable'];

export function RecordStrip({ week, words }: { week: WeekSummary; words: RecordWords }) {
  const srcs = [...(week.sources ?? [])].sort((a, b) => ORDER.indexOf(a.source) - ORDER.indexOf(b.source));
  const start = new Date(`${week.week_start}T12:00:00`);
  const letters = Array.from({ length: 7 }, (_, i) => words.dayLetters[(start.getDay() + i) % 7]);
  return (
    <div className="stack s8">
      <div className="rec">
        {srcs.map((s) => {
          const max = Math.max(1, ...s.per_day);
          return (
            <section key={s.source} className={`rec-src ${s.source}${s.days === 0 ? ' empty' : ''}`} aria-label={words.source(s.source)}>
              <div className="rec-top">
                <b>{words.source(s.source)}</b>
                <span>{s.days ? words.days(s.days) : words.none}</span>
              </div>
              <div className="rec-bars" aria-hidden="true">
                {s.per_day.map((v, i) => (
                  <i key={i} className={v ? '' : 'zero'} style={v ? { height: `${Math.max(12, (v / max) * 100)}%` } : undefined} />
                ))}
              </div>
              <div className="rec-days" aria-hidden="true">
                {letters.map((l, i) => (
                  <span key={i}>{l}</span>
                ))}
              </div>
              {(s.counts ?? []).length > 0 && (
                <ul className="rec-counts" lang="en">
                  {(s.counts ?? []).slice(0, 3).map((c) => (
                    <li key={c.label}>
                      <b>{Math.round(c.value).toLocaleString('en-GB')}</b> {c.label}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })}
      </div>
      <p className="rec-flow">{words.flow}</p>
    </div>
  );
}
