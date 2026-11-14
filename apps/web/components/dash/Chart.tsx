'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { MetricSeries, TimelinePoint } from '@contracts';
import { chartDomain } from '@/lib/chart-domain';
import { metricUnitLabel, shortDay, withUnit } from '@/lib/clinician';
import { pointMeaning, valueText, type DaySignal } from '@/lib/insight';
import type { ChipTone } from '@/lib/labels';
import { EmptyState } from './kit';

const M = { right: 16, bottom: 30, left: 62 };

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setSize({ w: Math.round(el.clientWidth), h: Math.round(el.clientHeight) });
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, ...size };
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

function niceTicks(lo: number, hi: number, count: number): number[] {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

/** Contiguous runs of recorded days: a missing day breaks the line, so gaps stay visible. */
function runs(points: TimelinePoint[]): number[][] {
  const out: number[][] = [];
  let cur: number[] = [];
  points.forEach((p, i) => {
    if (isNum(p.value)) cur.push(i);
    else if (cur.length) {
      out.push(cur);
      cur = [];
    }
  });
  if (cur.length) out.push(cur);
  return out;
}

export interface ChartMark {
  date: string;
  label: string;
  detail?: string;
}

export interface StateSpan {
  date: string;
  label: string;
  tone: ChipTone;
}

const STRIP = 18;
const MARK_ROW = 16;

/**
 * The one chart style: recorded values as a line with a mark per recorded day, the person's own usual range as a
 * band behind it (dashed outline while the baseline is still provisional), their usual as a dashed line, and
 * missing days as breaks in the line plus hollow marks on the axis. Above the plot, on the same day scale: the
 * consensus state for each day and dated annotations (care actions, questionnaires). Hover or arrow keys read
 * one day at a time.
 */
export function TrendChart({
  series,
  onDay,
  states = [],
  signals = [],
  marks = [],
}: {
  series: MetricSeries;
  onDay?: (date: string) => void;
  states?: StateSpan[];
  signals?: DaySignal[];
  marks?: ChartMark[];
}) {
  const { ref, w, h } = useSize<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const [byKey, setByKey] = useState(false);
  const pts = series.points;
  useEffect(() => setActive(null), [series.metric, pts.length]);

  const index = useMemo(() => new Map(pts.map((p, i) => [p.date, i])), [pts]);
  const shownMarks = useMemo(() => marks.filter((m) => index.has(m.date)).sort((a, b) => a.date.localeCompare(b.date)), [marks, index]);
  const hasStrip = states.some((s) => index.has(s.date)) || signals.some((s) => index.has(s.date));
  const top = (shownMarks.length ? MARK_ROW + 4 : 0) + (hasStrip ? STRIP + 10 : 0) + 10;

  const geo = useMemo(() => {
    const values = pts.flatMap((p) => [p.value, p.band_low, p.band_high, p.baseline_median]).filter(isNum);
    const { lo, hi } = chartDomain(values, series.unit);
    const iw = Math.max(10, w - M.left - M.right);
    const ih = Math.max(10, h - top - M.bottom);
    const X = (i: number) => M.left + (pts.length > 1 ? (i * iw) / (pts.length - 1) : iw / 2);
    const Y = (v: number) => top + ih - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo || 1)) * ih;
    return { lo, hi, iw, ih, X, Y };
  }, [pts, series.unit, w, h, top]);

  if (!pts.some((p) => isNum(p.value)))
    return (
      <div className="d-chart" ref={ref}>
        <EmptyState title="No readings for this measure yet" />
      </div>
    );

  const { lo, hi, iw, ih, X, Y } = geo;
  const colW = pts.length > 1 ? iw / (pts.length - 1) : iw;
  const yTicks = niceTicks(lo, hi, Math.max(2, Math.min(5, Math.floor(ih / 44))));
  const xEvery = Math.max(1, Math.ceil(pts.length / Math.max(2, Math.floor(iw / 64))));
  const bandRuns: number[][] = [];
  let cur: number[] = [];
  pts.forEach((p, i) => {
    if (isNum(p.band_low) && isNum(p.band_high)) cur.push(i);
    else if (cur.length) {
      bandRuns.push(cur);
      cur = [];
    }
  });
  if (cur.length) bandRuns.push(cur);
  const firstBand = bandRuns[0]?.[0] ?? pts.length;
  const firstValue = pts.findIndex((p) => isNum(p.value));
  // the days before a usual exists get a labelled bracket, on whichever side the readings leave free
  const lastBuilding = Math.min(firstBand, pts.length) - 1;
  const early = pts.slice(firstValue < 0 ? 0 : firstValue, lastBuilding + 1).map((p) => p.value).filter(isNum);
  const below = early.length > 0 && early.reduce((x, y) => x + y, 0) / early.length > (lo + hi) / 2;
  const building =
    firstValue >= 0 && lastBuilding > firstValue && X(lastBuilding) - X(firstValue) > 130
      ? { x0: X(firstValue), x1: X(lastBuilding), y: below ? top + ih - 6 : top + 4, below }
      : null;
  const a = active !== null ? pts[active] : null;
  const am = a ? pointMeaning(series, a) : null;
  const tipLeft = active !== null ? Math.min(Math.max(X(active), 108), Math.max(108, w - 108)) : 0;
  const stripY = shownMarks.length ? MARK_ROW + 4 : 0;

  // consecutive days with the same state become one labelled segment
  const segments: { from: number; to: number; label: string; tone: ChipTone }[] = [];
  for (const s of states) {
    const i = index.get(s.date);
    if (i === undefined) continue;
    const last = segments.at(-1);
    if (last && last.label === s.label && last.to === i - 1) last.to = i;
    else segments.push({ from: i, to: i, label: s.label, tone: s.tone });
  }
  const activeState = a ? states.find((s) => s.date === a.date) : null;
  const activeSignal = a ? signals.find((s) => s.date === a.date) : null;
  const activeMarks = a ? shownMarks.filter((m) => m.date === a.date) : [];

  // annotations: written out when every label fits on one row, otherwise numbered with a key under the chart,
  // so two labels can never collide
  let end = -Infinity;
  let fits = true;
  const direct = shownMarks.map((m) => {
    const x = X(index.get(m.date) as number);
    const half = (m.label.length * 6.4) / 2 + 6;
    const cx = Math.min(Math.max(x, half + 2), w - half - 2);
    if (cx - half < end) fits = false;
    end = cx + half;
    return { ...m, x, cx, n: 0 };
  });
  let lastX = -Infinity;
  const placed = fits
    ? direct
    : direct.map((m, i) => {
        const cx = Math.max(m.x, lastX + 17);
        lastX = cx;
        return { ...m, cx, n: i + 1 };
      });

  const move = (clientX: number, rect: DOMRect) => {
    const x = clientX - rect.left;
    const i = Math.round(((x - M.left) / iw) * (pts.length - 1));
    setByKey(false);
    setActive(Math.max(0, Math.min(pts.length - 1, i)));
  };
  const step = (delta: number) => {
    setByKey(true);
    setActive((i) => Math.max(0, Math.min(pts.length - 1, (i ?? pts.length - 1) + delta)));
  };
  const spoken = a
    ? `${shortDay(a.date)}: ${isNum(a.value) ? `${valueText(a.value, series.unit)}. ${am?.text}. ${am?.range}.` : 'no reading.'}${activeState ? ` State: ${activeState.label}.` : ''}${activeMarks.map((m) => ` ${m.label}.`).join('')}`
    : '';

  return (
    <>
    <div className="d-chart" ref={ref}>
      {w > 0 && h > 0 && (
        <svg
          width={w}
          height={h}
          role="img"
          tabIndex={0}
          aria-label={`${series.label} by day, with this person's usual range${hasStrip ? ' and the consensus state for each day' : ''}. Use the left and right arrow keys to read each day.`}
          onMouseMove={(e) => move(e.clientX, e.currentTarget.getBoundingClientRect())}
          onMouseLeave={() => setActive(null)}
          onClick={() => a && onDay?.(a.date)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') {
              e.preventDefault();
              step(-1);
            } else if (e.key === 'ArrowRight') {
              e.preventDefault();
              step(1);
            } else if (e.key === 'Enter' && a) onDay?.(a.date);
            else if (e.key === 'Escape') setActive(null);
          }}
          onBlur={() => setActive(null)}
        >
          {hasStrip && (
            <g>
              <text className="d-chart-tick" x={M.left - 8} y={stripY + STRIP / 2} textAnchor="end" dominantBaseline="central">
                {segments.length ? 'State' : 'Changes'}
              </text>
              {segments.length
                ? segments.map((sg) => {
                    const x0 = Math.max(M.left - 4, X(sg.from) - colW / 2);
                    const x1 = Math.min(M.left + iw + 4, X(sg.to) + colW / 2);
                    const fits = x1 - x0 - 8 >= sg.label.length * 6.6;
                    return (
                      <g key={`${sg.from}-${sg.label}`}>
                        <rect className={`d-strip d-strip-${sg.tone}`} x={x0 + 1} y={stripY} width={Math.max(2, x1 - x0 - 2)} height={STRIP} rx={4} />
                        {fits && (
                          <text className="d-strip-label" x={(x0 + x1) / 2} y={stripY + STRIP / 2} textAnchor="middle" dominantBaseline="central">
                            {sg.label}
                          </text>
                        )}
                        <title>{`${shortDay(pts[sg.from].date)} to ${shortDay(pts[sg.to].date)}: ${sg.label}`}</title>
                      </g>
                    );
                  })
                : signals.map((sg) => {
                    const i = index.get(sg.date);
                    if (i === undefined || !sg.measured) return null;
                    const level = !sg.compared ? 'ins' : sg.changed === 0 ? 'neutral' : sg.changed / sg.compared >= 0.34 ? 'call' : 'warn';
                    return (
                      <g key={sg.date}>
                        <rect className={`d-strip d-strip-${level}`} x={X(i) - Math.min(colW, 28) / 2 + 1} y={stripY} width={Math.max(2, Math.min(colW, 28) - 2)} height={STRIP} rx={4} />
                        {sg.changed > 0 && colW >= 14 && (
                          <text className="d-strip-label" x={X(i)} y={stripY + STRIP / 2} textAnchor="middle" dominantBaseline="central">
                            {sg.changed}
                          </text>
                        )}
                      </g>
                    );
                  })}
            </g>
          )}
          {yTicks.map((t) => (
            <g key={t}>
              <line className="d-chart-grid" x1={M.left} x2={M.left + iw} y1={Y(t)} y2={Y(t)} />
              <text className="d-chart-tick" x={M.left - 8} y={Y(t)} textAnchor="end" dominantBaseline="middle">
                {withUnit(t, series.unit)}
              </text>
            </g>
          ))}
          {building && (
            <g>
              <line className="d-chart-building" x1={building.x0} x2={building.x1} y1={building.y} y2={building.y} />
              <text className="d-chart-tick" x={(building.x0 + building.x1) / 2} y={building.y + (building.below ? -8 : 14)} textAnchor="middle">
                Building their usual
              </text>
            </g>
          )}
          {bandRuns.map((r) => (
            <path
              key={`b${r[0]}`}
              className={r.some((i) => pts[i].early) ? 'd-chart-band is-early' : 'd-chart-band'}
              d={
                r.length === 1
                  ? `M${X(r[0]) - 4},${Y(pts[r[0]].band_high as number)}H${X(r[0]) + 4}V${Y(pts[r[0]].band_low as number)}H${X(r[0]) - 4}Z`
                  : `M${r.map((i) => `${X(i)},${Y(pts[i].band_high as number)}`).join('L')}L${[...r].reverse().map((i) => `${X(i)},${Y(pts[i].band_low as number)}`).join('L')}Z`
              }
            />
          ))}
          {bandRuns.map((r) =>
            r.length > 1 ? (
              <path key={`m${r[0]}`} className="d-chart-usual" d={`M${r.filter((i) => isNum(pts[i].baseline_median)).map((i) => `${X(i)},${Y(pts[i].baseline_median as number)}`).join('L')}`} />
            ) : null,
          )}
          {placed.map((m) => (
            <g key={`${m.date}-${m.label}`}>
              <line className="d-chart-mark" x1={m.x} x2={m.x} y1={MARK_ROW} y2={top + ih} />
              {m.n ? (
                <>
                  <circle className="d-chart-mark-dot" cx={m.cx} cy={MARK_ROW / 2} r={7.5} />
                  <text className="d-chart-mark-n" x={m.cx} y={MARK_ROW / 2} textAnchor="middle" dominantBaseline="central">
                    {m.n}
                  </text>
                </>
              ) : (
                <text className="d-chart-mark-label" x={m.cx} y={MARK_ROW / 2} textAnchor="middle" dominantBaseline="central">
                  {m.label}
                </text>
              )}
              <title>{`${shortDay(m.date)}: ${m.label}${m.detail ? `. ${m.detail}` : ''}`}</title>
            </g>
          ))}
          {runs(pts).map((r) => (r.length > 1 ? <path key={`v${r[0]}`} className="d-chart-line" d={`M${r.map((i) => `${X(i)},${Y(pts[i].value as number)}`).join('L')}`} /> : null))}
          {pts.map((p, i) => {
            if (!isNum(p.value)) return <circle key={p.date} className="d-chart-missing" cx={X(i)} cy={top + ih} r={3} />;
            const tone = pointMeaning(series, p).tone;
            const r = active === i ? 5 : tone === 'worse' ? 4 : 3;
            return tone === 'better' ? (
              <rect key={p.date} className="d-chart-dot d-chart-dot-better" x={X(i) - r} y={Y(p.value) - r} width={r * 2} height={r * 2} transform={`rotate(45 ${X(i)} ${Y(p.value)})`} />
            ) : (
              <circle key={p.date} className={`d-chart-dot d-chart-dot-${tone}`} cx={X(i)} cy={Y(p.value)} r={r} />
            );
          })}
          <line className="d-chart-axis" x1={M.left} x2={M.left + iw} y1={top + ih} y2={top + ih} />
          {pts.map((p, i) =>
            (pts.length - 1 - i) % xEvery === 0 ? (
              <text key={p.date} className="d-chart-tick" x={X(i)} y={top + ih + 18} textAnchor={pts.length === 1 ? 'middle' : i === pts.length - 1 ? 'end' : i === 0 ? 'start' : 'middle'}>
                {shortDay(p.date)}
              </text>
            ) : null,
          )}
          {active !== null && <line className="d-chart-cross" x1={X(active)} x2={X(active)} y1={stripY} y2={top + ih} />}
        </svg>
      )}
      {a && am && (
        <div className="d-tip" style={{ left: tipLeft, top: top + 4 }} aria-hidden="true">
          <strong>{shortDay(a.date)}</strong>
          <span className="d-tip-v">{isNum(a.value) ? valueText(a.value, series.unit) : 'No reading this day'}</span>
          {isNum(a.value) && <span>{am.text}</span>}
          {isNum(a.value) && <span className="d-tip-m">{am.range}{a.early ? ' (early baseline, lower confidence)' : ''}</span>}
          {activeState && <span className="d-tip-m">State that day: {activeState.label}</span>}
          {!activeState && activeSignal && activeSignal.compared > 0 && (
            <span className="d-tip-m">
              {activeSignal.changed} of {activeSignal.compared} measures outside their usual
            </span>
          )}
          {activeMarks.map((m) => (
            <span key={m.label} className="d-tip-m">
              {m.label}
            </span>
          ))}
        </div>
      )}
      <span className="d-chart-unit">{metricUnitLabel(series.unit)}</span>
      <span className="d-sr" role="status">
        {byKey ? spoken : ''}
      </span>
    </div>
    {placed.some((m) => m.n) && (
      <ol className="d-marks" aria-label="Dated notes on the chart">
        {placed.map((m) => (
          <li key={`${m.date}-${m.label}`} title={m.detail}>
            <span className="d-marks-n" aria-hidden="true">
              {m.n}
            </span>
            <span className="d-meta">{shortDay(m.date)}</span> {m.label}
          </li>
        ))}
      </ol>
    )}
    </>
  );
}

export function ChartLegend({ early }: { early: boolean }) {
  return (
    <ul className="d-legend" aria-label="Chart key">
      <li>
        <svg width="22" height="10" aria-hidden="true"><line className="d-chart-line" x1="0" x2="22" y1="5" y2="5" /><circle className="d-chart-dot d-chart-dot-similar" cx="11" cy="5" r="3" /></svg>
        Recorded day
      </li>
      <li>
        <svg width="22" height="10" aria-hidden="true"><rect className={early ? 'd-chart-band is-early' : 'd-chart-band'} x="0.5" y="0.5" width="21" height="9" /><line className="d-chart-usual" x1="0" x2="22" y1="5" y2="5" /></svg>
        {early ? 'Usual range (early baseline)' : 'Their usual range'}
      </li>
      <li>
        <svg width="10" height="10" aria-hidden="true"><circle className="d-chart-dot d-chart-dot-worse" cx="5" cy="5" r="3.5" /></svg>
        Change from usual
      </li>
      <li>
        <svg width="10" height="10" aria-hidden="true"><rect className="d-chart-dot d-chart-dot-better" x="2" y="2" width="6" height="6" transform="rotate(45 5 5)" /></svg>
        Better side
      </li>
      <li>
        <svg width="10" height="10" aria-hidden="true"><circle className="d-chart-missing" cx="5" cy="5" r="3" /></svg>
        No reading
      </li>
    </ul>
  );
}
