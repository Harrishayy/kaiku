'use client';

import type { SourceVerdict } from '@contracts';
import { fmt, pct, prettify, relTime, sourceBlurb, sourceLabel } from '@/lib/format';
import { VerdictChip } from './ui';

/**
 * One consensus source (robot / glasses / laptop / any future source). Data-driven: renders whatever
 * SourceVerdict the cloud sends, so a 4th source needs no change here.
 * "insufficient" is shown as "not enough data" — never as fine.
 */
export function SourceCard({
  source,
  v,
  labelFor = prettify,
}: {
  source: string;
  v: SourceVerdict | undefined;
  labelFor?: (metric: string) => string;
}) {
  const verdict = v?.verdict ?? 'insufficient';
  const evidence = v?.evidence ?? [];
  return (
    <article className={`card source source-${verdict}`} aria-labelledby={`src-${source}`}>
      <header className="source-head">
        <h3 id={`src-${source}`}>{sourceLabel(source)}</h3>
        <VerdictChip verdict={verdict} />
      </header>
      <p className="muted small source-blurb">{sourceBlurb(source)}</p>
      {!v && <p className="small">No data from this source yet.</p>}
      {v && verdict === 'insufficient' && (
        <p className="small">
          Not enough recent data to compare with this person’s usual — excluded from the consensus vote.
        </p>
      )}
      {v && evidence.length > 0 && (
        <ul className="evidence">
          {evidence.slice(0, 4).map((e, i) => (
            <li key={`${e.metric}-${i}`}>
              <strong>{labelFor(e.metric)}</strong> {e.direction === 'down' ? 'lower' : 'higher'} than usual
              {e.days ? ` on ${e.days} of the last days` : ''}
              {typeof e.z === 'number' ? <span className="muted"> · z {fmt(e.z, 1)}</span> : null}
              {e.summary ? <div className="muted small">{e.summary}</div> : null}
            </li>
          ))}
        </ul>
      )}
      {v && verdict !== 'insufficient' && evidence.length === 0 && (
        <p className="small muted">No metric is drifting from the usual range.</p>
      )}
      {v && (
        <p className="muted small source-foot">
          Confidence {pct(v.confidence)} · last data {relTime(v.last_data_at)}
        </p>
      )}
    </article>
  );
}
