'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { postEvents } from '@/lib/api';
import { makeEnvelope } from '@/lib/envelope';
import { useCopy } from '@/lib/i18n';
import { CRISIS_SCRIPT_EN, CRISIS_SCRIPT_FI } from './CrisisPanel';

export type Notify = 'idle' | 'sending' | 'sent' | 'failed';

/**
 * "I'm not OK" (deterministic, no LLM): show the crisis screen at once, then raise obs.safety_flag{manual}.
 * The flag is sent once per page view.
 */
export function useCrisis(homeId: string | undefined, token: string | null | undefined) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Notify>('idle');
  const sent = useRef(false);
  const trigger = useCallback(async () => {
    setOpen(true);
    window.scrollTo({ top: 0 });
    if (sent.current || !homeId) return;
    sent.current = true;
    setStatus('sending');
    try {
      await postEvents(
        [makeEnvelope('obs.safety_flag', { trigger: 'manual', severity: 'high', handled_locally: true }, { source: 'laptop', homeId })],
        token ?? null,
      );
      setStatus('sent');
    } catch {
      setStatus('failed');
    }
  }, [homeId, token]);
  return { open, status, trigger };
}

/**
 * Crisis screen (design/ia.md): plain surface, no mascot, no motion, no character copy.
 * Text = config/safety_phrases.toml [script] (mirrored in CrisisPanel.tsx); buttons from copy.json help.*.
 * `status` is null when the cloud already knows (mascot mood "crisis"): then the care team was told.
 */
export function CrisisScreen({ status }: { status: Notify | null }) {
  const { t, lang } = useCopy();
  const ref = useRef<HTMLElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <section ref={ref} className="k-crisis ui" role="alertdialog" aria-labelledby="crisis-title" aria-describedby="crisis-body" tabIndex={-1} lang={lang}>
      <h1 id="crisis-title">{t('crisis.title')}</h1>
      <p id="crisis-body" className="ink2">
        {lang === 'fi' ? CRISIS_SCRIPT_FI : CRISIS_SCRIPT_EN}
      </p>
      <a className="k-call" href="tel:+358925250111">
        {t('help.mieli')}
        <span>{t('help.mieli.d')}</span>
      </a>
      <a className="k-call" href="tel:112">
        {t('help.112')}
        <span>{t('help.112.d')}</span>
      </a>
      <div className="k-call second" role="status">
        {status === 'sending' ? t('crisis.sending') : status === 'failed' ? t('crisis.failed') : t('crisis.team')}
        {status !== 'sending' && status !== 'failed' && <span>{t('crisis.team.d')}</span>}
      </div>
    </section>
  );
}
