'use client';

/**
 * Thin fetch wrapper for the Kaiku cloud API (handoff §6.7). Types come only from @contracts.
 * Same-origin by default (the cloud serves this static app). For local dev point it elsewhere:
 *   NEXT_PUBLIC_KAIKU_API=http://localhost:8000 pnpm dev
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export const API_BASE = (process.env.NEXT_PUBLIC_KAIKU_API ?? '').replace(/\/$/, '');
export const DEFAULT_HOME_ID = process.env.NEXT_PUBLIC_KAIKU_HOME_ID || 'demo-aino';

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number | null,
    /** raw `detail` from the response body (FastAPI 422 = list of {loc, msg, type}) */
    public detail: unknown = null,
  ) {
    super(message);
  }
}

/** Human lines from a FastAPI error detail: "sources.robot.min_confidence: Input should be ≤ 1". */
export function detailLines(detail: unknown): string[] {
  if (detail == null) return [];
  if (typeof detail === 'string') return [detail];
  if (Array.isArray(detail))
    return detail.map((d) => {
      if (d && typeof d === 'object' && 'msg' in d) {
        const loc = Array.isArray((d as { loc?: unknown[] }).loc)
          ? ((d as { loc: unknown[] }).loc.filter((x) => x !== 'body' && x !== 'criteria').join('.'))
          : '';
        return loc ? `${loc}: ${String((d as { msg: unknown }).msg)}` : String((d as { msg: unknown }).msg);
      }
      return typeof d === 'string' ? d : JSON.stringify(d);
    });
  return [JSON.stringify(detail)];
}

export async function api<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number; token?: string | null } = {},
): Promise<T> {
  const { timeoutMs = 10_000, token, headers, ...rest } = init;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...rest,
      signal: ctrl.signal,
      headers: {
        Accept: 'application/json',
        ...(rest.body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
    });
    if (!res.ok) {
      let detail: unknown = res.statusText;
      try {
        const body = await res.json();
        detail = body?.detail ?? body;
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(`${res.status} ${detailLines(detail).join('; ')}`, res.status, detail);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError('The cloud did not answer in time.', null);
    }
    throw new ApiError('Cannot reach the Kaiku cloud.', null);
  } finally {
    clearTimeout(timer);
  }
}

export interface Resource<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** Fetch `path` on mount (and every `pollMs` if given). Keeps the last good data on error. */
export function useApi<T>(path: string | null, pollMs?: number): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(path !== null);
  const [tick, setTick] = useState(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (path === null) return;
    let cancelled = false;
    const run = async () => {
      try {
        const d = await api<T>(path);
        if (!cancelled && alive.current) {
          setData(d);
          setError(null);
        }
      } catch (e) {
        if (!cancelled && alive.current) setError(e as ApiError);
      } finally {
        if (!cancelled && alive.current) setLoading(false);
      }
    };
    run();
    const id = pollMs ? setInterval(run, pollMs) : undefined;
    return () => {
      cancelled = true;
      if (id) clearInterval(id);
    };
  }, [path, pollMs, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** POST envelopes to /v1/events with the pairing token (if any). Returns the cloud's EventsResult. */
export async function postEvents<R = { accepted: number; duplicates: number; rejected: unknown[] }>(
  events: unknown[],
  token: string | null | undefined,
): Promise<R> {
  return api<R>('/v1/events', { method: 'POST', body: JSON.stringify({ events }), token, timeoutMs: 15_000 });
}
