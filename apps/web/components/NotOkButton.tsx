'use client';

import { useRef, useState } from 'react';
import { postEvents } from '@/lib/api';
import { makeEnvelope } from '@/lib/envelope';
import { CrisisPanel } from './CrisisPanel';

/**
 * Manual safety trigger for the person-facing pages (deterministic, no LLM — handoff §12).
 * Shows the fixed crisis panel immediately, then raises obs.safety_flag{trigger:"manual"} on the cloud.
 */
export function NotOkButton({ homeId, token }: { homeId: string; token: string | null }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'failed'>('idle');
  const sent = useRef(false);
  const ref = useRef<HTMLDivElement>(null);

  async function trigger() {
    setOpen(true);
    requestAnimationFrame(() => ref.current?.querySelector<HTMLElement>('[role=alertdialog]')?.focus());
    if (sent.current) return;
    sent.current = true;
    setState('sending');
    try {
      await postEvents(
        [makeEnvelope('obs.safety_flag', { trigger: 'manual', severity: 'high', handled_locally: true }, { source: 'laptop', homeId })],
        token,
      );
      setState('sent');
    } catch {
      setState('failed');
    }
  }

  if (open)
    return (
      <div ref={ref}>
        <CrisisPanel notified={state} />
      </div>
    );
  return (
    <button type="button" className="btn btn-notok" onClick={trigger}>
      I’m not OK
    </button>
  );
}
