'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { DebugDay, DebugRead } from '@contracts';
import { type ApiError, api } from '@/lib/api';
import { NO_DIFF, askCost, debugPath, diffDay, diffEmpty, localClock, pickRead, type AskCost, type DayDiff, type MetricMove } from '@/lib/debug';

export const POLL_MS = 10_000;
const QUICK_MS = 20_000;
/** A cold Gemma container can take minutes to answer. */
const ASK_MS = 240_000;

export interface DayView {
  /** the day on screen; while `stale` it is still the previous home or day, kept so the page does not jump */
  day: DebugDay | null;
  stale: boolean;
  /** the read on screen: Gemma's when one was asked for, otherwise the day's own */
  read: DebugRead | null;
  /** the read on screen is an earlier Gemma read kept across refreshes that did not ask */
  readKept: boolean;
  /** the kept read still matches the day's data (same digest) */
  readCurrent: boolean;
  error: ApiError | null;
  loading: boolean;
  asking: boolean;
  askError: ApiError | null;
  /** what the last ask on this day cost, from the home's ledger of today; null until one is found */
  askCost: AskCost | null;
  /** when the page last got an answer, on the developer's clock */
  refreshedAt: Date | null;
  /** what the latest refresh that brought anything brought */
  diff: DayDiff;
  /** envelope id → home-local time it was first seen, for everything that arrived while watching */
  arrived: Map<string, string>;
  /** metric id → its latest move while watching */
  moved: Map<string, MetricMove>;
  refresh: () => void;
}

interface Inner {
  day: DebugDay | null;
  stale: boolean;
  read: DebugRead | null;
  readKept: boolean;
  readCurrent: boolean;
  error: ApiError | null;
  refreshedAt: Date | null;
  diff: DayDiff;
  arrived: Map<string, string>;
  moved: Map<string, MetricMove>;
}

const EMPTY: Inner = { day: null, stale: false, read: null, readKept: false, readCurrent: true, error: null, refreshedAt: null, diff: NO_DIFF, arrived: new Map(), moved: new Map() };

/**
 * One day of one home. Every load asks without Gemma (fast, free); the generated read is asked for only while
 * `gemma` is on, once when it goes on and once per manual refresh, and then replaces the read in place.
 * Polling (`live`, today only) never asks Gemma, so leaving the page open costs nothing. The route belongs to
 * the admin role: `token` is the admin token this browser already holds for /tune/, or null on an open local cloud.
 */
export function useDebugDay(home: string | null, date: string | null, gemma: boolean, live: boolean, token: string | null): DayView {
  const [s, setS] = useState<Inner>(EMPTY);
  const [pending, setPending] = useState(0);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<ApiError | null>(null);
  const [cost, setCost] = useState<AskCost | null>(null);
  const [tick, setTick] = useState(0);
  const key = `${home ?? ''}|${date ?? ''}|${token ? 'admin' : ''}`;
  const keyRef = useRef(key);
  const inFlight = useRef<string | null>(null);
  const started = useRef<string | null>(null);
  const asked = useRef<string | null>(null);

  const accept = useCallback((k: string, next: DebugDay) => {
    if (keyRef.current !== k) return;
    setS((prev) => {
      const before = prev.stale ? null : prev.day;
      const diff = diffDay(before, next);
      const at = localClock(new Date().toISOString(), next.timezone);
      const arrived = diff.events.length ? new Map(prev.arrived) : prev.arrived;
      for (const id of diff.events) arrived.set(id, at);
      const moved = diff.metrics.length ? new Map(prev.moved) : prev.moved;
      for (const m of diff.metrics) moved.set(m.id, m);
      const picked = pickRead(before ? prev.read : null, next.read);
      return {
        day: next,
        stale: false,
        read: picked.read,
        readKept: picked.kept,
        readCurrent: picked.current,
        error: null,
        refreshedAt: new Date(),
        // a quiet refresh keeps the last marks on screen: reading them takes longer than one interval
        diff: before && diffEmpty(diff) ? prev.diff : diff,
        arrived,
        moved,
      };
    });
  }, []);

  const quick = useCallback(
    async (k: string) => {
      if (!home) return;
      inFlight.current = k;
      setPending((n) => n + 1);
      try {
        accept(k, await api<DebugDay>(debugPath(home, date, false), { timeoutMs: QUICK_MS, token }));
      } catch (e) {
        if (keyRef.current === k) setS((prev) => ({ ...prev, error: e as ApiError }));
      } finally {
        if (inFlight.current === k) inFlight.current = null;
        setPending((n) => n - 1);
      }
    },
    [home, date, token, accept],
  );

  // Another home or day starts clean (nothing from the previous one is "new" here), then loads. `started`
  // keeps React's development double-run of this effect from sending the request twice.
  useEffect(() => {
    if (keyRef.current !== key) {
      keyRef.current = key;
      // the previous day stays on screen, marked stale, until this one answers: nothing of it counts as "before"
      setS((prev) => ({ ...EMPTY, day: prev.day, read: prev.read, stale: prev.day !== null }));
      setCost(null);
      setAskError(null);
      setAsking(false);
    }
    const want = `${key}#${tick}`;
    if (!home || started.current === want) return;
    started.current = want;
    void quick(key);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);

  // The generated read costs money: exactly one request per switch-on and per manual refresh while it is on.
  useEffect(() => {
    if (!home || !gemma) {
      asked.current = null;
      return;
    }
    const want = `${key}#${tick}`;
    if (asked.current === want) return;
    asked.current = want;
    const k = key;
    setAsking(true);
    setAskError(null);
    const began = Date.now();
    api<DebugDay>(debugPath(home, date, true), { timeoutMs: ASK_MS, token })
      .then(async (d) => {
        accept(k, d);
        if (d.read.cached || d.read.fallback_reason === 'not_requested' || d.read.fallback_reason === 'cooldown') return;
        // The calls are logged under the home's today, and after this answer was put together: look them up once (free).
        const today = await api<DebugDay>(debugPath(home, null, false), { timeoutMs: QUICK_MS, token }).catch(() => null);
        if (today && keyRef.current === k) setCost(askCost(today.model_calls ?? [], d.read, began - 2000));
      })
      .catch((e) => {
        if (keyRef.current === k) setAskError(e as ApiError);
      })
      .finally(() => {
        if (keyRef.current === k) setAsking(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, gemma, tick]);

  const isToday = Boolean(s.day?.is_today);
  useEffect(() => {
    if (!live || !isToday) return;
    const k = key;
    const id = setInterval(() => {
      if (!document.hidden && inFlight.current !== k) void quick(k);
    }, POLL_MS);
    return () => clearInterval(id);
  }, [live, isToday, key, quick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return { ...s, loading: pending > 0, asking, askError, askCost: cost, refresh };
}
