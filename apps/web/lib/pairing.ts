/** Pure pairing logic (unit-tested). See usePairing() in params.ts for the browser side. */

export interface Pairing {
  homeId: string;
  token: string | null;
  paired: boolean;
  fromUrl: { home: boolean; token: boolean };
}

const HOME_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const TOKEN_RE = /^[A-Za-z0-9._~-]{8,256}$/;

/** URL params win over stored values; invalid values are ignored. */
export function parsePairing(
  search: string,
  stored: { home: string | null; token: string | null },
  defaultHome: string,
): Pairing {
  const q = new URLSearchParams(search);
  const urlHome = q.get('home');
  const urlToken = q.get('t');
  const home = urlHome && HOME_RE.test(urlHome) ? urlHome : null;
  const token = urlToken && TOKEN_RE.test(urlToken) ? urlToken : null;
  const storedHome = stored.home && HOME_RE.test(stored.home) ? stored.home : null;
  const storedToken = stored.token && TOKEN_RE.test(stored.token) ? stored.token : null;
  const finalToken = token ?? storedToken;
  return {
    homeId: home ?? storedHome ?? defaultHome,
    token: finalToken,
    paired: Boolean(finalToken),
    fromUrl: { home: Boolean(home), token: Boolean(token) },
  };
}
