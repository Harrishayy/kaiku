'use client';

import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react';
import type { InsightNode } from '@contracts';
import { shortDay } from '@/lib/clinician';
import {
  type Hood,
  type Look,
  type MapLayout,
  type PlacedRow,
  VALUE_CH,
  anchorOf,
  buildHoods,
  fillGraph,
  fitLabel,
  hoodCaption,
  hoodNotable,
  hoodOnDay,
  latestDay,
  layoutHood,
  layoutMap,
  linkLines,
  linkPath,
  neighboursOf,
  nodeOnDay,
  personPath,
  rowLabel,
  rowValue,
} from '@/lib/graph-layout';
import { stateChip } from '@/lib/labels';
import type { DashData } from '../data';
import { Chip, type ChipTone, EmptyState, Glyph } from '../kit';

type Graph = DashData['view']['graph'];
type Node = Graph['nodes'][number];
type Edge = Graph['edges'][number];
type Day = Graph['days'][number];
type Change = Day['changes'][number];

const KIND: Record<InsightNode['kind'], string> = {
  person: 'Person',
  signal_group: 'Signal group',
  measure: 'Measure',
  activity: 'Activity',
  routine: 'Routine',
  care_action: 'Care action',
  shared_topic: 'Count only',
};
const LOOK_WORD: Record<Look, string> = {
  better: 'Better than usual',
  worse: 'Change from usual',
  similar: 'As usual',
  unknown: 'No usual yet',
  plain: 'Recorded',
  off: 'Nothing recorded',
  still: 'Count only',
};
const LOOK_CHIP: Record<Look, ChipTone> = { better: 'ok', worse: 'warn', similar: 'neutral', unknown: 'ins', plain: 'info', off: 'ins', still: 'info' };
const CHANGE_WORD: Record<Change['kind'], string> = {
  care: 'Care team',
  moved_away: 'Moved away from usual',
  came_back: 'Back within usual',
  better: 'Better than usual',
  missed: 'Routine missed',
  first: 'New on this day',
  kept: 'Routines kept',
};
const CHANGE_ORDER: Change['kind'][] = ['care', 'moved_away', 'came_back', 'better', 'missed', 'first', 'kept'];
/** links drawn between two nodes when one of them is in focus (the rows and the trunk already show the rest) */
const CROSS = new Set<Edge['rel']>(['followed', 'moved_together', 'after', 'helped', 'moved_first', 'kept_through', 'slipped_during', 'talked_about', 'produces', 'about']);
const ICON = { prev: 'M15 6l-6 6 6 6', next: 'M9 6l6 6-6 6', play: 'M8 5v14l11-7z', pause: 'M8 5v14M16 5v14', back: 'M15 6l-6 6 6 6' };

const weekday = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'short' });
const longDay = (date: string) => `${weekday(date)} ${shortDay(date)}`;
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

function useSize<T extends HTMLElement>(key: unknown) {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setSize((s) => (s.w === Math.round(el.clientWidth) && s.h === Math.round(el.clientHeight) ? s : { w: Math.round(el.clientWidth), h: Math.round(el.clientHeight) }));
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
    // the element can be swapped when the view changes
  }, [key]);
  return { ref, ...size };
}

/** The shape says what a node is; the fill says how it reads on the chosen day. */
function Mark({ kind, x = 0, r = 5 }: { kind: InsightNode['kind']; x?: number; r?: number }) {
  if (kind === 'activity') return <rect className="d-gmark" x={x - r} y={-r} width={r * 2} height={r * 2} rx={2.5} />;
  if (kind === 'routine')
    return (
      <>
        <rect className="d-gmark d-gmark-ring" x={x - r} y={-r} width={r * 2} height={r * 2} rx={3.5} />
        <circle className="d-gmark-dot" cx={x} r={1.8} />
      </>
    );
  if (kind === 'care_action') return <rect className="d-gmark" x={x - r + 0.5} y={-r + 0.5} width={r * 2 - 1} height={r * 2 - 1} rx={1.5} transform={`rotate(45 ${x} 0)`} />;
  if (kind === 'shared_topic') return <rect className="d-gmark" x={x - r - 1} y={-r + 1.5} width={r * 2 + 2} height={r * 2 - 3} rx={r - 1.5} />;
  return <circle className="d-gmark" cx={x} r={r} />;
}

function Scrubber({ days, date, onPick, stateOf, careDays, dense }: { days: Day[]; date: string; onPick: (d: string) => void; stateOf: Map<string, ChipTone>; careDays: Set<string>; dense: boolean }) {
  const i = Math.max(0, days.findIndex((d) => d.date === date));
  // every day is numbered when there is room; otherwise the chosen day and one in seven
  const numbered = (k: number) => !dense || k === i || (days.length - 1 - k) % 7 === 0;
  const most = Math.max(1, ...days.map((d) => d.away));
  const go = (k: number) => onPick(days[Math.max(0, Math.min(days.length - 1, k))].date);
  const onKey = (e: KeyboardEvent) => {
    const step = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, PageDown: -7, PageUp: 7 }[e.key];
    if (step) go(i + step);
    else if (e.key === 'Home') go(0);
    else if (e.key === 'End') go(days.length - 1);
    else return;
    e.preventDefault();
  };
  const today = days[i];
  return (
    <div
      className="d-scrub"
      role="slider"
      tabIndex={0}
      aria-label="Day of the record"
      aria-valuemin={0}
      aria-valuemax={days.length - 1}
      aria-valuenow={i}
      aria-valuetext={`${longDay(today.date)}: ${today.recorded ? plural(today.away, 'measure') + ' away from usual' : 'nothing recorded'}`}
      onKeyDown={onKey}
    >
      {days.map((d, k) => (
        <button
          key={d.date}
          type="button"
          tabIndex={-1}
          aria-hidden="true"
          className={`d-scrub-day${k === i ? ' is-on' : ''}${d.recorded ? '' : ' is-empty'} d-scrub-${stateOf.get(d.date) ?? 'none'}`}
          title={`${longDay(d.date)}: ${d.recorded ? plural(d.away, 'measure') + ' away from usual' : 'nothing recorded'}`}
          onClick={() => onPick(d.date)}
        >
          <span className="d-scrub-state" />
          <span className="d-scrub-well">
            <span className="d-scrub-bar" style={{ height: `${Math.round((d.away / most) * 100)}%` }} />
            {careDays.has(d.date) && <span className="d-scrub-care" />}
          </span>
          <span className="d-scrub-num">{numbered(k) ? Number(d.date.slice(8)) : ''}</span>
        </button>
      ))}
    </div>
  );
}

export function GraphPanel({ data, onMetric, onDay, maximised, onMaximise }: { data: DashData; onMetric: (m: string) => void; onDay?: (d: string) => void; maximised: boolean; onMaximise: () => void }) {
  const graph = useMemo(() => fillGraph(data.view.graph), [data.view.graph]);
  const hasGraph = graph.nodes.length > 1;
  const { person, hoods } = useMemo(() => buildHoods(graph), [graph]);
  const days = graph.days;
  const latest = useMemo(() => latestDay(days), [days]);
  const [chosen, setChosen] = useState<string | null>(null);
  const date = chosen && days.some((d) => d.date === chosen) ? chosen : latest;
  const [picked, setPicked] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [level, setLevel] = useState<'overview' | 'nodes' | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [keyOpen, setKeyOpen] = useState<boolean | null>(null);
  const root = useSize<HTMLDivElement>(hasGraph);
  const mode = root.w >= 980 ? 'wide' : root.w >= 560 ? 'mid' : 'tile';
  const zoomed = mode !== 'wide' && zoom ? (hoods.find((x) => x.id === zoom) ?? null) : null;
  const view = mode === 'wide' ? (level ?? 'nodes') : zoomed ? 'hood' : mode === 'mid' && level === 'nodes' ? 'nodes' : 'overview';
  const canvas = useSize<HTMLDivElement>(`${hasGraph}:${mode}:${view}`);

  useEffect(() => {
    setPicked(null);
    setZoom(null);
    setChosen(null);
  }, [data.patient.id]);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      setChosen((cur) => {
        const i = days.findIndex((d) => d.date === (cur ?? latest));
        if (i < 0 || i >= days.length - 1) {
          setPlaying(false);
          return cur;
        }
        return days[i + 1].date;
      });
    }, 1200);
    return () => clearInterval(t);
  }, [playing, days, latest]);

  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);
  const layout = useMemo<MapLayout | null>(() => {
    if (view === 'overview' || canvas.w === 0) return null;
    if (view === 'hood') return zoomed ? layoutHood(zoomed, canvas.w) : null;
    return layoutMap(hoods, canvas.w, canvas.h);
  }, [view, hoods, zoomed, canvas.w, canvas.h]);
  const stateOf = useMemo(() => new Map(data.view.stateHistory.map((s) => [s.date, stateChip(s.state, s.agreement).tone])), [data.view.stateHistory]);
  const careDays = useMemo(() => new Set(graph.nodes.filter((n) => n.kind === 'care_action').flatMap((n) => n.days.map((d) => d.date))), [graph]);

  if (!hasGraph)
    return (
      <EmptyState title="Nothing learned yet">
        {graph.note || 'Activities, routines and what helps appear here as days are recorded.'}
      </EmptyState>
    );

  const today = days.find((d) => d.date === date) ?? null;
  const changes = today?.changes ?? [];
  const changed = new Map(changes.filter((c) => c.kind !== 'kept').map((c) => [c.node, c.kind]));
  const nameOf = (id: string) => byId.get(id)?.label ?? id;
  const sel = picked ? (byId.get(picked) ?? null) : null;
  const active = picked ?? hover;
  const near = picked && view !== 'hood' ? neighboursOf(picked, graph.edges) : null;
  const dim = (id: string) => Boolean(near && !near.has(id));
  const pick = (id: string) => setPicked((cur) => (cur === id ? null : id));
  const pickDay = (d: string) => {
    setPlaying(false);
    setChosen(d);
  };
  const step = (delta: number) => {
    const i = days.findIndex((d) => d.date === date);
    if (i >= 0) pickDay(days[Math.max(0, Math.min(days.length - 1, i + delta))].date);
  };
  const openNode = (id: string) => {
    setPicked(id);
    const hood = hoods.find((x) => x.nodes.some((n) => n.id === id));
    if (mode === 'wide') setLevel('nodes');
    else if (hood && view !== 'nodes') setZoom(hood.id);
  };
  const openHood = (id: string) => {
    if (mode === 'wide') setLevel('nodes');
    else setZoom(id);
  };
  const hoodDay = (h: Hood) => hoodOnDay(h, date, graph.edges);
  const metricOf = (id: string) => (id.startsWith('measure:') ? id.slice('measure:'.length) : null);
  const total = hoods.reduce((s, x) => ({ away: s.away + hoodDay(x).away, scored: s.scored + hoodDay(x).scored }), { away: 0, scored: 0 });
  const dayState = date ? data.view.stateHistory.find((s) => s.date === date) : null;
  const dayIndex = date ? days.findIndex((d) => d.date === date) : -1;

  const nodeLabel = (n: Node) => {
    const s = nodeOnDay(n, date);
    const on = date ? ` On ${longDay(date)}: ${s.lit ? s.text || LOOK_WORD[s.look] : 'nothing recorded'}.` : '';
    return `${KIND[n.kind]}: ${n.label}.${on}`;
  };
  const nodeProps = (n: Node) => ({
    role: 'button' as const,
    tabIndex: 0,
    'aria-pressed': picked === n.id,
    'aria-label': nodeLabel(n),
    onClick: () => pick(n.id),
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        pick(n.id);
      }
    },
    // a click selects without moving keyboard focus, so the focus ring stays a keyboard cue
    onMouseDown: (e: { preventDefault: () => void }) => e.preventDefault(),
    onMouseEnter: () => setHover(n.id),
    onMouseLeave: () => setHover(null),
    onFocus: () => setHover(n.id),
    onBlur: () => setHover(null),
  });
  const nodeClass = (n: Node, extra = '') => {
    const s = nodeOnDay(n, date);
    const mark = changed.get(n.id);
    return `d-gnode d-gk-${n.kind} d-look-${s.look}${s.lit ? ' is-lit' : ''}${picked === n.id ? ' is-picked' : ''}${dim(n.id) ? ' is-dim' : ''}${mark ? ` is-changed d-chg-${mark}` : ''}${extra}`;
  };

  const drawRow = (r: PlacedRow, pitch: number) => {
    const s = nodeOnDay(r.node, date);
    const left = r.side === 'left';
    const value = r.chip ? '' : rowValue(r.node, s.value);
    const chip = r.chip ? nodeOnDay(r.chip, date) : null;
    const labelW = r.labelW;
    const from = left ? r.labelX - 4 : r.markX - 10;
    const to = r.chip && r.valueW ? r.valueX - 3 : left ? r.markX + 10 : r.endX;
    return (
      <g key={r.node.id}>
        <g className={nodeClass(r.node)} transform={`translate(0,${r.y})`} {...nodeProps(r.node)}>
          <rect className="d-gnode-hit" x={from} y={-pitch / 2 + 1} width={Math.max(0, to - from)} height={pitch - 2} rx={6} />
          {changed.has(r.node.id) && <circle className="d-ghalo" cx={r.markX} r={9} />}
          <Mark kind={r.node.kind} x={r.markX} />
          <svg x={r.labelX} y={-pitch / 2} width={labelW} height={pitch}>
            <text className="d-gname" y={pitch / 2} dominantBaseline="central">
              {rowLabel(r.node.label, labelW)}
              <title>{r.node.label}</title>
            </text>
          </svg>
          {!r.chip && r.valueW > 0 && value && (
            <svg x={r.valueX} y={-pitch / 2} width={r.valueW} height={pitch}>
              <text className="d-gvalue" x={r.valueW} y={pitch / 2} textAnchor="end" dominantBaseline="central">
                {fitLabel(value, r.valueW, VALUE_CH)}
              </text>
            </svg>
          )}
        </g>
        {r.chip && r.valueW > 0 && chip && (
          <g className={nodeClass(r.chip, ' is-chip')} transform={`translate(0,${r.y})`} {...nodeProps(r.chip)}>
            <rect className="d-gnode-hit" x={r.valueX - 2} y={-pitch / 2 + 1} width={r.valueW + 4} height={pitch - 2} rx={6} />
            {changed.has(r.chip.id) && <circle className="d-ghalo" cx={r.chipX} r={9} />}
            <Mark kind="routine" x={r.chipX} />
            <text className="d-gvalue" x={r.valueX + r.valueW} textAnchor="end" dominantBaseline="central">
              {fitLabel(chip.value || '', r.valueW - (r.chipX - r.valueX) - 10, VALUE_CH)}
            </text>
          </g>
        )}
      </g>
    );
  };

  /** the tree inside a neighbourhood: a trunk on the side facing the person, a tick per row, an elbow to a child */
  const drawTree = (lay: MapLayout) =>
    lay.hoods.map((p) => {
      const rows = lay.rows.filter((r) => r.hood === p.hood.id);
      const dir = p.side === 'left' ? -1 : 1;
      return (
        <g key={p.hood.id} className={near && !p.hood.nodes.some((n) => near.has(n.id)) ? 'is-dim' : undefined}>
          {rows.length > 0 && <path className="d-gtrunk" d={`M${p.trunkX},${Math.min(p.port.y, p.trunkTop)}V${Math.max(p.port.y, p.trunkBottom)}`} />}
          {rows.map((r) => {
            if (r.depth === 0) return <path key={r.node.id} className={`d-gtick d-gtick-${r.node.kind}`} d={`M${p.trunkX},${r.y}H${r.markX - dir * 7}`} />;
            const parent = rows.find((x) => x.node.id === r.parent);
            if (!parent) return null;
            const on = active === r.node.id || active === parent.node.id;
            return <path key={r.node.id} className={`d-gtick d-gtick-child d-gtick-${r.node.kind}${on ? ' is-on' : ''}`} d={`M${parent.markX},${parent.y + 7}V${r.y - 4}Q${parent.markX},${r.y} ${parent.markX + dir * 4},${r.y}H${r.markX - dir * 7}`} />;
          })}
        </g>
      );
    });

  /** links between nodes: what the person reported as helping is always there, the rest when a node is in focus
   *  (a day's returns after a care action are counted in the caption of Care and listed beside the picture);
   *  labels only for the node in focus */
  const drawLinks = (lay: MapLayout) => {
    const lines: { key: string; cls: string; d: string; width?: number }[] = [];
    const tags = new Map<string, { x: number; y: number; anchor: 'start' | 'end'; words: string[] }>();
    const inHood = new Map(lay.rows.flatMap((r) => [[r.node.id, r.hood] as const, ...(r.chip ? [[r.chip.id, r.hood] as const] : [])]));
    for (const e of graph.edges) {
      if (!CROSS.has(e.rel)) continue;
      const mine = Boolean(active) && (e.src === active || e.dst === active);
      const always = e.rel === 'helped';
      if (!mine && !always) continue;
      // inside one neighbourhood the tree already draws these two
      if ((e.rel === 'produces' || e.rel === 'about') && inHood.get(e.src) === inHood.get(e.dst)) continue;
      const rough = anchorOf(lay, e.dst);
      const a = anchorOf(lay, e.src, rough ?? undefined);
      const b = a && anchorOf(lay, e.dst, a);
      if (!a || !b) continue;
      const d = a.out === 0 ? personPath(lay, b) : b.out === 0 ? personPath(lay, a) : linkPath(a, b);
      const elsewhen = mine && Boolean(date) && e.on.length > 0 && !e.on.includes(date as string);
      lines.push({ key: `${e.src}>${e.dst}:${e.rel}`, cls: `d-glink d-glink-${e.rel}${mine ? ' is-on' : ''}${elsewhen ? ' is-elsewhen' : ''}`, d, width: e.rel === 'helped' ? 1.5 + e.weight * 3 : undefined });
      if (mine && lay.gap >= 56) {
        const other = e.src === active ? b : a;
        const id = e.src === active ? e.dst : e.src;
        if (other.out === 0) continue;
        const word = e.tag || (e.rel === 'helped' ? plural(e.evidence, 'try', 'tries') : e.rel === 'talked_about' ? `${e.evidence}×` : '');
        if (!word) continue;
        const t = tags.get(id) ?? { x: other.x + other.out * 14, y: other.y, anchor: other.out > 0 ? 'start' : 'end', words: [] };
        if (!t.words.includes(word)) t.words.push(word);
        tags.set(id, t);
      }
    }
    return (
      <>
        <g className={near ? 'd-glinks has-focus' : 'd-glinks'}>
          {lines.map((l) => (
            <path key={l.key} className={l.cls} d={l.d} strokeWidth={l.width} />
          ))}
        </g>
        {/* a node with many links is read in the column beside the picture; a few are labelled where they land */}
        {tags.size <= 8 &&
          [...tags].map(([id, t]) => (
            <text key={id} className="d-gtag" x={t.x} y={t.y} textAnchor={t.anchor} dominantBaseline="central">
              {t.words.join(' · ')}
            </text>
          ))}
      </>
    );
  };

  const moved = changes.filter((c) => c.kind === 'moved_away').length;
  const back = changes.filter((c) => c.kind === 'came_back' || c.kind === 'better').length;
  const missed = changes.filter((c) => c.kind === 'missed').length;
  const brief = [moved && `${moved} moved away`, back && `${back} back`, missed && `${missed} missed`, careDays.has(date ?? '') && 'care action'].filter(Boolean).join(' · ');
  const awayLine = total.scored ? (total.away ? `${total.away} of ${total.scored} away` : 'within usual') : 'no usual yet';

  let picture = null;
  if (view === 'overview') {
    // how many nodes a cell can name under its summary: none in a small panel
    const cellH = (canvas.h - 16) / 3;
    const room = mode === 'tile' ? 0 : Math.max(0, Math.floor((cellH - 74) / 18));
    const cell = (place: Hood['place']) => {
      const hood = hoods.find((x) => x.place === place);
      if (!hood) return <span key={place} className="d-gcell is-none" aria-hidden="true" />;
      const s = hoodDay(hood);
      const notable = room ? hoodNotable(hood, date) : [];
      const shown = notable.slice(0, notable.length > room ? room - 1 : room);
      return (
        <button key={place} type="button" className={`d-gcell${s.away ? ' is-away' : ''}${s.lit ? '' : ' is-quiet'}${place === 'x' ? ' d-gcell-wide' : ''}`} aria-label={`${hood.label}: ${s.text}. Show its nodes.`} onClick={() => openHood(hood.id)}>
          <span className="d-gcell-name">{mode === 'tile' ? hood.short : hood.label}</span>
          <span className="d-gcell-sum">{mode === 'tile' ? s.brief : s.text}</span>
          {shown.length > 0 && (
            <span className="d-gcell-list">
              {shown.map(({ node, state }) => (
                <span key={node.id} className="d-gcell-row">
                  <span className={`d-gdot d-gk-${node.kind} d-look-${state.look}`} />
                  <span className="d-gcell-what">{node.label.replace(/^Talked about: /, 'Theme: ').split(' · ')[0]}</span>
                  <span className="d-gcell-val">{state.value && !['came up', 'logged', 'recorded'].includes(state.value) ? state.value : ''}</span>
                </span>
              ))}
              {notable.length > shown.length && <span className="d-gcell-more">and {notable.length - shown.length} more</span>}
            </span>
          )}
          {(mode !== 'tile' || cellH >= 60) && (
            <span className="d-gdots" aria-hidden="true">
              {hood.nodes.slice(0, 14).map((n) => (
                <span key={n.id} className={`d-gdot d-gk-${n.kind} d-look-${nodeOnDay(n, date).look}`} />
              ))}
            </span>
          )}
        </button>
      );
    };
    picture = (
      <div className="d-gover" role="group" aria-label="The neighbourhoods of the record around the person">
        {(['nw', 'n', 'ne', 'w'] as const).map(cell)}
        <div className="d-gcell d-gcell-person">
          {mode !== 'tile' && <span className="d-gperson-dot" aria-hidden="true" />}
          <span className="d-gcell-name">{person?.label ?? data.patient.display_name}</span>
          {date && <span className="d-gcell-sum">{mode === 'tile' ? awayLine : longDay(date)}</span>}
        </div>
        {(['e', 'sw', 's', 'se'] as const).map(cell)}
        {hoods.some((x) => x.place === 'x') && cell('x')}
      </div>
    );
  } else if (layout) {
    const single = view === 'hood';
    picture = (
      <svg className="d-gmap" width={layout.w} height={layout.h} role="group" aria-label={single ? 'The nodes of this neighbourhood. Select one to see what it is linked to.' : 'The record as a map: the person in the middle, neighbourhoods around. Select a node to see what it is linked to.'}>
        {!single &&
          layout.hoods.map((p) => {
            const s = hoodDay(p.hood);
            const full = `${p.hood.label} · ${s.text}`;
            const cap = hoodCaption(p.hood, s, p.w - 16);
            return (
              <g key={p.hood.id} className={`d-ghood${s.away ? ' is-away' : ''}${near && !p.hood.nodes.some((n) => near.has(n.id)) ? ' is-dim' : ''}`}>
                <rect className="d-ghood-box" x={p.x} y={p.y} width={p.w} height={p.h} rx={10} />
                <svg x={p.x + 8} y={p.y} width={p.w - 16} height={26}>
                  <text className="d-ghood-cap" y={14} dominantBaseline="central">
                    <tspan className="d-ghood-name">{cap.name}</tspan>
                    <tspan className="d-ghood-sum" dx={6}>
                      {cap.sum}
                    </tspan>
                    <title>{full}</title>
                  </text>
                </svg>
              </g>
            );
          })}
        {!single && layout.person && (
          <g className="d-gspokes">
            {layout.hoods.map((p) => (
              <path key={p.hood.id} className="d-gspoke" d={p.col === 1 ? `M${layout.person!.x},${layout.person!.y}V${p.port.y}` : personPath(layout, p.port)} />
            ))}
          </g>
        )}
        {drawTree(layout)}
        {!single && drawLinks(layout)}
        {layout.rows.map((r) => drawRow(r, layout.pitch))}
        {!single && layout.person && person && (
          <g className={`d-gnode d-gperson${picked === person.id ? ' is-picked' : ''}`} transform={`translate(${layout.person.x},${layout.person.y})`} {...nodeProps(person)}>
            <circle className="d-gperson-ring" r={15} />
            <circle className="d-gperson-mark" r={9} />
            <text className="d-gname d-gperson-name" y={25} textAnchor="middle" dominantBaseline="central">
              {fitLabel(person.label, 150)}
            </text>
          </g>
        )}
      </svg>
    );
  }

  // ---- beside the picture: the chosen day, or the node in focus
  // a tag every item of a group shares ("1 day after the care team follow-up") is said once, under the heading
  const groups = CHANGE_ORDER.map((kind) => {
    const items = changes.filter((c) => c.kind === kind);
    const tag = items.length && items[0].tag && items.every((c) => c.tag === items[0].tag) ? items[0].tag : '';
    return { kind, items, tag };
  }).filter((g) => g.items.length);
  /** one change in the list: the node and its reading on one line; under it only what the heading does not say */
  const changeLine = (c: Change, tagSaid: boolean) => {
    const node = byId.get(c.node);
    const [name, when] = (node?.label ?? c.node).replace(/^Talked about: /, 'Theme: ').split(' · ');
    const value = node ? rowValue(node, nodeOnDay(node, date).value) : '';
    const tag = tagSaid ? '' : c.tag;
    if (c.kind === 'missed') return { name, value: when ?? '', more: tag };
    if (c.kind === 'came_back') return { name, value, more: tag };
    // the sentence without the reading it starts with: "below their usual 3.2 1/s"
    const rest = value && (c.text.startsWith(`${value}, `) || c.text.startsWith(`${value}; `)) ? c.text.slice(value.length + 2) : c.text;
    return { name: c.kind === 'care' ? (node?.label ?? name) : name, value: c.kind === 'care' ? '' : value, more: [rest, tag].filter(Boolean).join(' · ') };
  };
  const lines = sel ? linkLines(sel.id, graph.edges) : [];
  const selDay = sel ? nodeOnDay(sel, date) : null;
  const selHood = sel ? hoods.find((x) => x.nodes.some((n) => n.id === sel.id)) : null;
  const names = (ids: string[], brief = false) =>
    ids.map((id, i) => (
      <span key={id}>
        {i > 0 && (i === ids.length - 1 ? ' and ' : ', ')}
        <button type="button" className="d-link" onClick={() => openNode(id)}>
          {brief ? nameOf(id).split(' · ')[0] : nameOf(id)}
        </button>
      </span>
    ));
  const nodeCard = sel && selDay && (
    <div className="d-gcard" role="status">
      <div className="d-row-head">
        <button type="button" className="d-link d-gback" onClick={() => setPicked(null)}>
          <Glyph d={ICON.back} size={12} /> The day
        </button>
        {metricOf(sel.id) && data.series.some((s) => s.metric === metricOf(sel.id)) && (
          <button type="button" className="d-link" onClick={() => onMetric(metricOf(sel.id) as string)}>
            Show in Trends
          </button>
        )}
      </div>
      <div className="d-row-head">
        <span className="d-row-title">{sel.label}</span>
        {sel.kind !== 'person' && <Chip tone={LOOK_CHIP[selDay.look]}>{LOOK_WORD[selDay.look]}</Chip>}
      </div>
      <span className="d-meta">
        {KIND[sel.kind]}
        {selHood ? ` · ${selHood.label}` : ''} · backed by {plural(sel.evidence, 'record')}
      </span>
      {date && sel.kind !== 'person' && (
        <p className="d-gday-line">
          <strong>{longDay(date)}:</strong> {selDay.lit ? selDay.text || 'recorded' : sel.days.length ? 'nothing recorded' : 'not dated; a count over the record'}
          {selDay.lit ? '.' : ''}
        </p>
      )}
      {sel.days.length > 0 && days.length > 1 && (
        <div className="d-gstrip" role="group" aria-label={`${sel.label}, day by day`}>
          {days.map((d) => {
            const s = nodeOnDay(sel, d.date);
            return <button key={d.date} type="button" tabIndex={-1} className={`d-gstrip-day d-look-${s.look}${d.date === date ? ' is-on' : ''}`} title={`${longDay(d.date)}: ${s.lit ? s.text || 'recorded' : 'nothing recorded'}`} aria-label={`${longDay(d.date)}: ${s.lit ? s.text || 'recorded' : 'nothing recorded'}`} onClick={() => pickDay(d.date)} />;
          })}
        </div>
      )}
      {sel.detail && <p className="d-gdetail">{sel.detail}</p>}
      {lines.length > 0 && (
        <ul className="d-bullets d-glines">
          {lines.map((l) => (
            <li key={l.key}>
              {l.lead}
              {l.others.length > 0 && <> {names(l.others)}</>}
              {l.tail ? ` ${l.tail}` : ''}.
            </li>
          ))}
        </ul>
      )}
    </div>
  );
  const dayCard = (
    <div className="d-gday">
      {date ? (
        <>
          <div className="d-row-head">
            <span className="d-row-title">{longDay(date)}</span>
            <span className="d-meta">
              Day {dayIndex + 1} of {days.length}
              {date === latest ? ' · latest with records' : ''}
            </span>
          </div>
          {dayState && (
            <span className="d-gday-state d-meta">
              Consensus on this day <Chip tone={stateChip(dayState.state, dayState.agreement).tone}>{stateChip(dayState.state, dayState.agreement).label}</Chip>
            </span>
          )}
          <p className="d-gday-line">{total.scored ? (total.away ? `${total.away} of ${total.scored} measures away from their usual.` : `All ${total.scored} measures within their usual.`) : today?.recorded ? 'No measure has a personal usual yet on this day.' : 'Nothing recorded on this day.'}</p>
          {groups.length > 0 ? (
            <div className="d-gchanges" aria-label={`What changed on ${longDay(date)}`}>
              {groups.map((g) =>
                g.kind === 'kept' ? (
                  <p key={g.kind} className="d-meta">
                    {CHANGE_WORD.kept}: {names(g.items.map((c) => c.node), true)}.
                  </p>
                ) : (
                  <div key={g.kind} className={`d-gchange d-chg-${g.kind}`}>
                    <span className="d-gchange-head">
                      <span className="d-gchange-mark" aria-hidden="true" />
                      {CHANGE_WORD[g.kind]}
                      {g.items.length > 1 ? ` · ${g.items.length}` : ''}
                    </span>
                    {g.tag && <span className="d-meta d-gchange-tag">{cap(g.tag)}</span>}
                    <ul>
                      {g.items.map((c) => {
                        const line = changeLine(c, Boolean(g.tag));
                        return (
                          <li key={`${c.node}:${c.kind}`}>
                            <button type="button" className="d-gchange-item" title={cap(c.text)} onClick={() => openNode(c.node)}>
                              <span className="d-gchange-row">
                                <span className="d-gchange-name">{line.name}</span>
                                {line.value && <span className="d-gchange-val">{line.value}</span>}
                              </span>
                              {line.more && <span className="d-meta">{cap(line.more)}</span>}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ),
              )}
            </div>
          ) : (
            <p className="d-meta">Nothing changed against the day before.</p>
          )}
          {onDay && data.view.days.some((d) => d.date === date) && (
            <button type="button" className="d-link" onClick={() => onDay(date)}>
              Open this day in the Daily account
            </button>
          )}
        </>
      ) : (
        <p className="d-meta">Select a node to see what it rests on. Day-by-day detail appears once the full record view is available.</p>
      )}
    </div>
  );
  // open beside the map, under the day (a long day pushes it down the column); a click keeps it as the reader left it
  const keyShown = keyOpen ?? mode === 'wide';
  const key = (
    <details className="d-gkey" open={keyShown}>
      <summary
        onClick={(e) => {
          e.preventDefault();
          setKeyOpen(!keyShown);
        }}
      >
        Key
      </summary>
      <ul className="d-gkey-list" aria-label="Graph key">
        <li><svg width="14" height="14" className="d-gnode d-gk-measure d-look-similar is-lit"><g transform="translate(7,7)"><Mark kind="measure" /></g></svg>Measure, as usual</li>
        <li><svg width="14" height="14" className="d-gnode d-gk-measure d-look-worse is-lit"><g transform="translate(7,7)"><Mark kind="measure" /></g></svg>Change from usual</li>
        <li><svg width="14" height="14" className="d-gnode d-gk-measure d-look-better is-lit"><g transform="translate(7,7)"><Mark kind="measure" /></g></svg>Better than usual</li>
        <li><svg width="14" height="14" className="d-gnode d-gk-measure d-look-unknown is-lit"><g transform="translate(7,7)"><Mark kind="measure" /></g></svg>No usual yet</li>
        <li><svg width="14" height="14" className="d-gnode d-gk-activity d-look-plain is-lit"><g transform="translate(7,7)"><Mark kind="activity" /></g></svg>Activity done</li>
        <li><svg width="14" height="14" className="d-gnode d-gk-routine d-look-similar is-lit"><g transform="translate(7,7)"><Mark kind="routine" /></g></svg>Routine kept</li>
        <li><svg width="14" height="14" className="d-gnode d-gk-routine d-look-worse is-lit"><g transform="translate(7,7)"><Mark kind="routine" /></g></svg>Routine missed</li>
        <li><svg width="14" height="14" className="d-gnode d-gk-care_action d-look-plain is-lit"><g transform="translate(7,7)"><Mark kind="care_action" /></g></svg>Care action</li>
        <li><svg width="16" height="14" className="d-gnode d-gk-shared_topic d-look-plain is-lit"><g transform="translate(8,7)"><Mark kind="shared_topic" /></g></svg>Theme, count only</li>
        <li><svg width="14" height="14" className="d-gnode d-gk-measure d-look-off"><g transform="translate(7,7)"><Mark kind="measure" /></g></svg>Nothing that day</li>
        <li><svg width="22" height="14"><path className="d-gtick d-gtick-activity" d="M1,7H21" /></svg>Does</li>
        <li><svg width="22" height="14"><path className="d-gtick d-gtick-child d-gtick-measure" d="M1,7H21" /></svg>Produces</li>
        <li><svg width="22" height="14"><path className="d-gtick d-gtick-shared_topic" d="M1,7H21" /></svg>Talked about</li>
        <li><svg width="22" height="14"><path className="d-glink d-glink-helped" d="M1,7H21" strokeWidth={3} /></svg>Reported to help</li>
        <li><svg width="22" height="14"><path className="d-glink d-glink-followed is-on" d="M1,7H21" /></svg>Followed, +1 day</li>
        <li><svg width="22" height="14"><path className="d-glink d-glink-moved_together is-on" d="M1,7H21" /></svg>Away together</li>
        <li><svg width="22" height="14"><path className="d-glink d-glink-after is-on" d="M1,7H21" /></svg>Back after care action</li>
      </ul>
      <p className="d-meta">A ring around a mark: it changed on this day. Links show order in time or what the person reported, never cause.</p>
    </details>
  );

  return (
    <div className={`d-graph is-${mode} is-v-${view}${maximised ? ' is-max' : ''}`} ref={root.ref}>
      {days.length > 0 && date && (
        <div className="d-gbar">
          <div className="d-gbar-ctl">
            <button type="button" className="d-tool" aria-label="Previous day" title="Previous day" disabled={dayIndex <= 0} onClick={() => step(-1)}>
              <Glyph d={ICON.prev} />
            </button>
            {mode !== 'tile' && (
              <button
                type="button"
                className="d-tool"
                aria-label={playing ? 'Pause the replay' : 'Replay the record day by day'}
                title={playing ? 'Pause' : 'Replay day by day'}
                aria-pressed={playing}
                onClick={() => {
                  if (!playing && dayIndex >= days.length - 1) setChosen(days[0].date);
                  setPlaying(!playing);
                }}
              >
                <Glyph d={playing ? ICON.pause : ICON.play} />
              </button>
            )}
            <button type="button" className="d-tool" aria-label="Next day" title="Next day" disabled={dayIndex >= days.length - 1} onClick={() => step(1)}>
              <Glyph d={ICON.next} />
            </button>
          </div>
          <Scrubber days={days} date={date} onPick={pickDay} stateOf={stateOf} careDays={careDays} dense={mode !== 'wide' || days.length > 21} />
          <div className="d-gbar-end">
            <span className="d-gbar-date" aria-live="polite">
              {mode === 'tile' ? shortDay(date) : longDay(date)}
            </span>
            {date !== latest && latest && mode !== 'tile' && (
              <button type="button" className="d-btn d-btn-quiet" onClick={() => pickDay(latest)}>
                Latest
              </button>
            )}
            {mode !== 'tile' && (
              <div className="d-seg" role="group" aria-label="Zoom">
                <button
                  type="button"
                  aria-pressed={view === 'overview'}
                  onClick={() => {
                    setLevel('overview');
                    setZoom(null);
                  }}
                >
                  Overview
                </button>
                <button
                  type="button"
                  aria-pressed={view === 'nodes'}
                  onClick={() => {
                    setLevel('nodes');
                    setZoom(null);
                  }}
                >
                  Nodes
                </button>
              </div>
            )}
          </div>
        </div>
      )}
      <div className="d-gmain">
        <div className="d-gstage">
          {zoomed && (
            <div className="d-gzoom">
              <button type="button" className="d-link d-gback" onClick={() => { setZoom(null); setPicked(null); }}>
                <Glyph d={ICON.back} size={12} /> All
              </button>
              <span className="d-row-title">{mode === 'tile' ? zoomed.short : zoomed.label}</span>
              <span className="d-meta">{mode === 'tile' ? hoodDay(zoomed).brief : hoodDay(zoomed).text}</span>
            </div>
          )}
          <div className={`d-gcanvas is-${view}`} ref={canvas.ref}>
            {picture}
          </div>
          {mode === 'tile' && view === 'hood' && (
            <div className="d-gfoot">
              {sel && selDay ? (
                <span className="d-gfoot-text" title={sel.detail ?? undefined}>
                  <strong>{sel.label.replace(/^Talked about: /, 'Theme: ').split(' · ')[0]}:</strong> {selDay.lit && selDay.text ? selDay.text : sel.days.length ? (selDay.lit ? 'recorded' : 'nothing recorded on this day') : sel.detail || 'a count over the record'}
                </span>
              ) : (
                <span className="d-gfoot-text d-meta">Select a node for its day</span>
              )}
              {!maximised && (
                <button type="button" className="d-link" onClick={onMaximise} aria-label="Open the full map of the knowledge graph">
                  Full map
                </button>
              )}
            </div>
          )}
          {/* a small panel names themes and notebook counts only inside a neighbourhood: the privacy note is there */}
          {mode === 'tile' && view === 'hood' && <p className="d-meta d-gnote d-gnote-tile">{graph.note}</p>}
        </div>
        {mode !== 'tile' && (
          <aside className="d-gside" aria-label="The chosen day and the node in focus">
            <div className="d-gside-body">
              {nodeCard || dayCard}
              {key}
            </div>
            <p className="d-meta d-gnote">{graph.note}</p>
          </aside>
        )}
      </div>
    </div>
  );
}
