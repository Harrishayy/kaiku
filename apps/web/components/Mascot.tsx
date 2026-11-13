'use client';

/**
 * Kaiku, drawn from design/mascot.spec.json (geometry, states, blink, tap) with design/tokens.json (glow by hour,
 * easings, durations). Never redrawn by hand. Same engine as the look book: poses as CSS individual transforms,
 * tracks + blinks + events via the Web Animations API. Reduce Motion → pose only, 300 ms cross-fade on change.
 */

import { useEffect, useId, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import specJson from '@design/mascot.spec.json';
import tokens from '@design/tokens.json';
import {
  cssValue,
  glowAt,
  paint,
  walkParts,
  type BlinkMode,
  type MascotSpec,
  type MascotState,
  type Part,
  type Pose,
  type PropName,
  type Shape,
  type Track,
} from '@/lib/mascot.ts';

const SPEC = specJson as unknown as MascotSpec;
const EASE: Record<string, string> = Object.fromEntries(
  Object.entries(tokens.motion.easing).map(([k, v]) => [k, `cubic-bezier(${(v as number[]).join(',')})`]),
);
const CROSSFADE = tokens.motion.duration.crossfade;
const DEFAULTS: Record<string, { opacity?: number }> = {};
walkParts(SPEC.parts, (p) => (DEFAULTS[p.id] = p.default ?? {}));
const CSSP: Record<PropName, 'translate' | 'rotate' | 'scale' | 'opacity'> = {
  translate: 'translate',
  rotate: 'rotate',
  scale: 'scale',
  opacity: 'opacity',
};

function shapeEl(s: Shape, uid: string, key: number): ReactNode {
  const style: CSSProperties & Record<string, string | number> = {};
  if (s.fill) style.fill = paint(s.fill, s, uid);
  if (s.stroke) {
    style.stroke = paint(s.stroke, s, uid);
    style.strokeWidth = s['stroke-width'] ?? 1;
    if (s['stroke-linecap']) style.strokeLinecap = s['stroke-linecap'] as CSSProperties['strokeLinecap'];
    if (s['stroke-linejoin']) style.strokeLinejoin = s['stroke-linejoin'] as CSSProperties['strokeLinejoin'];
  }
  if (s.opacity != null) style.opacity = s.opacity;
  if (s.type === 'path') return <path key={key} d={s.d} style={style} />;
  if (s.type === 'ellipse') return <ellipse key={key} cx={s.cx} cy={s.cy} rx={s.rx} ry={s.ry} style={style} />;
  return <circle key={key} cx={s.cx} cy={s.cy} r={s.r} style={style} />;
}

function partEl(p: Part, uid: string): ReactNode {
  const style: CSSProperties = { transformBox: 'view-box', transformOrigin: `${p.pivot[0]}px ${p.pivot[1]}px` };
  if (p.default?.opacity != null) style.opacity = p.default.opacity;
  let shapes: ReactNode = (p.shapes ?? []).map((s, i) => shapeEl(s, uid, i));
  if (p.id === 'glow')
    shapes = <g style={{ opacity: 'var(--k-glow-intensity)', transition: 'opacity 700ms' } as CSSProperties}>{shapes}</g>;
  return (
    <g key={p.id} data-part={p.id} style={style}>
      {shapes}
      {(p.children ?? []).map((c) =>
        c.clip ? (
          <g key={c.id} clipPath={`url(#${uid}-c-${c.clip})`}>
            {partEl(c, uid)}
          </g>
        ) : (
          partEl(c, uid)
        ),
      )}
    </g>
  );
}

function useReducedMotion(): boolean {
  const [rm, setRm] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const on = () => setRm(mq.matches);
    on();
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return rm;
}

/** Glow colour + intensity for the local hour; re-evaluated once a minute (motion.md "Time of day"). */
function useGlow(): CSSProperties {
  const [hour, setHour] = useState<number | null>(null);
  useEffect(() => {
    const read = () => {
      const d = new Date();
      setHour(d.getHours() + d.getMinutes() / 60);
    };
    read();
    const id = setInterval(read, 60_000);
    return () => clearInterval(id);
  }, []);
  if (hour === null) return {};
  const g = glowAt(tokens.glow.stops, hour);
  return { ['--k-glow' as string]: g.color, ['--k-glow-intensity' as string]: g.intensity.toFixed(2) };
}

const rnd = (a: number, b: number) => a + Math.random() * (b - a);

export interface MascotProps {
  state?: MascotState;
  /** for `peek`: the state whose pose the other parts take */
  compose?: MascotState;
  /** px; the mascot keeps its size at any text scale (layout.md) */
  size?: number;
  /** pose only, no tracks/blinks (small icons) */
  still?: boolean;
  /** tap → ear flick (default on) */
  tappable?: boolean;
  /** accessible name; omit for a decorative mascot */
  label?: string;
  className?: string;
  /** set the ear angle directly (weather check dial), degrees */
  ear?: number | null;
}

export function Mascot({ state = 'idle', compose, size = 96, still = false, tappable = true, label, className, ear = null }: MascotProps) {
  const uid = 'k' + useId().replace(/[^a-zA-Z0-9]/g, '');
  const ref = useRef<SVGSVGElement>(null);
  const parts = useRef<Record<string, SVGGElement>>({});
  const flicking = useRef(false);
  const rm = useReducedMotion();
  const glow = useGlow();
  const first = useRef(true);

  const tree = useMemo(
    () => (
      <>
        <defs>
          <radialGradient id={`${uid}-g`}>
            <stop offset="0" style={{ stopColor: 'var(--k-glow)', stopOpacity: 1 }} />
            <stop offset="1" style={{ stopColor: 'var(--k-glow)', stopOpacity: 0 }} />
          </radialGradient>
          {Object.entries(SPEC.clips).map(([id, c]) => (
            <clipPath key={id} id={`${uid}-c-${id}`}>
              <ellipse cx={c.cx} cy={c.cy} rx={c.rx} ry={c.ry} />
            </clipPath>
          ))}
        </defs>
        {SPEC.parts.map((p) => partEl(p, uid))}
      </>
    ),
    [uid],
  );

  useEffect(() => {
    const svg = ref.current;
    if (!svg) return;
    const map: Record<string, SVGGElement> = {};
    svg.querySelectorAll<SVGGElement>('[data-part]').forEach((n) => (map[n.dataset.part as string] = n));
    parts.current = map;
  }, [tree]);

  useEffect(() => {
    const P = parts.current;
    const anims: Animation[] = [];
    const timers: ReturnType<typeof setTimeout>[] = [];
    let busy = false;
    for (const [id, n] of Object.entries(P)) {
      n.style.translate = '';
      n.style.rotate = '';
      n.style.scale = '';
      n.style.opacity = DEFAULTS[id]?.opacity != null ? String(DEFAULTS[id].opacity) : '';
    }
    const pose = (p: Pose | undefined) => {
      for (const [id, pr] of Object.entries(p ?? {})) {
        const n = P[id];
        if (n) for (const [k, v] of Object.entries(pr)) n.style[CSSP[k as PropName]] = cssValue(k as PropName, v!);
      }
    };
    const st = SPEC.states[state] ?? SPEC.states.idle;
    const cst = compose ? SPEC.states[compose] : undefined;
    if (cst) pose(cst.pose);
    pose(st.pose);
    if (ear !== null && P.ear) P.ear.style.rotate = `${ear}deg`;

    const reduced = rm || still;
    if (reduced) {
      if (!first.current && ref.current)
        try {
          ref.current.animate([{ opacity: 0 }, { opacity: 1 }], { duration: CROSSFADE });
        } catch {
          /* WAAPI unsupported */
        }
      first.current = false;
      return;
    }
    first.current = false;
    const run = (tracks: Track[], duration: number, loop: boolean) => {
      for (const tr of tracks) {
        if (ear !== null && tr.part === 'ear') continue;
        const n = P[tr.part];
        if (!n) continue;
        try {
          anims.push(
            n.animate(
              tr.keys.map(([o, v]) => ({ offset: o, [CSSP[tr.prop]]: cssValue(tr.prop, v), easing: EASE[tr.easing] })),
              { duration, iterations: loop ? Infinity : 1, fill: 'forwards' },
            ),
          );
        } catch {
          /* WAAPI unsupported */
        }
      }
    };
    if (cst) run(cst.tracks, cst.duration, cst.loop);
    run(st.tracks, st.duration, st.loop);

    const blinkOnce = (m: BlinkMode) => {
      if (busy) return;
      for (const id of SPEC.blink.parts) {
        const n = P[id];
        if (!n) continue;
        const from = n.style.translate || '0px 0px';
        try {
          n.animate([{ translate: from }, { translate: cssValue('translate', SPEC.blink.closed) }, { translate: from }], {
            duration: m.duration,
            easing: EASE[SPEC.blink.easing],
          });
        } catch {
          /* WAAPI unsupported */
        }
      }
    };
    const blinkLoop = (m: BlinkMode) => {
      timers.push(
        setTimeout(() => {
          blinkOnce(m);
          if (Math.random() < (m.double_chance ?? 0)) timers.push(setTimeout(() => blinkOnce(m), m.duration + (m.double_gap ?? 140)));
          blinkLoop(m);
        }, rnd(m.interval[0], m.interval[1])),
      );
    };
    const mode = cst && st.composes ? cst.blink : st.blink;
    const bm = SPEC.blink.modes[mode];
    if (bm) blinkLoop(bm);
    const evs = cst?.events ?? st.events;
    for (const ev of Object.values(evs ?? {})) {
      const loop = () => {
        timers.push(
          setTimeout(() => {
            busy = true;
            run(ev.tracks, ev.duration, false);
            timers.push(setTimeout(() => (busy = false), ev.duration));
            loop();
          }, rnd(ev.interval[0], ev.interval[1])),
        );
      };
      loop();
    }
    return () => {
      anims.forEach((a) => a.cancel());
      timers.forEach(clearTimeout);
    };
  }, [state, compose, rm, still, ear, tree]);

  function flick() {
    if (!tappable || rm || still || flicking.current) return;
    const it = SPEC.interactions.tap;
    const n = parts.current[it.part];
    if (!n) return;
    flicking.current = true;
    try {
      n.animate(
        it.keys.map(([o, v]) => ({ offset: o, rotate: `${v}deg`, easing: EASE[it.easing] })),
        { duration: it.duration, composite: 'add' },
      );
    } catch {
      /* WAAPI unsupported */
    }
    setTimeout(() => (flicking.current = false), it.duration);
  }

  return (
    <span
      className={`k-mascot${className ? ' ' + className : ''}`}
      style={{ width: size, height: size, ...glow }}
      onClick={flick}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <svg ref={ref} viewBox={SPEC.viewBox.join(' ')} width="100%" height="100%" aria-hidden="true" focusable="false">
        {tree}
      </svg>
    </span>
  );
}
