'use client';

/**
 * "What Kaiku has learned" — the knowledge graph (GET /v1/me/graph, /v1/patients/{id}/graph) as a calm map in
 * columns: what the person TOLD Kaiku (what helps, people, places, likes, plans) on the left → the person in the
 * middle → what they DO (activities) → the rhythms (routines) of each activity on the right. Deterministic layout
 * (no physics, no randomness): one label per row, so labels never collide and the same graph always draws the same
 * picture. Click / Enter on a node → its links, labelled, in the panel; its edges light up with relation words.
 * Node size = evidence (sqrt).
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { GraphEdge, GraphNode, KnowledgeGraph } from '@contracts';

type NodeType = GraphNode['type'];
type Rel = GraphEdge['rel'];

export type GraphWords = {
  types: Record<NodeType, string>;
  rel: Record<Rel, string>;
  /** the same relation read from the other end ("done by", "rhythm"), for incoming links in the panel */
  relIn: Record<Rel, string>;
  evidence: (n: number) => string;
  links: string;
  hint: string;
  none: string;
  me: string;
};

const TOLD: NodeType[] = ['helper', 'person', 'place', 'like', 'plan'];
const LEGEND: NodeType[] = ['activity', 'routine', ...TOLD];
const W = 860;
const ROW = 46;
const GAP = 16;
const PAD = 34;
const X = { told: 236, me: 380, act: 560, routine: 690 };

type Col = 'told' | 'me' | 'act' | 'routine';
type P = { x: number; y: number; col: Col };

function layout(nodes: GraphNode[], edges: GraphEdge[]): { pos: Map<number, P>; h: number } {
  const pos = new Map<number, P>();
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const ev = (a: GraphNode, b: GraphNode) => b.evidence - a.evidence || a.label.localeCompare(b.label);
  const routinesOf = new Map<number, GraphNode[]>();
  const attached = new Set<number>();
  for (const e of edges)
    if (e.rel === 'of' && byId.get(e.src)?.type === 'routine' && byId.get(e.dst)?.type === 'activity') {
      routinesOf.set(e.dst, [...(routinesOf.get(e.dst) ?? []), byId.get(e.src)!]);
      attached.add(e.src);
    }
  // right side: one row per activity (or per routine when it has several), then loose routines (e.g. sleep)
  const right: { act?: GraphNode; routines: GraphNode[] }[] = nodes
    .filter((n) => n.type === 'activity')
    .sort(ev)
    .map((a) => ({ act: a, routines: routinesOf.get(a.id) ?? [] }));
  nodes.filter((n) => n.type === 'routine' && !attached.has(n.id)).forEach((r) => right.push({ routines: [r] }));
  const rightRows = right.reduce((s, r) => s + Math.max(1, r.routines.length), 0);
  // left side: told things grouped by type, a small gap between groups
  const left = TOLD.map((t) => nodes.filter((n) => n.type === t).sort(ev)).filter((g) => g.length);
  const leftH = left.reduce((s, g) => s + g.length * ROW, 0) + Math.max(0, left.length - 1) * GAP;
  const rightH = rightRows * ROW;
  const inner = Math.max(leftH, rightH, ROW * 3);
  const h = inner + PAD * 2;
  let y = PAD + (inner - leftH) / 2 + ROW / 2;
  for (const g of left) {
    g.forEach((n) => {
      pos.set(n.id, { x: X.told, y, col: 'told' });
      y += ROW;
    });
    y += GAP;
  }
  y = PAD + (inner - rightH) / 2;
  for (const r of right) {
    const span = Math.max(1, r.routines.length) * ROW;
    if (r.act) pos.set(r.act.id, { x: X.act, y: y + span / 2 + 6, col: 'act' });
    r.routines.forEach((rt, k) => pos.set(rt.id, { x: X.routine, y: y + ROW * k + ROW / 2 + 6, col: 'routine' }));
    y += span;
  }
  const me = nodes.find((n) => n.type === 'me');
  if (me) pos.set(me.id, { x: X.me, y: h / 2, col: 'me' });
  return { pos, h };
}

const short = (s: string, n = 30) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

export function LearnedGraph({ graph, words }: { graph: KnowledgeGraph; words: GraphWords }) {
  const { nodes, edges } = graph;
  const { pos, h } = useMemo(() => layout(nodes, edges), [nodes, edges]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const maxEv = Math.max(1, ...nodes.filter((n) => n.type !== 'me').map((n) => n.evidence));
  const [sel, setSel] = useState<number | null>(null);
  const canvas = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // narrow screens scroll the map sideways: start centred on the person, so both sides peek in
    const el = canvas.current;
    if (el && el.scrollWidth > el.clientWidth) el.scrollLeft = (el.scrollWidth * X.me) / W - el.clientWidth / 2;
  }, [h]);
  const [hover, setHover] = useState<number | null>(null);
  const focus = hover ?? sel;
  const near = useMemo(() => {
    const s = new Set<number>();
    if (focus == null) return s;
    s.add(focus);
    edges.forEach((e) => {
      if (e.src === focus) s.add(e.dst);
      if (e.dst === focus) s.add(e.src);
    });
    return s;
  }, [focus, edges]);
  const radius = (n: GraphNode) => (n.type === 'me' ? 30 : 6 + 9 * Math.sqrt(n.evidence / maxEv));
  const counts = useMemo(() => {
    const c = new Map<NodeType, number>();
    nodes.forEach((n) => n.type !== 'me' && c.set(n.type, (c.get(n.type) ?? 0) + 1));
    return c;
  }, [nodes]);
  const selected = sel != null ? byId.get(sel) : undefined;
  const name = (n: GraphNode) => (n.type === 'me' ? n.label || words.me : n.label);
  const links = selected
    ? edges
        .filter((e) => e.src === selected.id || e.dst === selected.id)
        .map((e) => ({ e, other: byId.get(e.src === selected.id ? e.dst : e.src)!, out: e.src === selected.id }))
        .filter((l) => l.other)
        .sort((x, y) => y.e.evidence - x.e.evidence)
    : [];

  return (
    <div className="kg">
      <div className="kg-legend" aria-hidden="true">
        {LEGEND.filter((t) => counts.get(t)).map((t) => (
          <span key={t} className={`kg-key kg-t-${t}`}>
            <i />
            {words.types[t]} <b>{counts.get(t)}</b>
          </span>
        ))}
      </div>
      <div className="kg-body">
        <div className="kg-canvas k-scroll-x" ref={canvas}>
          <svg viewBox={`0 0 ${W} ${h}`} role="group" aria-label={words.hint} onMouseLeave={() => setHover(null)}>
            <g className="kg-edges">
              {edges.map((e, i) => {
                const a = pos.get(e.src);
                const b = pos.get(e.dst);
                if (!a || !b) return null;
                const on = focus != null && (e.src === focus || e.dst === focus);
                const dim = focus != null && !on;
                const dx = (b.x - a.x) / 2;
                const d = `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`;
                return (
                  <g key={i} className={`kg-e kg-r-${e.rel}${on ? ' on' : ''}${dim ? ' dim' : ''}`}>
                    <path d={d} strokeWidth={1 + 2.5 * e.weight}>
                      <title>{`${name(byId.get(e.src)!)} — ${words.rel[e.rel]} — ${name(byId.get(e.dst)!)} (${words.evidence(e.evidence)})`}</title>
                    </path>
                    {on && (
                      <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} className="kg-elabel">
                        {words.rel[e.rel]}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
            <g className="kg-nodes">
              {nodes.map((n) => {
                const p = pos.get(n.id);
                if (!p) return null;
                const r = radius(n);
                const dim = focus != null && !near.has(n.id);
                const lab =
                  p.col === 'told'
                    ? { x: p.x - r - 8, y: p.y + 4.5, a: 'end' as const }
                    : p.col === 'routine'
                      ? { x: p.x + r + 8, y: p.y + 4.5, a: 'start' as const }
                      : { x: p.x, y: p.y - r - 7, a: 'middle' as const };
                return (
                  <g
                    key={n.id}
                    className={`kg-n kg-t-${n.type}${sel === n.id ? ' sel' : ''}${dim ? ' dim' : ''}`}
                    role="button"
                    tabIndex={0}
                    aria-pressed={sel === n.id}
                    aria-label={`${words.types[n.type]}: ${name(n)}, ${words.evidence(n.evidence)}`}
                    onClick={() => setSel(sel === n.id ? null : n.id)}
                    onKeyDown={(ev) => {
                      if (ev.key === 'Enter' || ev.key === ' ') {
                        ev.preventDefault();
                        setSel(sel === n.id ? null : n.id);
                      }
                    }}
                    onMouseEnter={() => setHover(n.id)}
                    onFocus={() => setHover(n.id)}
                    onBlur={() => setHover(null)}
                  >
                    <circle cx={p.x} cy={p.y} r={r + 8} className="kg-hit" />
                    <circle cx={p.x} cy={p.y} r={r} className="kg-dot" />
                    {n.type === 'me' ? (
                      <text x={p.x} y={p.y + 5} textAnchor="middle" className="kg-me">
                        {short(name(n), 10)}
                      </text>
                    ) : (
                      <text x={lab.x} y={lab.y} textAnchor={lab.a} className="kg-label">
                        {short(n.label)}
                        {n.evidence > 0 && <tspan className="kg-ev">{` ${n.evidence}`}</tspan>}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>
        </div>
        <aside className="kg-panel" aria-live="polite">
          {!selected ? (
            <p className="sm mut">{words.hint}</p>
          ) : (
            <>
              <span className={`kg-key kg-t-${selected.type}`}>
                <i />
                {words.types[selected.type]}
              </span>
              <b className="kg-title">{name(selected)}</b>
              {selected.detail && <p className="sm ink2">{selected.detail}</p>}
              <p className="xs mut">{words.evidence(selected.evidence)}</p>
              <h3 className="lbl">{words.links}</h3>
              {links.length === 0 ? (
                <p className="sm mut">{words.none}</p>
              ) : (
                <ul className="kg-links">
                  {links.map(({ e, other, out }, i) => (
                    <li key={i}>
                      <button type="button" onClick={() => setSel(other.id)}>
                        <span className="kg-rel">{out ? words.rel[e.rel] : words.relIn[e.rel]}</span>
                        <span className={`kg-key kg-t-${other.type}`}>
                          <i />
                        </span>
                        <span className="kg-other">{name(other)}</span>
                        <span className="kg-n-ev">{e.evidence}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
