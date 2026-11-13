'use client';

import type { MetricSeries, TimelinePoint } from '@contracts';
import { fmt } from '@/lib/format';

const W = 640;
const H = 150;
const PAD = { top: 10, right: 8, bottom: 22, left: 36 };

const outside = (p: TimelinePoint) =>
  typeof p.value === 'number' &&
  typeof p.band_low === 'number' &&
  typeof p.band_high === 'number' &&
  (p.value < p.band_low || p.value > p.band_high);

/** Worse-direction deviation: below band when worse_when=down, above band when worse_when=up. */
const worse = (p: TimelinePoint, dir: 'up' | 'down') =>
  typeof p.value === 'number' &&
  (dir === 'down'
    ? typeof p.band_low === 'number' && p.value < p.band_low
    : typeof p.band_high === 'number' && p.value > p.band_high);

/**
 * Daily values with the personal baseline band. Generic: label/unit/direction come from the series,
 * so new metrics need no frontend change. Hand-rolled SVG, no chart dependency.
 */
export function TimelineChart({ series }: { series: MetricSeries }) {
  const { label, unit, points, worse_when } = series;
  const vals = points
    .flatMap((p) => [p.value, p.band_low, p.band_high, p.baseline_median])
    .filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  const last = [...points].reverse().find((p) => typeof p.value === 'number') ?? null;
  const lastWorse = last ? worse(last, worse_when) : false;

  if (points.length === 0 || vals.length === 0) {
    return (
      <figure className="chart">
        <figcaption className="chart-head">
          <span className="chart-title">{label}</span>
        </figcaption>
        <p className="muted small">No data yet.</p>
      </figure>
    );
  }

  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const padY = (hi - lo) * 0.08;
  lo -= padY;
  hi += padY;
  const n = points.length;
  const x = (i: number) => PAD.left + (n === 1 ? (W - PAD.left - PAD.right) / 2 : (i / (n - 1)) * (W - PAD.left - PAD.right));
  const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);

  const bandPaths: string[] = [];
  let run: number[] = [];
  const flush = () => {
    if (run.length >= 1) {
      const top = run.map((i) => `${x(i)},${y(points[i].band_high as number)}`);
      const bottom = [...run].reverse().map((i) => `${x(i)},${y(points[i].band_low as number)}`);
      bandPaths.push(`M${top.join('L')}L${bottom.join('L')}Z`);
    }
    run = [];
  };
  points.forEach((p, i) => {
    if (typeof p.band_low === 'number' && typeof p.band_high === 'number') run.push(i);
    else flush();
  });
  flush();

  const linePath = (get: (p: TimelinePoint) => number | null | undefined) => {
    let d = '';
    let pen = false;
    points.forEach((p, i) => {
      const v = get(p);
      if (typeof v === 'number' && Number.isFinite(v)) {
        d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      } else pen = false;
    });
    return d;
  };

  const ticks = [hi - padY, (hi + lo) / 2, lo + padY];
  const digits = hi - lo < 5 ? 1 : 0;

  return (
    <figure className="chart">
      <figcaption className="chart-head">
        <span className="chart-title">
          {label}
          {unit ? <span className="muted"> · {unit}</span> : null}
          <span className="muted small"> · worse when {worse_when === 'down' ? 'lower' : 'higher'}</span>
        </span>
        <span className={lastWorse ? 'chart-last drift' : 'chart-last'}>
          {last ? fmt(last.value, digits) : '—'}
          {lastWorse && <span className="small"> change from usual</span>}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label}: ${n} days, latest ${last ? fmt(last.value, digits) : 'none'}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="grid" />
            <text x={PAD.left - 6} y={y(t) + 4} className="axis" textAnchor="end">
              {fmt(t, digits)}
            </text>
          </g>
        ))}
        {bandPaths.map((d, i) => (
          <path key={i} d={d} className="band" />
        ))}
        <path d={linePath((p) => p.baseline_median)} className="median" />
        <path d={linePath((p) => p.value)} className="value" />
        {points.map((p, i) =>
          typeof p.value === 'number' ? (
            <circle
              key={p.date}
              cx={x(i)}
              cy={y(p.value)}
              r={2.6}
              className={worse(p, worse_when) ? 'dot dot-out' : outside(p) ? 'dot dot-better' : 'dot'}
            >
              <title>{`${p.date}: ${fmt(p.value, digits)}`}</title>
            </circle>
          ) : null,
        )}
        <text x={PAD.left} y={H - 5} className="axis">
          {points[0]?.date}
        </text>
        <text x={W - PAD.right} y={H - 5} className="axis" textAnchor="end">
          {points[n - 1]?.date}
        </text>
      </svg>
    </figure>
  );
}

/** PHQ-9 totals over time with the standard severity cut-offs (5/10/15/20) as reference lines. */
export function Phq9Chart({ entries }: { entries: { ts: string; total: number; item9_positive: boolean }[] }) {
  if (entries.length === 0) return <p className="muted small">No PHQ-9 yet.</p>;
  const pts = [...entries].sort((a, b) => (a.ts < b.ts ? -1 : 1));
  const n = pts.length;
  const x = (i: number) => PAD.left + (n === 1 ? (W - PAD.left - PAD.right) / 2 : (i / (n - 1)) * (W - PAD.left - PAD.right));
  const y = (v: number) => PAD.top + (1 - v / 27) * (H - PAD.top - PAD.bottom);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.total).toFixed(1)}`).join('');
  return (
    <figure className="chart">
      <figcaption className="chart-head">
        <span className="chart-title">
          PHQ-9 total <span className="muted">· 0–27, every 14 days</span>
        </span>
        <span className="chart-last">{pts[n - 1].total}</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`PHQ-9: ${n} entries, latest ${pts[n - 1].total}`}>
        {[5, 10, 15, 20].map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="grid" />
            <text x={PAD.left - 6} y={y(t) + 4} className="axis" textAnchor="end">
              {t}
            </text>
          </g>
        ))}
        <path d={d} className="value" />
        {pts.map((p, i) => (
          <circle key={p.ts} cx={x(i)} cy={y(p.total)} r={3.2} className={p.item9_positive ? 'dot dot-flag' : 'dot'}>
            <title>{`${p.ts.slice(0, 10)}: ${p.total}${p.item9_positive ? ' (item 9 positive)' : ''}`}</title>
          </circle>
        ))}
        <text x={PAD.left} y={H - 5} className="axis">
          {pts[0].ts.slice(0, 10)}
        </text>
        <text x={W - PAD.right} y={H - 5} className="axis" textAnchor="end">
          {pts[n - 1].ts.slice(0, 10)}
        </text>
      </svg>
    </figure>
  );
}
