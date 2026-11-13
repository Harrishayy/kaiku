'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import {
  CONSENSUS_SOURCES,
  type ActionRequest,
  type ActionResult,
  type Consensus,
  type MeResponse,
  type MetricSeries,
  type PatientsResponse,
  type Phq9History,
  type TimelineResponse,
} from '@contracts';
import { api, useApi } from '@/lib/api';
import {
  ACTION_LABEL,
  STATE_HINT,
  VERDICT_LABEL,
  activityLabel,
  dateTime,
  pct,
  prettify,
  relTime,
  sourceLabel,
} from '@/lib/format';
import { useQueryParam } from '@/lib/params';
import { SourceCard } from '@/components/SourceCard';
import { Phq9Chart, TimelineChart } from '@/components/TimelineChart';
import { AgreementBadge, Empty, ErrorBox, Loading, PageHead, SimBadge, StaleNote, StateChip } from '@/components/ui';

type ActionName = ActionRequest['action'];
const ACTIONS: ActionName[] = ['flag_booster', 'flag_icbt_referral', 'acknowledge', 'send_message'];

export function PatientDetail() {
  const id = useQueryParam('id');
  if (id === undefined) return <Loading />;
  if (!id) return <Empty>No patient selected. Go back to the <Link href="/clinician/">patient list</Link>.</Empty>;
  return <Detail id={id} />;
}

function Detail({ id }: { id: string }) {
  const enc = encodeURIComponent(id);
  const consensus = useApi<Consensus>(`/v1/patients/${enc}/consensus`, 15_000);
  const timeline = useApi<TimelineResponse>(`/v1/patients/${enc}/timeline`);
  const phq9 = useApi<Phq9History>(`/v1/patients/${enc}/phq9`);
  const me = useApi<MeResponse>(`/v1/me?home_id=${enc}`);
  const list = useApi<PatientsResponse>('/v1/patients');
  const summary = list.data?.patients.find((p) => p.id === id);

  const labelFor = useMemo(() => {
    const m = new Map((timeline.data?.series ?? []).map((s) => [s.metric, s.label]));
    return (metric: string) => m.get(metric) ?? prettify(metric);
  }, [timeline.data]);

  const c = consensus.data;
  const sources = useMemo(() => {
    const list = c?.sources ?? [];
    const extra = list.map((s) => s.source as string).filter((s) => !(CONSENSUS_SOURCES as readonly string[]).includes(s));
    return [...CONSENSUS_SOURCES, ...extra].map((s) => ({ source: s as string, v: list.find((x) => x.source === s) }));
  }, [c]);

  if (consensus.loading && !c) return <Loading label="Loading consensus…" />;
  if (consensus.error && !c) return <ErrorBox error={consensus.error} onRetry={consensus.reload} what="this patient" />;
  if (!c) return null;

  const worse = sources.filter((s) => s.v?.verdict === 'worse');
  const sufficient = sources.filter((s) => s.v && s.v.verdict !== 'insufficient');

  return (
    <>
      <p className="small">
        <Link href="/clinician/">← All patients</Link>
      </p>
      <PageHead
        title={summary?.display_name ?? id}
        lede={
          <>
            Consensus <code>{c.rule_version}</code> · computed {relTime(c.computed_at)}
            {c.acknowledged_by ? ` · acknowledged by ${c.acknowledged_by}` : ''}
          </>
        }
      >
        <SimBadge show={Boolean(summary?.sim ?? me.data?.sim)} />
        <AgreementBadge agreement={c.agreement} />
        <StateChip state={c.state} large />
      </PageHead>
      <StaleNote show={Boolean(consensus.error)} />

      <section className={`consensus-head s-${c.state}`} aria-label="Consensus">
        <p className="consensus-hint">{STATE_HINT[c.state]}</p>
        {c.state === 'safety' && c.safety_since && (
          <p className="small">
            <strong>Safety flag since {dateTime(c.safety_since)}.</strong> The person was shown the MIELI Crisis Helpline (09 2525 0111)
            and 112 locally. Call today.
          </p>
        )}
        <p className="small muted">
          {worse.length} of {sufficient.length} source{sufficient.length === 1 ? '' : 's'} with enough data report worse ·{' '}
          {sources.length - sufficient.length} without enough data.
        </p>
      </section>

      {c.agreement === 'disagree' && (
        <section className="callout callout-disagree" aria-label="Sources disagree">
          <h2>Sources disagree</h2>
          <ul>
            {sources
              .filter((s) => s.v)
              .map((s) => (
                <li key={s.source}>
                  <strong>{sourceLabel(s.source)}:</strong> {VERDICT_LABEL[s.v!.verdict].toLowerCase()}
                  {s.v!.evidence?.length
                    ? ` — ${s.v!.evidence
                        .slice(0, 2)
                        .map((e) => `${e.direction === 'down' ? 'lower' : 'higher'} ${labelFor(e.metric).toLowerCase()}`)
                        .join(', ')}`
                    : ''}
                </li>
              ))}
          </ul>
          {c.explanation?.disagreement_note && <p className="small">{c.explanation.disagreement_note}</p>}
        </section>
      )}
      {c.agreement === 'low_coverage' && (
        <section className="callout callout-coverage" aria-label="Low coverage">
          <strong>Low coverage.</strong> Only {sufficient.length} source{sufficient.length === 1 ? ' has' : 's have'} enough recent
          data, so this consensus is less certain. Missing data is never read as “fine”.
        </section>
      )}

      <div className="source-grid">
        {sources.map(({ source, v }) => (
          <SourceCard key={source} source={source} v={v} labelFor={labelFor} />
        ))}
      </div>

      <div className="grid-2" style={{ marginTop: 16 }}>
        <div>
          <ExplanationPanel c={c} />
          <section className="card" aria-labelledby="tl-h">
            <h2 id="tl-h">Trends against personal baseline</h2>
            <div className="legend" aria-hidden="true">
              <span>
                <i style={{ background: 'var(--chart-band)' }} /> usual range
              </span>
              <span>
                <i style={{ background: 'var(--chart-median)', height: 2 }} /> median
              </span>
              <span>
                <i style={{ background: 'var(--amber)', borderRadius: '50%', width: 8 }} /> change from usual (worse direction)
              </span>
            </div>
            {timeline.loading && !timeline.data && <Loading label="Loading timelines…" />}
            {timeline.error && !timeline.data && <ErrorBox error={timeline.error} onRetry={timeline.reload} what="timelines" />}
            {timeline.data && timeline.data.series.length === 0 && <p className="muted">No data yet.</p>}
            {timeline.data && <SeriesBySource series={timeline.data.series} />}
          </section>
        </div>
        <div>
          <Actions id={id} onDone={consensus.reload} suggested={c.explanation?.suggested_actions ?? []} />
          <section className="card" aria-labelledby="phq-h">
            <h2 id="phq-h">PHQ-9 (clinical anchor)</h2>
            {phq9.loading && !phq9.data && <Loading />}
            {phq9.error && !phq9.data && <p className="muted small">PHQ-9 history unavailable.</p>}
            {phq9.data && (
              <>
                <Phq9Chart entries={phq9.data.entries} />
                {phq9.data.next_due && <p className="muted small">Next due {phq9.data.next_due}.</p>}
              </>
            )}
          </section>
          <section className="card" aria-labelledby="help-h">
            <h2 id="help-h">What helps this person</h2>
            {me.data?.what_helps?.length ? (
              <HelpList items={me.data.what_helps} />
            ) : (
              <p className="muted small">Not enough activity history yet.</p>
            )}
            {me.data?.next_suggestion && (
              <p className="small">
                Next suggestion: <strong>{activityLabel(me.data.next_suggestion.arm)}</strong> — {me.data.next_suggestion.reason}
              </p>
            )}
          </section>
        </div>
      </div>
    </>
  );
}

function ExplanationPanel({ c }: { c: Consensus }) {
  const e = c.explanation;
  return (
    <section className="card" aria-labelledby="exp-h">
      <h2 id="exp-h">
        Explanation <span className="muted small">— an explanation, not a decision</span>
      </h2>
      {!e && <p className="muted">No explanation yet. The state above comes from the deterministic rule alone.</p>}
      {e && (
        <>
          <p className="brief-headline">{e.headline}</p>
          <p>{e.text}</p>
          {e.per_source && e.per_source.length > 0 && (
            <ul className="evidence">
              {e.per_source.map((s) => (
                <li key={s.source}>
                  <strong>{sourceLabel(s.source)}:</strong> {s.summary}
                </li>
              ))}
            </ul>
          )}
          <p className="caveat">{e.caveats}</p>
          <p className="muted small">
            Written by {e.by === 'gemma' ? `Gemma${e.model ? ` (${e.model})` : ''}` : 'a fixed template (no AI)'}
            {e.generated_at ? ` · ${relTime(e.generated_at)}` : ''}. The consensus state is decided by rule {c.rule_version}, never
            by the model.
          </p>
        </>
      )}
    </section>
  );
}

function SeriesBySource({ series }: { series: MetricSeries[] }) {
  const groups = new Map<string, MetricSeries[]>();
  series.forEach((s) => groups.set(s.source, [...(groups.get(s.source) ?? []), s]));
  const order = [...CONSENSUS_SOURCES, ...[...groups.keys()].filter((k) => !(CONSENSUS_SOURCES as readonly string[]).includes(k))];
  return (
    <>
      {order
        .filter((src) => groups.has(src))
        .map((src) => (
          <div key={src} className="series-group">
            <h3>{sourceLabel(src)}</h3>
            {groups.get(src)!.map((s) => (
              <TimelineChart key={s.metric} series={s} />
            ))}
          </div>
        ))}
    </>
  );
}

function HelpList({ items }: { items: NonNullable<MeResponse['what_helps']> }) {
  const sorted = [...items].sort((a, b) => (b.mean_effect ?? -1) - (a.mean_effect ?? -1));
  return (
    <ul className="helps">
      {sorted.map((h) => (
        <li key={h.activity}>
          <span>{h.label || activityLabel(h.activity)}</span>
          <span className="bar" aria-hidden="true">
            <span style={{ transform: `scaleX(${Math.max(0, Math.min(1, h.mean_effect ?? 0))})` }} />
          </span>
          <span className="muted small num">
            {typeof h.mean_effect === 'number' ? pct(h.mean_effect) : '—'} · {h.tries} tries
          </span>
        </li>
      ))}
    </ul>
  );
}

function Actions({ id, onDone, suggested }: { id: string; onDone: () => void; suggested: string[] }) {
  const [busy, setBusy] = useState<ActionName | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [by, setBy] = useState('');

  async function run(action: ActionName) {
    setBusy(action);
    setError(null);
    setDone(null);
    try {
      const body: ActionRequest = { action, note: note.trim() || null, by: by.trim() || null };
      const r = await api<ActionResult>(`/v1/patients/${encodeURIComponent(id)}/actions`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setDone(`${ACTION_LABEL[action]} logged. State now: ${r.state.replace('_', ' ')}.`);
      if (action === 'send_message') setNote('');
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="card" aria-labelledby="act-h">
      <h2 id="act-h">Actions</h2>
      <p className="muted small">Logged only — no external system is contacted in this prototype.</p>
      <label htmlFor="by" className="small">
        Your initials (optional)
      </label>
      <input id="by" type="text" value={by} onChange={(e) => setBy(e.target.value)} maxLength={80} />
      <label htmlFor="note" className="small" style={{ display: 'block', marginTop: 8 }}>
        Note / message to the person (for “Send a message”)
      </label>
      <textarea id="note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      <div className="btn-col" style={{ marginTop: 10 }}>
        {ACTIONS.map((a) => (
          <button
            key={a}
            type="button"
            className={suggested.includes(a) ? 'btn' : 'btn btn-ghost'}
            disabled={busy !== null || (a === 'send_message' && !note.trim())}
            onClick={() => run(a)}
          >
            {busy === a ? 'Saving…' : ACTION_LABEL[a]}
            {suggested.includes(a) && <span className="small">suggested</span>}
          </button>
        ))}
      </div>
      {done && (
        <p className="small" role="status">
          {done}
        </p>
      )}
      {error && (
        <p className="small" role="alert" style={{ color: 'var(--red)' }}>
          {error}
        </p>
      )}
    </section>
  );
}
