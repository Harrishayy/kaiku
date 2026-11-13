/**
 * "What Kaiku saw today" (pure, unit-tested): today's uplinked observations → receipt lines as copy keys.
 * Only counts and minutes — never values about the person's state. Unknown types are left out.
 */

export interface SawLine {
  key: string;
  vars?: Record<string, number>;
}

interface Ev {
  type: string;
  payload?: Record<string, unknown> | null;
}

const ONCE: Record<string, string> = {
  'obs.drum_session': 'saw.l.drum',
  'obs.hrv_session': 'saw.l.breathe',
  'obs.light_level': 'saw.l.light',
  'obs.presence': 'saw.l.presence',
  'obs.laptop_session': 'saw.l.session',
  'obs.screen_activity': 'saw.mac',
  'obs.wearable_daily': 'saw.watch',
  'obs.speech_features': 'saw.voice',
};
const ORDER = [
  'saw.l.ritual', 'saw.l.presence', 'saw.l.dial', 'saw.l.drum', 'saw.l.breathe', 'saw.l.light', 'saw.voice',
  'saw.l.walk', 'saw.l.play', 'saw.l.session', 'saw.mac', 'saw.watch', 'saw.l.friend',
];

export function sawToday(events: Ev[]): SawLine[] {
  const seen = new Set<string>();
  let dials = 0;
  let walkMin = 0;
  let walks = 0;
  let games = 0;
  for (const e of events) {
    const p = e.payload ?? {};
    if (e.type === 'obs.ritual' && p.step === 'close' && p.status === 'completed') seen.add('saw.l.ritual');
    else if (e.type === 'obs.self_report') dials += 1;
    else if (e.type === 'obs.outing') {
      walks += 1;
      walkMin += typeof p.minutes === 'number' ? p.minutes : 0;
    } else if (e.type === 'obs.play_session') games += 1;
    else if (e.type === 'obs.friend_link' && p.direction === 'sent') seen.add('saw.l.friend');
    else if (ONCE[e.type]) seen.add(ONCE[e.type]);
  }
  const out: SawLine[] = [...seen].map((key) => ({ key }));
  if (dials) out.push({ key: 'saw.l.dial', vars: { n: dials } });
  if (walks) out.push({ key: 'saw.l.walk', vars: { n: Math.round(walkMin) } });
  if (games) out.push({ key: 'saw.l.play', vars: { n: games } });
  return out.sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));
}

/** Local midnight as a UTC ISO string (the `since` for today's events). */
export function localMidnightIso(now: Date = new Date()): string {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

/** Distinct days with a good moment in the highlights (for "did something together on n of 7 days"). */
export function togetherDays(highlights: { date: string; kind: string }[]): number {
  return new Set(highlights.filter((h) => h.kind === 'good').map((h) => h.date)).size;
}
