'use client';

import Link from 'next/link';
import { useRef, useState } from 'react';
import type { Phq9History } from '@contracts';
import { postEvents, useApi } from '@/lib/api';
import { makeEnvelope } from '@/lib/envelope';
import { usePairing } from '@/lib/params';
import { CrisisPanel } from '@/components/CrisisPanel';
import { Loading, PageHead } from '@/components/ui';

/** PHQ-9 (Kroenke, Spitzer & Williams; public domain). Wording must not be changed. */
export const PHQ9_ITEMS = [
  'Little interest or pleasure in doing things',
  'Feeling down, depressed, or hopeless',
  'Trouble falling or staying asleep, or sleeping too much',
  'Feeling tired or having little energy',
  'Poor appetite or overeating',
  'Feeling bad about yourself — or that you are a failure or have let yourself or your family down',
  'Trouble concentrating on things, such as reading the newspaper or watching television',
  'Moving or speaking so slowly that other people could have noticed? Or the opposite — being so fidgety or restless that you have been moving around a lot more than usual',
  'Thoughts that you would be better off dead or of hurting yourself in some way',
];
const OPTIONS = ['Not at all', 'Several days', 'More than half the days', 'Nearly every day'];

type Step = 'form' | 'done' | 'crisis';
type SendState = 'idle' | 'sending' | 'sent' | 'failed';

export function Phq9Flow() {
  const pairing = usePairing();
  const history = useApi<Phq9History>(pairing ? `/v1/patients/${encodeURIComponent(pairing.homeId)}/phq9` : null);
  const [answers, setAnswers] = useState<(number | null)[]>(Array(9).fill(null));
  const [step, setStep] = useState<Step>('form');
  const [send, setSend] = useState<SendState>('idle');
  const [sendError, setSendError] = useState<string | null>(null);
  const crisisRef = useRef<HTMLDivElement>(null);
  const flagSent = useRef(false);

  if (!pairing) return <Loading />;
  const { homeId, token } = pairing;
  const answered = answers.filter((a) => a !== null).length;
  const total = answers.reduce<number>((s, a) => s + (a ?? 0), 0);
  const today = new Date().toISOString().slice(0, 10);
  const due = history.data?.next_due ?? null;

  const phq9Env = (items: number[]) =>
    makeEnvelope(
      'obs.phq9',
      {
        total: items.reduce((a, b) => a + b, 0),
        items: items as [number, number, number, number, number, number, number, number, number],
        item9_positive: items[8] > 0,
        mode: 'laptop',
      },
      { source: 'laptop', homeId },
    );

  /** Deterministic crisis path: item 9 > 0 → stop, show the fixed panel, raise the safety flag first. */
  async function triggerCrisis(current: (number | null)[]) {
    setStep('crisis');
    requestAnimationFrame(() => crisisRef.current?.querySelector<HTMLElement>('[role=alertdialog]')?.focus());
    if (flagSent.current) return;
    flagSent.current = true;
    setSend('sending');
    const events: unknown[] = [
      makeEnvelope('obs.safety_flag', { trigger: 'phq9_item9', severity: 'high', handled_locally: true }, { source: 'laptop', homeId }),
    ];
    // Only send the questionnaire itself if every item was answered — never invent missing answers.
    if (current.every((a) => a !== null)) events.push(phq9Env(current as number[]));
    try {
      await postEvents(events, token);
      setSend('sent');
    } catch {
      setSend('failed');
    }
  }

  function choose(q: number, value: number) {
    const next = [...answers];
    next[q] = value;
    setAnswers(next);
    if (q === 8 && value > 0) void triggerCrisis(next);
  }

  async function submit() {
    setStep('done');
    setSend('sending');
    try {
      await postEvents([phq9Env(answers as number[])], token);
      setSend('sent');
    } catch (e) {
      setSendError((e as Error).message);
      setSend('failed');
    }
  }

  if (step === 'crisis') {
    return (
      <div ref={crisisRef}>
        <CrisisPanel notified={send} />
        <p className="muted small">The questionnaire has stopped. You can close this page whenever you are ready.</p>
      </div>
    );
  }

  if (step === 'done') {
    return (
      <section className="card" aria-live="polite">
        <h2>Thank you — that’s this fortnight’s questionnaire.</h2>
        {send === 'sending' && <Loading label="Sending to your care team…" />}
        {send === 'sent' && <p>Your answers have been shared with your care team. The next one is in about two weeks.</p>}
        {send === 'failed' && (
          <div className="state state-error" role="alert">
            <div>
              <strong>We couldn’t send your answers.</strong> {sendError}
              {!token && <div className="small">This device isn’t paired yet — open the link your care team gave you.</div>}
            </div>
            <button type="button" className="btn btn-ghost" onClick={submit}>
              Try again
            </button>
          </div>
        )}
        <p className="small">
          <Link href="/me/">Back to your week</Link>
        </p>
      </section>
    );
  }

  return (
    <>
      <PageHead
        title="PHQ-9"
        lede="The standard two-weekly questionnaire your care team uses. It anchors everything else Kaiku notices."
      />
      {due && due > today && (
        <p className="banner">Not due until {due} — you can still fill it in if you’d like.</p>
      )}
      {due && due <= today && <p className="banner banner-due">Due now. Thank you for taking two minutes.</p>}
      {!token && (
        <p className="banner">
          This device isn’t paired yet, so answers may not reach your care team. Open the link they gave you (it contains{' '}
          <code>?t=</code>).
        </p>
      )}
      <section className="card" aria-labelledby="phq-title">
        <p className="stepper">{answered} of 9 answered</p>
        <h2 id="phq-title">Over the last 2 weeks, how often have you been bothered by any of the following problems?</h2>
        <ol className="phq">
          {PHQ9_ITEMS.map((q, i) => (
            <li key={i}>
              <fieldset>
                <legend>
                  {i + 1}. {q}
                </legend>
                <div className="options">
                  {OPTIONS.map((label, v) => (
                    <label key={v} className="option">
                      <input type="radio" name={`q${i}`} value={v} checked={answers[i] === v} onChange={() => choose(i, v)} />
                      <span>{label}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            </li>
          ))}
        </ol>
        <div className="btn-row" style={{ marginTop: 16 }}>
          <button type="button" className="btn" disabled={answered < 9} onClick={submit}>
            Send to my care team
          </button>
          {answered < 9 && <span className="muted small">Please answer all nine questions.</span>}
          {answered === 9 && <span className="muted small">Total {total} / 27</span>}
        </div>
      </section>
    </>
  );
}
