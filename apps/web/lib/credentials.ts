/** Select only the credential scoped to this endpoint. The website holds no person credential: a person's own
 *  routes (`/v1/me`, the companion) get none, so care-team access is never lent to a person's notebook. */
export interface Credentials { clinician: string | null; admin: string | null }
export function credentialFor(path: string, c: Credentials): string | null {
  const u = new URL(path, 'https://kaiku.invalid');
  if (u.pathname.startsWith('/v1/admin/')) return c.admin;
  // The dashboard only reads /v1/events (a day's records with their sender); the cloud lets the care team read it.
  if (u.pathname.startsWith('/v1/patients') || u.pathname.startsWith('/v1/health') || u.pathname === '/v1/eval'
    || u.pathname === '/v1/events') return c.clinician || c.admin;
  return null;
}
export function storedCredential(path: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return credentialFor(path, { clinician: sessionStorage.getItem('kaiku.clinician'), admin: localStorage.getItem('kaiku.admin') });
  } catch { return null; }
}
export function credentialsChanged() { window.dispatchEvent(new Event('kaiku:credentials')); }
