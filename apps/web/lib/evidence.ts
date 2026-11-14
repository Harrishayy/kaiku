/**
 * Evidence by day (pure, unit-tested): one plain sentence per observation, grouped the way a practitioner asks
 * about a day. Wording is neutral and never diagnostic; nothing here reads audio, images or transcripts.
 */

import { durationMinutes, clockMinutes } from './clinician.ts';
import type { ObsEvent } from './insight.ts';

export type EvidenceGroup = 'checkin' | 'outing' | 'tasks' | 'body' | 'screen' | 'support' | 'safety' | 'other';

export const GROUP_LABEL: Record<EvidenceGroup, string> = {
  safety: 'Safety',
  checkin: 'Check-in ritual',
  outing: 'Walks and outings',
  tasks: 'Tasks and games',
  body: 'Sleep and body (watch)',
  screen: 'Screen rhythm',
  support: 'Suggestions and responses',
  other: 'Other records',
};
export const GROUP_ORDER: EvidenceGroup[] = ['safety', 'checkin', 'outing', 'tasks', 'body', 'screen', 'support', 'other'];

const n = (p: Record<string, unknown>, k: string): number | null => (typeof p[k] === 'number' && Number.isFinite(p[k]) ? (p[k] as number) : null);
const words = (s: unknown) => String(s ?? '').replace(/[._]/g, ' ').trim();
const cap = (s: string) => s.replace(/^\w/, (c) => c.toUpperCase());
const join = (parts: (string | null | false | undefined)[]) => parts.filter(Boolean).join(' · ');

const GAME: Record<string, string> = {
  firefly: 'Firefly (attention and reaction)',
  pebbles: 'Pebbles (working memory)',
  story: 'Story (spoken task)',
  breath: 'Breathing game',
};
const ACTIVITY: Record<string, string> = {
  breathe: 'paced breathing',
  drum: 'drumming',
  walk: 'a walk',
  daylight_walk: 'a daylight walk',
  friend_ping: 'a friend ping',
  icbt: 'an iCBT exercise',
  icbt_exercise: 'an iCBT exercise',
};
const activity = (a: unknown) => ACTIVITY[String(a)] ?? words(a);

export interface EvidenceLine {
  group: EvidenceGroup;
  title: string;
  detail: string;
}

export function describeObs(e: Pick<ObsEvent, 'type' | 'payload'>): EvidenceLine {
  const p = e.payload ?? {};
  switch (e.type) {
    case 'obs.safety_flag':
      return { group: 'safety', title: 'Safety flag raised', detail: join([`Trigger: ${words(p.trigger)}`, p.handled_locally ? 'crisis script shown on the device' : 'not handled on the device']) };
    case 'obs.self_report':
      return { group: 'checkin', title: `${cap(words(p.item ?? 'rating'))} rated ${n(p, 'value') ?? '?'} of 5`, detail: p.context === 'ritual' ? 'During the morning ritual' : 'Outside the ritual' };
    case 'obs.ritual':
      return { group: 'checkin', title: `Morning ritual: ${words(p.step)} ${words(p.status)}`, detail: n(p, 'duration_s') !== null ? `Took ${durationMinutes((n(p, 'duration_s') as number) / 60)}` : '' };
    case 'obs.presence':
      return { group: 'checkin', title: p.first_of_day ? 'First interaction of the day' : 'Near the robot', detail: join([n(p, 'dwell_s') !== null && `stayed ${Math.round(n(p, 'dwell_s') as number)} sec`]) };
    case 'obs.drum_session':
      return { group: 'checkin', title: 'Drum session', detail: join([n(p, 'taps') !== null && `${n(p, 'taps')} taps`, n(p, 'tempo_bpm') !== null && `${Math.round(n(p, 'tempo_bpm') as number)} beats a minute`, n(p, 'regularity') !== null && `regularity ${Math.round((n(p, 'regularity') as number) * 100)}%`]) };
    case 'obs.hrv_session':
      return { group: 'checkin', title: 'Breathing together', detail: join([n(p, 'hr_bpm') !== null && `heart rate ${Math.round(n(p, 'hr_bpm') as number)} bpm`, n(p, 'rmssd_pre_ms') !== null && n(p, 'rmssd_post_ms') !== null && `heart rate variability ${Math.round(n(p, 'rmssd_pre_ms') as number)} to ${Math.round(n(p, 'rmssd_post_ms') as number)} ms`]) };
    case 'obs.speech_features':
      return { group: 'checkin', title: 'Speech rhythm measured (no audio kept)', detail: n(p, 'pause_ratio') !== null ? `Pauses ${Math.round((n(p, 'pause_ratio') as number) * 100)}% of speaking time` : '' };
    case 'obs.light_level':
      return { group: 'checkin', title: 'Room light', detail: n(p, 'lux_est') !== null ? `About ${Math.round(n(p, 'lux_est') as number)} lux` : '' };
    case 'obs.outing':
      return {
        group: 'outing',
        title: `Outing of ${n(p, 'minutes') !== null ? durationMinutes(n(p, 'minutes') as number) : 'unknown length'}`,
        detail: join([n(p, 'steps') !== null && `${(n(p, 'steps') as number).toLocaleString('en-GB')} steps`, n(p, 'daylight_min') !== null && `${Math.round(n(p, 'daylight_min') as number)} min of daylight`, p.method ? `measured by ${words(p.method)}` : null]),
      };
    case 'obs.play_session':
      return {
        group: 'tasks',
        title: GAME[String(p.game)] ?? cap(words(p.game)),
        detail: join([
          n(p, 'reaction_ms_median') !== null && `reaction ${Math.round(n(p, 'reaction_ms_median') as number)} ms`,
          n(p, 'lapses') !== null && `${n(p, 'lapses')} ${n(p, 'lapses') === 1 ? 'lapse' : 'lapses'}`,
          n(p, 'span_max') !== null && `longest sequence ${n(p, 'span_max')}`,
          n(p, 'accuracy') !== null && `${Math.round((n(p, 'accuracy') as number) * 100)}% correct`,
          n(p, 'pause_ratio') !== null && `pauses ${Math.round((n(p, 'pause_ratio') as number) * 100)}%`,
          n(p, 'duration_s') !== null && `${Math.round(n(p, 'duration_s') as number)} sec`,
        ]),
      };
    case 'obs.laptop_session':
      return { group: 'tasks', title: 'Laptop session', detail: join([n(p, 'reaction_ms_median') !== null && `reaction ${Math.round(n(p, 'reaction_ms_median') as number)} ms`, n(p, 'pause_ratio') !== null && `pauses ${Math.round((n(p, 'pause_ratio') as number) * 100)}%`]) };
    case 'obs.phq9':
      return { group: 'tasks', title: `PHQ-9 questionnaire: ${n(p, 'total') ?? '?'} of 27`, detail: p.item9_positive ? 'Item 9 answered above zero' : 'Item 9 answered zero' };
    case 'obs.wearable_daily':
      return {
        group: 'body',
        title: n(p, 'sleep_min') !== null ? `Slept ${durationMinutes(n(p, 'sleep_min') as number)}` : 'Watch daily summary',
        detail: join([
          n(p, 'sleep_midpoint_min') !== null && `middle of sleep ${clockMinutes(n(p, 'sleep_midpoint_min') as number)}`,
          n(p, 'resting_hr_bpm') !== null && `resting heart rate ${Math.round(n(p, 'resting_hr_bpm') as number)} bpm`,
          n(p, 'hrv_sdnn_ms') !== null && `heart rate variability ${Math.round(n(p, 'hrv_sdnn_ms') as number)} ms`,
          n(p, 'steps') !== null && `${(n(p, 'steps') as number).toLocaleString('en-GB')} steps`,
        ]),
      };
    case 'obs.screen_activity':
      return {
        group: 'screen',
        title: n(p, 'active_min') !== null ? `${durationMinutes(n(p, 'active_min') as number)} of active screen time` : 'Screen rhythm',
        detail: join([n(p, 'late_night_min') !== null && `${durationMinutes(n(p, 'late_night_min') as number)} between midnight and 05:00`, n(p, 'breaks') !== null && `${n(p, 'breaks')} breaks`, n(p, 'longest_stretch_min') !== null && `longest stretch ${durationMinutes(n(p, 'longest_stretch_min') as number)}`]),
      };
    case 'obs.nudge_offered':
      return { group: 'support', title: `Kaiku suggested ${activity(p.arm)}`, detail: typeof p.reason === 'string' ? `“${p.reason}”` : '' };
    case 'obs.nudge_outcome':
      return { group: 'support', title: `Suggestion ${p.accepted ? 'taken up' : 'passed on'}: ${activity(p.arm)}`, detail: '' };
    case 'obs.intervention_response': {
      const d = (p.delta ?? {}) as Record<string, unknown>;
      const parts = Object.entries(d).filter(([, v]) => typeof v === 'number').map(([k, v]) => `${words(k)} ${(v as number) > 0 ? 'up' : (v as number) < 0 ? 'down' : 'unchanged'}${v ? ` ${Math.abs(v as number)}` : ''}`);
      return { group: 'support', title: `Before and after ${activity(p.activity)}`, detail: parts.length ? `Self-rated ${parts.join(', ')}` : '' };
    }
    case 'obs.friend_link':
      return { group: 'support', title: `Friend lamp ${words(p.direction)}`, detail: p.ack ? 'Acknowledged' : '' };
    default:
      return { group: 'other', title: cap(words(e.type.replace(/^obs\./, ''))), detail: '' };
  }
}

export const localDate = (ts: string): string => {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.slice(0, 10);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export const localTime = (ts: string): string => {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? '' : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

export interface DayEvidence {
  date: string;
  count: number;
  groups: { group: EvidenceGroup; items: (EvidenceLine & { id: string; time: string; source: string; sim: boolean })[] }[];
}

/** Newest day first; inside a day, groups in a fixed order and records by time. */
export function byDay(events: ObsEvent[]): DayEvidence[] {
  const days = new Map<string, ObsEvent[]>();
  for (const e of events) {
    const d = localDate(e.ts);
    days.set(d, [...(days.get(d) ?? []), e]);
  }
  return [...days.entries()]
    .sort((a, b) => b[0].localeCompare(a[0]))
    .map(([date, list]) => {
      const items = [...list].sort((a, b) => a.ts.localeCompare(b.ts)).map((e) => ({ ...describeObs(e), id: e.id, time: localTime(e.ts), source: e.source, sim: Boolean(e.sim) }));
      return {
        date,
        count: list.length,
        groups: GROUP_ORDER.map((group) => ({ group, items: items.filter((i) => i.group === group) })).filter((g) => g.items.length),
      };
    });
}
