'use client';

/**
 * Three week panels from GET /v1/me/week or /v1/patients/{id}/week: Routines (a 7-dot strip per rhythm: this week's
 * days vs the usual), Going well, Worth a look. Sentences come from the cloud, already worded for the audience; this
 * component only lays them out. Person view never uses red: "worth a look" is honey, like "worth a check-in".
 */

import type { Routine, WeekItem, WeekSummary } from '@contracts';

export type WeekWords = {
  routines: string;
  well: string;
  look: string;
  routinesEmpty: string;
  wellEmpty: string;
  lookEmpty: string;
  status: Record<Routine['status'], string>;
  sleepStatus: Record<Routine['status'], string>;
  range: (from: string, to: string) => string;
  tag?: (i: WeekItem) => string | null;
  basis?: (r: Routine) => string | null;
};

const fmt = (d: string, locale: string) =>
  new Date(`${d}T12:00:00`).toLocaleDateString(locale, { weekday: 'short', day: 'numeric', month: 'short' });

function Dots({ r }: { r: Routine }) {
  const usual = Math.round(r.usual_per_week);
  return (
    <span className="wk-dots" aria-hidden="true">
      {Array.from({ length: 7 }, (_, i) => (
        <i key={i} className={i < r.this_week ? 'on' : i < usual ? 'usual' : ''} />
      ))}
    </span>
  );
}

export function WeekPanels({ week, words, locale = 'en-GB' }: { week: WeekSummary; words: WeekWords; locale?: string }) {
  return (
    <div className="wk">
      <p className="xs mut wk-range">{words.range(fmt(week.week_start, locale), fmt(week.week_end, locale))}</p>
      <section className="k-card wk-routines" aria-labelledby="wk-r">
        <h3 id="wk-r" className="wk-h">
          {words.routines}
        </h3>
        {week.routines.length === 0 ? (
          <p className="sm mut">{words.routinesEmpty}</p>
        ) : (
          <ul className="wk-rlist">
            {week.routines.map((r) => (
              <li key={`${r.activity}-${r.weekday ?? ''}`} className={`wk-r st-${r.status}`}>
                <div className="wk-rtop">
                  <b>{r.label}</b>
                  <span className={`wk-st st-${r.status}`}>
                    {(r.activity === 'sleep' ? words.sleepStatus : words.status)[r.status]}
                  </span>
                </div>
                <div className="wk-rmeta">
                  {r.activity !== 'sleep' && <Dots r={r} />}
                  <span className="xs mut" lang="en">
                    {r.text}
                  </span>
                </div>
                {words.basis?.(r) && <span className="xs mut">{words.basis(r)}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
      <div className="wk-two">
        <Items id="wk-w" title={words.well} empty={words.wellEmpty} items={week.going_well} tone="well" tag={words.tag} />
        <Items id="wk-l" title={words.look} empty={words.lookEmpty} items={week.worth_a_look} tone="look" tag={words.tag} />
      </div>
    </div>
  );
}

function Items({
  id,
  title,
  empty,
  items,
  tone,
  tag,
}: {
  id: string;
  title: string;
  empty: string;
  items: WeekItem[];
  tone: 'well' | 'look';
  tag?: (i: WeekItem) => string | null;
}) {
  return (
    <section className={`k-card wk-items wk-${tone}`} aria-labelledby={id}>
      <h3 id={id} className="wk-h">
        <i aria-hidden="true" />
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="sm mut">{empty}</p>
      ) : (
        <ul>
          {items.map((it, i) => (
            <li key={i} className={`wk-i k-${it.kind}`}>
              <span lang="en">{it.text}</span>
              {tag?.(it) && <span className="wk-tag">{tag(it)}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
