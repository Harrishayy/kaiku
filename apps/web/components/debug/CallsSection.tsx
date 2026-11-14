'use client';

import { Fragment } from 'react';
import type { DebugDay } from '@contracts';
import { callOutcome, latency, localClock, modelTotals, num, orderCalls, slowestCall, toolsInOrder, usd } from '@/lib/debug';
import { Empty, Mono, Tag } from './bits';

const OUTCOME_TONE = { failed: 'bad', fallback: 'warn', ok: undefined } as const;

/** The companion's conversations that started this day: shape and tools only. The service sends no words. */
export function ConversationsBody({ day }: { day: DebugDay }) {
  const list = day.conversations ?? [];
  if (!list.length) return <Empty>No companion conversation started {day.is_today ? 'today' : 'on this day'}.</Empty>;
  return (
    <div className="dbg-scroll">
      <table className="dbg-table" aria-label="Companion conversations that started this day">
        <thead>
          <tr>
            <th scope="col">Start</th>
            <th scope="col">Surface</th>
            <th scope="col">Purpose</th>
            <th scope="col" className="dbg-num" title="Minutes it ran / Live minutes the spend ledger counts for it">
              Min / billed
            </th>
            <th scope="col">How it ended</th>
            <th scope="col" title="In call order while the conversation is open (shown with arrows); one of each, unordered, once the device has uploaded it">
              Tools
            </th>
            <th scope="col" title="Whether the person’s setting kept the words of this conversation. This page never shows them.">
              Words kept
            </th>
          </tr>
        </thead>
        <tbody>
          {list.map((c) => {
            const tools = c.tools ?? [];
            const feel = c.feel ?? [];
            return (
              <Fragment key={c.session_id}>
                <tr>
                  <th scope="row" className="dbg-mono dbg-nowrap" title={`session ${c.session_id}`}>
                    {localClock(c.start, day.timezone)}
                    <span className="dbg-dim"> → {c.end ? localClock(c.end, day.timezone) : 'open'}</span>
                  </th>
                  <td className="dbg-mono">{c.surface}</td>
                  <td className="dbg-mono">{c.intent}</td>
                  <td className="dbg-num">
                    {num(c.minutes, 1)} <span className="dbg-dim">/ {num(c.billed_minutes, 1)}</span>
                  </td>
                  <td>{c.outcome ? <Tag tone={c.outcome === 'crisis' ? 'bad' : c.outcome === 'completed' ? 'ok' : undefined}>{c.outcome}</Tag> : <Tag tone="warn">never closed</Tag>}</td>
                  <td>
                    {tools.length ? (
                      <>
                        <ol className={`dbg-tools${toolsInOrder(c) ? ' is-ordered' : ''}`}>
                          {tools.map((t, i) => (
                            <li key={i}>
                              <Mono>{t}</Mono>
                            </li>
                          ))}
                        </ol>
                        <span className="dbg-dim"> {toolsInOrder(c) ? 'in call order' : 'one of each, order not kept'}</span>
                      </>
                    ) : (
                      <span className="dbg-dim">no tool call</span>
                    )}
                  </td>
                  <td>{c.transcript_kept ? 'yes' : 'no'}</td>
                </tr>
                {feel.length > 0 && (
                  <tr className="dbg-sub">
                    <td colSpan={7}>
                      <table className="dbg-table dbg-table-inner">
                        <caption className="dbg-caption">feel calls ({feel.length}): what was heard, then the plan</caption>
                        <thead>
                          <tr>
                            <th scope="col">Time</th>
                            <th scope="col">Heard: kind</th>
                            <th scope="col">Valence</th>
                            <th scope="col">Energy</th>
                            <th scope="col">Tone</th>
                            <th scope="col">Via</th>
                            <th scope="col">Plan: stance</th>
                            <th scope="col">Depth</th>
                            <th scope="col">Offer</th>
                          </tr>
                        </thead>
                        <tbody>
                          {feel.map((f, i) => (
                            <tr key={i}>
                              <td className="dbg-mono dbg-nowrap">{localClock(f.ts, day.timezone)}</td>
                              <td className="dbg-mono">{f.kind}</td>
                              <td className="dbg-mono">{f.valence}</td>
                              <td className="dbg-mono">{f.energy ?? '—'}</td>
                              <td className="dbg-mono">{(f.tone ?? []).join(', ') || '—'}</td>
                              <td className="dbg-mono">{f.via ?? '—'}</td>
                              <td className="dbg-mono">{f.stance ?? <span className="dbg-dim">not stored</span>}</td>
                              <td className="dbg-mono">{f.depth ?? '—'}</td>
                              <td>{f.offered === null || f.offered === undefined ? <span className="dbg-dim">not stored</span> : f.offered ? <Tag tone="ok">offered</Tag> : 'no offer'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Every model call of the day: totals per model, then the calls with failures on top and the slowest marked. */
export function ModelCallsBody({ day }: { day: DebugDay }) {
  const calls = day.model_calls ?? [];
  if (!calls.length) return <Empty>No model was called {day.is_today ? 'today' : 'on this day'}.</Empty>;
  const totals = modelTotals(calls);
  const slowest = slowestCall(calls);
  const ordered = orderCalls(calls);
  return (
    <>
      <div className="dbg-scroll">
        <table className="dbg-table dbg-totals">
          <caption className="dbg-caption">Totals per model</caption>
          <thead>
            <tr>
              <th scope="col">Provider</th>
              <th scope="col">Model</th>
              <th scope="col" className="dbg-num">
                Calls
              </th>
              <th scope="col" className="dbg-num">
                Failed
              </th>
              <th scope="col" className="dbg-num">
                Fallback
              </th>
              <th scope="col" className="dbg-num" title="Sum over the calls that recorded a latency">
                Total latency
              </th>
              <th scope="col" className="dbg-num">
                Slowest
              </th>
              <th scope="col" className="dbg-num" title="Sum of the spend ledger’s estimates, over the calls that have one">
                Est. cost
              </th>
            </tr>
          </thead>
          <tbody>
            {totals.map((t) => (
              <tr key={`${t.provider}/${t.model}`} className={t.failed ? 'is-bad' : undefined}>
                <td className="dbg-mono">{t.provider}</td>
                <th scope="row" className="dbg-mono">
                  {t.model}
                </th>
                <td className="dbg-num">{t.calls}</td>
                <td className="dbg-num">{t.failed || <span className="dbg-dim">0</span>}</td>
                <td className="dbg-num">{t.fallback || <span className="dbg-dim">0</span>}</td>
                <td className="dbg-num">{t.timed ? latency(t.latency_ms) : '—'}</td>
                <td className="dbg-num">{latency(t.slowest_ms)}</td>
                <td className="dbg-num">
                  {t.costed ? usd(t.est_usd) : '—'}
                  {t.costed > 0 && t.costed < t.calls && <span className="dbg-dim"> ({t.costed} of {t.calls})</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="dbg-scroll">
        <table className="dbg-table">
          <caption className="dbg-caption">Calls ({calls.length}): failures first, then fallbacks, then by time</caption>
          <thead>
            <tr>
              <th scope="col">Time</th>
              <th scope="col">Provider</th>
              <th scope="col">Model</th>
              <th scope="col">Task</th>
              <th scope="col">Route</th>
              <th scope="col">Result</th>
              <th scope="col" className="dbg-num">
                Latency
              </th>
              <th scope="col" className="dbg-num" title="Tokens in / out. The ledger does not record them yet when this is empty.">
                Tokens in / out
              </th>
              <th scope="col" className="dbg-num" title="The spend ledger’s estimate for this call, when one row matches it">
                Est. cost
              </th>
              <th scope="col" title="Empty: the ledger does not record cache hits">
                Cache
              </th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((c, i) => {
              const outcome = callOutcome(c);
              return (
                <tr key={`${c.ts}-${i}`} className={outcome === 'failed' ? 'is-bad' : outcome === 'fallback' ? 'is-flagged' : undefined}>
                  <td className="dbg-mono dbg-nowrap">{localClock(c.ts, day.timezone)}</td>
                  <td className="dbg-mono">{c.provider}</td>
                  <td className="dbg-mono">{c.model}</td>
                  <td className="dbg-mono">{c.task}</td>
                  <td className="dbg-mono">{c.route ?? '—'}</td>
                  <td>
                    <Tag tone={OUTCOME_TONE[outcome]}>{outcome}</Tag>
                  </td>
                  <td className="dbg-num">
                    {latency(c.latency_ms)}
                    {c === slowest && <Tag tone="warn">slowest</Tag>}
                  </td>
                  <td className="dbg-num">
                    {num(c.tokens_in, 0)} / {num(c.tokens_out, 0)}
                  </td>
                  <td className="dbg-num">{usd(c.est_usd)}</td>
                  <td>{c.cache_hit === null || c.cache_hit === undefined ? '—' : c.cache_hit ? 'hit' : 'miss'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
