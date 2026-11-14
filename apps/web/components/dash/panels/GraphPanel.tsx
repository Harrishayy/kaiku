'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { InsightNode } from '@contracts';
import { PAD, edgeWords, fitLabel, layoutGraph, learnedView } from '@/lib/graph-layout';
import { TONE_WORD } from '@/lib/insight';
import type { DashData } from '../data';
import { Chip, EmptyState, toneChip } from '../kit';

const KIND: Record<InsightNode['kind'], string> = {
  person: 'Person',
  signal_group: 'Signal group',
  measure: 'Measure',
  activity: 'Activity',
  routine: 'Routine',
  care_action: 'Care action',
  shared_topic: 'Shared topic',
};
const R: Record<InsightNode['kind'], number> = { person: 9, signal_group: 7, activity: 7, care_action: 7, shared_topic: 6, measure: 5, routine: 5 };
const SQUARE = new Set<InsightNode['kind']>(['signal_group', 'routine', 'care_action']);
const ROW_TILE = 36;
const ROW_WIDE = 56;

type Pick = { type: 'node'; id: string } | { type: 'edge'; key: string } | null;
const edgeKey = (e: { src: string; dst: string; rel: string }) => `${e.src}>${e.dst}:${e.rel}`;

function useWidth(present: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setW(Math.round(el.clientWidth));
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
    // the element only exists once there is a graph to draw
  }, [present]);
  return { ref, w };
}

export function GraphPanel({ data, onMetric }: { data: DashData; onMetric: (m: string) => void }) {
  const graph = data.view.graph;
  const hasGraph = graph.nodes.length > 1;
  const [all, setAll] = useState(false);
  const [picked, setPicked] = useState<Pick>(null);
  const [hover, setHover] = useState<string | null>(null);
  const { ref, w } = useWidth(hasGraph);
  const size = w >= 760 ? 'wide' : w >= 460 ? 'mid' : 'tile';
  const learned = useMemo(() => learnedView(graph, size === 'wide' ? { left: 9, right: 10 } : size === 'mid' ? { left: 6, right: 6 } : { left: 4, right: 3 }), [graph, size]);
  const hasLearned = learned.nodes.length > 0;
  const showAll = all || !hasLearned;
  useEffect(() => setPicked(null), [showAll, data.patient.id]);

  if (!hasGraph)
    return (
      <EmptyState title="Nothing learned yet">
        {graph.note || 'Activities, routines and what helps appear here as days are recorded.'}
      </EmptyState>
    );

  const nameOf = (id: string) => graph.nodes.find((n) => n.id === id)?.label ?? id;
  const metricOf = (id: string) => (id.startsWith('measure:') ? id.slice('measure:'.length) : null);
  const edgesShown = showAll ? graph.edges : learned.edges;
  const selNode = picked?.type === 'node' ? graph.nodes.find((n) => n.id === picked.id) : null;
  const selEdge = picked?.type === 'edge' ? edgesShown.find((e) => edgeKey(e) === picked.key) : null;
  const links = selNode ? edgesShown.filter((e) => e.src === selNode.id || e.dst === selNode.id) : [];
  const focus = hover ?? (picked?.type === 'node' ? picked.id : null);
  const near = new Set<string>();
  if (focus) {
    near.add(focus);
    for (const e of edgesShown) {
      if (e.src === focus) near.add(e.dst);
      if (e.dst === focus) near.add(e.src);
    }
  }
  if (selEdge) {
    near.add(selEdge.src);
    near.add(selEdge.dst);
  }
  const dimNode = (id: string) => (focus || selEdge ? !near.has(id) : false);
  const edgeOn = (e: { src: string; dst: string; rel: string }) => (selEdge ? edgeKey(e) === edgeKey(selEdge) : focus ? e.src === focus || e.dst === focus : false);
  const pickNode = (id: string) => setPicked(picked?.type === 'node' && picked.id === id ? null : { type: 'node', id });
  const wide = w >= 760;
  const ROW_H = wide ? ROW_WIDE : ROW_TILE;

  const nodeProps = (node: (typeof graph.nodes)[number]) => ({
    role: 'button' as const,
    tabIndex: 0,
    'aria-pressed': picked?.type === 'node' && picked.id === node.id,
    'aria-label': `${KIND[node.kind]}: ${node.label}. ${node.evidence} records. ${TONE_WORD[node.tone]}.`,
    onClick: () => pickNode(node.id),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        pickNode(node.id);
      }
    },
    onMouseEnter: () => setHover(node.id),
    onMouseLeave: () => setHover(null),
    onFocus: () => setHover(node.id),
    onBlur: () => setHover(null),
  });
  const mark = (kind: InsightNode['kind'], r: number) =>
    SQUARE.has(kind) ? <rect className="d-node-mark" x={-r} y={-r} width={r * 2} height={r * 2} rx={2} /> : <circle className="d-node-mark" r={r} />;

  let drawing = null;
  if (w > 0 && !showAll) {
    // learned layer: person in the middle, what they do on the left, the measures it touches on the right
    // a narrow tile has no room for labels on both sides: everything fans out to the right of the person instead
    const single = w < 460;
    const nodes = single ? learned.nodes.map((n, i) => ({ ...n, side: 'right' as const, row: i })) : learned.nodes;
    const h = Math.max(150, (single ? nodes.length : learned.rows) * ROW_H + 16);
    const cx = single ? 28 : w / 2;
    const colGap = single ? 64 : Math.min(150, Math.max(54, w * 0.16));
    const xOf = (side: 'left' | 'right') => (side === 'left' ? cx - colGap : cx + colGap);
    const room = single ? w - cx - colGap - 12 : Math.max(60, cx - colGap - 20);
    const count = { left: nodes.filter((n) => n.side === 'left').length, right: nodes.filter((n) => n.side === 'right').length };
    const yOf = (n: (typeof nodes)[number]) => h / 2 + (n.row - (count[n.side] - 1) / 2) * ROW_H;
    const pos = new Map<string, { x: number; y: number; r: number; side: 'left' | 'right' | 'centre' }>();
    if (learned.centre) pos.set(learned.centre.id, { x: cx, y: h / 2, r: R.person, side: 'centre' });
    for (const n of nodes) pos.set(n.node.id, { x: xOf(n.side), y: yOf(n), r: R[n.node.kind], side: n.side });
    drawing = (
      <svg width={w} height={h} role="group" aria-label="What Kaiku has learned about this person. Select a node or a link to see its evidence.">
        {learned.edges.map((e) => {
          const a = pos.get(e.src);
          const b = pos.get(e.dst);
          if (!a || !b) return null;
          const key = edgeKey(e);
          const on = edgeOn(e);
          // same-side links bow toward the middle, away from the labels
          const same = a.side === b.side && a.side !== 'centre';
          const bow = same ? (a.side === 'left' ? 1 : -1) * Math.min(colGap * 0.7, 26 + Math.abs(a.y - b.y) * 0.25) : 0;
          const d = same
            ? `M${a.x},${a.y}C${a.x + bow},${a.y} ${b.x + bow},${b.y} ${b.x},${b.y}`
            : `M${a.x},${a.y}C${(a.x + b.x) / 2},${a.y} ${(a.x + b.x) / 2},${b.y} ${b.x},${b.y}`;
          // the label sits a third of the way in from the outer node, clear of the crowded middle
          const outer = a.side === 'centre' ? b : a;
          const inner = outer === a ? b : a;
          const lx = same ? a.x + bow * 0.75 : outer.x + (inner.x - outer.x) * 0.38;
          const ly = same ? (a.y + b.y) / 2 : outer.y + (inner.y - outer.y) * 0.12;
          return (
            <g
              key={key}
              className={`d-link-edge${on ? ' is-on' : ''}${(focus || selEdge) && !on ? ' is-dim' : ''}`}
              role="button"
              tabIndex={0}
              aria-label={`${nameOf(e.src)} to ${nameOf(e.dst)}: ${edgeWords(e)}`}
              onClick={() => setPicked(picked?.type === 'edge' && picked.key === key ? null : { type: 'edge', key })}
              onKeyDown={(ev) => {
                if (ev.key === 'Enter' || ev.key === ' ') {
                  ev.preventDefault();
                  setPicked({ type: 'edge', key });
                }
              }}
            >
              <path className="d-edge-hit" d={d} />
              <path className={`d-edge d-edge-${e.rel}${e.rel === 'did' ? '' : ' is-learned'}`} d={d} strokeWidth={e.rel === 'helped' ? 1.5 + e.weight * 2.5 : 1.5} />
              {on && (
                <text className="d-edge-label" x={lx} y={ly} textAnchor="middle" dominantBaseline="central">
                  {fitLabel(edgeWords(e), Math.min(320, w - 40))}
                </text>
              )}
            </g>
          );
        })}
        {learned.centre && (
          <g className={`d-node d-node-${learned.centre.tone}${picked?.type === 'node' && picked.id === learned.centre.id ? ' is-picked' : ''}`} transform={`translate(${cx},${h / 2})`} {...nodeProps(learned.centre)}>
            <circle className="d-node-mark d-node-centre" r={R.person + 3} />
            <text className="d-node-name" y={R.person + 18} textAnchor={single ? 'start' : 'middle'} x={single ? -R.person - 3 : 0}>
              {fitLabel(learned.centre.label, single ? colGap + 10 : colGap * 2 - 24)}
            </text>
          </g>
        )}
        {nodes.map((n) => {
          const p = pos.get(n.node.id)!;
          const dir = n.side === 'left' ? -1 : 1;
          return (
            <g
              key={n.node.id}
              className={`d-node d-node-${n.node.tone}${picked?.type === 'node' && picked.id === n.node.id ? ' is-picked' : ''}${dimNode(n.node.id) ? ' is-dim' : ''}`}
              transform={`translate(${p.x},${p.y})`}
              {...nodeProps(n.node)}
            >
              <rect className="d-node-hit" x={n.side === 'left' ? -room - 6 : -p.r - 6} y={-ROW_H / 2 + 3} width={room + p.r + 12} height={ROW_H - 6} rx={8} />
              {mark(n.node.kind, p.r)}
              <text className="d-node-name" x={dir * (p.r + 8)} y={n.sub ? -7 : 0} textAnchor={n.side === 'left' ? 'end' : 'start'} dominantBaseline="central">
                {fitLabel(n.node.label, room - p.r - 10)}
                <title>{n.node.label}</title>
              </text>
              {n.sub && (
                <text className="d-node-sub" x={dir * (p.r + 8)} y={9} textAnchor={n.side === 'left' ? 'end' : 'start'} dominantBaseline="central">
                  {fitLabel(n.sub, (room - p.r - 10) * 1.1)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    );
  } else if (w > 0) {
    // everything: the layered tree, one row per node
    const layout = layoutGraph(graph);
    const gw = Math.max(360, w);
    const narrow = gw < 520;
    const X = narrow ? [12, 44, Math.round(gw * 0.54)] : [16, Math.round(gw * 0.2), Math.round(gw * 0.56)];
    const room = [X[1] - X[0] - 34, X[2] - X[1] - 34, gw - X[2] - 22];
    const pos = new Map(
      layout.nodes.map((p) => {
        const r = R[p.node.kind];
        return [p.node.id, { x: X[p.col], y: p.y, r, out: X[p.col] + r + 8 + fitLabel(p.node.label, room[p.col]).length * 6.9 + 6 }];
      }),
    );
    drawing = (
      <>
        <div className="d-graph-cols" style={{ width: gw }} aria-hidden="true">
          {!narrow && <span style={{ left: X[0] }}>Person</span>}
          <span style={{ left: X[1] }}>{narrow ? 'Groups' : 'Groups and activities'}</span>
          <span style={{ left: X[2] }}>{narrow ? 'Measures' : 'Measures and routines'}</span>
        </div>
        <svg width={gw} height={layout.height + PAD} role="group" aria-label="Everything in the record's graph. Select a node to see its evidence.">
          {layout.edges.map((e) => {
            const a = pos.get(e.src)!;
            const b = pos.get(e.dst)!;
            const [l, r] = a.x <= b.x ? [a, b] : [b, a];
            const x0 = Math.min(l.out, r.x - r.r - 16);
            const on = edgeOn(e);
            return <path key={edgeKey(e)} className={`d-edge d-edge-${e.rel}${on ? ' is-on' : ''}${focus && !on ? ' is-dim' : ''}`} d={`M${x0},${l.y}C${(x0 + r.x) / 2},${l.y} ${(x0 + r.x) / 2},${r.y} ${r.x - r.r},${r.y}`} strokeWidth={e.rel === 'helped' ? 1 + e.weight * 2.5 : 1.25} />;
          })}
          {layout.nodes.map(({ node, col }) => {
            const p = pos.get(node.id)!;
            return (
              <g key={node.id} className={`d-node d-node-${node.tone}${picked?.type === 'node' && picked.id === node.id ? ' is-picked' : ''}${dimNode(node.id) ? ' is-dim' : ''}`} transform={`translate(${p.x},${p.y})`} {...nodeProps(node)}>
                <rect className="d-node-hit" x={-p.r - 4} y={-12} width={room[col] + p.r * 2 + 12} height={24} rx={6} />
                {mark(node.kind, p.r)}
                <text className="d-node-name" x={p.r + 8} dominantBaseline="central">
                  {fitLabel(node.label, room[col])}
                  <title>{node.label}</title>
                </text>
              </g>
            );
          })}
        </svg>
      </>
    );
  }

  const learnedLinks = learned.edges.filter((e) => e.rel !== 'did');
  return (
    <div className={`d-graph${wide ? ' is-wide' : ''}`}>
      <div className="d-toolbar">
        <span className="d-strong">{showAll ? 'Everything in the record' : 'What Kaiku learned'}</span>
        {hasLearned && (
          <button type="button" className="d-btn" aria-pressed={all} onClick={() => setAll(!all)}>
            {all ? 'Show learned only' : 'Show all measures'}
          </button>
        )}
      </div>
      <div className="d-graph-main">
        <div className={showAll ? 'd-graph-scroll' : 'd-graph-fit'} ref={ref}>
          {drawing}
        </div>
        <div className="d-graph-side">
          {selNode ? (
            <div className="d-citation" role="status">
              <div className="d-row-head">
                <span className="d-row-title">{selNode.label}</span>
                <Chip tone={toneChip[selNode.tone]}>{TONE_WORD[selNode.tone]}</Chip>
              </div>
              <span className="d-meta">
                {KIND[selNode.kind]} · backed by {selNode.evidence} {selNode.evidence === 1 ? 'record' : 'records'}
              </span>
              {selNode.detail && <span>{selNode.detail}</span>}
              {links.length > 0 && (
                <ul className="d-bullets">
                  {links.slice(0, 8).map((e) => {
                    const other = e.src === selNode.id ? e.dst : e.src;
                    return (
                      <li key={edgeKey(e)}>
                        <button type="button" className="d-link" onClick={() => setPicked({ type: 'node', id: other })}>
                          {nameOf(other)}
                        </button>{' '}
                        <span className="d-muted">({edgeWords(e)})</span>
                      </li>
                    );
                  })}
                  {links.length > 8 && <li className="d-muted">and {links.length - 8} more links</li>}
                </ul>
              )}
              {metricOf(selNode.id) && data.series.some((s) => s.metric === metricOf(selNode.id)) && (
                <button type="button" className="d-link" onClick={() => onMetric(metricOf(selNode.id) as string)}>
                  Show in Trends
                </button>
              )}
            </div>
          ) : selEdge ? (
            <div className="d-citation" role="status">
              <span className="d-row-title">
                {selEdge.dst === learned.centre?.id ? nameOf(selEdge.src) : selEdge.src === learned.centre?.id ? nameOf(selEdge.dst) : `${nameOf(selEdge.src)} → ${nameOf(selEdge.dst)}`}
              </span>
              <span>{edgeWords(selEdge)}</span>
              <span className="d-meta">A link in time or in what the person reported, never proof of cause.</span>
            </div>
          ) : !showAll && learnedLinks.length > 0 ? (
            <ul className="d-learned" aria-label="Learned links">
              {learnedLinks.slice(0, wide ? 10 : 4).map((e) => (
                <li key={edgeKey(e)}>
                  <button type="button" className="d-learned-item" onClick={() => setPicked({ type: 'edge', key: edgeKey(e) })}>
                    <span className="d-row-title">{e.src === learned.centre?.id ? nameOf(e.dst) : e.dst === learned.centre?.id ? nameOf(e.src) : `${nameOf(e.src)} → ${nameOf(e.dst)}`}</span>
                    <span className="d-meta">{edgeWords(e)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="d-muted">Select a node to see what it rests on.</p>
          )}
          {!showAll && learned.hidden > 0 && (
            <p className="d-meta">
              {learned.hidden} more learned {learned.hidden === 1 ? 'item' : 'items'} {wide ? 'are in the full view (Show all measures).' : 'appear when this panel is maximised.'}
            </p>
          )}
          <ul className="d-legend" aria-label="Graph key">
            <li><span className="d-key d-key-better" />Better</li>
            <li><span className="d-key d-key-worse" />Change from usual</li>
            <li><span className="d-key d-key-similar" />As usual</li>
            <li><span className="d-key d-key-unknown" />Not enough data</li>
            <li><span className="d-key-line" />Helped (thicker = stronger response)</li>
          </ul>
          <p className="d-meta">{graph.note}</p>
        </div>
      </div>
    </div>
  );
}
