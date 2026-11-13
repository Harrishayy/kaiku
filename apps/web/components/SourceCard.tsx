'use client';

import type { MetricSeries, SourceVerdict } from '@contracts';
import { cardSeries, num, sourceMissing, sparkline, verdictChip } from '@/lib/clinician.ts';
import { pct, relTime, sourceBlurb, sourceLabel } from '@/lib/format';

/**
 * One consensus source (look book clinician card): verdict chip + up to 3 metrics with sparkline and usual band.
 * Data-driven: any source the cloud reports renders. "insufficient" is never shown as fine; a source with no data
 * at all (e.g. no watch) says so plainly and that it isn't counted.
 */
export function SourceCard({ source, v, series }: { source: string; v: SourceVerdict | undefined; series: MetricSeries[] }) {
  const chip = verdictChip(v?.verdict);
  const metrics = cardSeries(source, v, series);
  const missing = sourceMissing(v, series, source);
  return (
    <article className="k-src" aria-labelledby={`src-${source}`}>
      <div className="h">
        <span id={`src-${source}`}>{sourceLabel(source)}</span>
        <span className={`k-chip ${chip.cls}`}>{chip.label}</span>
      </div>
      <p className="xs mut">{sourceBlurb(source)}</p>
      {missing ? (
        <p className="sm mut">
          {source === 'wearable' ? 'No watch connected.' : 'No data from this source yet.'} Not counted, so it can’t pull the
          consensus either way.
        </p>
      ) : (
        <>
          {v?.verdict === 'insufficient' && (
            <p className="sm mut">Not enough recent data to compare with this person’s usual. Not counted in the consensus.</p>
          )}
          {metrics.map((s) => (
            <Metric key={s.metric} s={s} />
          ))}
        </>
      )}
      {v && !missing && (
        <p className="foot">
          Confidence {pct(v.confidence)} · last data {relTime(v.last_data_at)}
        </p>
      )}
    </article>
  );
}

function Metric({ s }: { s: MetricSeries }) {
  const sp = sparkline(s.points);
  if (!sp) return null;
  const v = sp.last.value as number;
  const worse =
    (s.worse_when === 'down' && typeof sp.last.band_low === 'number' && v < sp.last.band_low) ||
    (s.worse_when === 'up' && typeof sp.last.band_high === 'number' && v > sp.last.band_high);
  return (
    <div className="k-met">
      <span title={s.unit ? `${s.label} (${s.unit})` : s.label}>{s.label}</span>
      <svg viewBox="0 0 72 22" aria-hidden="true">
        {sp.band && <rect x="0" y={sp.band.y.toFixed(1)} width="72" height={sp.band.h.toFixed(1)} rx="2" style={{ fill: 'var(--k-sky-soft)' }} />}
        <polyline points={sp.line} style={{ fill: 'none', stroke: 'var(--k-muted)', strokeWidth: 1.5 }} />
        <circle cx={sp.dot.x} cy={sp.dot.y} r="2.6" style={{ fill: worse ? 'var(--k-honey)' : 'var(--k-sage)' }} />
      </svg>
      <b>{num(v)}</b>
    </div>
  );
}
