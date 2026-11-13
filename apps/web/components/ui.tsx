'use client';

import type { ReactNode } from 'react';
import type { ApiError } from '@/lib/api';
import {
  AGREEMENT_LABEL,
  STATE_CLASS,
  STATE_LABEL,
  VERDICT_CLASS,
  VERDICT_LABEL,
  type Agreement,
  type State,
  type Verdict,
} from '@/lib/format';

export function StateChip({ state, large = false }: { state: State; large?: boolean }) {
  return (
    <span className={`chip ${STATE_CLASS[state]}${large ? ' chip-lg' : ''}`}>
      <span className="chip-dot" aria-hidden="true" />
      {STATE_LABEL[state]}
    </span>
  );
}

export function VerdictChip({ verdict, compact = false }: { verdict: Verdict; compact?: boolean }) {
  const short: Record<Verdict, string> = { worse: 'worse', as_usual: 'as usual', better: 'better', insufficient: 'no data' };
  return (
    <span className={`chip ${VERDICT_CLASS[verdict]}${verdict === 'insufficient' ? ' chip-dashed' : ''}`}>
      <span className="chip-dot" aria-hidden="true" />
      {compact ? short[verdict] : VERDICT_LABEL[verdict]}
    </span>
  );
}

export function AgreementBadge({ agreement }: { agreement: Agreement }) {
  if (agreement === 'agree') return <span className="tag">{AGREEMENT_LABEL.agree}</span>;
  return (
    <span className={agreement === 'disagree' ? 'tag tag-disagree' : 'tag tag-coverage'}>{AGREEMENT_LABEL[agreement]}</span>
  );
}

export function SimBadge({ show = true }: { show?: boolean }) {
  if (!show) return null;
  return (
    <span className="badge-sim" title="Synthetic data produced by the simulator — not a real person">
      SIMULATED
    </span>
  );
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
        <button type="button" className="btn btn-ghost" onClick={onRetry}>
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
