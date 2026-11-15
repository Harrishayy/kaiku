'use client';

import type { ReactNode } from 'react';
import type { ApiError } from '@/lib/api';
import type { Tone } from '@/lib/insight';
import { label, type ChipTone } from '@/lib/labels';

export type { ChipTone };

/** The one chip. A dot plus words, so tone never rests on colour alone. */
export function Chip({ tone = 'neutral', children, title }: { tone?: ChipTone; children: ReactNode; title?: string }) {
  return (
    <span className={`d-chip d-chip-${tone}`} title={title}>
      <span className="d-chip-dot" aria-hidden="true" />
      {children}
    </span>
  );
}

/** Shape cue + words for a comparison: filled = as usual or better, ring = change from usual, dashed = not enough data. */
export function ToneMark({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className="d-tone">
      <span className={`d-mark d-mark-${tone}`} aria-hidden="true" />
      {children}
    </span>
  );
}

export function Busy({ label }: { label: string }) {
  return (
    <div className="d-state" role="status" aria-live="polite">
      <span className="d-spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="d-state d-state-empty">
      <strong>{title}</strong>
      {children && <span>{children}</span>}
    </div>
  );
}

export function Problem({ what, error, onRetry }: { what: string; error: ApiError; onRetry?: () => void }) {
  const unreachable = error.status === null;
  return (
    <div className="d-state d-state-error" role="alert">
      <strong>{what} could not be loaded.</strong>
      <span>
        {unreachable
          ? 'The Kaiku service is not answering. Nothing has been lost; this view retries on its own.'
          : error.status === 401 || error.status === 403
            ? 'Care team access is needed for this record.'
            : 'Something went wrong on our side. Try again in a moment.'}
      </span>
      {onRetry && (
        <button type="button" className="d-btn d-btn-quiet d-btn-outline" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

const CAPTURE: Record<string, string> = {
  hub: 'home robot',
  head: 'robot head',
  sensors: 'robot sensors',
  phone: 'iPhone app',
  laptop: 'Mac app',
  glasses: 'glasses',
  friendlink: 'friend lamp',
  cloud: 'Kaiku service',
  sim: 'simulator',
};
export const captureLabel = (source: string) => CAPTURE[source] ?? source;

/** Where records actually came from (the sender on each record), with a discreet simulated-source marker. */
export function Provenance({ sources, simulated }: { sources: string[]; simulated?: boolean }) {
  if (!sources.length && !simulated) return null;
  return (
    <span className="d-prov">
      {sources.length ? `Sent by ${sources.map(captureLabel).join(', ')}` : 'Sender not recorded'}
      {simulated && <SimMark />}
    </span>
  );
}

export function SimMark() {
  return (
    <span className="d-sim" title="These records were sent by a simulated source, not a connected device">
      {label('common.simulated')}
    </span>
  );
}

export function Glyph({ d, size = 16 }: { d: string; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}
