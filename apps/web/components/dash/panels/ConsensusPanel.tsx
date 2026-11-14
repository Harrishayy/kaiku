'use client';

import { consensusSentence } from '@/lib/clinician';
import { stateChip, verdictChip } from '@/lib/labels';
import { STATE_HINT, relTime, sourceLabel } from '@/lib/format';
import { cleanText } from '@/lib/insight';
import type { DashData } from '../data';
import { Chip, Provenance } from '../kit';

const WHEN: Record<string, string> = { today: 'Today', this_week: 'This week', next_contact: 'Next contact' };

export function ConsensusPanel({ data, onMetric }: { data: DashData; onMetric: (m: string) => void }) {
  const { consensus: c, view, week } = data;
  const stage = view.stage;
  const chip = stateChip(c.state, c.agreement);
  const voting = c.sources.filter((s) => s.verdict !== 'insufficient');
  const changed = voting.filter((s) => s.verdict === 'worse');
  const lowCoverage = c.agreement === 'low_coverage';
  const agreement =
    voting.length === 0
      ? 'No signal group has enough recent data to give a verdict.'
      : c.agreement === 'disagree'
        ? `Signal groups disagree: ${changed.length} of ${voting.length} with data show a change from their usual.`
        : `${voting.length} of ${c.sources.length} signal groups have enough data; ${changed.length ? `${changed.length} show a change from their usual` : 'none shows a change from their usual'}.`;
  const labelOf = new Map(data.series.map((s) => [s.metric, s.label]));

  return (
    <div className="d-stack">
      <div className="d-verdict">
        <Chip tone={chip.tone}>
          {chip.label}
          {c.acknowledged_by ? ' · acknowledged' : ''}
        </Chip>
        {view.statusLine ? (
          // one sentence from the cloud says what the state is, when it was raised, what is back and why it still shows
          <p className="d-status">{view.statusLine}</p>
        ) : (
          <>
            <p className="d-strong">{consensusSentence(c)}.</p>
            <p>{lowCoverage ? 'This is not a confirmed steady picture: too few signal groups can vote yet.' : STATE_HINT[c.state]}</p>
            {(stage.early || stage.building) && (
              <p className="d-callout">
                Day {stage.day} of record: {stage.building ? 'still building their usual, so nothing can be compared yet' : 'early baseline, lower confidence'}.
                {stage.steadyAfter && stage.day < stage.steadyAfter ? ` A record is not read as stable before day ${stage.steadyAfter}.` : ''}
              </p>
            )}
            {c.acknowledged_by && <p className="d-meta">Acknowledged by {c.acknowledged_by}.</p>}
          </>
        )}
        {c.safety_since && <p className="d-strong">Safety flag recorded {relTime(c.safety_since)}.</p>}
      </div>

      <section aria-label="Signal groups">
        <h3 className="d-h3">Signal groups</h3>
        <p className="d-muted">{agreement}</p>
        <ul className="d-rows">
          {c.sources.map((v) => {
            const vc = verdictChip(v.verdict);
            const cov = view.coverage.groups.find((g) => g.source === v.source);
            const senders = [...new Set((cov?.types ?? []).flatMap((t) => t.captured_by ?? []))];
            const sim = (cov?.types ?? []).some((t) => t.simulated > 0);
            const note = c.explanation?.per_source?.find((p) => p.source === v.source)?.summary;
            return (
              <li key={v.source} className="d-row-item">
                <div className="d-row-head">
                  <span className="d-row-title">{sourceLabel(v.source)}</span>
                  <Chip tone={vc.tone}>{vc.label}</Chip>
                </div>
                {(v.evidence ?? []).length > 0 ? (
                  <ul className="d-bullets">
                    {(v.evidence ?? []).map((e) => (
                      <li key={e.metric}>
                        <button type="button" className="d-link" onClick={() => onMetric(e.metric)}>
                          {labelOf.get(e.metric) ?? e.metric.replace(/_/g, ' ')}
                        </button>
                        : {/ (later|earlier|slower|faster|higher|lower) than usual/.exec(e.summary ?? '')?.[1] ?? (e.direction === 'up' ? 'higher' : 'lower')} than their usual on {e.days} recent {e.days === 1 ? 'day' : 'days'}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>
                    {v.verdict === 'insufficient'
                      ? v.last_data_at
                        ? 'Too few recent usable days to compare with their usual.'
                        : 'Nothing has been received from this group.'
                      : note
                        ? cleanText(note).replace(/^[^:]+:\s*/, '').replace(/^\w/, (ch) => ch.toUpperCase())
                        : 'Within their usual range.'}
                  </p>
                )}
                <p className="d-meta">
                  {v.last_data_at ? `Last data ${relTime(v.last_data_at)}` : 'No data yet'}
                  {cov ? ` · ${cov.days_last_14} of the last 14 days` : ''}
                  {v.verdict !== 'insufficient' ? ` · data confidence ${Math.round(v.confidence * 100)}%` : ''}
                </p>
                <Provenance sources={senders} simulated={sim} />
              </li>
            );
          })}
        </ul>
      </section>

      {(week?.next_steps ?? []).length > 0 && (
        <section aria-label="Suggested next steps">
          <h3 className="d-h3">Suggested next steps</h3>
          <ul className="d-rows">
            {(week?.next_steps ?? []).map((n) => (
              <li key={n.text} className="d-row-item">
                <div className="d-row-head">
                  <span className="d-row-title">{n.text}</span>
                  <Chip>{WHEN[n.when] ?? n.when}</Chip>
                </div>
                {n.why && <p className="d-muted">{n.why}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {c.explanation?.disagreement_note && <p>{cleanText(c.explanation.disagreement_note)}</p>}
      {c.explanation?.caveats && (
        <details className="d-details">
          <summary>How to read this</summary>
          <p>{cleanText(c.explanation.caveats)}</p>
          <p className="d-muted">The state is set by a fixed rule over the signal groups. No model decides it.</p>
        </details>
      )}
    </div>
  );
}
