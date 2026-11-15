/**
 * Pure view-model helpers for the clinician pages (unit-tested). They only rearrange what the cloud decided:
 * the state, verdicts and evidence come from the consensus; numbers come from the timeline series.
 */

import type { Consensus, TimelinePoint } from '../../../contracts/ts/models.ts';

export function lastValue(points: TimelinePoint[]): TimelinePoint | null {
  for (let i = points.length - 1; i >= 0; i--) if (typeof points[i].value === 'number') return points[i];
  return null;
}

export function num(v: number | null | undefined): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  const s = a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2);
  return (s.includes('.') ? s.replace(/\.?0+$/, '') : s) || '0'; // 8900 stays 8900; 2.50 → 2.5
}

/** Format raw clinical units without changing the underlying measurement. */
export function durationMinutes(value: number): string {
  const minutes = Math.max(0, Math.round(value));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60), rest = minutes % 60;
  return `${hours} h${rest ? ` ${rest} min` : ''}`;
}

export function clockMinutes(value: number): string {
  const minute = ((Math.round(value) % 1440) + 1440) % 1440;
  return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;
}

export function withUnit(v: number | null | undefined, unit: string | undefined, missing = 'Not recorded'): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return missing;
  if (unit?.includes('midnight')) return clockMinutes(v);
  if (unit === 'min') return durationMinutes(v);
  if (unit === 's') return v >= 60 ? durationMinutes(v / 60) : `${Math.round(v)} sec`;
  if (unit === 'ratio') return `${Math.round(v * 100)}%`;
  if (unit === 'steps' || unit === 'count') return `${Math.round(v).toLocaleString('en-GB')}${unit === 'steps' ? ' steps' : ''}`;
  if (unit === 'ms') return `${Math.round(v)} ms`;
  if (!unit || ['', '0–1', '1–5'].includes(unit)) return num(v);
  return `${num(v)} ${unit}`;
}

export function metricUnitLabel(unit: string | undefined): string {
  if (unit?.includes('midnight')) return 'Time of day';
  if (unit === 'min' || unit === 's') return 'Duration';
  if (unit === 'ratio') return 'Percent';
  return unit ?? '';
}

export function shortDay(date: string | null | undefined): string {
  if (!date) return 'Date not recorded';
  const d = new Date(`${date.slice(0, 10)}T12:00:00`);
  return Number.isNaN(d.getTime()) ? 'Date not recorded' : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

/** "2 of 3 sources with data show a change from usual". */
export function consensusSentence(c: Consensus): string {
  const withData = c.sources.filter((s) => s.verdict !== 'insufficient');
  const worse = withData.filter((s) => s.verdict === 'worse').length;
  if (withData.length === 0) return 'No signal group has enough recent data yet';
  if (worse === 0) return `All ${withData.length} signal groups with data look as usual or better`;
  return `${worse} of ${withData.length} signal groups with data show a change from usual`;
}
