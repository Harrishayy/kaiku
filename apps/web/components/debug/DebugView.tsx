'use client';

import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import type { DebugDay, PatientsResponse } from '@contracts';
import { API_BASE, type ApiError, apiOrigin, detailLines, useApi } from '@/lib/api';
import { Busy, SimMark } from '@/components/dash/kit';
import { useAdminToken } from '@/lib/params';
import {
  NO_EVENT_FILTER,
  NO_METRIC_FILTER,
  READING_LABEL,
  callSummary,
  conversationSummary,
  debugPath,
  diffEmpty,
  diffLine,
  isDate,
  localClock,
  metricCounts,
  problemKind,
  shiftDate,
  usd,
  type CiteTarget,
  type EventFilter,
  type MetricFilter,
  type SectionId,
} from '@/lib/debug';
import { Section, Tag, type EventMarks, type Nav } from './bits';
import { ConversationsBody, ModelCallsBody } from './CallsSection';
import { EventsBody } from './EventsSection';
import { MetricsBody } from './MetricsSection';
import { ResultBody } from './ResultSection';
import { POLL_MS, useDebugDay } from './useDebugDay';
import { VerdictsBody } from './VerdictsSection';

const SECTIONS: SectionId[] = ['result', 'verdicts', 'metrics', 'events', 'conversations', 'calls'];
const ALL_OPEN = Object.fromEntries(SECTIONS.map((s) => [s, true])) as Record<SectionId, boolean>;
const OPEN_KEY = 'kaiku.debug.sections.v1';
/**
 * What an ask costs, by the spend ledger's own estimates for real reads of the seeded record (2026-11-14): about
 * $0.005 a model call, and an ask makes one call, or two when the first answer fails validation. After an ask the
 * read shows that ask's real numbers.
 */
const ASK_COST = 'about $0.01 an ask';
const ASK_HINT =
  'Ask Gemma to write the read of this day: one model call, or two when the first answer fails validation, each about $0.005 by the spend ledger’s estimate. Off again when the day or home changes; auto-refresh never asks.';

function loadOpen(): Record<SectionId, boolean> {
  try {
    const raw = JSON.parse(window.localStorage.getItem(OPEN_KEY) ?? '{}') as Record<string, unknown>;
    return Object.fromEntries(SECTIONS.map((s) => [s, raw[s] !== false])) as Record<SectionId, boolean>;
  } catch {
    return ALL_OPEN;
  }
}

/** `?id=<home>&date=<YYYY-MM-DD>`: read after mount (static export), kept in the address bar so a day can be linked. */
function useDayParams() {
  const [params, setParams] = useState<{ id: string | null; date: string | null } | undefined>(undefined);
  const read = useCallback(() => {
    const q = new URLSearchParams(window.location.search);
    const date = q.get('date');
    setParams({ id: q.get('id'), date: isDate(date) ? date : null });
  }, []);
  useEffect(() => {
    read();
    window.addEventListener('popstate', read);
    return () => window.removeEventListener('popstate', read);
  }, [read]);
  const go = useCallback(
    (next: { id?: string | null; date?: string | null }) => {
      const url = new URL(window.location.href);
      for (const [k, v] of Object.entries(next)) {
        if (v) url.searchParams.set(k, v);
        else url.searchParams.delete(k);
      }
      window.history.pushState(null, '', url.toString());
      read();
    },
    [read],
  );
  return { params, go };
}

export function DebugView() {
  const { params, go } = useDayParams();
  const patients = useApi<PatientsResponse>('/v1/patients');
  const known = useMemo(() => patients.data?.patients ?? [], [patients.data]);
  // Without ?id= the page opens the first home the service lists; it never assumes one.
  const home = params === undefined ? null : (params.id ?? known[0]?.id ?? null);
  const date = params?.date ?? null;
  const key = `${home ?? ''}|${date ?? ''}`;

  // Asking Gemma is a choice for the day in view: another day or home is off again.
  const [askKey, setAskKey] = useState<string | null>(null);
  const gemma = askKey === key;
  const [live, setLive] = useState(false);
  const admin = useAdminToken();
  const view = useDebugDay(admin.token === undefined ? null : home, date, gemma, live, admin.token ?? null);
  // A day that could not be loaded never hides behind the previous one.
  const day = view.stale && view.error ? null : view.day;
  const stale = view.stale && day !== null;

  const [open, setOpen] = useState(ALL_OPEN);
  useEffect(() => setOpen(loadOpen()), []);
  const toggle = useCallback((id: SectionId) => {
    setOpen((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      try {
        window.localStorage.setItem(OPEN_KEY, JSON.stringify(next));
      } catch {
        /* storage blocked: the choice lasts for this visit */
      }
      return next;
    });
  }, []);

  const [metricFilter, setMetricFilter] = useState<MetricFilter>(NO_METRIC_FILTER);
  const [eventFilter, setEventFilter] = useState<EventFilter>(NO_EVENT_FILTER);
  const [reveal, setReveal] = useState<{ anchor: string; block: ScrollLogicalPosition; n: number } | null>(null);
  const [hit, setHit] = useState<string | null>(null);

  const jump = useCallback((t: CiteTarget) => {
    setOpen((prev) => (prev[t.section] ? prev : { ...prev, [t.section]: true }));
    // the row a citation names must be on screen, whatever was filtered away
    if (t.section === 'metrics') setMetricFilter(NO_METRIC_FILTER);
    if (t.section === 'events') setEventFilter(NO_EVENT_FILTER);
    setHit(t.anchor);
    setReveal({ anchor: t.anchor, block: 'center', n: Date.now() });
  }, []);
  const openSection = useCallback((id: SectionId) => {
    setOpen((prev) => (prev[id] ? prev : { ...prev, [id]: true }));
    setReveal({ anchor: `dbg-sec-${id}`, block: 'start', n: Date.now() });
  }, []);

  useEffect(() => {
    if (!reveal) return;
    let tries = 0;
    let frame = 0;
    const land = () => {
      const el = document.getElementById(reveal.anchor);
      if (!el) {
        if (tries++ < 30) frame = requestAnimationFrame(land);
        return;
      }
      const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      el.scrollIntoView({ block: reveal.block, behavior: calm ? 'auto' : 'smooth' });
      (el.matches('section') ? el.querySelector<HTMLElement>('.dbg-sec-toggle') : el)?.focus({ preventScroll: true });
    };
    land();
    const fade = setTimeout(() => setHit(null), 2600);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(fade);
    };
  }, [reveal]);

  const nav: Nav = useMemo(() => ({ jump, hit }), [jump, hit]);
  const marks: EventMarks = useMemo(() => ({ fresh: new Set(view.diff.events), arrived: view.arrived }), [view.diff, view.arrived]);

  const current = date ?? (stale ? null : (day?.date ?? null));
  const [homeDraft, setHomeDraft] = useState('');
  useEffect(() => setHomeDraft(home ?? ''), [home]);
  const submitHome = (e: FormEvent) => {
    e.preventDefault();
    const id = homeDraft.trim();
    if (id && id !== home) go({ id });
  };

  if (params === undefined) return <Busy label="Opening the debug page" />;

  return (
    <div className="dbg">
      <div className="dbg-bar">
        <div className="dbg-bar-row">
          <h1 className="dbg-title">Debug day</h1>
          <form className="dbg-home" onSubmit={submitHome}>
            <label htmlFor="dbg-home">Home</label>
            <input
              id="dbg-home"
              className="dbg-input dbg-mono"
              list="dbg-homes"
              value={homeDraft}
              spellCheck={false}
              autoComplete="off"
              placeholder="home id"
              onChange={(e) => {
                setHomeDraft(e.target.value);
                // picking a listed home opens it at once; any other id waits for Enter
                if (e.target.value !== home && known.some((p) => p.id === e.target.value)) go({ id: e.target.value });
              }}
            />
            <datalist id="dbg-homes">
              {known.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </datalist>
          </form>
          <div className="dbg-daypick" role="group" aria-label="Day">
            <button type="button" className="d-btn" aria-label="Previous day" disabled={!current} onClick={() => current && go({ date: shiftDate(current, -1) })}>
              ‹
            </button>
            <input
              type="date"
              className="dbg-input dbg-mono"
              aria-label="Day to look at"
              value={current ?? ''}
              onChange={(e) => isDate(e.target.value) && go({ date: e.target.value })}
            />
            <button type="button" className="d-btn" aria-label="Next day" disabled={!current || Boolean(day?.is_today)} onClick={() => current && go({ date: shiftDate(current, 1) })}>
              ›
            </button>
            <button type="button" className="d-btn" aria-pressed={Boolean(day?.is_today)} onClick={() => go({ date: null })}>
              Today
            </button>
          </div>
          {day?.is_today && !stale && <Tag tone="ok">today</Tag>}
          {day?.sim && !stale && <SimMark />}
          {stale && (
            <span className="dbg-dim" role="status">
              loading {date ?? 'today'}…
            </span>
          )}
          <span className="dbg-grow" />
          <label className="dbg-switch" title={day?.is_today ? `Ask again every ${POLL_MS / 1000} s and mark what arrived. Never asks Gemma.` : 'Only today’s data can still arrive'}>
            <input type="checkbox" role="switch" checked={live && Boolean(day?.is_today)} disabled={!day?.is_today} onChange={(e) => setLive(e.target.checked)} />
            Auto-refresh {POLL_MS / 1000} s
          </label>
          <label className="dbg-switch" title={ASK_HINT}>
            <input type="checkbox" role="switch" checked={gemma} disabled={!home} onChange={(e) => setAskKey(e.target.checked ? key : null)} />
            Ask Gemma <span className="dbg-dim">{ASK_COST}</span>
          </label>
          <button type="button" className="d-btn" disabled={!home || view.loading} onClick={view.refresh}>
            {view.loading ? 'Refreshing' : 'Refresh'}
          </button>
        </div>
        {day && (
          <div className={`dbg-bar-day${stale ? ' is-stale' : ''}`}>
            <Steps day={day} view={view} reading={view.read?.reading} onOpen={openSection} live={live && Boolean(day.is_today)} home={day.home_id} />
          </div>
        )}
      </div>

      {!home && !patients.loading && (
        <div className="dbg-state" role="status">
          <strong>Which home?</strong>
          <span>
            {patients.error
              ? 'The service did not list its homes, so type a home id above and press Enter.'
              : 'This service lists no home yet. Type a home id above and press Enter, or seed a record first.'}
          </span>
        </div>
      )}
      {!home && patients.loading && <Busy label="Looking for a home on this service" />}
      {home && !day && !view.error && <Busy label={`Loading ${date ?? 'today'} for ${home}`} />}
      {home && !day && view.error && (
        <DayProblem error={view.error} home={home} known={known.map((p) => p.id)} hasToken={Boolean(admin.token)} onRetry={view.refresh} onPick={(id) => go({ id })} />
      )}

      {day && view.read && (
        <div className={`dbg-day${stale ? ' is-stale' : ''}`} aria-busy={stale}>
          {view.error && (
            <p className="dbg-note is-bad" role="alert">
              The last refresh failed ({view.error.message}). Showing the answer from {view.refreshedAt ? view.refreshedAt.toLocaleTimeString() : 'earlier'}.
            </p>
          )}
          {day.events_total === 0 && (
            <p className="dbg-note is-warn" role="status">
              No envelope arrived {day.is_today ? 'today' : 'on this day'}. Everything below is what the pipeline gives for a day without data.
            </p>
          )}
          <Section id="result" title="Result" open={open.result} onToggle={() => toggle('result')} meta={<ResultMeta day={day} reading={view.read.reading} />}>
            <ResultBody day={day} read={view.read} readKept={view.readKept} readCurrent={view.readCurrent} asking={view.asking} askError={view.askError} askCost={view.askCost} nav={nav} />
          </Section>
          <Section id="verdicts" title="Signal-group verdicts" open={open.verdicts} onToggle={() => toggle('verdicts')} meta={<VerdictsMeta day={day} />}>
            <VerdictsBody day={day} nav={nav} />
          </Section>
          <Section id="metrics" title="Metrics" open={open.metrics} onToggle={() => toggle('metrics')} meta={<MetricsMeta day={day} />}>
            <MetricsBody day={day} nav={nav} filter={metricFilter} onFilter={setMetricFilter} marks={marks} moved={view.moved} />
          </Section>
          <Section id="events" title="Events" open={open.events} onToggle={() => toggle('events')} meta={<EventsMeta day={day} fresh={marks.fresh.size} arrived={view.arrived.size} />}>
            <EventsBody day={day} nav={nav} filter={eventFilter} onFilter={setEventFilter} marks={marks} now={(view.refreshedAt ?? new Date()).getTime()} />
          </Section>
          <Section id="conversations" title="Companion conversations" open={open.conversations} onToggle={() => toggle('conversations')} meta={<ConversationsMeta day={day} />}>
            <ConversationsBody day={day} />
          </Section>
          <Section id="calls" title="Model calls" open={open.calls} onToggle={() => toggle('calls')} meta={<CallsMeta day={day} />}>
            <ModelCallsBody day={day} />
          </Section>
        </div>
      )}
    </div>
  );
}

/** The day in one line, in page order; each step opens its section. */
function Steps({
  day,
  view,
  reading,
  onOpen,
  live,
  home,
}: {
  day: DebugDay;
  view: ReturnType<typeof useDebugDay>;
  reading: keyof typeof READING_LABEL | undefined;
  onOpen: (id: SectionId) => void;
  live: boolean;
  home: string;
}) {
  const m = metricCounts(day.metrics);
  const worse = day.verdicts.filter((v) => v.verdict === 'worse').length;
  const calls = callSummary(day.model_calls ?? []);
  const conv = conversationSummary(day.conversations ?? []);
  const changed = !diffEmpty(view.diff);
  const line = diffLine(view.diff);
  return (
    <>
      <nav className="dbg-bar-row" aria-label="Steps of the day">
        <ol className="dbg-steps">
          <li>
            <button type="button" onClick={() => onOpen('result')}>
              Result <span className="dbg-mono">{day.consensus.state}</span>
              {reading && <span className="dbg-mono dbg-dim">{reading}</span>}
            </button>
          </li>
          <li>
            <button type="button" onClick={() => onOpen('verdicts')}>
              Verdicts{' '}
              <span className="dbg-mono">
                {worse} worse of {day.verdicts.length}
              </span>
            </button>
          </li>
          <li>
            <button type="button" onClick={() => onOpen('metrics')}>
              Metrics{' '}
              <span className="dbg-mono">
                {m.flagged} flagged of {m.total}
              </span>
            </button>
          </li>
          <li>
            <button type="button" onClick={() => onOpen('events')}>
              Events <span className="dbg-mono">{day.events_total}</span>
              {view.diff.events.length > 0 && <Tag tone="new">{view.diff.events.length} new</Tag>}
            </button>
          </li>
          <li>
            <button type="button" onClick={() => onOpen('conversations')}>
              Conversations <span className="dbg-mono">{conv.count}</span>
            </button>
          </li>
          <li>
            <button type="button" onClick={() => onOpen('calls')}>
              Model calls <span className="dbg-mono">{calls.calls}</span>
              {calls.failed > 0 && <Tag tone="bad">{calls.failed} failed</Tag>}
            </button>
          </li>
        </ol>
      </nav>
      <div className="dbg-bar-row dbg-status">
        <span className="dbg-change" role="status" aria-live="polite" title={changed ? line : undefined}>
          {live && <Tag tone="ok">watching</Tag>}
          {changed ? <span className="dbg-change-line">Last change: {line}</span> : live ? <span className="dbg-dim">nothing new since this page opened the day</span> : null}
        </span>
        <span className="dbg-bounds" title="The home’s timezone, and the local midnights that bound this day, in UTC">
          <span className="dbg-mono">{day.timezone}</span>
          <span className="dbg-mono dbg-dim">
            {day.day_start.slice(0, 16).replace('T', ' ')}Z → {day.day_end.slice(0, 16).replace('T', ' ')}Z
          </span>
        </span>
        <span className="dbg-dim dbg-nowrap">
          computed <span className="dbg-mono">{localClock(day.computed_at, day.timezone)}</span>
        </span>
        <a className="dbg-raw" href={`${API_BASE}${debugPath(home, day.date, false)}`} target="_blank" rel="noreferrer" title="The same answer as served, without asking Gemma">
          Raw JSON
        </a>
      </div>
    </>
  );
}

function ResultMeta({ day, reading }: { day: DebugDay; reading: keyof typeof READING_LABEL }) {
  return (
    <>
      <span className="dbg-mono">{day.consensus.state}</span>
      {day.consensus.held && <Tag tone="warn">held</Tag>}
      <span className="dbg-dim">read:</span> <span className="dbg-mono">{reading}</span>
    </>
  );
}

function VerdictsMeta({ day }: { day: DebugDay }) {
  return (
    <>
      {day.verdicts.map((v) => (
        <span key={v.source} className="dbg-mono">
          {v.source}={v.verdict}
        </span>
      ))}
    </>
  );
}

function MetricsMeta({ day }: { day: DebugDay }) {
  const m = metricCounts(day.metrics);
  return (
    <span className="dbg-mono">
      {m.total} metrics · {m.flagged} flagged · {m.beyond} beyond threshold this day · {m.withData} with a value · {m.observeOnly} observe-only
    </span>
  );
}

function EventsMeta({ day, fresh, arrived }: { day: DebugDay; fresh: number; arrived: number }) {
  return (
    <>
      <span className="dbg-mono">{day.events_total} this day</span>
      {arrived > 0 && <span className="dbg-mono">{arrived} arrived while watching</span>}
      {fresh > 0 && <Tag tone="new">{fresh} new</Tag>}
    </>
  );
}

function ConversationsMeta({ day }: { day: DebugDay }) {
  const c = conversationSummary(day.conversations ?? []);
  return (
    <span className="dbg-mono">
      {c.count} started · {c.minutes.toFixed(1)} min · {c.billed.toFixed(1)} billed · {c.feels} feel calls{c.open ? ` · ${c.open} never closed` : ''}
    </span>
  );
}

function CallsMeta({ day }: { day: DebugDay }) {
  const c = callSummary(day.model_calls ?? []);
  return (
    <>
      <span className="dbg-mono">
        {c.calls} calls · {c.fallback} fallback · est. {c.costed ? usd(c.est_usd) : '—'}
      </span>
      {c.failed > 0 && <Tag tone="bad">{c.failed} failed</Tag>}
    </>
  );
}

/** Why the day could not be loaded, in a developer's terms. */
function DayProblem({
  error,
  home,
  known,
  hasToken,
  onRetry,
  onPick,
}: {
  error: ApiError;
  home: string;
  known: string[];
  hasToken: boolean;
  onRetry: () => void;
  onPick: (id: string) => void;
}) {
  const kind = problemKind(error.status, error.detail);
  const where = apiOrigin();
  return (
    <div className="dbg-state" role="alert">
      {kind === 'closed' && (
        <>
          <strong>This is a local, team-only page</strong>
          <span>
            The service at <span className="dbg-mono">{where}</span> keeps the debug route closed, the way it keeps its admin routes closed: it answers the admin role only.
            Open this page from a cloud running on your own machine in demo mode.
          </span>
          <span>
            {hasToken
              ? 'The admin token stored in this browser was sent and refused.'
              : 'No admin token is stored in this browser. If you hold this service’s token, store it once on the Tuning page; this page then sends it too.'}
          </span>
          <span className="dbg-mono">{detailLines(error.detail).join('; ')}</span>
        </>
      )}
      {kind === 'no_route' && (
        <>
          <strong>This service has no debug route</strong>
          <span>
            The cloud at <span className="dbg-mono">{where}</span> is running code from before the route was added. This is a local, team-only page: restart that
            cloud from the current working tree, in demo mode, and try again.
          </span>
        </>
      )}
      {kind === 'unknown_home' && (
        <>
          <strong>
            No home called <span className="dbg-mono">{home}</span> on this service
          </strong>
          <span>{detailLines(error.detail).join('; ')}</span>
          {known.length > 0 && (
            <span className="dbg-inline">
              Homes it lists:
              {known.map((id) => (
                <button key={id} type="button" className="dbg-cite" onClick={() => onPick(id)}>
                  {id}
                </button>
              ))}
            </span>
          )}
        </>
      )}
      {kind === 'bad_request' && (
        <>
          <strong>The service refused this request</strong>
          <span>{detailLines(error.detail).join('; ')}</span>
        </>
      )}
      {kind === 'unreachable' && (
        <>
          <strong>The Kaiku service is not answering</strong>
          <span>
            Nothing came back from <span className="dbg-mono">{where}</span>. {error.message}
          </span>
        </>
      )}
      {kind === 'server' && (
        <>
          <strong>The service failed on this day</strong>
          <span className="dbg-mono">{error.message}</span>
        </>
      )}
      <button type="button" className="d-btn" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}
