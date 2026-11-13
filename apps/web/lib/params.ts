'use client';

import { useEffect, useState } from 'react';
import { DEFAULT_HOME_ID } from './api';
import { parsePairing, type Pairing } from './pairing.ts';

/**
 * Read a query parameter on the client. Static export has no server, so we read
 * window.location after mount (returns `undefined` until then — render a loading state).
 */
export function useQueryParam(name: string): string | null | undefined {
  const [value, setValue] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    const read = () => setValue(new URLSearchParams(window.location.search).get(name));
    read();
    window.addEventListener('popstate', read);
    return () => window.removeEventListener('popstate', read);
  }, [name]);
  return value;
}

/** ?home=<id> overrides NEXT_PUBLIC_KAIKU_HOME_ID (default demo-aino). For clinician/demo pages. */
export function useHomeId(): string | undefined {
  const q = useQueryParam('home');
  if (q === undefined) return undefined;
  return q && /^[a-z0-9][a-z0-9_-]*$/.test(q) ? q : DEFAULT_HOME_ID;
}

const KEY_HOME = 'kaiku.home';
const KEY_TOKEN = 'kaiku.token';

function store(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage blocked (private mode) — pairing then lasts for this page only */
  }
}

function load(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/**
 * Pairing for the person-facing apps (/session, /phq9, /me): the care team hands out a link
 * `…/session/?home=<home_id>&t=<pairing token>`. We remember both in localStorage, then strip `t`
 * from the address bar so it doesn't end up in screenshots or shared links. The token is sent as
 * `Authorization: Bearer <t>` on POST /v1/events. No Gemini or admin key ever reaches the browser.
 */
export function usePairing(): (Pairing & { forget: () => void }) | undefined {
  const [pairing, setPairing] = useState<Pairing | undefined>(undefined);
  useEffect(() => {
    const p = parsePairing(window.location.search, { home: load(KEY_HOME), token: load(KEY_TOKEN) }, DEFAULT_HOME_ID);
    if (p.fromUrl.home) store(KEY_HOME, p.homeId);
    if (p.fromUrl.token) {
      store(KEY_TOKEN, p.token);
      const url = new URL(window.location.href);
      url.searchParams.delete('t');
      window.history.replaceState(null, '', url.toString());
    }
    setPairing(p);
  }, []);
  if (!pairing) return undefined;
  return {
    ...pairing,
    forget: () => {
      store(KEY_HOME, null);
      store(KEY_TOKEN, null);
      setPairing({ homeId: DEFAULT_HOME_ID, token: null, paired: false, fromUrl: { home: false, token: false } });
    },
  };
}

const KEY_ADMIN = 'kaiku.admin';

/**
 * Admin token for /tune/ (`?admin=<KAIKU_ADMIN_TOKEN>` once, or pasted on the page). Stored in localStorage,
 * stripped from the URL, sent as Bearer only to /v1/admin/*. `undefined` until mounted; `null` = none.
 */
export function useAdminToken(): { token: string | null | undefined; set: (t: string | null) => void } {
  const [token, setToken] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    const url = new URL(window.location.href);
    const fromUrl = url.searchParams.get('admin');
    if (fromUrl) {
      store(KEY_ADMIN, fromUrl);
      url.searchParams.delete('admin');
      window.history.replaceState(null, '', url.toString());
    }
    setToken(fromUrl || load(KEY_ADMIN));
  }, []);
  return {
    token,
    set: (t) => {
      store(KEY_ADMIN, t && t.trim() ? t.trim() : null);
      setToken(t && t.trim() ? t.trim() : null);
    },
  };
}
