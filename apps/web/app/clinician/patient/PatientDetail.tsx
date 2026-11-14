'use client';

/**
 * Clinician patient view (design/ia.md "Clinician", look book): header → consensus chip + one sentence + rule →
 * four source cards → evidence table → explanation ("written by AI, not a decision") + actions → timeline → PHQ-9.
 * → this week (routines, going well, worth a look; GET /v1/patients/{id}/week) → what Kaiku has learned (graph, only
 * when the person shares: activities, what helps, routines; never people, places, likes, plans).
 * English only. Kaiku appears only as a 30 px icon. Never shows the person's memories list.
 */

import Link from 'next/link';
import { useMemo, useState } from 'react';
import {
  CONSENSUS_SOURCES,
  type ActionRequest,
  type ActionResult,
  type Consensus,
  type KnowledgeGraph,
  type MeResponse,
  type MetricSeries,
  type PatientsResponse,
  type Phq9History,
  type TimelineResponse,
  type WeekSummary,
} from '@contracts';
import { api, useApi } from '@/lib/api';
import { consensusChip, consensusSentence, evidenceRows, VERDICT_WORD } from '@/lib/clinician.ts';
import { ACTION_LABEL, STATE_HINT, activityLabel, dateTime, relTime, sourceLabel } from '@/lib/format';
import { useQueryParam } from '@/lib/params';
import { Mascot } from '@/components/Mascot';
import { SourceCard } from '@/components/SourceCard';
import { Phq9Chart, TimelineChart } from '@/components/TimelineChart';
import { LearnedGraph, type GraphWords } from '@/components/LearnedGraph';
import { WeekPanels, type WeekWords } from '@/components/WeekPanels';
import { RecordStrip } from '@/components/RecordStrip';

type ActionName = ActionRequest['action'];

export function PatientDetail() {
  const id = useQueryParam('id');
  if (id === undefined)
    return (
      <div className="ui k-cl">
        <p className="mut" role="status">
          Loading…
        </p>
      </div>
    );
  if (!id)
    return (
      <div className="ui k-cl">
        <div className="k-empty">
          <span>
            No one selected. Go back to <Link href="/clinician/">who needs a call</Link>.
          </span>
        </div>
      </div>
    );
  return <Detail id={id} />;
}

function Detail({ id }: { id: string }) {
  const enc = encodeURIComponent(id);
  const consensus = useApi<Consensus>(`/v1/patients/${enc}/consensus`, 15_000);
  const timeline = useApi<TimelineResponse>(`/v1/patients/${enc}/timeline`);
  const phq9 = useApi<Phq9History>(`/v1/patients/${enc}/phq9`);
  const me = useApi<MeResponse>(`/v1/me?home_id=${enc}`);
  const week = useApi<WeekSummary>(`/v1/patients/${enc}/week`, 60_000);
  const graph = useApi<KnowledgeGraph>(`/v1/patients/${enc}/graph`, 120_000);
  const list = useApi<PatientsResponse>('/v1/patients');
  const summary = list.data?.patients.find((p) => p.id === id);
  const series = useMemo(() => timeline.data?.series ?? [], [timeline.data]);

  const c = consensus.data;
  const sources = useMemo(() => {
    const vs = c?.sources ?? [];
    const extra = vs.map((s) => s.source as string).filter((s) => !(CONSENSUS_SOURCES as readonly string[]).includes(s));
    return [...CONSENSUS_SOURCES, ...extra].map((s) => ({ source: s as string, v: vs.find((x) => x.source === s) }));
  }, [c]);
  const rows = useMemo(() => (c ? evidenceRows(c, series) : []), [c, series]);

  if (consensus.loading && !c)
    return (
      <div className="ui k-cl">
        <p className="mut" role="status">
          Loading consensus…
        </p>
      </div>
    );
  if (consensus.error && !c)
    return (
      <div className="ui k-cl">
        <div className="k-banner" role="alert">
          <div>
            <b>Couldn’t load this person.</b> {consensus.error.status === 404 ? 'No one with this id.' : 'Can’t reach the Kaiku cloud.'}{' '}
            <button type="button" className="k-b k-b-soft k-b-small" onClick={consensus.reload}>
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  if (!c) return null;

  const chip = consensusChip(c.state, c.agreement);
  const name = (summary?.display_name ?? id).replace(/\s*\(SIMULATED\)$/, '');
  const lastPhq = phq9.data?.entries.at(-1);
  const lastData = sources.map((s) => s.v?.last_data_at).filter(Boolean).sort().at(-1);
  const sim = Boolean(summary?.sim ?? me.data?.sim);

  return (
    <div className="ui k-cl" lang="en">
      <Link className="k-back" href="/clinician/">
        ← Who needs a call
      </Link>
      <div className="k-cl-head">
        <Mascot state={c.state === 'stable' ? 'idle' : 'cozy'} size={30} still tappable={false} />
        <div>
          <h1 style={{ fontSize: '1.5em' }}>
            {name} {sim && <span className="k-sim">SIMULATED</span>}
          </h1>
          <p className="meta">
            Last data {relTime(lastData)}
            {lastPhq ? ` · last PHQ-9 ${lastPhq.total} (${dateTime(lastPhq.ts)})` : ' · no PHQ-9 yet'}
            {c.acknowledged_by ? ` · acknowledged by ${c.acknowledged_by}` : ''}
          </p>
        </div>
      </div>

      <section className="k-consensus" aria-label="Consensus">
        <div className="stack s8">
          <div className="row-wrap">
            <span className={`k-chip k-chip-lg ${chip.cls}`}>{chip.label}</span>
            <b>{consensusSentence(c)}</b>
          </div>
          <p className="sm ink2">{STATE_HINT[c.state]}</p>
          {c.state === 'safety' && c.safety_since && (
            <p className="sm">
              <b>Safety flag since {dateTime(c.safety_since)}.</b> The person was shown the MIELI Crisis Helpline (09 2525 0111)
              and 112 on their device. Call today.
            </p>
          )}
          {c.agreement === 'disagree' && (
            <p className="sm">
              {c.explanation?.disagreement_note ?? (
                <>
                  <b>Sources disagree.</b> Look at each source card below before deciding.
                </>
              )}
            </p>
          )}
          {c.agreement === 'low_coverage' && (
            <p className="sm">
              <b>Low coverage.</b> Fewer than two sources have enough recent data, so this is less certain. Missing data is never
              read as fine.
            </p>
          )}
          <p className="k-rule">
            Rule {c.rule_version} · computed {relTime(c.computed_at)} ·{' '}
            {sources.map((s) => `${sourceLabel(s.source)} ${VERDICT_WORD[s.v?.verdict ?? 'insufficient']}`).join(' · ')}
          </p>
        </div>
        <QuickActions id={id} onDone={consensus.reload} />
      </section>

      {week.data && week.data.next_steps && week.data.next_steps.length > 0 && (
        <NextSteps id={id} steps={week.data.next_steps} onDone={consensus.reload} />
      )}

      <div className="k-srcs">
        {sources.map(({ source, v }) => (
          <SourceCard key={source} source={source} v={v} series={series} />
        ))}
      </div>

      <section className="k-card" aria-labelledby="wk-h">
        <h2 id="wk-h">This week</h2>
        <p className="xs mut">
          Computed by fixed rules from observations against this person’s own usual
          {week.data?.shared ? ' and, shared by the person, their conversations with Kaiku' : ''}. Not a decision; it never
          changes the consensus.
        </p>
        {!week.data ? (
          <p className="sm mut">{week.error ? 'Week summary unavailable.' : 'Loading…'}</p>
        ) : (
          <>
            <h3>One record: what each source added</h3>
            <RecordStrip
              week={week.data}
              words={{
                source: (s) => sourceLabel(s),
                days: (n) => `${n}/7 days`,
                none: 'No data',
                flow: 'Every observation lands in one record per person. The routines, the two lists below, the consensus and the learned map are all computed from it.',
                dayLetters: ['S', 'M', 'T', 'W', 'T', 'F', 'S'],
              }}
            />
            <WeekPanels week={week.data} words={CARE_WEEK} />
          </>
        )}
      </section>

      <section className="k-card" aria-labelledby="kg-h">
        <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
          <h2 id="kg-h">What Kaiku has learned</h2>
          {graph.data?.shared && <span className="k-chip ok">Shared by {name}</span>}
        </div>
        {!graph.data ? (
          <p className="sm mut">{graph.error ? 'Unavailable.' : 'Loading…'}</p>
        ) : !graph.data.shared ? (
          <div className="k-empty sm">
            <b>Not shared.</b>
            <span>
              {name} hasn’t turned on “Share with my care team” on their own page. What Kaiku learns stays with them until
              they do.
            </span>
          </div>
        ) : (
          <>
            <p className="xs mut">
              Activities, what helps and routines, with how many observations, sessions or notes back each one. Click a node
              to see its links.
              {graph.data.withheld && graph.data.withheld.length > 0 &&
                ` Kept private by design: ${graph.data.withheld.map((w) => CARE_GRAPH.types[w].toLowerCase()).join(', ')}.`}
            </p>
            <LearnedGraph graph={graph.data} words={CARE_GRAPH} />
          </>
        )}
      </section>

        <section className="k-card" aria-labelledby="ev-h" style={{ padding: '12px 6px 4px' }}>
          <h2 id="ev-h" className="lbl" style={{ paddingInline: 10 }}>
            Evidence
          </h2>
          {rows.length === 0 ? (
            <p className="sm mut" style={{ padding: '0 10px 10px' }}>
              No metric is drifting from this person’s usual range.
            </p>
          ) : (
            <div className="k-scroll-x" tabIndex={0} aria-label="Evidence table, scrolls sideways">
              <table className="k-ev">
                <thead>
                  <tr>
                    <th scope="col">Metric</th>
                    <th scope="col">Source</th>
                    <th scope="col">Latest</th>
                    <th scope="col">Usual (median, range)</th>
                    <th scope="col">How unusual</th>
                    <th scope="col">Direction</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={`${r.metric}-${i}`}>
                      <td>{r.label}</td>
                      <td>{sourceLabel(r.source)}</td>
                      <td>{r.today}</td>
                      <td>{r.usual}</td>
                      <td className="nw">
                        {r.size}
                        {r.z !== '—' && <span className="zw">z {r.z}</span>}
                      </td>
                      <td className={r.worse ? 'worse' : 'better'}>{r.direction}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="xs mut k-ev-note">
                How unusual: the latest value compared with this person’s own usual, measured in their usual day-to-day spread
                (z). About 2 or more counts as a change. Clay = in the direction that counts as a change; green = the other way.
              </p>
            </div>
          )}
        </section>

      <div className="k-cl-bottom">
        <section className="k-card" aria-labelledby="tl-h" id="timeline">
          <h2 id="tl-h">Timeline against personal usual</h2>
          <div className="k-legend" aria-hidden="true">
            <span>
              <i style={{ background: 'var(--chart-band)' }} />
              usual range
            </span>
            <span>
              <i style={{ background: 'var(--chart-median)', height: 2 }} />
              median
            </span>
            <span>
              <i style={{ background: 'var(--k-honey)', borderRadius: '50%', width: 8, height: 8 }} />
              change from usual
            </span>
          </div>
          {timeline.loading && !timeline.data && <p className="sm mut">Loading timelines…</p>}
          {timeline.error && !timeline.data && (
            <p className="sm mut">
              Timelines unavailable.{' '}
              <button type="button" className="k-b k-b-ghost k-b-small" onClick={timeline.reload}>
                Try again
              </button>
            </p>
          )}
          {timeline.data && <SeriesBySource series={series} />}
        </section>
        <div className="k-cl-right">
          <ExplanationCard c={c} />
          <Actions id={id} onDone={consensus.reload} suggested={c.explanation?.suggested_actions ?? []} />
          <section className="k-card" aria-labelledby="phq-h">
            <h2 id="phq-h">PHQ-9</h2>
            {phq9.loading && !phq9.data && <p className="sm mut">Loading…</p>}
            {phq9.error && !phq9.data && <p className="sm mut">PHQ-9 history unavailable.</p>}
            {phq9.data && (
              <>
                <Phq9Chart entries={phq9.data.entries} />
                {phq9.data.next_due && <p className="xs mut">Next due {phq9.data.next_due}.</p>}
              </>
            )}
          </section>
          <section className="k-card" aria-labelledby="help-h">
            <h2 id="help-h">What helps this person</h2>
            {me.data?.what_helps?.length ? (
              <ul className="stack s8" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {[...me.data.what_helps]
                  .sort((a, b) => (b.mean_effect ?? -1) - (a.mean_effect ?? -1))
                  .map((h) => (
                    <li key={h.activity} className="sm" style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <span style={{ minWidth: 0 }}>{h.label || activityLabel(h.activity)}</span>
                      <span className="mut num" style={{ flex: 'none' }}>
                        {typeof h.mean_effect === 'number' ? `${Math.round(h.mean_effect * 100)}%` : '—'} · {h.tries} tries
                      </span>
                    </li>
                  ))}
              </ul>
            ) : (
              <p className="sm mut">Not enough activity history yet.</p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

const CARE_WEEK: WeekWords = {
  routines: 'Routines',
  well: 'Going well this week',
  look: 'Worth a look this week',
  routinesEmpty: 'No regular rhythm found yet (needs about three weeks of data).',
  wellEmpty: 'Nothing stands out on the positive side this week.',
  lookEmpty: 'Nothing stands out this week.',
  status: { kept: 'kept', partly: 'partly', slipped: 'fewer than usual' },
  sleepStatus: { kept: 'steady', partly: 'shifted a little', slipped: 'shifted' },
  range: (from, to) => `Last 7 days: ${from} – ${to}. Usual = the 3 weeks before.`,
  tag: (i) => (i.source ? sourceLabel(i.source) : null),
  basis: (r) => (r.basis?.includes('episodes') ? 'Includes conversations with Kaiku (shared)' : null),
};

const CARE_GRAPH: GraphWords = {
  types: {
    me: 'Person',
    activity: 'Activities',
    routine: 'Routines',
    helper: 'What helps (told)',
    person: 'People',
    place: 'Places',
    like: 'Likes',
    plan: 'Plans',
  },
  rel: {
    knows: 'knows',
    goes_to: 'goes to',
    likes: 'likes',
    helped_by: 'helped by',
    plans: 'plans',
    did: 'does',
    helped: 'helped (bandit)',
    about: 'about',
    keeps: 'keeps',
    of: 'routine of',
  },
  relIn: {
    knows: 'known by',
    goes_to: 'visited by',
    likes: 'liked by',
    helped_by: 'helps',
    plans: 'planned by',
    did: 'done by',
    helped: 'helped',
    about: 'mentioned in',
    keeps: 'kept by',
    of: 'routine',
  },
  evidence: (n) => `Evidence: ${n}`,
  links: 'Links',
  hint: 'Click a node to see what it links to.',
  none: 'No links.',
  me: 'Person',
};

const WHEN: Record<string, string> = { today: 'Today', this_week: 'This week', next_contact: 'Next contact' };

function NextSteps({ id, steps, onDone }: { id: string; steps: NonNullable<WeekSummary['next_steps']>; onDone: () => void }) {
  const [done, setDone] = useState<Record<string, string>>({});
  return (
    <section className="k-card" aria-labelledby="ns-h">
      <h2 id="ns-h">Suggested next steps</h2>
      <p className="xs mut">Chosen by fixed rules from the consensus and this week’s record. Suggestions only; the decision is yours.</p>
      <ul className="steps">
        {steps.map((s, i) => (
          <li key={i} className="step">
            <span className={`step-when ${s.when}`}>{WHEN[s.when]}</span>
            <div>
              <b>{s.text}</b>
              {s.why && <p>{s.why}</p>}
            </div>
            {s.action && (
              <button
                type="button"
                className="k-b k-b-soft k-b-small"
                disabled={Boolean(done[s.action])}
                onClick={async () => {
                  try {
                    await postAction(id, { action: s.action! });
                    setDone((d) => ({ ...d, [s.action!]: 'Logged' }));
                    onDone();
                  } catch {
                    setDone((d) => ({ ...d, [s.action!]: '' }));
                  }
                }}
              >
                {done[s.action] || ACTION_LABEL[s.action]}
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ExplanationCard({ c }: { c: Consensus }) {
  const e = c.explanation;
  return (
    <section className="k-card" aria-labelledby="exp-h">
      <h2 id="exp-h" className="lbl">
        Summary · {e?.by === 'gemma' ? 'written by AI' : 'from a fixed template'}, not a decision
      </h2>
      {!e && <p className="sm mut">No summary yet. The state above comes from the rule alone.</p>}
      {e && (
        <>
          <p className="sm" style={{ fontWeight: 700 }}>
            {e.text}
          </p>
          {e.per_source && e.per_source.length > 0 && (
            <ul className="stack s8 sm ink2" style={{ margin: 0, paddingLeft: '1.1em' }}>
              {e.per_source.map((s) => (
                <li key={s.source}>{s.summary}</li>
              ))}
            </ul>
          )}
          <p className="xs mut">{e.caveats}</p>
          <p className="xs mut">
            {e.by === 'gemma' ? `Gemma${e.model ? ` (${e.model})` : ''}` : 'Template'}
            {e.generated_at ? ` · ${relTime(e.generated_at)}` : ''}. The state comes from the rule above, never from the model.
          </p>
        </>
      )}
    </section>
  );
}

function SeriesBySource({ series }: { series: MetricSeries[] }) {
  const groups = new Map<string, MetricSeries[]>();
  series
    .filter((s) => s.points.some((p) => typeof p.value === 'number'))
    .forEach((s) => groups.set(s.source, [...(groups.get(s.source) ?? []), s]));
  const order = [...CONSENSUS_SOURCES, ...[...groups.keys()].filter((k) => !(CONSENSUS_SOURCES as readonly string[]).includes(k))];
  if (groups.size === 0) return <p className="sm mut">No data yet.</p>;
  return (
    <>
      {order
        .filter((src) => groups.has(src))
        .map((src) => (
          <details key={src} className="k-tl-group" open={src === order.find((o) => groups.has(o))}>
            <summary>
              <h3 style={{ display: 'inline' }}>{sourceLabel(src)}</h3>{' '}
              <span className="xs mut">· {groups.get(src)!.length} metrics</span>
              <span className="tl-show">Show / hide</span>
            </summary>
            <div className="k-tl-charts">
              {groups.get(src)!.map((s) => (
                <TimelineChart key={s.metric} series={s} />
              ))}
            </div>
          </details>
        ))}
    </>
  );
}

async function postAction(id: string, body: ActionRequest): Promise<ActionResult> {
  return api<ActionResult>(`/v1/patients/${encodeURIComponent(id)}/actions`, { method: 'POST', body: JSON.stringify(body) });
}

function QuickActions({ id, onDone }: { id: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="stack s8">
      <div className="k-acts">
        <button
          type="button"
          className="pri"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await postAction(id, { action: 'acknowledge' });
              setMsg('Marked as seen.');
              onDone();
            } catch {
              setMsg('Couldn’t save. Try again.');
            } finally {
              setBusy(false);
            }
          }}
        >
          Mark as called
        </button>
        <a className="k-b k-b-soft k-b-small" href="#actions">
          More actions
        </a>
      </div>
      {msg && (
        <p className="xs mut" role="status">
          {msg}
        </p>
      )}
    </div>
  );
}

const ACTIONS: ActionName[] = ['flag_booster', 'flag_icbt_referral', 'send_message', 'acknowledge'];

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
      const r = await postAction(id, { action, note: note.trim() || null, by: by.trim() || null });
      setDone(`${ACTION_LABEL[action]} logged. Consensus now: ${consensusChip(r.state, 'agree').label.toLowerCase()}.`);
      if (action === 'send_message') setNote('');
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="k-card" aria-labelledby="act-h" id="actions">
      <h2 id="act-h">Actions</h2>
      <p className="xs mut">Logged in Kaiku only; no outside system is contacted in this prototype.</p>
      <label htmlFor="by">Your initials (optional)</label>
      <input id="by" type="text" value={by} onChange={(e) => setBy(e.target.value)} maxLength={80} />
      <label htmlFor="note">Note, or a message to the person</label>
      <textarea id="note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      <div className="k-acts">
        {ACTIONS.map((a) => (
          <button
            key={a}
            type="button"
            className={suggested.includes(a) ? 'pri' : ''}
            disabled={busy !== null || (a === 'send_message' && !note.trim())}
            onClick={() => run(a)}
          >
            {busy === a ? 'Saving…' : ACTION_LABEL[a]}
          </button>
        ))}
      </div>
      {done && (
        <p className="xs" role="status">
          {done}
        </p>
      )}
      {error && (
        <p className="xs" role="alert" style={{ fontWeight: 700 }}>
          {error}
        </p>
      )}
    </section>
  );
}
