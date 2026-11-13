'use client';

import { useEffect, useRef, useState } from 'react';
import type { Envelope, LiveEventsResponse } from '@contracts';
import { api, ApiError } from '@/lib/api';
import { clockTime, describe } from '@/lib/format';
import { useHomeId } from '@/lib/params';
import { Empty, ErrorBox, Loading, PageHead, SimBadge, StaleNote } from '@/components/ui';

type Ev = Envelope<Record<string, unknown>>;
const POLL_MS = 2000;
const KEEP = 150;

export function LiveFeed() {
  const homeId = useHomeId();
  const [events, setEvents] = useState<Ev[]>([]);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [error, setError] = useState<ApiError | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [paused, setPaused] = useState(false);
  const since = useRef<string | null>(null);

  useEffect(() => {
    if (!homeId || paused) return;
    let cancelled = false;
    const poll = async () => {
      const q = new URLSearchParams({ home_id: homeId, limit: '50' });
      if (since.current) q.set('since', since.current);
      try {
        const r = await api<LiveEventsResponse>(`/v1/events?${q}`, { timeoutMs: 8000 });
        if (cancelled) return;
        setError(null);
        setLoaded(true);
        const all = r.events as unknown as Ev[];
        const incoming = all.filter((e) => e.type.startsWith('obs.'));
        if (all.length) {
          const newest = all.reduce((m, e) => (e.ts > m ? e.ts : m), since.current ?? '');
          since.current = newest || since.current;
        }
        if (incoming.length) {
          setFresh(new Set(incoming.map((e) => e.id)));
          setEvents((prev) => {
            const seen = new Set(prev.map((e) => e.id));
            const add = incoming.filter((e) => !seen.has(e.id));
            return [...add, ...prev].sort((a, b) => (a.ts < b.ts ? 1 : -1)).slice(0, KEEP);
          });
        }
      } catch (e) {
        if (!cancelled) {
          setError(e as ApiError);
          setLoaded(true);
        }
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [homeId, paused]);

  if (!homeId) return <Loading />;
  const connected = loaded && !error && !paused;

  return (
    <>
      <PageHead
        title="What Kaiku just sensed"
        lede={
          <>
            Home <code>{homeId}</code>. Derived observations only — raw audio, camera frames and sensor streams never leave the
            home.
          </>
        }
      >
        <span className="small">
          <span className={connected ? 'pulse-dot' : 'pulse-dot off'} aria-hidden="true" />
          {paused ? 'Paused' : connected ? 'Live' : error ? 'Reconnecting' : 'Connecting'}
        </span>
        <button type="button" className="btn btn-ghost" onClick={() => setPaused((p) => !p)}>
          {paused ? 'Resume' : 'Pause'}
        </button>
      </PageHead>

      {!loaded && <Loading label="Connecting to the live stream…" />}
      {error && events.length === 0 && <ErrorBox error={error} what="live events" />}
      <StaleNote show={Boolean(error && events.length > 0)} />
      {loaded && !error && events.length === 0 && (
        <Empty>Nothing yet. Start the sims and the hub (`make sim` + `make hub`) or wave at the robot.</Empty>
      )}

      {events.length > 0 && (
        <section className="card" aria-label="Event stream">
          <ol className="feed" aria-live="polite" aria-relevant="additions">
            {events.map((e) => {
              const d = describe(e);
              return (
                <li key={e.id} className={fresh.has(e.id) ? 'feed-new' : undefined}>
                  <time dateTime={e.ts}>{clockTime(e.ts)}</time>
                  <div>
                    <div className={e.type === 'obs.safety_flag' ? 'title flag' : 'title'}>
                      {d.title} <SimBadge show={Boolean(e.sim)} />
                    </div>
                    {d.detail && <div className="muted small">{d.detail}</div>}
                    <div className="muted small">
                      <code>{e.type}</code> · from {e.source}
                      {typeof e.quality === 'number' ? ` · quality ${Math.round(e.quality * 100)}%` : ''}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </>
  );
}
