'use client';

import { useMemo, useState } from 'react';
import { CONSENSUS_SOURCES } from '@contracts';
import { lastValue, shortDay } from '@/lib/clinician';
import { sourceLabel } from '@/lib/format';
import { ACTION_LABEL } from '@/lib/format';
import { localDate } from '@/lib/evidence';
import { daySignals, pointMeaning, valueText, type Tone } from '@/lib/insight';
import { stateChip } from '@/lib/labels';
import { ChartLegend, TrendChart, type ChartMark } from '../Chart';
import type { DashData } from '../data';
import { Chip, EmptyState, ToneMark, type ChipTone } from '../kit';

const RANGES = [
  { days: 14, label: '2 weeks' },
  { days: 30, label: '30 days' },
  { days: 0, label: 'All' },
];

const VS_PREVIOUS: Record<Tone, string> = {
  better: 'Better than the week before',
  worse: 'Less favourable than the week before',
  similar: 'About the same as the week before',
  unknown: 'Week before not comparable',
};
const VS_USUAL: Record<Tone, string> = {
  better: 'Better than their usual',
  worse: 'A change from their usual',
  similar: 'Within their usual',
  unknown: 'No usual to compare yet',
};

const PHASE: Record<string, { label: string; tone: ChipTone }> = {
  settling: { label: 'Settling in', tone: 'ins' },
  steady: { label: 'Steady', tone: 'ok' },
  dip: { label: 'Dip from their usual', tone: 'warn' },
  recovering: { label: 'Coming back', tone: 'info' },
  recovered: { label: 'Back in their usual', tone: 'ok' },
};

const COURSE_KIND: Record<string, string> = {
  onset: 'First away from their usual',
  lowest: 'Furthest from their usual',
  back_in_range: 'Back within their usual',
  still_away: 'Still away from their usual',
};

const ACTION_MARK: Record<string, string> = {
  acknowledge: 'Care team reviewed',
  send_message: 'Care team message',
  flag_booster: 'Booster flagged',
  flag_icbt_referral: 'iCBT referral flagged',
};

/** A care action as a chart note: the first words of the practitioner's own note when there is one. */
function actionLabel(action: string, note: string | null | undefined): string {
  const words = (note ?? '').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return ACTION_MARK[action] ?? ACTION_LABEL[action] ?? 'Care team action';
  return `Care team: ${words.slice(0, 4).join(' ').replace(/[.,;:]$/, '')}${words.length > 4 ? '…' : ''}`;
}

const SUSTAINED: Record<string, string> = {
  change_from_usual: 'Rule reading: sustained change from their usual',
  better_than_usual: 'Rule reading: sustained on the better side',
  as_usual: 'Rule reading: no sustained change',
  not_enough_data: 'Rule reading: too few recent days',
};

export function TrendsPanel({
  data,
  metric,
  onMetric,
  onDay,
}: {
  data: DashData;
  metric: string | null;
  onMetric: (m: string) => void;
  onDay: (d: string) => void;
}) {
  const [range, setRange] = useState(0);
  const [courseOpen, setCourseOpen] = useState(false);
  const withData = useMemo(() => data.series.filter((s) => s.points.some((p) => typeof p.value === 'number')), [data.series]);
  const signals = useMemo(() => daySignals(data.series), [data.series]);
  const groups = useMemo(() => {
    const order: string[] = [...CONSENSUS_SOURCES];
    for (const s of withData) if (!order.includes(s.source)) order.push(s.source);
    return order.map((src) => ({ src, list: withData.filter((s) => s.source === src) })).filter((g) => g.list.length);
  }, [withData]);

  // Default to the measure the consensus leans on most, else the first one with readings.
  const lead = data.consensus.sources.flatMap((v) => v.evidence ?? []).find((e) => withData.some((s) => s.metric === e.metric))?.metric;
  const current = withData.find((s) => s.metric === metric) ?? withData.find((s) => s.metric === lead) ?? withData[0];
  if (!current)
    return (
      <EmptyState title="No measures recorded yet">
        Charts appear after the first day of check-ins, walks, app use or watch data.
      </EmptyState>
    );

  const states = data.view.stateHistory.map((d) => ({ date: d.date, ...stateChip(d.state, d.agreement) }));
  const course = data.view.course;
  // the cloud's course of change carries the dated points; without it, the action log and questionnaires do
  const marks: ChartMark[] = course?.events.length
    ? course.events
        // the points that belong on this chart: care actions, questionnaires, and this measure's own turning points
        .filter((e) => e.kind === 'care_action' || e.kind === 'phq9' || e.metric_id === current.metric)
        .map((e) => ({ date: e.date, label: e.metric_id ? (COURSE_KIND[e.kind] ?? e.label) : e.kind === 'phq9' ? e.text.replace(/\s+on \d+ \w+\.?$/, '') : e.label, detail: e.text }))
    : [
        ...data.view.actions.map((act) => ({ date: localDate(act.ts), label: actionLabel(act.action, act.note), detail: [act.by, act.note].filter(Boolean).join(': ') })),
        ...(data.phq9?.entries ?? []).map((e) => ({ date: localDate(e.ts), label: `PHQ-9: ${e.total} of 27` })),
      ];
  const stage = data.view.stage;
  const shown = range ? { ...current, points: current.points.slice(-range) } : current;
  const last = lastValue(current.points);
  const m = last ? pointMeaning(current, last) : null;
  const cmp = data.view.comparison?.groups.flatMap((g) => g.metrics).find((x) => x.metric === current.metric) ?? null;

  return (
    <div className="d-trends">
      <div className="d-toolbar">
        <label className="d-field">
          <span className="d-field-k">Measure</span>
          <select value={current.metric} onChange={(e) => onMetric(e.target.value)}>
            {groups.map((g) => (
              <optgroup key={g.src} label={sourceLabel(g.src)}>
                {g.list.map((s) => (
                  <option key={s.metric} value={s.metric}>
                    {s.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        <div className="d-seg" role="group" aria-label="Period shown">
          {RANGES.map((r) => (
            <button key={r.days} type="button" aria-pressed={range === r.days} onClick={() => setRange(r.days)}>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {course && (
        <div className={`d-course${courseOpen ? ' is-open' : ''}`}>
          <Chip tone={PHASE[course.phase]?.tone ?? 'neutral'}>{PHASE[course.phase]?.label ?? course.phase}</Chip>
          <p>{course.summary}</p>
          <button type="button" className="d-link" aria-expanded={courseOpen} onClick={() => setCourseOpen(!courseOpen)}>
            {courseOpen ? 'Less' : 'More'}
          </button>
        </div>
      )}

      {last && m && (
        <p className="d-lead">
          <span className="d-lead-v">{valueText(last.value, current.unit)}</span>
          <span className="d-lead-t">
            on {shortDay(last.date)}. {m.text}. <ToneMark tone={m.tone}>{m.range}</ToneMark>
          </span>
        </p>
      )}

      <TrendChart series={shown} onDay={onDay} states={states} signals={signals} marks={marks} />
      <ChartLegend early={stage.early} />

      <div className="d-compare" aria-label="Period comparison">
        {cmp ? (
          <>
            <Cell k="This week" v={cmp.this_week_text ?? valueText(cmp.this_week, current.unit)} note={`${cmp.days_this_week} of 7 days recorded`} />
            <Cell k="Week before" v={cmp.previous_week_text ?? valueText(cmp.previous_week, current.unit)} note={`${cmp.days_previous_week} of 7 days recorded`} />
            <Cell k="Their usual" v={cmp.usual_text ?? valueText(cmp.usual, current.unit)} note={cmp.early_baseline ? 'Early baseline, lower confidence' : 'Median of their own earlier days'} />
            <div className="d-compare-tones">
              <ToneMark tone={cmp.vs_previous}>{VS_PREVIOUS[cmp.vs_previous]}</ToneMark>
              <ToneMark tone={cmp.vs_usual}>{VS_USUAL[cmp.vs_usual]}</ToneMark>
              <span className="d-meta">{SUSTAINED[cmp.sustained]}</span>
            </div>
            <p className="d-compare-meaning">{cmp.meaning}</p>
          </>
        ) : (
          <p className="d-compare-meaning d-muted">A week-by-week comparison appears once two weeks have readings.</p>
        )}
      </div>
    </div>
  );
}

function Cell({ k, v, note }: { k: string; v: string; note: string }) {
  return (
    <div className="d-cell" title={note}>
      <span className="d-cell-k">{k}</span>
      <span className="d-cell-v">{v}</span>
      <span className="d-cell-n">{note}</span>
    </div>
  );
}
