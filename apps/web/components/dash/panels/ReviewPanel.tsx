'use client';

import { useState } from 'react';
import type { AgentStep, RecordCitation, ReviewFinding } from '@contracts';
import { shortDay } from '@/lib/clinician';
import { dateTime, sourceLabel } from '@/lib/format';
import { FALLBACK_REASON, valueText } from '@/lib/insight';
import type { DashData } from '../data';
import { Busy, Chip, EmptyState, type ChipTone } from '../kit';

const THEME: Record<ReviewFinding['theme'], { label: string; tone: ChipTone }> = {
  change: { label: 'Change from usual', tone: 'warn' },
  improvement: { label: 'Improved', tone: 'ok' },
  steady: { label: 'Steady', tone: 'neutral' },
  routine: { label: 'Routine', tone: 'info' },
  what_helps: { label: 'What helps', tone: 'info' },
  coverage: { label: 'Coverage', tone: 'neutral' },
};

const ACTOR: Record<AgentStep['actor'], string> = { code: 'Rules', gemma: 'Gemma', template: 'Template' };
const STATUS: Record<AgentStep['status'], { label: string; tone: ChipTone }> = {
  ok: { label: 'Done', tone: 'ok' },
  cached: { label: 'From cache', tone: 'info' },
  skipped: { label: 'Skipped', tone: 'neutral' },
  rejected: { label: 'Rejected', tone: 'warn' },
  fallback: { label: 'Fallback used', tone: 'warn' },
};

export function ReviewPanel({ data, onMetric }: { data: DashData; onMetric: (m: string) => void }) {
  const [tab, setTab] = useState<'review' | 'trace'>('review');
  const [openCite, setOpenCite] = useState<string | null>(null);
  const { review, evidence, trace, fromCloud } = data.view;
  const byId = new Map(evidence.map((e) => [e.id, e]));
  const byModel = review.by === 'gemma';
  const byLength = [...(data.view.comparison?.groups.flatMap((g) => g.metrics) ?? [])].sort((a, b) => b.label.length - a.label.length);
  const rejected = trace.reduce((n, s) => n + Object.values(s.rejected ?? {}).reduce((a, b) => a + b, 0), 0);

  return (
    <div className="d-stack">
      <div className="d-seg" role="tablist" aria-label="Review views">
        <button type="button" role="tab" aria-selected={tab === 'review'} onClick={() => setTab('review')}>
          Review
        </button>
        <button type="button" role="tab" aria-selected={tab === 'trace'} onClick={() => setTab('trace')}>
          Agent trace{trace.length ? ` (${trace.length} steps)` : ''}
        </button>
      </div>

      <div className="d-byline">
        <Chip tone={byModel ? 'info' : 'neutral'}>{byModel ? 'Written by Gemma' : 'Rule-based summary'}</Chip>
        <span className="d-meta">
          {byModel && review.model ? `${review.model} · ` : ''}
          {dateTime(review.generated_at)}
          {review.cached ? ' · from cache' : ''}
        </span>
      </div>
      {!byModel && !data.insightLoading && (
        <p className="d-callout">
          {data.insightError && !fromCloud
              ? 'The intelligence layer could not be reached, so this summary is assembled from the consensus and the weekly record.'
              : (FALLBACK_REASON[review.fallback_reason ?? ''] ?? 'The model did not write this review, so the rule-based summary is shown.')}{' '}
          <button type="button" className="d-link" onClick={data.reloadInsight}>
            Ask again
          </button>
        </p>
      )}
      {data.insightLoading && <Busy label="Kaiku is reading the record. The rule-based summary is shown meanwhile." />}

      {tab === 'review' ? (
        <>
          {review.overview ? (
            <div className="d-overview">
              <span className="d-overview-k">Gemma’s reading of the whole record</span>
              <p>{review.overview}</p>
              <p className="d-meta">Rule summary: {review.headline}</p>
            </div>
          ) : (
            <p className="d-headline">{review.headline}</p>
          )}
          {review.findings.length === 0 ? (
            <EmptyState title="Nothing to review yet">Findings appear once a few days of data are recorded.</EmptyState>
          ) : (
            <ol className="d-findings">
              {review.findings.map((f, i) => {
                const cited = f.cites.map((id) => byId.get(id)).filter((e): e is RecordCitation => Boolean(e));
                return (
                  <li key={`${f.title}-${i}`} className="d-finding">
                    <div className="d-row-head">
                      <span className="d-row-title">{f.title}</span>
                      <Chip tone={THEME[f.theme].tone}>{THEME[f.theme].label}</Chip>
                    </div>
                    <p className="d-meaning">{f.meaning}</p>
                    {f.consider && (
                      <p className="d-consider">
                        <span className="d-strong">Consider: </span>
                        {f.consider}
                      </p>
                    )}
                    {(f.facts.length > 0 || cited.length > 0) && (
                      <details className="d-proof">
                        <summary>
                          Evidence from the record ({Math.max(f.facts.length, cited.length)})
                        </summary>
                        <ul>
                          {f.facts.map((t, fi) => {
                            // "Mood dial (Check-ins & robot): …", "Mood dial: …" or "Mood dial 3 of 5 …"
                            const cmp = byLength.find((x) => t.startsWith(x.label));
                            const colon = t.indexOf(': ');
                            const name = cmp ? cmp.label : colon > 0 && colon < 60 ? t.slice(0, colon) : '';
                            const rest = name ? t.slice(name.length).replace(/^\s*\([^)]*\)/, '').replace(/^[:\s]+/, '') : t;
                            return (
                              <li key={t}>
                                {name && <span className="d-fact-name">{name}</span>}
                                <span>{rest.replace(/^\w/, (ch) => ch.toUpperCase())}</span>
                                {cmp && f.facts.findIndex((x) => x.startsWith(cmp.label)) === fi && (
                                  <span className="d-fact-mini">
                                    <span>This week {cmp.this_week_text ?? 'not recorded'}</span>
                                    <span>Week before {cmp.previous_week_text ?? 'not recorded'}</span>
                                    <span>Usual {cmp.usual_text ?? 'not set yet'}</span>
                                    <button type="button" className="d-link" onClick={() => onMetric(cmp.metric)}>
                                      Trends
                                    </button>
                                  </span>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                        {cited.length > 0 && (
                          <div className="d-cites" aria-label="Cited records">
                            <span className="d-meta">Cited</span>
                            {cited.map((e) => {
                              const key = `${i}:${e.id}`;
                              return (
                                <button key={e.id} type="button" className="d-cite" aria-expanded={openCite === key} onClick={() => setOpenCite(openCite === key ? null : key)}>
                                  {e.label}
                                </button>
                              );
                            })}
                          </div>
                        )}
                        {cited.map((e) => (openCite === `${i}:${e.id}` ? <Citation key={e.id} e={e} onMetric={onMetric} /> : null))}
                      </details>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </>
      ) : trace.length === 0 ? (
        <EmptyState title="No trace for this summary">
          {fromCloud ? 'The service returned no steps for this review.' : 'This summary was assembled in the browser from the consensus and weekly record, so no model steps were run.'}
        </EmptyState>
      ) : (
        <>
          <p className="d-muted">
            Each step the service ran for this review. Rules decide the state; Gemma only words the meaning, and every claim it makes is checked against the record.
            {rejected > 0 ? ` ${rejected} model ${rejected === 1 ? 'claim was' : 'claims were'} rejected by the checker.` : ''}
          </p>
          <ol className="d-trace">
            {trace.map((s, i) => (
              <li key={`${s.step}-${i}`} className="d-step">
                <span className="d-step-n" aria-hidden="true">
                  {i + 1}
                </span>
                <div className="d-step-body">
                  <div className="d-row-head">
                    <span className="d-row-title">{s.label}</span>
                    <Chip tone={STATUS[s.status].tone}>{STATUS[s.status].label}</Chip>
                  </div>
                  {s.detail && <p>{s.detail}</p>}
                  <p className="d-meta">
                    {ACTOR[s.actor]}
                    {s.model ? ` · ${s.model}` : ''}
                    {typeof s.latency_ms === 'number' ? ` · ${s.latency_ms < 1000 ? `${Math.round(s.latency_ms)} ms` : `${(s.latency_ms / 1000).toFixed(1)} s`}` : ''}
                    {s.cache_hit ? ' · cache hit' : ''}
                    {typeof s.items === 'number' ? ` · ${s.items} ${s.items === 1 ? 'item' : 'items'}` : ''}
                  </p>
                  {Object.keys(s.rejected ?? {}).length > 0 && (
                    <p className="d-meta">
                      Rejected by the checker: {Object.entries(s.rejected ?? {}).map(([k, n]) => `${k.replace(/_/g, ' ')} × ${n}`).join(', ')}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}

export function Citation({ e, onMetric }: { e: RecordCitation; onMetric?: (m: string) => void }) {
  const hasValue = typeof e.value === 'number';
  return (
    <div className="d-citation">
      <span className="d-row-title">{e.label}</span>
      {hasValue && (
        <span>
          {valueText(e.value, e.unit ?? undefined)}
          {typeof e.baseline === 'number' ? `, their usual ${valueText(e.baseline, e.unit ?? undefined)}` : ''}
        </span>
      )}
      {e.detail && <span>{e.detail}</span>}
      <span className="d-meta">
        {e.source ? sourceLabel(e.source) : 'Record'}
        {e.observed_at ? ` · ${shortDay(e.observed_at)}` : ''}
      </span>
      {e.metric && onMetric && (
        <button type="button" className="d-link" onClick={() => onMetric(e.metric as string)}>
          Show in Trends
        </button>
      )}
    </div>
  );
}
