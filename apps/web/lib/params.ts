'use client';

import { useEffect, useState } from 'react';
import { credentialsChanged } from './credentials';

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

function store(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage blocked (private mode): the value then lasts for this page only */
  }
}

function load(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

const KEY_ADMIN = 'kaiku.admin';

/**
 * Admin token for /tune/ (`?admin=<KAIKU_ADMIN_TOKEN>` once, or pasted on the page). Stored in localStorage,
 * stripped from the URL, sent as Bearer only to this service (admin and debug routes; record routes when no care-team token is set). `undefined` until mounted; `null` = none.
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
      credentialsChanged();
    },
  };
}
