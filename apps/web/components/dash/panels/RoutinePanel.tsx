'use client';

import type { HelpEffect, Routine } from '@contracts';
import type { DashData } from '../data';
import { Chip, EmptyState, type ChipTone } from '../kit';

const PARTS = ['morning', 'afternoon', 'evening', 'night'] as const;
const PART_LABEL: Record<string, string> = { morning: 'Morning', afternoon: 'Afternoon', evening: 'Evening', night: 'Night', any: 'No fixed time' };
const STATUS: Record<Routine['status'], { label: string; tone: ChipTone }> = {
  kept: { label: 'Kept', tone: 'ok' },
  partly: { label: 'Partly kept', tone: 'info' },
  slipped: { label: 'Slipped', tone: 'warn' },
};
const CADENCE: Record<Routine['cadence'], string> = { daily: 'Daily', most_days: 'Most days', weekly: 'Weekly' };
const CERTAINTY: Record<HelpEffect['certainty'], string> = { early: 'Early signal', building: 'Still forming', consistent: 'Consistent so far' };

function effectWords(mean: number | null | undefined): string {
  if (typeof mean !== 'number') return 'No response recorded yet';
  if (mean >= 0.6) return 'Reported responses lean above neutral so far';
  if (mean <= 0.4) return 'Reported responses lean below neutral so far';
  return 'Reported responses are mixed so far';
}

export function RoutinePanel({ data }: { data: DashData }) {
  const r = data.view.routine;
  if (!r.routines.length && !r.helps.length)
    return <EmptyState title="No routine learned yet">Kaiku needs about a week of days before it can say what is usual.</EmptyState>;
  const parts = [...PARTS, 'any' as const]
    .map((part) => ({
      part,
      list: r.routines
        .filter((x) => (x.day_part ?? 'any') === part)
        .sort((a, b) => (a.usual_time ?? '99').localeCompare(b.usual_time ?? '99')),
    }))
    .filter((g) => g.list.length);

  return (
    <div className="d-stack">
      <div className="d-verdict">
        <p className="d-strong">{r.summary}</p>
        <div className="d-chips">
          <Chip tone="ok">{r.kept} kept</Chip>
          <Chip tone="info">{r.partly} partly</Chip>
          <Chip tone={r.slipped ? 'warn' : 'neutral'}>{r.slipped} slipped</Chip>
        </div>
      </div>

      {parts.length > 0 && (
        <section aria-label="Usual day">
          <h3 className="d-h3">Their usual day</h3>
          {parts.map((g) => (
            <div key={g.part} className="d-daypart">
              <h4 className="d-h4">{PART_LABEL[g.part]}</h4>
              <ul className="d-rows">
                {g.list.map((x) => (
                  <li key={`${x.activity}-${x.label}`} className="d-routine">
                    <span className="d-routine-time">{x.usual_time ?? (x.weekday ? x.weekday.slice(0, 3) : 'Varies')}</span>
                    <div className="d-routine-body">
                      <div className="d-row-head">
                        <span className="d-row-title">{x.label}</span>
                        <Chip tone={STATUS[x.status].tone}>{STATUS[x.status].label}</Chip>
                      </div>
                      <div className="d-adherence">
                        <span className="d-pips" role="img" aria-label={`${x.this_week} of 7 days this week`}>
                          {Array.from({ length: 7 }, (_, i) => (
                            <span key={i} className={i < x.this_week ? 'd-pip on' : 'd-pip'} />
                          ))}
                        </span>
                        <span>
                          {x.this_week} of 7 days this week, usually {Number(x.usual_per_week.toFixed(1))} a week
                        </span>
                      </div>
                      <p className="d-meta">
                        {CADENCE[x.cadence]}
                        {x.weekday ? ` · ${x.weekday}` : ''}
                        {(x.basis ?? []).includes('episodes') ? ' · seen in records and shared conversations' : ' · seen in records'}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      )}

      <section aria-label="What helps">
        <h3 className="d-h3">What helps</h3>
        {r.caveat && <p className="d-callout">{r.caveat}</p>}
        {r.helps.length === 0 ? (
          <p className="d-muted">No before-and-after responses recorded yet.</p>
        ) : (
          <ul className="d-rows">
            {r.helps.map((h) => (
              <li key={h.activity} className="d-row-item">
                <div className="d-row-head">
                  <span className="d-row-title">{h.label}</span>
                  <Chip tone={h.certainty === 'consistent' && !r.early_record ? 'ok' : 'ins'}>{CERTAINTY[h.certainty]}</Chip>
                </div>
                <Effect h={h} />
                <p>
                  {effectWords(h.mean_effect)}: {h.tries} {h.tries === 1 ? 'try' : 'tries'}
                  {typeof h.low === 'number' && typeof h.high === 'number' ? `, estimate anywhere between ${Math.round(h.low * 100)}% and ${Math.round(h.high * 100)}% (50% is neutral)` : ', too few to give a range'}.
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** Response scale 0..1 with the neutral point marked; the bar is the learner's uncertainty, the dot its estimate. */
function Effect({ h }: { h: HelpEffect }) {
  if (typeof h.mean_effect !== 'number') return null;
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  const has = typeof h.low === 'number' && typeof h.high === 'number';
  return (
    <div className="d-effect">
      <div
        className="d-effect-track"
        role="img"
        aria-label={`Estimated response ${pct(h.mean_effect)} on a scale where 50% is neutral${has ? `, likely between ${pct(h.low as number)} and ${pct(h.high as number)}` : ''}`}
      >
        <span className="d-effect-mid" />
        {has && <span className="d-effect-range" style={{ left: pct(h.low as number), width: pct((h.high as number) - (h.low as number)) }} />}
        <span className="d-effect-dot" style={{ left: pct(h.mean_effect) }} />
      </div>
      <div className="d-effect-scale">
        <span>Less helpful</span>
        <span>Neutral</span>
        <span>More helpful</span>
      </div>
    </div>
  );
}
