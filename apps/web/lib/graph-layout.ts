/**
 * Layered layout for the permitted knowledge graph (pure, unit-tested). Three columns: the person, then signal
 * groups and activities, then measures and routines. Every node in a column gets its own row, so labels can
 * never collide however many nodes arrive.
 */

import type { InsightEdge, InsightNode } from '../../../contracts/ts/models.ts';

type Node = Required<InsightNode>;
type Edge = Required<InsightEdge>;

export const ROW = 28;
export const PAD = 20;

export interface PlacedNode {
  node: Node;
  col: 0 | 1 | 2;
  /** centre y in px */
  y: number;
}

export interface GraphLayout {
  nodes: PlacedNode[];
  /** edges worth drawing: both ends placed, and no person→child shortcut when the child already hangs off a parent */
  edges: Edge[];
  height: number;
}

const colOf = (kind: InsightNode['kind']): 0 | 1 | 2 =>
  kind === 'person' ? 0 : kind === 'signal_group' || kind === 'activity' || kind === 'care_action' || kind === 'shared_topic' ? 1 : 2;

export function layoutGraph(graph: { nodes: Node[]; edges: Edge[] }): GraphLayout {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const edges = graph.edges.filter((e) => byId.has(e.src) && byId.has(e.dst));
  const mid = graph.nodes.filter((n) => colOf(n.kind) === 1);
  const leaves = graph.nodes.filter((n) => colOf(n.kind) === 2);
  // a leaf hangs off the first middle-column node it shares an edge with
  const parentOf = new Map<string, string>();
  for (const leaf of leaves) {
    const e = edges.find(
      (x) => (x.src === leaf.id && byId.get(x.dst) && colOf(byId.get(x.dst)!.kind) === 1) || (x.dst === leaf.id && byId.get(x.src) && colOf(byId.get(x.src)!.kind) === 1),
    );
    if (e) parentOf.set(leaf.id, e.src === leaf.id ? e.dst : e.src);
  }
  const placed: PlacedNode[] = [];
  let row = 0;
  for (const m of mid) {
    const kids = leaves.filter((l) => parentOf.get(l.id) === m.id);
    if (!kids.length) {
      placed.push({ node: m, col: 1, y: PAD + row * ROW });
      row += 1;
    } else {
      kids.forEach((k, i) => placed.push({ node: k, col: 2, y: PAD + (row + i) * ROW }));
      placed.push({ node: m, col: 1, y: PAD + (row + (kids.length - 1) / 2) * ROW });
      row += kids.length;
    }
    row += 0.4; // breathing room between clusters
  }
  for (const orphan of leaves.filter((l) => !parentOf.has(l.id))) {
    placed.push({ node: orphan, col: 2, y: PAD + row * ROW });
    row += 1;
  }
  const height = Math.max(ROW * 3, PAD * 2 + Math.max(0, row - 1) * ROW);
  for (const p of graph.nodes.filter((n) => colOf(n.kind) === 0)) placed.push({ node: p, col: 0, y: height / 2 });
  const col = new Map(placed.map((p) => [p.node.id, p.col]));
  const drawn = edges.filter((e) => {
    const a = col.get(e.src);
    const b = col.get(e.dst);
    if (a === undefined || b === undefined || a === b) return false;
    const leaf = a === 2 ? e.src : b === 2 ? e.dst : null;
    // person → leaf is implied by person → parent → leaf
    return !(leaf && (a === 0 || b === 0) && parentOf.has(leaf));
  });
  return { nodes: placed, edges: drawn, height };
}

/** Truncate a label to the pixels available (≈ 7 px a character at the caption size). */
export function fitLabel(label: string, px: number): string {
  const max = Math.max(6, Math.floor(px / 7));
  return label.length <= max ? label : `${label.slice(0, max - 1).trimEnd()}…`;
}

export interface LearnedNode {
  node: Node;
  /** second line: the routine folded into its activity ("Daily · 07:22 · kept") */
  sub: string | null;
  side: 'left' | 'right';
  row: number;
}

export interface LearnedView {
  centre: Node | null;
  nodes: LearnedNode[];
  /** edges between the nodes shown (routine links re-pointed to the activity they belong to) */
  edges: Edge[];
  rows: number;
  /** learned nodes left out because they do not fit this size */
  hidden: number;
}

const DOING = new Set<InsightNode['kind']>(['activity', 'routine', 'care_action', 'shared_topic']);

/**
 * What Kaiku learned about this person, arranged so it fits a panel: the person in the middle, what they do
 * (activities, routines, care actions) on the left, the measures a learned link touches on the right. One row per
 * node on each side, so labels cannot collide. A routine is folded into the activity it is a pattern of.
 * Without layer information from the cloud, activities, routines and what helped count as learned.
 */
export function learnedView(graph: { nodes: Node[]; edges: Edge[] }, cap: { left: number; right: number } = { left: 99, right: 99 }): LearnedView {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const tagged = graph.nodes.some((n) => n.layer === 'learned') || graph.edges.some((e) => e.layer === 'learned');
  const edgeIn = (e: Edge) => (tagged ? e.layer === 'learned' : ['did', 'keeps', 'of', 'helped'].includes(e.rel));
  let edges = graph.edges.filter((e) => edgeIn(e) && byId.has(e.src) && byId.has(e.dst));
  const touched = new Set(edges.flatMap((e) => [e.src, e.dst]));
  // a measure belongs here only when a learned link touches it
  const nodeIn = (n: Node) =>
    n.kind !== 'person' && (tagged ? (n.layer === 'learned' && n.kind !== 'measure') || touched.has(n.id) : DOING.has(n.kind) && touched.has(n.id));
  const centre = graph.nodes.find((n) => n.kind === 'person') ?? null;

  // fold each routine into the activity it is a pattern of
  const foldInto = new Map<string, string>();
  const sub = new Map<string, string>();
  // (the "pattern of" link may sit in the structure layer, so look at every edge for it)
  for (const e of graph.edges) {
    if (e.rel !== 'of' || !byId.has(e.src) || !byId.has(e.dst)) continue;
    const [a, b] = [byId.get(e.src)!, byId.get(e.dst)!];
    const routine = a.kind === 'routine' ? a : b.kind === 'routine' ? b : null;
    const host = routine === a ? b : a;
    if (!routine || host.kind !== 'activity' || foldInto.has(routine.id)) continue;
    if (tagged && routine.layer !== 'learned' && !touched.has(routine.id)) continue;
    foldInto.set(routine.id, host.id);
    const kept = edges.find((x) => x.rel === 'keeps' && (x.src === routine.id || x.dst === routine.id));
    // "Walks and outings · around 15:00" under the activity "Walks and outings" keeps only the time
    const when = routine.label.includes(' · ') && !/^(daily|weekly|most days)\b/i.test(routine.label) ? routine.label.split(' · ').slice(1).join(' · ') : routine.label;
    sub.set(host.id, [when, kept?.label].filter(Boolean).join(' · '));
    touched.add(host.id);
  }
  const at = (id: string) => foldInto.get(id) ?? id;
  const seen = new Set<string>();
  edges = edges
    .filter((e) => e.rel !== 'of' || !foldInto.has(e.src) && !foldInto.has(e.dst))
    .map((e) => ({ ...e, src: at(e.src), dst: at(e.dst) }))
    .filter((e) => {
      const key = `${e.src}>${e.dst}:${e.rel}`;
      if (e.src === e.dst || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  // person → activity "did" says nothing once the same pair has a richer link (keeps, helped)
  edges = edges.filter((e) => e.rel !== 'did' || !edges.some((x) => x !== e && x.rel !== 'did' && x.src === e.src && x.dst === e.dst));

  // when there is more than fits, keep what says most: care actions, what moved first, what helped, then by links
  const score = (n: Node) => {
    const mine = edges.filter((e) => (e.src === n.id || e.dst === n.id) && e.rel !== 'did' && e.rel !== 'has_signal');
    return mine.length + (n.kind === 'care_action' ? 6 : 0) + (mine.some((e) => e.rel === 'moved_first') ? 4 : 0) + (mine.some((e) => e.rel === 'helped') ? 3 : 0) - (n.kind === 'shared_topic' ? 2 : 0);
  };
  const shown = graph.nodes.filter((n) => nodeIn(n) && !foldInto.has(n.id));
  const pickTop = (list: Node[], max: number) => {
    if (list.length <= max) return list;
    const keep = new Set([...list].sort((a, b) => score(b) - score(a)).slice(0, max).map((n) => n.id));
    return list.filter((n) => keep.has(n.id));
  };
  const allLeft = shown.filter((n) => DOING.has(n.kind));
  const allRight = shown.filter((n) => !DOING.has(n.kind));
  let left = pickTop(allLeft, cap.left);
  let right = pickTop(allRight, cap.right);
  const hidden = allLeft.length + allRight.length - left.length - right.length;
  if (!right.length && left.length > 3) {
    // nothing on the measure side yet: balance the two sides so the picture still reads as a whole
    const half = Math.ceil(left.length / 2);
    right = left.slice(half);
    left = left.slice(0, half);
  }
  const ids = new Set([...(centre ? [centre.id] : []), ...left.map((n) => n.id), ...right.map((n) => n.id)]);
  const place = (list: Node[], side: 'left' | 'right'): LearnedNode[] => list.map((node, row) => ({ node, sub: sub.get(node.id) ?? null, side, row }));
  return {
    centre,
    nodes: [...place(left, 'left'), ...place(right, 'right')],
    edges: edges.filter((e) => ids.has(e.src) && ids.has(e.dst)),
    rows: Math.max(left.length, right.length),
    hidden,
  };
}

const REL_WORDS: Record<string, string> = {
  did: 'did',
  keeps: 'keeps as a routine',
  of: 'pattern of',
  helped: 'helped',
  has_signal: 'signal group',
  measures: 'measure',
  moved_first: 'moved first',
  followed: 'followed',
  moved_together: 'moved together',
  kept_through: 'kept through the change',
  slipped_during: 'slipped during the change',
  after: 'came after',
};

/** A learned link as words: the cloud's label when it says more than the relation name, plus the evidence count. */
export function edgeWords(e: Pick<Edge, 'rel' | 'label' | 'evidence' | 'weight'>): string {
  const rel = REL_WORDS[e.rel] ?? e.rel.replace(/_/g, ' ');
  if (e.rel === 'helped') {
    // a reported response on a handful of tries is never worded as certain
    const sure = e.evidence < 5 ? 'early signal' : e.evidence < 12 ? 'uncertain' : 'consistent so far';
    return `helped · ${e.evidence} ${e.evidence === 1 ? 'try' : 'tries'} · ${sure}`;
  }
  const said = e.label && e.label.toLowerCase() !== rel && !rel.startsWith(e.label.toLowerCase()) ? e.label : rel;
  // a label that already carries its count ("kept: 6 of the last 7 days") needs no second one
  return /\d/.test(said) ? said : `${said} · ${e.evidence} ${e.evidence === 1 ? 'record' : 'records'}`;
}
