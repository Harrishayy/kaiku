'use client';

import type { ReactNode } from 'react';
import type { ApiError } from '@/lib/api';
import { AGREEMENT_LABEL, type Agreement, type State, type Verdict } from '@/lib/format';
import { stateChip, verdictChip } from '@/lib/labels';
import { Chip, SimMark } from './dash/kit';

/** Team pages use the dashboard's one chip. A bare state has no agreement, so it is shown as the cloud named it. */
export function StateChip({ state }: { state: State; large?: boolean }) {
  const c = stateChip(state, 'agree');
  return <Chip tone={c.tone}>{c.label}</Chip>;
}

export function VerdictChip({ verdict }: { verdict: Verdict; compact?: boolean }) {
  const c = verdictChip(verdict);
  return <Chip tone={c.tone}>{c.label}</Chip>;
}

export function AgreementBadge({ agreement }: { agreement: Agreement }) {
  return <Chip tone={agreement === 'agree' ? 'neutral' : agreement === 'disagree' ? 'warn' : 'ins'}>{AGREEMENT_LABEL[agreement]}</Chip>;
}

export function SimBadge({ show = true }: { show?: boolean }) {
  return show ? <SimMark /> : null;
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorBox({ error, onRetry, what }: { error: ApiError; onRetry?: () => void; what: string }) {
  return (
    <div className="state state-error" role="alert">
      <div>
        <strong>Couldn’t load {what}.</strong> {error.message}
        {error.status === null && (
          <div className="muted small">
            Kaiku can’t reach the server right now. Check your connection and try again in a moment.
          </div>
        )}
      </div>
      {onRetry && (
        <button type="button" className="d-btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="state state-empty">{children}</div>;
}

export function StaleNote({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <p className="stale" role="status">
      Connection lost — showing the last data we received. Retrying…
    </p>
  );
}

export function PageHead({ title, lede, children }: { title: string; lede?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {lede && <p className="lede">{lede}</p>}
      </div>
      {children && <div className="page-head-aside">{children}</div>}
    </div>
  );
}

/** Visible "camera on" / "microphone on" pill — shown whenever a device is live. */
export function DeviceIndicator({ kind, on }: { kind: 'camera' | 'microphone'; on: boolean }) {
  return (
    <span className={on ? 'device on' : 'device'} role="status" aria-live="polite">
      <span className="device-dot" aria-hidden="true" />
      {kind === 'camera' ? 'Camera' : 'Microphone'} {on ? 'on — analysed here, nothing recorded' : 'off'}
    </span>
  );
}
