'use client';

/**
 * Firefly (design/ia.md Play): fireflies glow for 1.5 s, moths drift; tap fireflies, let moths go; 60 s.
 * Gentle end with a jar of caught fireflies, never a number. Quietly records one play_session (game firefly,
 * device web): reaction median + IQR, lapses, false taps — computed here, only numbers are sent.
 */

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { postEvents } from '@/lib/api';
import { makeEnvelope } from '@/lib/envelope';
import { useCopy } from '@/lib/i18n';
import { makeSchedule, reactionStats, type Trial } from '@/lib/metrics';
import { usePairing } from '@/lib/params';
import { Mascot } from '@/components/Mascot';
import { CrisisScreen, useCrisis } from '@/components/CrisisScreen';

const GAME_MS = 60_000;
const SHOW_MS = 1500;

interface Bug {
  id: number;
  kind: Trial['kind'];
  x: number;
  y: number;
  shownAt: number;
}

export function FireflyGame() {
  const { t, lang } = useCopy();
  const pairing = usePairing();
  const crisis = useCrisis(pairing?.homeId, pairing?.token);
  const [phase, setPhase] = useState<'intro' | 'play' | 'end'>('intro');
  const [bug, setBug] = useState<Bug | null>(null);
  const [caught, setCaught] = useState(0);
  const [cheer, setCheer] = useState(true);
  const trials = useRef<Trial[]>([]);
  const current = useRef<{ bug: Bug; trial: Trial } | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const started = useRef(0);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  function later(fn: () => void, ms: number) {
    timers.current.push(setTimeout(fn, ms));
  }

  function start() {
    trials.current = [];
    setCaught(0);
    setPhase('play');
    started.current = performance.now();
    const schedule = makeSchedule(40);
    let i = 0;
    let id = 0;
    const next = () => {
      const elapsed = performance.now() - started.current;
      if (elapsed > GAME_MS - SHOW_MS || i >= schedule.length) return finish();
      const s = schedule[i++];
      later(() => {
        const b: Bug = { id: id++, kind: s.kind, x: 10 + Math.random() * 80, y: 12 + Math.random() * 76, shownAt: performance.now() };
        const trial: Trial = { kind: s.kind, rt: null };
        trials.current.push(trial);
        current.current = { bug: b, trial };
        setBug(b);
        later(() => {
          if (current.current?.bug.id === b.id) current.current = null;
          setBug((x) => (x?.id === b.id ? null : x));
          next();
        }, SHOW_MS);
      }, s.isiMs * 0.6);
    };
    next();
  }

  function tap(b: Bug) {
    const c = current.current;
    if (!c || c.bug.id !== b.id || c.trial.rt !== null) return;
    c.trial.rt = Math.round(performance.now() - b.shownAt);
    if (b.kind === 'go') setCaught((n) => n + 1);
    setBug(null);
  }

  function finish() {
    setBug(null);
    setPhase('end');
    setCheer(true);
    later(() => setCheer(false), 3000);
    const st = reactionStats(trials.current);
    if (!pairing || st.go_trials === 0) return;
    const duration_s = Math.round((performance.now() - started.current) / 1000);
    postEvents(
      [
        makeEnvelope(
          'obs.play_session',
          {
            game: 'firefly',
            device: 'web',
            duration_s,
            reaction_ms_median: st.reaction_ms_median,
            reaction_ms_iqr: st.reaction_ms_iqr,
            lapses: st.lapses,
            false_taps: st.false_alarms,
          },
          { source: 'laptop', homeId: pairing.homeId },
        ),
      ],
      pairing.token,
    ).catch(() => {
      /* quiet: the game is the point, not the upload */
    });
  }

  if (crisis.open) return <CrisisScreen status={crisis.status} />;

  return (
    <div className="ui" lang={lang} style={{ paddingBlock: '16px 40px' }}>
      <div className="k-night">
        <div className="k-gametop">
          <h1 style={{ fontSize: '1.375em' }}>{t('game.firefly.t')}</h1>
          {phase !== 'end' && (
            <button type="button" className="k-notok" onClick={crisis.trigger}>
              {t('common.notok')}
            </button>
          )}
        </div>

        {phase === 'intro' && (
          <div className="k-center">
            <Mascot state="idle" size={140} label="Kaiku" />
            <p className="ink2">{t('ff.intro')}</p>
            <button type="button" className="k-b k-b-pri" onClick={start}>
              {t('game.start')}
            </button>
            <Link className="k-b k-b-ghost" href="/me/">
              {t('common.nottoday')}
            </Link>
          </div>
        )}

        {phase === 'play' && (
          <div className="k-field" aria-live="polite">
            {bug && (
              <button
                key={bug.id}
                type="button"
                className={bug.kind === 'nogo' ? 'k-fly moth' : 'k-fly'}
                style={{ left: `${bug.x}%`, top: `${bug.y}%` }}
                aria-label={t(bug.kind === 'nogo' ? 'ff.moth' : 'ff.firefly')}
                onPointerDown={() => tap(bug)}
              >
                <i />
              </button>
            )}
          </div>
        )}

        {phase === 'end' && (
          <div className="k-center">
            <Mascot state={cheer ? 'cheering' : 'happy'} size={120} label="Kaiku" />
            <Jar n={caught} />
            <p className="ink2">{caught > 0 ? t('ff.end') : t('ff.end.none')}</p>
            <button type="button" className="k-b k-b-pri" onClick={start}>
              {t('game.again')}
            </button>
            <Link className="k-b k-b-ghost" href="/me/">
              {t('game.enough')}
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

/** The jar shows the fireflies caught as little lights, never a count. */
function Jar({ n }: { n: number }) {
  const dots = Array.from({ length: Math.min(n, 24) }, (_, i) => ({
    left: 12 + ((i * 37) % 84),
    top: 18 + ((i * 53) % 70),
  }));
  return (
    <div className="k-jar" aria-hidden="true">
      {dots.map((d, i) => (
        <i key={i} style={{ left: `${d.left}%`, top: `${d.top}%` }} />
      ))}
    </div>
  );
}
