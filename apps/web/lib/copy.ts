/**
 * Pure copy lookup (unit-tested). Tables come from design/copy.json (ground truth) merged with
 * lib/copy-web.json (web-only keys design/copy.json doesn't have yet; design wins on a shared key).
 * A missing key falls back to English, then to an empty string — a key name never reaches the screen.
 */

export type Lang = 'en' | 'fi';
export const LANGS: Lang[] = ['en', 'fi'];
export type Table = Record<string, string>;
export type Tables = Record<Lang, Table>;
export type Vars = Record<string, string | number>;

export function mergeTables(design: Partial<Record<string, unknown>>, web: Partial<Record<string, unknown>>): Tables {
  const pick = (src: Partial<Record<string, unknown>>, l: Lang) => (src[l] ?? {}) as Table;
  return {
    en: { ...pick(web, 'en'), ...pick(design, 'en') },
    fi: { ...pick(web, 'fi'), ...pick(design, 'fi') },
  };
}

export function fill(s: string, vars?: Vars): string {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}

export function translate(tables: Tables, lang: Lang, key: string, vars?: Vars): string {
  const s = tables[lang]?.[key] ?? tables.en[key] ?? '';
  return fill(s, vars);
}

export function parseLang(v: string | null | undefined): Lang | null {
  if (!v) return null;
  const l = v.toLowerCase().slice(0, 2);
  return l === 'fi' ? 'fi' : l === 'en' ? 'en' : null;
}

/** Time-of-day greeting key (same split as the look book and the Apple apps). */
export function greetKey(hour: number): string {
  if (hour < 5) return 'today.greet.late';
  if (hour < 12) return 'today.greet.morning';
  if (hour < 18) return 'today.greet.afternoon';
  if (hour < 23) return 'today.greet.evening';
  return 'today.greet.late';
}

/** First name from a home id ("demo-aino" → "Aino"); same rule the cloud uses for display names. */
export function nameFromHome(homeId: string): string {
  const last = homeId.split('-').pop() ?? homeId;
  return last.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
