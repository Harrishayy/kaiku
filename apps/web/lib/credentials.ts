/** Select only the credential scoped to this endpoint. Never use clinician access for a person's notebook. */
export interface Credentials { home: string | null; person: string | null; clinician: string | null; admin: string | null }
export function credentialFor(path: string, c: Credentials): string | null {
  const u = new URL(path, 'https://kaiku.invalid');
  if (u.pathname.startsWith('/v1/admin/') || u.pathname === '/v1/eval') return c.admin;
  if (u.pathname.startsWith('/v1/patients') || u.pathname.startsWith('/v1/health')) return c.clinician || c.admin;
  const home = u.searchParams.get('home_id');
  if (home && home === c.home) return c.person;
  return null;
}
export function storedCredential(path: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return credentialFor(path, { home: localStorage.getItem('kaiku.home'), person: localStorage.getItem('kaiku.token'),
      clinician: sessionStorage.getItem('kaiku.clinician'), admin: localStorage.getItem('kaiku.admin') });
  } catch { return null; }
}
export function credentialsChanged() { window.dispatchEvent(new Event('kaiku:credentials')); }
