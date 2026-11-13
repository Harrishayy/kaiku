'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import type { LaptopSession } from '@contracts';
import { postEvents } from '@/lib/api';
import { makeEnvelope } from '@/lib/envelope';
import { startExpressivity, type ExpressivitySession } from '@/lib/expressivity';
import { fmt, pct } from '@/lib/format';
import { makeSchedule, reactionStats, type Trial } from '@/lib/metrics';
import { usePairing } from '@/lib/params';
import { startSpeechTask, type SpeechResult, type SpeechSession } from '@/lib/speech';
import { NotOkButton } from '@/components/NotOkButton';
import { DeviceIndicator, Loading, PageHead } from '@/components/ui';

const SPEECH_S = 30;
const REACTION_TRIALS = 24; // ≈ 60 s with 1.2–2.8 s gaps
const NOGO_SHOW_MS = 900;
const GO_TIMEOUT_MS = 1200;

type Step = 'intro' | 'speak' | 'react' | 'review' | 'sent';

export function SessionFlow() {
  const pairing = usePairing();
  const [step, setStep] = useState<Step>('intro');
  const [useCamera, setUseCamera] = useState(true);
  const [speech, setSpeech] = useState<SpeechResult | null>(null);
  const [expressivity, setExpressivity] = useState<number | null>(null);
  const [reaction, setReaction] = useState<ReturnType<typeof reactionStats> | null>(null);
  const [sendState, setSendState] = useState<'idle' | 'sending' | 'sent' | 'failed'>('idle');
  const [sendError, setSendError] = useState<string | null>(null);
  const startedAt = useRef<number>(0);

  if (!pairing) return <Loading />;
  const { homeId, token } = pairing;

  const payload: LaptopSession = {
    speech_rate: speech?.speech_rate ?? null,
    pause_ratio: speech?.pause_ratio ?? null,
    pitch_variability: speech?.pitch_variability ?? null,
    expressivity_index: expressivity,
    reaction_ms_median: reaction?.reaction_ms_median ?? null,
    reaction_ms_iqr: reaction?.reaction_ms_iqr ?? null,
    lapses: reaction ? reaction.lapses : null,
    duration_s: Math.round((Date.now() - startedAt.current) / 100) / 10,
  };

  async function send() {
    setSendState('sending');
    setSendError(null);
    try {
      await postEvents([makeEnvelope('obs.laptop_session', payload, { source: 'laptop', homeId })], token);
      setSendState('sent');
      setStep('sent');
    } catch (e) {
      setSendError((e as Error).message);
      setSendState('failed');
    }
  }

  return (
    <>
      <PageHead title="Your 2-minute session" lede="Talk for half a minute, then a quick reaction game. Everything is analysed here in your browser — nothing is recorded." />
      {!token && step !== 'sent' && (
        <p className="banner">
          This device isn’t paired yet, so results may not reach your care team. Open the link they gave you (it contains{' '}
          <code>?t=</code>).
        </p>
      )}

      {step === 'intro' && (
        <section className="card consent">
          <p className="stepper">Before we start</p>
          <ul>
            <li>
              <strong>Microphone:</strong> we measure pace, pauses and pitch variation while you speak. The audio never leaves this
              browser and is not stored.
            </li>
            <li>
              <strong>Camera (optional):</strong> a face-landmark model running in your browser measures how much your expression
              moves. No image is kept or sent.
            </li>
            <li>
              <strong>Only numbers are sent</strong>, and you’ll see them before anything is shared. More in{' '}
              <Link href="/consent/">consent &amp; privacy</Link>.
            </li>
          </ul>
          <label className="check">
            <input type="checkbox" checked={useCamera} onChange={(e) => setUseCamera(e.target.checked)} /> Use my camera for facial
            expressivity
          </label>
          <div className="btn-row" style={{ marginTop: 12 }}>
            <button
              type="button"
              className="btn"
              onClick={() => {
                startedAt.current = Date.now();
                setStep('speak');
              }}
            >
              I understand — start
            </button>
          </div>
        </section>
      )}

      {step === 'speak' && (
        <SpeakStep
          useCamera={useCamera}
          onDone={(s, e) => {
            setSpeech(s);
            setExpressivity(e);
            setStep('react');
          }}
        />
      )}

      {step === 'react' && (
        <ReactionStep
          onDone={(r) => {
            setReaction(r);
            setStep('review');
          }}
        />
      )}

      {step === 'review' && (
        <section className="card" aria-labelledby="rev-h">
          <p className="stepper">Done · review before sending</p>
          <h2 id="rev-h">These numbers are all that will be shared</h2>
          <div className="table-wrap">
            <table>
              <tbody>
                <tr>
                  <th scope="row">Speech pace</th>
                  <td className="num">{payload.speech_rate === null ? 'not measured' : `${fmt(payload.speech_rate, 2)} syllables/s`}</td>
                </tr>
                <tr>
                  <th scope="row">Pauses</th>
                  <td className="num">{payload.pause_ratio === null ? 'not measured' : pct(payload.pause_ratio)}</td>
                </tr>
                <tr>
                  <th scope="row">Pitch variation</th>
                  <td className="num">
                    {payload.pitch_variability === null ? 'not measured' : `${fmt(payload.pitch_variability, 2)} semitones`}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Facial expressivity</th>
                  <td className="num">{payload.expressivity_index === null ? 'not measured' : fmt(payload.expressivity_index, 2)}</td>
                </tr>
                <tr>
                  <th scope="row">Reaction time</th>
                  <td className="num">
                    {payload.reaction_ms_median === null
                      ? 'not measured'
                      : `${fmt(payload.reaction_ms_median)} ms (spread ${fmt(payload.reaction_ms_iqr)} ms)`}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Slow or missed</th>
                  <td className="num">{payload.lapses ?? 'not measured'}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="btn-row" style={{ marginTop: 12 }}>
            <button type="button" className="btn" disabled={sendState === 'sending'} onClick={send}>
              {sendState === 'sending' ? 'Sending…' : 'Send to my care team'}
            </button>
            <Link className="btn btn-ghost" href="/me/">
              Discard
            </Link>
          </div>
          {sendState === 'failed' && (
            <p role="alert" className="small" style={{ color: 'var(--red)' }}>
              Couldn’t send: {sendError}
            </p>
          )}
        </section>
      )}

      {step === 'sent' && (
        <section className="card" aria-live="polite">
          <h2>Thank you — that’s today’s session.</h2>
          <p>Only the numbers you saw were shared. See you tomorrow.</p>
          <Link href="/me/">Back to your week</Link>
        </section>
      )}

      <section className="card" style={{ marginTop: 16 }}>
        <p className="small">If today feels like too much, you don’t have to handle it alone.</p>
        <NotOkButton homeId={homeId} token={token} />
      </section>
    </>
  );
}

function SpeakStep({ useCamera, onDone }: { useCamera: boolean; onDone: (s: SpeechResult | null, expr: number | null) => void }) {
  const [phase, setPhase] = useState<'ready' | 'live' | 'error'>('ready');
  const [level, setLevel] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [micOn, setMicOn] = useState(false);
  const [camOn, setCamOn] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const speech = useRef<SpeechSession | null>(null);
  const expr = useRef<ExpressivitySession | null>(null);

  useEffect(
    () => () => {
      speech.current?.stop();
      void expr.current?.stop();
    },
    [],
  );

  async function start() {
    setNote(null);
    if (useCamera && video.current) {
      try {
        expr.current = await startExpressivity(video.current);
        setCamOn(true);
      } catch {
        setNote('Camera unavailable or declined — continuing with voice only.');
      }
    }
    try {
      speech.current = await startSpeechTask({
        durationS: SPEECH_S,
        onLevel: (l, e) => {
          setLevel(l);
          setElapsed(e);
        },
      });
      setMicOn(true);
      setPhase('live');
      const s = await speech.current.done;
      setMicOn(false);
      const e = expr.current ? await expr.current.stop() : null;
      setCamOn(false);
      onDone(s, e);
    } catch (e) {
      const e2 = expr.current ? await expr.current.stop() : null;
      setCamOn(false);
      setPhase('error');
      setNote(
        (e as Error).name === 'NotAllowedError'
          ? 'Microphone permission was declined. That’s fine — you can skip to the reaction game.'
          : 'No microphone available. You can skip to the reaction game.',
      );
      expr.current = null;
      void e2;
    }
  }

  return (
    <section className="card" aria-labelledby="speak-h">
      <p className="stepper">Step 1 of 2 · Speaking</p>
      <h2 id="speak-h">Tell me about your morning, for about 30 seconds</h2>
      <p className="muted">Anything at all — what you had for breakfast, the weather, what’s planned today.</p>
      <div className="devices">
        <DeviceIndicator kind="microphone" on={micOn} />
        {useCamera && <DeviceIndicator kind="camera" on={camOn} />}
      </div>
      {/* Preview only; frames are read in memory for blendshape scores and never stored. */}
      <video ref={video} className={camOn ? 'cam-preview' : 'cam-preview hidden'} playsInline muted aria-label="Camera preview" />
      {phase === 'ready' && (
        <div className="btn-row">
          <button type="button" className="btn" onClick={start}>
            Start speaking
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => onDone(null, null)}>
            Skip
          </button>
        </div>
      )}
      {phase === 'live' && (
        <>
          <div className="meter" role="progressbar" aria-label="Time" aria-valuemin={0} aria-valuemax={SPEECH_S} aria-valuenow={Math.round(elapsed)}>
            <div style={{ transform: `scaleX(${Math.min(1, elapsed / SPEECH_S)})` }} />
          </div>
          <p className="small muted" style={{ marginTop: 8 }}>
            {Math.max(0, Math.ceil(SPEECH_S - elapsed))} s left · voice level
          </p>
          <div className="meter" aria-hidden="true" style={{ height: 6 }}>
            <div style={{ transform: `scaleX(${level})`, background: 'var(--chart-median)' }} />
          </div>
          <div className="btn-row" style={{ marginTop: 12 }}>
            <button type="button" className="btn btn-ghost" onClick={() => speech.current?.stop()}>
              Stop early
            </button>
          </div>
        </>
      )}
      {phase === 'error' && (
        <div className="btn-row">
          <button type="button" className="btn" onClick={() => onDone(null, null)}>
            Continue to the reaction game
          </button>
        </div>
      )}
      {note && (
        <p className="small" role="status">
          {note}
        </p>
      )}
    </section>
  );
}

function ReactionStep({ onDone }: { onDone: (r: ReturnType<typeof reactionStats>) => void }) {
  const [phase, setPhase] = useState<'ready' | 'run'>('ready');
  const [stim, setStim] = useState<'none' | 'go' | 'nogo'>('none');
  const [index, setIndex] = useState(0);
  const trials = useRef<Trial[]>([]);
  const shownAt = useRef<number | null>(null);
  const current = useRef<Trial | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const finished = useRef(false);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  function respond() {
    const t = current.current;
    if (!t || shownAt.current === null || t.rt !== null) return;
    t.rt = Math.round(performance.now() - shownAt.current);
    setStim('none');
  }

  useEffect(() => {
    if (phase !== 'run') return;
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Space' || e.key === ' ') {
        e.preventDefault();
        respond();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [phase]);

  function run() {
    setPhase('run');
    const schedule = makeSchedule(REACTION_TRIALS);
    let at = 600;
    schedule.forEach((s, i) => {
      at += s.isiMs;
      timers.current.push(
        setTimeout(() => {
          const t: Trial = { kind: s.kind, rt: null };
          trials.current.push(t);
          current.current = t;
          shownAt.current = performance.now();
          setIndex(i + 1);
          setStim(s.kind);
          timers.current.push(setTimeout(() => setStim('none'), s.kind === 'go' ? GO_TIMEOUT_MS : NOGO_SHOW_MS));
        }, at),
      );
    });
    timers.current.push(
      setTimeout(() => {
        if (finished.current) return;
        finished.current = true;
        onDone(reactionStats(trials.current));
      }, at + GO_TIMEOUT_MS + 200),
    );
  }

  return (
    <section className="card" aria-labelledby="react-h">
      <p className="stepper">Step 2 of 2 · Reaction game · about 1 minute</p>
      <h2 id="react-h">Tap when the circle is green. Don’t tap when it’s red.</h2>
      <p className="muted small">Press the space bar or tap the big area. It’s fine to miss some.</p>
      {phase === 'ready' && (
        <button type="button" className="btn" onClick={run}>
          Start the game
        </button>
      )}
      {phase === 'run' && (
        <>
          <button
            type="button"
            className={`react-pad ${stim}`}
            onPointerDown={(e) => {
              e.preventDefault();
              respond();
            }}
            aria-label={stim === 'go' ? 'Green — tap now' : stim === 'nogo' ? 'Red — do not tap' : 'Wait'}
          >
            <span className="react-dot" aria-hidden="true" />
          </button>
          <p className="small muted" role="status">
            {index} / {REACTION_TRIALS}
          </p>
        </>
      )}
    </section>
  );
}
