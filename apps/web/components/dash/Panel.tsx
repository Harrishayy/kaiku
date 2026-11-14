'use client';

import { type CSSProperties, type KeyboardEvent, type ReactNode, useState } from 'react';
import { PANEL_TITLE, type PanelId, type Slot } from '@/lib/layout';
import { Glyph } from './kit';

export interface PanelControls {
  index: number;
  count: number;
  dragging: PanelId | null;
  maximised: boolean;
  onDragStart: (id: PanelId) => void;
  onDragEnd: () => void;
  onDrop: (target: PanelId) => void;
  onShift: (id: PanelId, delta: -1 | 1) => void;
  onPromote: (id: PanelId) => void;
  onCollapse: (id: PanelId) => void;
  onMaximise: (id: PanelId | null) => void;
}

const ICON = {
  grip: 'M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01',
  collapse: 'M6 15h12',
  max: 'M8 4H4v4M16 4h4v4M8 20H4v-4M16 20h4v-4',
  restore: 'M4 9h5V4M20 9h-5V4M4 15h5v5M20 15h-5v5',
};

/** The one card: title, summary line, move / maximise / collapse controls, internally scrolling body. */
export function Panel({
  id,
  slot,
  controls,
  meta,
  children,
}: {
  id: PanelId;
  slot: Slot;
  controls: PanelControls;
  meta?: ReactNode;
  children: ReactNode;
}) {
  const [over, setOver] = useState(false);
  const title = PANEL_TITLE[id];
  const { index, count, dragging, maximised } = controls;
  const style: CSSProperties = maximised
    ? { gridColumn: '1 / -1', gridRow: '1 / -1' }
    : { gridColumn: `${slot.c[0]} / ${slot.c[1]}`, gridRow: `${slot.r[0]} / ${slot.r[1]}` };

  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault();
      controls.onShift(id, -1);
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault();
      controls.onShift(id, 1);
    } else if (e.key === 'Home') {
      e.preventDefault();
      controls.onPromote(id);
    }
  };

  const droppable = dragging !== null && dragging !== id;
  return (
    <section
      className={`d-panel${index === 0 ? ' is-main' : ''}${maximised ? ' is-max' : ''}${over && droppable ? ' is-over' : ''}${dragging === id ? ' is-dragging' : ''}`}
      style={style}
      aria-labelledby={`panel-${id}-title`}
      data-panel={id}
      onDragOver={(e) => {
        if (!droppable) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        controls.onDrop(id);
      }}
    >
      <header className="d-panel-head">
        <button
          type="button"
          className="d-grip"
          draggable
          aria-label={`Move ${title}`}
          aria-roledescription="draggable panel"
          aria-describedby="d-move-hint"
          title={`Drag to move · position ${index + 1} of ${count}`}
          onKeyDown={onKey}
          onDragStart={(e) => {
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', id);
            controls.onDragStart(id);
          }}
          onDragEnd={controls.onDragEnd}
        >
          <Glyph d={ICON.grip} />
        </button>
        <h2 id={`panel-${id}-title`} className="d-panel-title">
          {title}
        </h2>
        {meta && <div className="d-panel-meta">{meta}</div>}
        <div className="d-panel-tools">
          <button
            type="button"
            className="d-tool"
            aria-pressed={maximised}
            aria-label={maximised ? `Restore ${title}` : `Maximise ${title}`}
            title={maximised ? 'Restore' : 'Maximise'}
            onClick={() => controls.onMaximise(maximised ? null : id)}
          >
            <Glyph d={maximised ? ICON.restore : ICON.max} />
          </button>
          <button type="button" className="d-tool" aria-label={`Collapse ${title}`} aria-expanded="true" aria-controls={`panel-${id}-body`} title="Collapse to the bar below" onClick={() => controls.onCollapse(id)}>
            <Glyph d={ICON.collapse} />
          </button>
        </div>
      </header>
      <div className="d-panel-body" id={`panel-${id}-body`} tabIndex={0} role="group" aria-label={`${title} content`}>
        {children}
      </div>
    </section>
  );
}
