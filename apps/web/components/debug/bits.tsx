'use client';

import type { ReactNode } from 'react';
import type { DebugDay, DebugEvent } from '@contracts';
import { SOURCE_OF } from '@contracts';
import { Glyph } from '@/components/dash/kit';
import { anchorOf, countsElsewhere, laneLabel, laneOf, localStamp, num, payloadLine, stampedOutside, type CiteTarget, type SectionId } from '@/lib/debug';

/** What every section needs to point at another row: jump there, and know which row was just jumped to. */
export interface Nav {
  jump: (target: CiteTarget) => void;
  /** DOM id of the row a citation or link just landed on */
  hit: string | null;
}

const CHEVRON = 'M9 6l6 6-6 6';

export function Chevron({ open }: { open: boolean }) {
  return (
    <span className={`dbg-chev${open ? ' is-open' : ''}`} aria-hidden="true">
      <Glyph d={CHEVRON} size={14} />
    </span>
  );
}

/** One collapsible step of the pipeline. The heading is the toggle; `meta` stays visible when it is closed. */
export function Section({
  id,
  title,
  meta,
  open,
  onToggle,
  children,
}: {
  id: SectionId;
  title: string;
  meta?: ReactNode;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section className="dbg-sec" id={`dbg-sec-${id}`} aria-labelledby={`dbg-h-${id}`}>
      <div className="dbg-sec-head">
        <h2 id={`dbg-h-${id}`}>
          <button type="button" className="dbg-sec-toggle" aria-expanded={open} aria-controls={`dbg-body-${id}`} onClick={onToggle}>
            <Chevron open={open} />
            {title}
          </button>
        </h2>
        {meta && <div className="dbg-sec-meta">{meta}</div>}
      </div>
      <div id={`dbg-body-${id}`} className="dbg-sec-body" hidden={!open}>
        {open && children}
      </div>
    </section>
  );
}

/**
 * A value beside the threshold it is held against. The relation is plain arithmetic on two served numbers;
 * `hot` says which side is worth a developer's eye (reaching a worse weight, falling under a confidence).
 */
export function Against({ value, min, digits = 2, hot, tone }: { value: number; min: number; digits?: number; hot: 'met' | 'unmet'; tone: 'ok' | 'warn' | 'ins' }) {
  const met = value >= min;
  return (
    <span className={`dbg-against${met === (hot === 'met') ? ` is-hot is-${tone}` : ''}`}>
      <span className="dbg-against-v">{num(value, digits)}</span>
      <span className="dbg-against-op">{met ? '≥' : '<'}</span>
      <span className="dbg-against-min">{num(min, digits)}</span>
    </span>
  );
}

export function Mono({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span className="dbg-mono" title={title}>
      {children}
    </span>
  );
}

/** A quiet word in a box: a raw enum, a flag, a count. */
export function Tag({ children, tone, title }: { children: ReactNode; tone?: 'warn' | 'ok' | 'bad' | 'new'; title?: string }) {
  return (
    <span className={`dbg-tag${tone ? ` dbg-tag-${tone}` : ''}`} title={title}>
      {children}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="dbg-empty">{children}</p>;
}

export interface EventMarks {
  /** ids that arrived in the latest refresh */
  fresh: Set<string>;
  /** id → when it was first seen, for everything that arrived while this page was watching */
  arrived: Map<string, string>;
}

/** The rows of an events table: one line per envelope; the toggle opens its full compact payload. */
export function EventRows({
  day,
  events,
  nav,
  marks,
  open,
  onToggle,
  anchors,
}: {
  day: DebugDay;
  events: DebugEvent[];
  nav: Nav;
  marks: EventMarks;
  open: Set<string>;
  onToggle: (id: string) => void;
  /** only the main timeline owns the anchors a citation jumps to */
  anchors: boolean;
}) {
  return (
    <>
      {events.map((e) => {
        const lane = laneOf(e, SOURCE_OF);
        const isOpen = open.has(e.id);
        const anchor = anchorOf.event(e.id);
        const fresh = marks.fresh.has(e.id);
        const seen = marks.arrived.get(e.id);
        const outside = stampedOutside(e, day);
        const elsewhere = countsElsewhere(e, day.metrics);
        const cls = [fresh ? 'is-new' : seen ? 'is-arrived' : '', anchors && nav.hit === anchor ? 'is-hit' : ''].filter(Boolean).join(' ');
        return (
          <tr key={e.id} id={anchors ? anchor : undefined} tabIndex={anchors ? -1 : undefined} className={cls || undefined}>
            <td className="dbg-mono dbg-nowrap">
              <button type="button" className="dbg-rowbtn" aria-expanded={isOpen} aria-label={`${isOpen ? 'Hide' : 'Show'} all fields of ${e.type} at ${e.local_time}`} onClick={() => onToggle(e.id)}>
                <Chevron open={isOpen} />
                {e.local_time}
              </button>
            </td>
            <td className="dbg-nowrap">
              {laneLabel(lane)}
              {e.source !== lane && (
                <>
                  {' '}
                  <Mono title="The envelope’s own source">{e.source}</Mono>
                </>
              )}
            </td>
            <td className="dbg-mono dbg-nowrap">{e.type}</td>
            <td className="dbg-num">{num(e.quality)}</td>
            <td>{e.sim && <Tag title="Sent by a simulated source, not a connected device">sim</Tag>}</td>
            <td className="dbg-mono dbg-payload">
              {isOpen ? <pre className="dbg-pre">{JSON.stringify({ id: e.id, ts: e.ts, ...e.payload }, null, 2)}</pre> : payloadLine(e.payload)}
            </td>
            <td>
              <span className="dbg-inline">
                {(e.metrics ?? []).map((m) =>
                  anchors ? (
                    <button key={m} type="button" className="dbg-cite" onClick={() => nav.jump({ section: 'metrics', anchor: anchorOf.metric(m) })}>
                      {m}
                    </button>
                  ) : (
                    <Mono key={m}>{m}</Mono>
                  ),
                )}
                {outside && (
                  <Tag tone="warn" title={`Stamped ${localStamp(e.ts, day.timezone)}, ${outside} this day’s bounds: listed here because it measures this day`}>
                    stamped {localStamp(e.ts, day.timezone).slice(5, 10)}
                  </Tag>
                )}
                {elsewhere && <Tag title="Stamped inside this day, but none of the metrics it names lists it here: it measures another day and counts there">counts on another day</Tag>}
                {fresh && <Tag tone="new">new</Tag>}
                {!fresh && seen && <Tag title={`First seen by this page at ${seen}`}>arrived {seen}</Tag>}
              </span>
            </td>
          </tr>
        );
      })}
    </>
  );
}
