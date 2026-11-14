/**
 * The knowledge graph as a map (pure, unit-tested). The person sits in the middle; neighbourhoods (what a group of
 * nodes is about, declared by the cloud) sit at fixed compass places around them, the same for every person. Inside
 * a neighbourhood the nodes form a small tree, one row each: an activity with its routine on the same row, the
 * measures it produces under it, then the other measures, care actions and themes. One row per node and one box
 * per label, so nothing can overlap; the same graph and size always give the same picture.
 */

import type { InsightDomain, InsightEdge, InsightGraphDay, InsightNode, InsightNodeDay } from '../../../contracts/ts/models.ts';

/** the as-served shape: the same contract types with their defaults present */
type Deep<T> = T extends (infer U)[] ? Deep<U>[] : T extends object ? { [K in keyof T]-?: Deep<T[K]> } : T;
type Node = Deep<InsightNode>;
type Edge = Deep<InsightEdge>;
type Day = Deep<InsightGraphDay>;
/** a compass place around the person; 'x' = the middle column under the person, for records the cloud gave no neighbourhood when every place is taken */
export type Place = InsightDomain['place'] | 'x';
export type GraphIn = { nodes: Node[]; edges: Edge[]; domains?: InsightDomain[]; days?: Day[] };

/**
 * A graph from a service that predates the map (no neighbourhoods, no day data) still draws, grouped by kind and
 * without a scrubber: lists that are missing read as empty. A complete graph is returned as it is.
 */
export function fillGraph<G extends { nodes: Node[]; edges: Edge[]; domains: InsightDomain[]; days: Day[] }>(g: G): G {
  const whole = Array.isArray(g.domains) && Array.isArray(g.days) && g.nodes.every((n) => Array.isArray(n.days) && typeof n.domain === 'string') && g.edges.every((e) => Array.isArray(e.on) && typeof e.tag === 'string');
  if (whole) return g;
  return {
    ...g,
    domains: g.domains ?? [],
    days: g.days ?? [],
    nodes: g.nodes.map((n) => ({ ...n, domain: n.domain ?? '', days: n.days ?? [] })),
    edges: g.edges.map((e) => ({ ...e, on: e.on ?? [], tag: e.tag ?? '' })),
  };
}

export interface MapRow {
  node: Node;
  depth: 0 | 1;
  /** the row this one hangs under: the activity that produces a measure, the node a theme is about */
  parent: string | null;
  /** an activity's routine, drawn on the same row */
  chip: Node | null;
}

export interface Hood {
  id: string;
  label: string;
  short: string;
  place: Place;
  rows: MapRow[];
  /** every node of the neighbourhood, routines on a row included */
  nodes: Node[];
}

const BY_KIND: { id: string; label: string; short: string; place: Place; kinds: InsightNode['kind'][] }[] = [
  { id: 'doing', label: 'Activities and routines', short: 'Activities', place: 'w', kinds: ['activity', 'routine'] },
  { id: 'measures', label: 'Measures', short: 'Measures', place: 'e', kinds: ['measure'] },
  { id: 'told', label: 'What they tell Kaiku', short: 'Notebook', place: 'n', kinds: ['shared_topic'] },
  { id: 'care', label: 'Care', short: 'Care', place: 's', kinds: ['care_action'] },
];
const PLACES: Place[] = ['nw', 'n', 'ne', 'w', 'e', 'sw', 's', 'se'];

/** "Morning ritual · around 07:22" → minutes after midnight, for ordering a neighbourhood by the day's rhythm. */
const usualMinute = (label: string): number => {
  const m = /around (\d{2}):(\d{2})/.exec(label);
  return m ? Number(m[1]) * 60 + Number(m[2]) : Number.POSITIVE_INFINITY;
};

/**
 * Group the permitted graph into neighbourhoods and order each one as a tree. The person and the signal groups are
 * not rows: who sent a record is not what it is about. Without domains from the cloud (the fallback view) nodes are
 * grouped by kind instead; a node whose domain is unknown goes to "Other records" in a free place (under the person
 * when all eight are taken): it is never dropped and never put where it was not declared.
 */
export function buildHoods(graph: GraphIn): { person: Node | null; hoods: Hood[] } {
  const person = graph.nodes.find((n) => n.kind === 'person') ?? null;
  const declared = graph.domains ?? [];
  const known = new Set(declared.map((d) => d.id));
  const members = new Map<string, Node[]>();
  const kindHood = (n: Node) => BY_KIND.find((k) => k.kinds.includes(n.kind))?.id ?? 'measures';
  for (const n of graph.nodes) {
    if (n.kind === 'person' || n.kind === 'signal_group') continue;
    const key = declared.length ? (known.has(n.domain) ? n.domain : 'other') : kindHood(n);
    members.set(key, [...(members.get(key) ?? []), n]);
  }
  const defs: { id: string; label: string; short: string; place: Place }[] = declared.length ? [...declared] : BY_KIND.map(({ id, label, short, place }) => ({ id, label, short, place }));
  if (members.has('other')) defs.push({ id: 'other', label: 'Other records', short: 'Other', place: PLACES.find((p) => !defs.some((d) => d.place === p)) ?? 'x' });
  const order = new Map(graph.nodes.map((n, i) => [n.id, i]));
  const hoods: Hood[] = [];
  for (const def of defs) {
    const nodes = members.get(def.id) ?? [];
    if (!nodes.length) continue;
    const inHood = new Set(nodes.map((n) => n.id));
    const chipOf = new Map<string, Node>();
    for (const e of graph.edges) {
      if (e.rel !== 'of' || !inHood.has(e.src) || !inHood.has(e.dst)) continue;
      const routine = nodes.find((n) => n.id === e.src && n.kind === 'routine');
      const host = nodes.find((n) => n.id === e.dst && n.kind === 'activity');
      if (routine && host && !chipOf.has(host.id)) chipOf.set(host.id, routine);
    }
    const chips = new Set([...chipOf.values()].map((n) => n.id));
    const placed = new Set<string>();
    const rows: MapRow[] = [];
    const childrenOf = (parent: string) =>
      nodes.filter(
        (n) =>
          !placed.has(n.id) &&
          !chips.has(n.id) &&
          ((n.kind === 'measure' && graph.edges.some((e) => e.rel === 'produces' && e.src === parent && e.dst === n.id)) ||
            (n.kind === 'shared_topic' && graph.edges.some((e) => e.rel === 'about' && e.src === n.id && e.dst === parent))),
      );
    const add = (node: Node, chip: Node | null) => {
      rows.push({ node, depth: 0, parent: null, chip });
      placed.add(node.id);
      // measures first, then the theme that sits beside it
      for (const child of childrenOf(node.id).sort((a, b) => Number(a.kind !== 'measure') - Number(b.kind !== 'measure'))) {
        rows.push({ node: child, depth: 1, parent: node.id, chip: null });
        placed.add(child.id);
      }
    };
    const when = (n: Node) => usualMinute(n.kind === 'routine' ? n.label : (chipOf.get(n.id)?.label ?? ''));
    const hosts = nodes.filter((n) => n.kind === 'activity' || (n.kind === 'routine' && !chips.has(n.id)));
    for (const host of [...hosts].sort((a, b) => when(a) - when(b) || order.get(a.id)! - order.get(b.id)!)) add(host, chipOf.get(host.id) ?? null);
    for (const kind of ['measure', 'care_action', 'shared_topic'] as const)
      for (const n of nodes) if (n.kind === kind && !placed.has(n.id) && !chips.has(n.id)) add(n, null);
    hoods.push({ ...def, rows, nodes });
  }
  return { person, hoods };
}

// ------------------------------------------------------------------ the day

export type Look = 'better' | 'worse' | 'similar' | 'unknown' | 'plain' | 'off' | 'still';

export interface NodeOnDay {
  /** something is recorded for this node on the day */
  lit: boolean;
  look: Look;
  value: string;
  text: string;
}

export const dayOf = (node: Pick<Node, 'days'>, date: string | null): Deep<InsightNodeDay> | null => (date ? (node.days.find((d) => d.date === date) ?? null) : null);

/** The latest day with something recorded: where the scrubber starts. */
export const latestDay = (days: Pick<Day, 'date' | 'recorded'>[]): string | null => [...days].reverse().find((d) => d.recorded)?.date ?? days[days.length - 1]?.date ?? null;

/**
 * How a node looks on a day. A measure and a kept or missed routine carry a tone; an activity, a theme or a care
 * action is simply recorded ("plain"); nothing that day is "off"; a node that is never dated (a notebook count) is
 * "still". Without day data (the fallback view) every node is shown with its overall tone.
 */
export function nodeOnDay(node: Node, date: string | null): NodeOnDay {
  const toned = node.kind === 'measure' || node.kind === 'routine';
  if (!date) return { lit: true, look: toned ? node.tone : 'plain', value: '', text: node.detail ?? '' };
  if (!node.days.length) return { lit: false, look: 'still', value: '', text: '' };
  const d = dayOf(node, date);
  if (!d) return { lit: false, look: 'off', value: '', text: '' };
  const tone = d.tone ?? 'unknown';
  const look: Look = node.kind === 'measure' ? tone : node.kind === 'routine' && tone !== 'unknown' ? tone : 'plain';
  return { lit: true, look, value: d.value ?? '', text: d.text };
}

export interface HoodDay {
  /** measures away from their usual */
  away: number;
  /** measures that could be read against a usual */
  scored: number;
  better: number;
  missed: number;
  /** nodes with something recorded */
  lit: number;
  text: string;
  /** the same in a few words, for a small cell: "3 of 6 away" */
  brief: string;
}

/** One line for a neighbourhood on a day: "3 of 6 away from usual · 1 routine missed". Counts only. */
export function hoodOnDay(hood: Hood, date: string | null, edges: Pick<Edge, 'rel' | 'src' | 'dst' | 'on'>[] = []): HoodDay {
  let away = 0;
  let scored = 0;
  let better = 0;
  let missed = 0;
  let lit = 0;
  let unread = 0;
  for (const n of hood.nodes) {
    const s = nodeOnDay(n, date);
    if (s.lit) lit += 1;
    if (n.kind === 'measure' && s.lit) {
      if (s.look === 'unknown') unread += 1;
      else scored += 1;
      if (s.look === 'worse') away += 1;
      if (s.look === 'better') better += 1;
    }
    if (n.kind === 'routine' && s.look === 'worse') missed += 1;
  }
  const parts: string[] = [];
  if (scored) parts.push(away ? `${away} of ${scored} away from usual` : 'within usual');
  else if (unread) parts.push('no personal usual yet');
  if (better) parts.push(`${better} better`);
  if (missed) parts.push(parts.length ? `${missed} missed` : `${missed} routine${missed === 1 ? '' : 's'} missed`);
  const counted = hood.nodes.filter((n) => n.kind === 'shared_topic').length;
  const care = hood.nodes.every((n) => n.kind === 'care_action');
  // measures back within their usual on this day that the cloud ties to a care action here (order in time)
  const back = date ? new Set(edges.filter((e) => e.rel === 'after' && e.on.includes(date) && hood.nodes.some((n) => n.id === e.src)).map((e) => e.dst)).size : 0;
  if (!parts.length) parts.push(care && date ? (lit ? 'action logged' : back ? '' : 'no action this day') : lit ? `${lit} recorded` : counted === hood.nodes.length ? 'counts only' : date ? 'nothing recorded' : `${hood.nodes.length} on record`);
  if (back) parts.push(lit ? `${back} back the same day` : `${back} back within usual after it`);
  const said = parts.filter(Boolean);
  const brief = away ? `${away} of ${scored} away` : missed ? `${missed} missed` : back && !lit ? `${back} back after it` : said[0].replace('no personal usual yet', 'no usual yet').replace(' this day', '');
  return { away, scored, better, missed, lit, text: said.join(' · '), brief };
}

export interface Notable {
  node: Node;
  state: NodeOnDay;
}

/**
 * The nodes of a neighbourhood worth naming on a day, most telling first: measures away from usual, routines
 * missed, measures better than usual, then what was done or recorded. For the zoomed-out view.
 */
export function hoodNotable(hood: Hood, date: string | null): Notable[] {
  const rank = (n: Node, s: NodeOnDay) => (n.kind === 'care_action' ? 0 : s.look === 'worse' ? (n.kind === 'measure' ? 1 : 2) : s.look === 'better' ? 3 : n.kind === 'activity' || n.kind === 'routine' ? 4 : n.kind === 'measure' ? 5 : 6);
  const look = new Map(hood.nodes.map((n) => [n.id, nodeOnDay(n, date).look]));
  // an activity and its kept routine are one thing done; a missed routine speaks for its activity
  const twin = (n: Node) => (n.kind === 'routine' && look.get(n.id) !== 'worse' && look.has(`activity:${n.id.slice('routine:'.length)}`) && look.get(`activity:${n.id.slice('routine:'.length)}`) !== 'off');
  return hood.nodes
    .map((node, i) => ({ node, state: nodeOnDay(node, date), i }))
    .filter((x) => x.state.lit && !twin(x.node))
    .sort((a, b) => rank(a.node, a.state) - rank(b.node, b.state) || a.i - b.i)
    .map(({ node, state }) => ({ node, state }));
}

// ------------------------------------------------------------------ geometry

export interface PlacedRow extends MapRow {
  hood: string;
  /** which side of the picture the neighbourhood is on: left ones are mirrored, so their marks face the person */
  side: 'left' | 'right';
  y: number;
  markX: number;
  /** label box */
  labelX: number;
  labelW: number;
  /** value box (the day's reading, or the routine on the row); zero width when there is no room */
  valueX: number;
  valueW: number;
  /** where the routine's mark sits, when the row has one */
  chipX: number;
  /** the far end of the row, for a link leaving it away from the trunk */
  endX: number;
}

export interface PlacedHood {
  hood: Hood;
  side: 'left' | 'right';
  col: 0 | 1 | 2;
  x: number;
  y: number;
  w: number;
  h: number;
  trunkX: number;
  trunkTop: number;
  trunkBottom: number;
  /** where the spoke from the person arrives */
  port: { x: number; y: number };
}

export interface MapLayout {
  w: number;
  /** the height the picture needs; more than the room given when the rows do not fit at the smallest pitch */
  h: number;
  pitch: number;
  /** the corridor between two columns, and the width of a column */
  gap: number;
  cw: number;
  person: { x: number; y: number } | null;
  hoods: PlacedHood[];
  rows: PlacedRow[];
}

export const CAP = 24; // caption line of a neighbourhood
export const PAD = 4;
const GAP_Y = 8;
const PERSON = 64; // room kept for the person between the top and bottom middle neighbourhoods
const MIN_PITCH = 16;
const MAX_PITCH = 24;
const COLS: Place[][] = [
  ['nw', 'w', 'sw'],
  ['n', 'x', 's'],
  ['ne', 'e', 'se'],
];

const EDGE = 8; // between the box of a neighbourhood and the text in it
/** pixels a character of a value takes */
export const VALUE_CH = 6.4;
/** a routine on its activity's row: its mark, then a time or "missed" */
const CHIP_CH = 9;

const hoodHeight = (h: Hood, pitch: number) => CAP + h.rows.length * pitch + PAD;

const QUIET = new Set(['came up', 'logged', 'recorded']);

/** What a row prints beside its label for a day: the reading, the time, or how often a theme came up (a count). */
export function rowValue(node: Pick<Node, 'kind' | 'evidence'>, value: string): string {
  if (node.kind === 'shared_topic') return `${node.evidence}×`;
  return value && !QUIET.has(value) ? value : '';
}

const widestValue = (node: Node) => Math.max(rowValue(node, '').length, ...node.days.map((d) => rowValue(node, d.value).length));

function placeRows(hood: Hood, side: 'left' | 'right', x: number, y: number, w: number, pitch: number, valueW: number): { rows: PlacedRow[]; trunkX: number } {
  const trunkX = side === 'left' ? x + w - 7 : x + 7;
  const rows = hood.rows.map((r, i): PlacedRow => {
    const inset = 14 + r.depth * 14;
    const markX = side === 'left' ? trunkX - inset : trunkX + inset;
    // read left to right on both sides: label, then the day's value; on the left the mark closes the row
    const valueEnd = side === 'left' ? markX - 10 : x + w - EDGE;
    const labelX = side === 'left' ? x + EDGE + r.depth * 10 : markX + 10;
    // the value box is as wide as the widest value this node ever prints (a routine on the row takes it all), and
    // the label has the rest: it reads the same on every day
    const chars = r.chip ? CHIP_CH : widestValue(r.node);
    const room = Math.min(valueW, chars ? Math.ceil(chars * VALUE_CH) + 4 : 0);
    const valueX = valueEnd - room;
    const labelEnd = room ? valueX - 6 : valueEnd;
    return { ...r, hood: hood.id, side, y: y + CAP + (i + 0.5) * pitch, markX, labelX, labelW: Math.max(0, labelEnd - labelX), valueX, valueW: room, chipX: valueX + 7, endX: side === 'left' ? x : x + w };
  });
  return { rows, trunkX };
}

/**
 * Place the neighbourhoods in three columns around the person: west-side places on the left (mirrored), north and
 * south in the middle with the person between them, east-side places on the right. The row pitch shrinks until the
 * tallest column fits the room; below the smallest pitch the picture grows instead (the panel scrolls).
 */
export function layoutMap(hoods: Hood[], w: number, h: number): MapLayout {
  const width = Math.max(320, Math.floor(w));
  const wide = width >= 780;
  const gap = wide ? Math.round(Math.min(92, Math.max(46, width * 0.062))) : 14;
  const cw = Math.floor((width - 2 * gap) / 3);
  // the most a value may take: a reading is never cut ("1,001 steps"), the label gives way first
  const valueW = cw >= 236 ? 80 : cw >= 170 ? 74 : 0;
  const byPlace = new Map(hoods.map((x) => [x.place, x]));
  const cols = COLS.map((places) => places.map((p) => byPlace.get(p)).filter((x): x is Hood => Boolean(x)));
  const fixed = (c: Hood[], i: number) => c.length * (CAP + PAD) + Math.max(0, c.length - 1) * GAP_Y + (i === 1 ? PERSON : 0);
  const rowsIn = (c: Hood[]) => c.reduce((s, x) => s + x.rows.length, 0);
  const fits = cols.map((c, i) => (rowsIn(c) ? Math.floor(((h - fixed(c, i)) / rowsIn(c)) * 2) / 2 : MAX_PITCH));
  const pitch = Math.max(MIN_PITCH, Math.min(MAX_PITCH, ...fits));
  const height = Math.max(Math.floor(h), ...cols.map((c, i) => fixed(c, i) + rowsIn(c) * pitch), 120);
  const placedHoods: PlacedHood[] = [];
  const placedRows: PlacedRow[] = [];
  cols.forEach((c, i) => {
    const x = i * (cw + gap);
    const side = i === 0 ? 'left' : 'right';
    const tall = (hood: Hood | undefined) => (hood ? hoodHeight(hood, pitch) : 0);
    const top = c.find((hood) => hood.place.startsWith('n'));
    const bottom = c.find((hood) => hood.place.startsWith('s'));
    const middle = c.find((hood) => hood !== top && hood !== bottom);
    const yBottom = height - tall(bottom);
    // a north place at the top, a south place at the bottom, east or west between them, never touching;
    // in the middle column the person has the centre, so anything extra sits just above the south place
    const low = (bottom ? yBottom - GAP_Y : height) - tall(middle);
    const yMiddle = i === 1 ? low : Math.max(top ? tall(top) + GAP_Y : 0, Math.min((height - tall(middle)) / 2, low));
    for (const hood of c) {
      const y = Math.round(hood === top ? 0 : hood === bottom ? yBottom : yMiddle);
      const { rows, trunkX } = placeRows(hood, side, x, y, cw, pitch, valueW);
      const first = rows[0]?.y ?? y + CAP;
      const last = rows[rows.length - 1]?.y ?? y + CAP;
      placedHoods.push({ hood, side, col: i as 0 | 1 | 2, x, y, w: cw, h: tall(hood), trunkX, trunkTop: first, trunkBottom: last, port: { x: trunkX, y: first } });
      placedRows.push(...rows);
    }
  });
  const north = placedHoods.find((p) => p.hood.place === 'n');
  const south = placedHoods.find((p) => p.col === 1 && p.hood.place !== 'n');
  const from = north ? north.y + north.h : 0;
  const to = south ? Math.min(...placedHoods.filter((p) => p.col === 1 && p.hood.place !== 'n').map((p) => p.y)) : height;
  const person = { x: cw + gap + cw / 2, y: Math.round((from + to) / 2) };
  // a side neighbourhood is reached at its trunk, level with the person where it can be; one above or below, at its near edge
  for (const p of placedHoods)
    p.port = p.col === 1 ? { x: person.x, y: p.hood.place === 'n' ? p.y + p.h : p.y } : { x: p.trunkX, y: Math.max(p.trunkTop, Math.min(p.trunkBottom, person.y)) };
  return { w: width, h: height, pitch, gap, cw, person, hoods: placedHoods, rows: placedRows };
}

/** One neighbourhood on its own (a small panel zoomed into it): a single column, marks on the left. */
export function layoutHood(hood: Hood, w: number, pitch = 22): MapLayout {
  const width = Math.max(200, Math.floor(w));
  const { rows, trunkX } = placeRows(hood, 'right', 0, -CAP + 4, width, pitch, width >= 300 ? 80 : 66);
  const top = rows[0]?.y ?? 0;
  const bottom = rows[rows.length - 1]?.y ?? 0;
  const h = hood.rows.length * pitch + 8;
  return { w: width, h, pitch, gap: 0, cw: width, person: null, rows, hoods: [{ hood, side: 'right', col: 0, x: 0, y: 0, w: width, h, trunkX, trunkTop: top, trunkBottom: bottom, port: { x: trunkX, y: top } }] };
}

export interface Anchor {
  x: number;
  y: number;
  /** the direction a link leaves in: +1 to the right, -1 to the left, 0 from the person */
  out: -1 | 0 | 1;
}

/** Where links attach to a node: its mark (facing the person), or the far end of its row for a middle-column node
 *  linked to something on the right. */
export function anchorOf(layout: MapLayout, id: string, toward?: { x: number }): Anchor | null {
  for (const r of layout.rows) {
    const chip = r.chip?.id === id;
    if (r.node.id !== id && !chip) continue;
    const col = layout.hoods.find((p) => p.hood.id === r.hood)?.col ?? 0;
    if (chip) return { x: r.chipX, y: r.y, out: r.side === 'left' ? 1 : -1 };
    if (col === 1 && toward && toward.x > r.endX) return { x: r.endX, y: r.y, out: 1 };
    return { x: r.markX, y: r.y, out: r.side === 'left' ? 1 : -1 };
  }
  return layout.person && id === 'person' ? { ...layout.person, out: 0 } : null;
}

/** A calm curve between two anchors. Ends in the same column bow into the corridor they both face. */
export function linkPath(a: Anchor, b: Anchor): string {
  const f = (n: number) => Math.round(n * 10) / 10;
  if (Math.abs(a.x - b.x) < 40 && a.out === b.out && a.out !== 0) {
    const bow = a.out * Math.min(64, 22 + Math.abs(a.y - b.y) * 0.28);
    return `M${f(a.x)},${f(a.y)}C${f(a.x + bow)},${f(a.y)} ${f(b.x + bow)},${f(b.y)} ${f(b.x)},${f(b.y)}`;
  }
  const mx = (a.x + b.x) / 2;
  return `M${f(a.x)},${f(a.y)}C${f(mx)},${f(a.y)} ${f(mx)},${f(b.y)} ${f(b.x)},${f(b.y)}`;
}

/**
 * From a node or a neighbourhood to the person. The turn is made in the corridor beside the middle column and the
 * last stretch runs level through the room the person has between the middle neighbourhoods, so the line crosses
 * no box and no label: a side column sweeps across its corridor, a middle-column node bows out into it and back.
 */
export function personPath(layout: MapLayout, a: { x: number; y: number }): string {
  const p = layout.person;
  if (!p) return '';
  const f = (n: number) => Math.round(n * 10) / 10;
  const doorL = layout.cw + layout.gap;
  const doorR = doorL + layout.cw;
  const home = `L${f(p.x)},${f(p.y)}`;
  if (a.x < doorL - layout.gap / 2) {
    const mid = layout.cw + layout.gap / 2;
    return `M${f(a.x)},${f(a.y)}H${f(layout.cw)}C${f(mid)},${f(a.y)} ${f(mid)},${f(p.y)} ${f(doorL)},${f(p.y)}${home}`;
  }
  if (a.x > doorR + layout.gap / 2) {
    const mid = doorR + layout.gap / 2;
    return `M${f(a.x)},${f(a.y)}H${f(doorR + layout.gap)}C${f(mid)},${f(a.y)} ${f(mid)},${f(p.y)} ${f(doorR)},${f(p.y)}${home}`;
  }
  // in the middle column the marks face left: out into the left corridor, level with the person, and back in
  const c = (8 * (doorL - layout.gap / 2) - a.x - doorL) / 6;
  return `M${f(a.x)},${f(a.y)}C${f(c)},${f(a.y)} ${f(c)},${f(p.y)} ${f(doorL)},${f(p.y)}${home}`;
}

/** The caption of a neighbourhood in the room it has: the full name and the day's line when they fit, then the
 *  short name, then fewer words; never a cut-off count. */
export function hoodCaption(hood: Pick<Hood, 'label' | 'short'>, s: Pick<HoodDay, 'text' | 'brief'>, px: number): { name: string; sum: string } {
  const fits = (name: string, sum: string) => name.length * 7 + 8 + sum.length * 6.2 <= px;
  const compact = s.text.replace(' away from usual', ' away').replace('no personal usual yet', 'no usual yet');
  for (const [name, sum] of [[hood.label, s.text], [hood.short, s.text], [hood.label, compact], [hood.short, compact], [hood.short, s.brief]])
    if (fits(name, sum)) return { name, sum };
  return { name: hood.short, sum: fitLabel(s.brief, px - hood.short.length * 7 - 8, 6.2) };
}

// ------------------------------------------------------------------ words

/** Truncate a label to the pixels available (≈ 7 px a character at the caption size). */
export function fitLabel(label: string, px: number, per = 7): string {
  const max = Math.max(4, Math.floor(px / per));
  return label.length <= max ? label : `${label.slice(0, max - 1).trimEnd()}…`;
}

/** A row's label: whole when it fits, otherwise without its bracket ("Sleep (watch)" → "Sleep"), then cut.
 *  A reflection theme is always "Theme: sleep": a fixed label for what came up, never the person's words. */
export function rowLabel(label: string, px: number): string {
  const said = label.replace(/^Talked about: /, 'Theme: ');
  const max = Math.floor(px / 6.6);
  if (said.length <= max) return said;
  return fitLabel(said.replace(/\s*\(.*?\)/g, '').trim(), px, 6.6);
}

export type Rel = InsightEdge['rel'];

/** The relations that are learned from this record or declared between two nodes, as opposed to how the record is
 *  organised (the rows and the trunk already show those). */
export const LINK_RELS: Rel[] = ['helped', 'moved_first', 'followed', 'moved_together', 'after', 'kept_through', 'slipped_during', 'produces', 'about', 'talked_about', 'keeps'];

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
  talked_about: 'talked about',
  produces: 'produces',
  about: 'about',
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

export interface LinkLine {
  /** stable key */
  key: string;
  rel: Rel;
  /** the sentence, without the other nodes' names: "Moved 1 day later than (order, not cause)" style lead-in */
  lead: string;
  /** what follows the names, if anything */
  tail: string;
  others: string[];
  evidence: number;
}

/**
 * What links a node to what, as sentences. Links of one kind that say the same thing are told once, with every
 * node they reach ("Moved 1 day after …: Mood dial, Energy dial"). Order in time is never worded as cause.
 */
export function linkLines(id: string, edges: Edge[]): LinkLine[] {
  const out = new Map<string, LinkLine>();
  const put = (rel: Rel, variant: string, lead: string, tail: string, other: string, evidence: number) => {
    const key = `${rel}:${variant}`;
    const line = out.get(key) ?? { key, rel, lead, tail, others: [], evidence: 0 };
    if (other !== 'person' && !line.others.includes(other)) line.others.push(other);
    line.evidence = Math.max(line.evidence, evidence);
    out.set(key, line);
  };
  for (const e of edges) {
    if (e.src !== id && e.dst !== id) continue;
    const from = e.src === id;
    const other = from ? e.dst : e.src;
    switch (e.rel) {
      case 'produces':
        put(e.rel, from ? 'out' : 'in', from ? 'A session of it gives readings of' : 'Read during', `(${e.label})`, other, e.evidence);
        break;
      case 'about':
        put(e.rel, from ? 'out' : 'in', from ? 'About the same part of life as' : 'They talk about it:', from ? '(declared, not learned)' : '(a theme count, never their words)', other, e.evidence);
        break;
      case 'of':
      case 'keeps':
        if (e.rel === 'of') put('keeps', from ? 'of' : 'has', from ? 'A pattern of' : 'Kept as a routine:', '', other, e.evidence);
        else if (!from) put('keeps', 'kept', `This week ${e.label}`, '', other, e.evidence);
        break;
      case 'helped':
        put(e.rel, 'x', `Reported response: ${edgeWords(e).replace(/^helped · /, '')}`, '(what the person reported, not proof of effect)', other, e.evidence);
        break;
      case 'moved_first':
        put(e.rel, 'x', `Among the ${e.label.replace(/^first to move, /, 'first to move away from usual, ')}`, '', other, e.evidence);
        break;
      case 'followed':
        put(e.rel, `${from ? 'out' : 'in'}:${e.label}`, from ? 'Moved away first; these followed' : `${e.label.replace(/ \(order, not cause\)$/, '').replace(/^moved/, 'Moved away')} than`, from ? `${e.tag} (order, not cause)` : '(order, not cause)', other, e.evidence);
        break;
      case 'moved_together':
        put(e.rel, e.label, `${e.label[0].toUpperCase()}${e.label.slice(1)} as`, '', other, e.evidence);
        break;
      case 'after':
        put(e.rel, `${from ? 'out' : 'in'}:${e.label}`, from ? `${e.label[0].toUpperCase()}${e.label.slice(1)}:` : `${e.label[0].toUpperCase()}${e.label.slice(1).replace(/ after$/, '')} after`, '(order in time, not proof of effect)', other, e.evidence);
        break;
      case 'kept_through':
      case 'slipped_during':
        put(e.rel, 'x', `${e.rel === 'kept_through' ? 'Kept through the change' : 'Slipped during the change'}: ${e.label}`, '', other, e.evidence);
        break;
      case 'talked_about':
        put(e.rel, 'x', `Came up ${e.label}`, '(a theme count, never their words)', other, e.evidence);
        break;
      default:
        break;
    }
  }
  const rank: Rel[] = ['moved_first', 'followed', 'moved_together', 'after', 'helped', 'kept_through', 'slipped_during', 'keeps', 'produces', 'about', 'talked_about'];
  return [...out.values()].sort((a, b) => rank.indexOf(a.rel) - rank.indexOf(b.rel));
}

/** The nodes a node is linked to by something learned or declared: what stays lit when it is focused. */
export function neighboursOf(id: string, edges: Edge[]): Set<string> {
  const near = new Set<string>([id]);
  for (const e of edges) {
    if (e.rel === 'has_signal' || e.rel === 'measures' || e.rel === 'did') continue;
    if (e.src === id) near.add(e.dst);
    if (e.dst === id) near.add(e.src);
  }
  near.delete('person');
  near.add(id);
  return near;
}
