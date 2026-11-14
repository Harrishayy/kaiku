'use client';

import { useState } from 'react';
import type { DebugClaim, DebugDay, DebugRead } from '@contracts';
import type { ApiError } from '@/lib/api';
import { Chip } from '@/components/dash/kit';
import { stateChip } from '@/lib/labels';
import { READING_LABEL, READING_TONE, anchorOf, claimGroups, fallbackWords, latency, localClock, num, rejectedTotal, resolveCites, usd, type AskCost, type ClaimGroup } from '@/lib/debug';
import { Chevron, Empty, Mono, Tag, type Nav } from './bits';

/** The answer first: what the rule decided for this day, then the read of the day with its citations. */
export function ResultBody({
  day,
  read,
  readKept,
  readCurrent,
  asking,
  askError,
  askCost,
  nav,
}: {
  day: DebugDay;
  read: DebugRead;
  readKept: boolean;
  readCurrent: boolean;
  asking: boolean;
  askError: ApiError | null;
  askCost: AskCost | null;
  nav: Nav;
}) {
  return (
    <div className="dbg-result">
      <ConsensusBox day={day} nav={nav} />
      <ReadBox day={day} read={read} readKept={readKept} readCurrent={readCurrent} asking={asking} askError={askError} askCost={askCost} nav={nav} />
    </div>
  );
}

function ConsensusBox({ day, nav }: { day: DebugDay; nav: Nav }) {
  const c = day.consensus;
  const chip = stateChip(c.state, c.agreement);
  const anchor = anchorOf.consensus();
  const reasons = c.reasons ?? [];
  const changed = c.changed ?? [];
  return (
    <div className={`dbg-box${nav.hit === anchor ? ' is-hit' : ''}`} id={anchor} tabIndex={-1} aria-labelledby="dbg-consensus-h">
      <h3 id="dbg-consensus-h">Consensus for this day</h3>
      <p className="dbg-answer">
        <Chip tone={chip.tone}>{chip.label}</Chip>
        <Mono title="state, as stored">{c.state}</Mono>
        {c.held && <Tag tone="warn" title="The rule alone gives a lower state for this day; the earlier state is kept by hysteresis">held</Tag>}
        {c.acknowledged_by && <Tag tone="ok">acknowledged by {c.acknowledged_by}</Tag>}
      </p>
      <dl className="dbg-kv">
        <dt>Rule alone</dt>
        <dd>
          <Mono>{c.raw_state}</Mono>
          {c.raw_state !== c.state ? <span className="dbg-dim"> for this day alone, before hysteresis</span> : <span className="dbg-dim"> (same as the state)</span>}
        </dd>
        <dt>Agreement</dt>
        <dd>
          <Mono>{c.agreement}</Mono>
        </dd>
        <dt>Day before</dt>
        <dd>{c.previous_state ? <Mono>{c.previous_state}</Mono> : <span className="dbg-dim">no state the day before</span>}</dd>
        <dt>In this state since</dt>
        <dd>{c.state_since ? <Mono>{c.state_since}</Mono> : <span className="dbg-dim">not recorded</span>}</dd>
        {c.safety_since && (
          <>
            <dt>Safety since</dt>
            <dd>
              <Mono>{c.safety_since}</Mono>
            </dd>
          </>
        )}
        <dt>Acknowledged</dt>
        <dd>{c.acknowledged_by ? c.acknowledged_by : <span className="dbg-dim">no</span>}</dd>
        <dt>Rule version</dt>
        <dd>
          <Mono>{c.rule_version}</Mono>
        </dd>
      </dl>
      <h4>Why the rule gives this state</h4>
      {reasons.length ? (
        <ul className="dbg-list">
          {reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : (
        <Empty>The rule gave no reason.</Empty>
      )}
      <h4>
        Changed since the day before <span className="dbg-count">{changed.length}</span>
      </h4>
      {changed.length ? (
        <ul className="dbg-list dbg-list-cols dbg-mono">
          {changed.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      ) : (
        <Empty>Nothing differs from the day before.</Empty>
      )}
    </div>
  );
}

function ReadBox({
  day,
  read,
  readKept,
  readCurrent,
  asking,
  askError,
  askCost,
  nav,
}: {
  day: DebugDay;
  read: DebugRead;
  readKept: boolean;
  readCurrent: boolean;
  asking: boolean;
  askError: ApiError | null;
  askCost: AskCost | null;
  nav: Nav;
}) {
  const [openAll, setOpenAll] = useState(false);
  const rejected = Object.entries(read.rejected ?? {});
  const dropped = rejectedTotal(read.rejected);
  const gemma = read.by === 'gemma';
  return (
    <div className="dbg-box" aria-labelledby="dbg-read-h">
      <div className="dbg-box-head">
        <h3 id="dbg-read-h">Read of the day</h3>
        <button type="button" className="d-btn d-btn-quiet dbg-small" aria-pressed={openAll} onClick={() => setOpenAll((v) => !v)}>
          {openAll ? 'Hide cited facts' : 'Show all cited facts'}
        </button>
      </div>
      <p className="dbg-answer">
        <Chip tone={READING_TONE[read.reading]}>{READING_LABEL[read.reading]}</Chip>
        <Mono title="reading: decided by code from the day’s metrics, never by the model">{read.reading}</Mono>
        <span className="dbg-dim">the word is decided by code</span>
      </p>
      <p className={`dbg-prov${gemma ? ' is-gemma' : ''}`}>
        {gemma ? (
          <>
            <strong>Written by Gemma</strong>
            {read.model && <Mono>{read.model}</Mono>}
            <Tag>{read.cached ? 'cached' : 'new call'}</Tag>
          </>
        ) : (
          <>
            <strong>Written by code</strong>
            <span>deterministic fallback: {fallbackWords(read.fallback_reason)}</span>
            {read.fallback_reason && <Mono>{read.fallback_reason}</Mono>}
            {read.model && <Mono title="The model that would have written it">{read.model}</Mono>}
          </>
        )}
        <span className="dbg-dim">
          at {localClock(read.generated_at, day.timezone)} · digest <Mono>{read.digest.slice(0, 10)}</Mono>
        </span>
      </p>
      {(gemma || dropped > 0) && (
        <p className="dbg-prov">
          {dropped > 0 ? (
            <>
              <Tag tone="warn">
                {dropped} {dropped === 1 ? 'claim' : 'claims'} rejected by the validators
              </Tag>
              {rejected.map(([category, n]) => (
                <Mono key={category}>
                  {category} × {n}
                </Mono>
              ))}
            </>
          ) : (
            <span className="dbg-dim">The validators rejected no claim.</span>
          )}
        </p>
      )}
      {askCost && (
        <p className="dbg-prov">
          <span>
            This ask: {askCost.calls} model {askCost.calls === 1 ? 'call' : 'calls'}
          </span>
          <Mono>{latency(askCost.latency_ms)}</Mono>
          <Mono title="The spend ledger’s estimate, logged under the home’s today">est. {usd(askCost.est_usd)}</Mono>
        </p>
      )}
      {readKept && (
        <p className={`dbg-note${readCurrent ? '' : ' is-warn'}`} role="status">
          {readCurrent
            ? 'Kept from the last time Gemma was asked. The day’s data has the same digest, so the read still describes it.'
            : 'Kept from the last time Gemma was asked. The day’s data has changed since (the digest differs): ask again for a read of what is there now.'}
        </p>
      )}
      {asking && (
        <p className="dbg-note" role="status">
          <span className="d-spinner" aria-hidden="true" /> Asking Gemma for this day. A cold model can take a few minutes; the read below stays until it answers.
        </p>
      )}
      {askError && (
        <p className="dbg-note is-bad" role="alert">
          Gemma was asked and the request failed: {askError.message}
        </p>
      )}

      <ul className="dbg-claims">
        <Claim claim={read.summary} lead day={day} nav={nav} openAll={openAll} />
      </ul>
      {claimGroups(read).map((g) => (
        <ClaimGroupBlock key={`${read.digest}-${read.by}-${g.key}`} group={g} first={gemma ? MAX_CLAIMS : FIRST_CLAIMS} day={day} nav={nav} openAll={openAll} />
      ))}
    </div>
  );
}

/**
 * How many claims a part shows before a developer asks for the rest. The read written by code lists every measure
 * with its whole fact, so it starts short; Gemma's parts are kept to six by the validators and are shown whole.
 */
const FIRST_CLAIMS = 3;
const MAX_CLAIMS = 6;

function ClaimGroupBlock({ group, first, day, nav, openAll }: { group: ClaimGroup; first: number; day: DebugDay; nav: Nav; openAll: boolean }) {
  const [all, setAll] = useState(false);
  const shown = all ? group.claims : group.claims.slice(0, first);
  return (
    <div className="dbg-claimgroup">
      <h4>
        {group.title} <span className="dbg-count">{group.claims.length}</span>
      </h4>
      {group.claims.length ? (
        <ul className="dbg-claims">
          {shown.map((c, i) => (
            <Claim key={i} claim={c} day={day} nav={nav} openAll={openAll} />
          ))}
        </ul>
      ) : (
        <Empty>{group.empty}</Empty>
      )}
      {group.claims.length > first && (
        <button type="button" className="d-btn d-btn-quiet dbg-small" aria-expanded={all} onClick={() => setAll((v) => !v)}>
          {all ? `Show the first ${first}` : `Show all ${group.claims.length}`}
        </button>
      )}
    </div>
  );
}

/** One claim with the facts it cites: the name jumps to the row, the toggle shows each fact's detail and numbers. */
function Claim({ claim, lead, day, nav, openAll }: { claim: DebugClaim; lead?: boolean; day: DebugDay; nav: Nav; openAll: boolean }) {
  const [own, setOwn] = useState(false);
  const open = own || openAll;
  const cites = resolveCites(claim, day.facts ?? [], day);
  return (
    <li className={`dbg-claim${lead ? ' is-lead' : ''}`}>
      <p className="dbg-claim-text">{claim.text}</p>
      <div className="dbg-cites">
        <button type="button" className="dbg-rowbtn" aria-expanded={open} disabled={openAll} onClick={() => setOwn((v) => !v)}>
          <Chevron open={open} />
          {cites.length} {cites.length === 1 ? 'fact' : 'facts'}
        </button>
        {cites.map((c) => (
          <button
            key={c.id}
            type="button"
            className={`dbg-cite${c.fact ? '' : ' is-missing'}`}
            disabled={!c.target}
            title={c.target ? `${c.id}: go to its row` : `${c.id}: nothing on this page has that name`}
            onClick={() => c.target && nav.jump(c.target)}
          >
            {c.fact?.label ?? c.id}
          </button>
        ))}
      </div>
      {open && (
        <ul className="dbg-facts">
          {cites.map((c) => (
            <li key={c.id}>
              <Mono>{c.id}</Mono>
              {c.fact ? (
                <span className="dbg-fact-detail">
                  <span>{c.fact.detail}</span>
                  {(c.fact.numbers ?? []).length > 0 && (
                    <span className="dbg-fact-numbers" title="The numbers a claim citing this fact may use">
                      <span className="dbg-dim">numbers</span> {(c.fact.numbers ?? []).map((n) => num(n, 3)).join('  ')}
                    </span>
                  )}
                </span>
              ) : (
                <Tag tone="bad">cited, but not among the day’s facts</Tag>
              )}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
