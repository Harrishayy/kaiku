/**
 * Dashboard panel layout (pure, unit-tested). The layout is an ordered list of open panels (the first one is the
 * main panel) plus the panels parked in the dock. Slots are computed from how many panels are open, so panels can
 * never overlap: moving a panel only changes the order, collapsing one only moves it to the dock.
 */

export const PANEL_IDS = ['trends', 'consensus', 'review', 'routine', 'graph', 'evidence', 'care', 'ask', 'coverage'] as const;
export type PanelId = (typeof PANEL_IDS)[number];

export const PANEL_TITLE: Record<PanelId, string> = {
  trends: 'Trends',
  consensus: 'Consensus now',
  review: 'Kaiku’s review',
  routine: 'Routine',
  graph: 'Knowledge graph',
  evidence: 'Daily account',
  care: 'Care actions & notes',
  ask: 'Ask the record',
  coverage: 'Coverage',
};

export interface Layout {
  /** open panels in slot order; order[0] is the main panel */
  order: PanelId[];
  /** collapsed panels, in dock order */
  docked: PanelId[];
}

export const LAYOUT_KEY = 'kaiku.dashboard.layout.v6';

const PRIORITY: PanelId[] = ['trends', 'consensus', 'review', 'evidence', 'graph', 'routine', 'care', 'ask', 'coverage'];

/**
 * Default layout for a viewport: Trends (main), Consensus now and Kaiku's review are always open, side by side;
 * the Daily account and the Knowledge graph (as its small overview: the parts of life on the chosen day) join them
 * when the screen is at least 1280 wide and 800 high. The rest, Routine first, wait in the dock.
 */
export const defaultLayout = (width = 1440, height = 900): Layout => {
  const open = width >= 1280 && height >= 800 ? 5 : 3;
  return { order: PRIORITY.slice(0, open), docked: PRIORITY.slice(open) };
};

const isPanel = (v: unknown): v is PanelId => typeof v === 'string' && (PANEL_IDS as readonly string[]).includes(v);

/** Parse a saved layout. Unknown ids are dropped, missing panels are docked, duplicates collapse to one. */
export function readLayout(raw: string | null | undefined, fallback: () => Layout = defaultLayout): Layout {
  if (!raw) return fallback();
  try {
    const v = JSON.parse(raw) as { order?: unknown; docked?: unknown };
    if (!v || typeof v !== 'object' || !Array.isArray(v.order) || !Array.isArray(v.docked)) return fallback();
    const seen = new Set<PanelId>();
    const take = (list: unknown[]) =>
      list.filter(isPanel).filter((id) => (seen.has(id) ? false : (seen.add(id), true)));
    const order = take(v.order);
    const docked = take(v.docked);
    for (const id of PANEL_IDS) if (!seen.has(id)) docked.push(id);
    return { order, docked };
  } catch {
    return fallback();
  }
}

export const isOpen = (l: Layout, id: PanelId) => l.order.includes(id);

/** Collapse to the dock, or expand from it (to the end of the open panels). */
export function togglePanel(l: Layout, id: PanelId): Layout {
  if (l.order.includes(id)) return { order: l.order.filter((p) => p !== id), docked: [...l.docked.filter((p) => p !== id), id] };
  return { order: [...l.order.filter((p) => p !== id), id], docked: l.docked.filter((p) => p !== id) };
}

/** Move an open panel one slot earlier (-1) or later (+1). Out-of-range moves return the same layout. */
export function shiftPanel(l: Layout, id: PanelId, delta: -1 | 1): Layout {
  const i = l.order.indexOf(id);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= l.order.length) return l;
  const order = [...l.order];
  [order[i], order[j]] = [order[j], order[i]];
  return { ...l, order };
}

/** Drop `id` on `target`: the two swap slots. Dropping a docked panel opens it in the target's slot. */
export function dropPanel(l: Layout, id: PanelId, target: PanelId): Layout {
  if (id === target || !l.order.includes(target)) return l;
  const order = [...l.order];
  const t = order.indexOf(target);
  const i = order.indexOf(id);
  if (i >= 0) {
    [order[i], order[t]] = [order[t], order[i]];
    return { ...l, order };
  }
  order.splice(t, 0, id);
  return { order, docked: l.docked.filter((p) => p !== id) };
}

/** Make a panel the main one (slot 0), opening it if needed. */
export function promotePanel(l: Layout, id: PanelId): Layout {
  return { order: [id, ...l.order.filter((p) => p !== id)], docked: l.docked.filter((p) => p !== id) };
}

export interface Slot {
  /** 1-based grid lines on a 12 × 12 grid: column start / end, row start / end */
  c: [number, number];
  r: [number, number];
}

/**
 * Slot rectangles for n open panels on a 12 × 12 grid. Slot 0 is the main panel: the full-height left column.
 * The other panels tile the right column in at most two columns. The rectangles tile the grid exactly (tested),
 * so panels cannot overlap or leave holes.
 */
export function slots(n: number): Slot[] {
  const count = Math.max(0, Math.min(PANEL_IDS.length, Math.floor(n)));
  if (count === 0) return [];
  if (count === 1) return [{ c: [1, 13], r: [1, 13] }];
  const k = count - 1;
  const split = k === 1 ? 9 : 7; // where the main panel ends
  const out: Slot[] = [{ c: [1, split], r: [1, 13] }];
  if (k === 1) return [...out, { c: [split, 13], r: [1, 13] }];
  // two side panels stand side by side, full height, so both are readable at a glance
  if (k === 2) return [...out, { c: [7, 10], r: [1, 13] }, { c: [10, 13], r: [1, 13] }];
  const rows = Math.ceil(k / 2);
  const mid = split + (13 - split) / 2;
  const edges = Array.from({ length: rows + 1 }, (_, i) => 1 + Math.round((i * 12) / rows));
  let row = 0;
  let left = k;
  if (k % 2 === 1) {
    // an odd panel out takes the whole first row
    out.push({ c: [split, 13], r: [edges[0], edges[1]] });
    row = 1;
    left -= 1;
  }
  for (; left > 0; left -= 2, row++) {
    out.push({ c: [split, mid], r: [edges[row], edges[row + 1]] });
    out.push({ c: [mid, 13], r: [edges[row], edges[row + 1]] });
  }
  return out;
}
