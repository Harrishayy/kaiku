/** The one label table: state and verdict words come from design/copy.json, never retyped here. */
import copy from '@design/copy.json';
import type { Consensus, SourceVerdict } from '@contracts';

const EN = copy.en as Record<string, string>;
export const label = (key: string): string => EN[key] ?? key;

/** ok = stable / better (sage, filled) · warn = worth a check-in / change from usual (honey, half) ·
 *  call = needs a call (clay, ring) · ins = not enough data (dashed) · crisis = safety only (triangle) ·
 *  neutral = as usual · info = plain information. */
export type ChipTone = 'ok' | 'warn' | 'call' | 'ins' | 'info' | 'crisis' | 'neutral';

/** The one consensus state → label + tone map. Low coverage never reads as a steady state. */
export function stateChip(state: Consensus['state'], agreement: Consensus['agreement']): { label: string; tone: ChipTone } {
  if (state === 'safety') return { label: label('state.safety'), tone: 'crisis' };
  if (state === 'needs_call') return { label: label('state.needs_call'), tone: 'call' };
  if (state === 'watch' && agreement === 'low_coverage') return { label: label('state.insufficient'), tone: 'ins' };
  if (state === 'watch') return { label: label('state.watch'), tone: 'warn' };
  return { label: label('state.stable'), tone: 'ok' };
}

export function verdictChip(v: SourceVerdict['verdict'] | undefined): { label: string; tone: ChipTone } {
  if (v === 'worse') return { label: label('verdict.worse'), tone: 'warn' };
  if (v === 'better') return { label: label('verdict.better'), tone: 'ok' };
  if (v === 'as_usual') return { label: label('verdict.as_usual'), tone: 'neutral' };
  return { label: label('verdict.insufficient'), tone: 'ins' };
}
