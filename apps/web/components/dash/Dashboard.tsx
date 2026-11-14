'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PatientsResponse } from '@contracts';
import { useApi } from '@/lib/api';
import { consensusSentence, shortDay } from '@/lib/clinician';
import { stateChip } from '@/lib/labels';
import { credentialsChanged } from '@/lib/credentials';
import { relTime, sortByState } from '@/lib/format';
import {
  LAYOUT_KEY,
  PANEL_TITLE,
  defaultLayout,
  dropPanel,
  promotePanel,
  readLayout,
  shiftPanel,
  slots,
  togglePanel,
  type Layout,
  type PanelId,
} from '@/lib/layout';
import { useQueryParam } from '@/lib/params';
import { Mascot } from '../Mascot';
import { useRecord, type DashData } from './data';
import { Busy, Chip, EmptyState, Problem } from './kit';
import { Panel, type PanelControls } from './Panel';
import { AskPanel } from './panels/AskPanel';
import { CarePanel } from './panels/CarePanel';
import { ConsensusPanel } from './panels/ConsensusPanel';
import { CoveragePanel } from './panels/CoveragePanel';
import { EvidencePanel } from './panels/EvidencePanel';
import { GraphPanel } from './panels/GraphPanel';
import { ReviewPanel } from './panels/ReviewPanel';
import { RoutinePanel } from './panels/RoutinePanel';
import { TrendsPanel } from './panels/TrendsPanel';

const fitLayout = () => defaultLayout(window.innerWidth, window.innerHeight);

function loadLayout(): Layout {
  try {
    return readLayout(window.localStorage.getItem(LAYOUT_KEY), fitLayout);
  } catch {
    return fitLayout();
  }
}

function saveLayout(l: Layout) {
  try {
    window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(l));
  } catch {
    /* storage blocked: the layout lasts for this visit */
  }
}

export function Dashboard() {
  const patients = useApi<PatientsResponse>('/v1/patients', 30_000);
  const wanted = useQueryParam('id');
  const list = useMemo(() => sortByState(patients.data?.patients ?? []), [patients.data]);
  const patient = wanted === undefined ? null : (list.find((p) => p.id === wanted) ?? list[0] ?? null);
  const record = useRecord(patient);

  const [layout, setLayout] = useState<Layout>(() => defaultLayout());
  const [ready, setReady] = useState(false);
  const [dragging, setDragging] = useState<PanelId | null>(null);
  const [maximised, setMaximised] = useState<PanelId | null>(null);
  const [metric, setMetric] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [said, setSaid] = useState('');
  const focusAfter = useRef<PanelId | null>(null);

  useEffect(() => {
    setLayout(loadLayout());
    setReady(true);
  }, []);

  const update = useCallback((next: (l: Layout) => Layout, message: (l: Layout) => string) => {
    setLayout((prev) => {
      const l = next(prev);
      if (l !== prev) {
        saveLayout(l);
        setSaid(message(l));
      }
      return l;
    });
  }, []);

  useEffect(() => {
    if (!maximised) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMaximised(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [maximised]);

  // Keep keyboard focus on the grip after a keyboard move, so repeated arrow presses keep working.
  useEffect(() => {
    const id = focusAfter.current;
    if (!id) return;
    focusAfter.current = null;
    document.querySelector<HTMLButtonElement>(`[data-panel="${id}"] .d-grip`)?.focus();
  });

  const place = (l: Layout, id: PanelId) => `${PANEL_TITLE[id]} is now panel ${l.order.indexOf(id) + 1} of ${l.order.length}.`;
  const base: Omit<PanelControls, 'index' | 'count' | 'maximised'> = {
    dragging,
    onDragStart: setDragging,
    onDragEnd: () => setDragging(null),
    onDrop: (target) => {
      if (dragging) update((l) => dropPanel(l, dragging, target), (l) => place(l, dragging));
      setDragging(null);
    },
    onShift: (id, delta) => {
      focusAfter.current = id;
      update((l) => shiftPanel(l, id, delta), (l) => place(l, id));
    },
    onPromote: (id) => {
      focusAfter.current = id;
      update((l) => promotePanel(l, id), () => `${PANEL_TITLE[id]} is now the main panel.`);
    },
    onCollapse: (id) => {
      if (maximised === id) setMaximised(null);
      update((l) => togglePanel(l, id), () => `${PANEL_TITLE[id]} collapsed to the bar below.`);
    },
    onMaximise: setMaximised,
  };

  const open = useCallback(
    (id: PanelId) => update((l) => (l.order.includes(id) ? l : togglePanel(l, id)), () => `${PANEL_TITLE[id]} opened.`),
    [update],
  );
  const showMetric = useCallback(
    (m: string) => {
      setMetric(m);
      open('trends');
      setMaximised((cur) => (cur && cur !== 'trends' ? null : cur));
    },
    [open],
  );
  const showDay = useCallback(
    (d: string) => {
      setDay(d);
      open('evidence');
      setMaximised((cur) => (cur && cur !== 'evidence' ? null : cur));
    },
    [open],
  );

  const select = (id: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set('id', id);
    window.history.pushState(null, '', url.toString());
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  const rects = slots(layout.order.length);
  const data = record.data;
  const body = (id: PanelId, d: DashData) => {
    switch (id) {
      case 'trends':
        return <TrendsPanel data={d} metric={metric} onMetric={setMetric} onDay={showDay} />;
      case 'consensus':
        return <ConsensusPanel data={d} onMetric={showMetric} />;
      case 'review':
        return <ReviewPanel data={d} onMetric={showMetric} />;
      case 'routine':
        return <RoutinePanel data={d} />;
      case 'graph':
        return <GraphPanel data={d} onMetric={showMetric} maximised={maximised === 'graph'} onMaximise={() => setMaximised('graph')} />;
      case 'evidence':
        return <EvidencePanel data={d} day={day} onDay={(x) => setDay(x || null)} onMetric={showMetric} />;
      case 'care':
        return <CarePanel data={d} />;
      case 'ask':
        return <AskPanel data={d} onMetric={showMetric} />;
      case 'coverage':
        return <CoveragePanel data={d} onDay={showDay} />;
    }
  };

  return (
    <div className="dash">
      <a className="d-skip" href="#dash-panels">
        Skip to panels
      </a>
      <header className="d-top">
        <div className="d-brand">
          <Mascot size={30} still tappable={false} />
          <div className="d-brand-text">
            <span className="d-brand-name">Kaiku</span>
            <span className="d-brand-sub">Practitioner dashboard</span>
          </div>
        </div>
        {data ? <HeaderFacts data={data} people={list} onSelect={select} /> : <div className="d-top-fill" />}
        <div className="d-top-actions">
          <CareAccess />
          <button
            type="button"
            className="d-btn d-btn-quiet"
            onClick={() => {
              setMaximised(null);
              update(() => fitLayout(), () => 'Layout reset.');
            }}
          >
            Reset layout
          </button>
        </div>
      </header>

      <main id="dash-panels" className="d-main" data-ready={ready}>
        {!data ? (
          <div className="d-fullstate">
            {patients.error && !patients.data ? (
              <Problem what="The record list" error={patients.error} onRetry={patients.reload} />
            ) : record.error ? (
              <Problem what="This record" error={record.error} onRetry={record.reload} />
            ) : patients.data && list.length === 0 ? (
              <EmptyState title="No one is connected yet">
                When a person pairs their Kaiku and their first check-in arrives, their record opens here.
              </EmptyState>
            ) : (
              <Busy label="Opening the record…" />
            )}
          </div>
        ) : layout.order.length === 0 ? (
          <div className="d-fullstate">
            <EmptyState title="Every panel is collapsed">Open one from the bar below, or reset the layout.</EmptyState>
          </div>
        ) : (
          <div className={`d-grid${maximised ? ' has-max' : ''}`} data-count={layout.order.length}>
            {layout.order.map((id, i) => (
              <Panel
                key={id}
                id={id}
                slot={rects[i]}
                controls={{ ...base, index: i, count: layout.order.length, maximised: maximised === id }}
              >
                {body(id, data)}
              </Panel>
            ))}
          </div>
        )}
      </main>

      <footer className="d-dock">
        <div
          className={`d-dock-panels${dragging && layout.order.includes(dragging) ? ' is-target' : ''}`}
          onDragOver={(e) => {
            if (dragging && layout.order.includes(dragging)) e.preventDefault();
          }}
          onDrop={(e) => {
            e.preventDefault();
            if (dragging && layout.order.includes(dragging)) base.onCollapse(dragging);
            setDragging(null);
          }}
        >
          <span className="d-dock-label">{layout.docked.length ? 'Collapsed' : 'All panels open'}</span>
          {layout.docked.map((id) => (
            <button
              key={id}
              type="button"
              className="d-dock-chip"
              draggable
              aria-label={`Open ${PANEL_TITLE[id]}`}
              onClick={() => open(id)}
              onDragStart={(e) => {
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', id);
                setDragging(id);
              }}
              onDragEnd={() => setDragging(null)}
            >
              <span aria-hidden="true">+</span> {PANEL_TITLE[id]}
            </button>
          ))}
        </div>
        <div className="d-dock-aside">
          <span title="Not a medical device. Kaiku explains a consensus; it never decides care.">Research prototype</span>
          <nav aria-label="Team pages" className="d-team">
            <Link href="/health/">System health</Link>
            <Link href="/eval/">Evaluation</Link>
            <Link href="/tune/">Tuning</Link>
          </nav>
        </div>
      </footer>
      <p className="d-sr" id="d-move-hint">
        Drag onto another panel to swap places, or use the arrow keys. Home makes it the main panel.
      </p>
      <div className="d-sr" role="status" aria-live="polite">
        {said}
      </div>
    </div>
  );
}

function HeaderFacts({
  data,
  people,
  onSelect,
}: {
  data: DashData;
  people: PatientsResponse['patients'];
  onSelect: (id: string) => void;
}) {
  const { patient, consensus, recorded } = data;
  const stage = data.view.stage;
  const chip = stateChip(consensus.state, consensus.agreement);
  const last = patient.last_activity_at ?? null;
  return (
    <div className="d-facts">
      <div className="d-person">
        {people.length > 1 ? (
          <label className="d-switch">
            <span className="d-sr">Person</span>
            <select value={patient.id} onChange={(e) => onSelect(e.target.value)}>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="d-person-name" title={patient.display_name}>
            {patient.display_name}
          </span>
        )}
        {consensus.simulated && (
          <span className="d-sim" title="This record was seeded from simulated sources, not connected devices">
            Simulated record
          </span>
        )}
      </div>
      <div className="d-fact">
        <span className="d-fact-k">Record</span>
        <span
          className="d-fact-v"
          title={`${recorded.days} recorded ${recorded.days === 1 ? 'day' : 'days'}${recorded.first && recorded.last ? `, ${shortDay(recorded.first)} to ${shortDay(recorded.last)}` : ''}.${stage.early && !stage.building ? ' Scored against an early baseline: lower confidence.' : ''}`}
        >
          Day {stage.day || recorded.days}
          <span className="d-fact-note">{stage.building ? 'building their usual' : stage.early ? 'early baseline' : `${recorded.days} days of data`}</span>
        </span>
      </div>
      <div className="d-fact d-fact-wide">
        <span className="d-fact-k">Consensus</span>
        <span className="d-fact-v">
          <Chip tone={chip.tone}>
            {chip.label}
            {consensus.acknowledged_by ? ' · acknowledged' : ''}
          </Chip>
          <span className="d-fact-note" title={data.view.statusLine || consensusSentence(consensus)}>
            {data.view.statusLine || consensusSentence(consensus)}
          </span>
        </span>
      </div>
      <div className="d-fact">
        <span className="d-fact-k">Freshness</span>
        <span className="d-fact-v">
          {data.stale ? (
            <Chip tone="warn" title={`The service is not answering; showing the last data received${last ? ` (${relTime(last)})` : ''}. Retrying.`}>
              Connection lost
            </Chip>
          ) : last ? (
            `Last data ${relTime(last)}`
          ) : (
            'No data received yet'
          )}
        </span>
      </div>
    </div>
  );
}

/** Credentials stay in this browser tab, never in links or source files. */
function CareAccess() {
  const [value, setValue] = useState('');
  const [status, setStatus] = useState('');
  const ref = useRef<HTMLDetailsElement>(null);
  return (
    <details className="d-pop" ref={ref}>
      <summary className="d-btn d-btn-quiet">Care team access</summary>
      <form
        className="d-pop-body"
        onSubmit={(e) => {
          e.preventDefault();
          try {
            sessionStorage.setItem('kaiku.clinician', value.trim());
            setValue('');
            setStatus('Access updated.');
            credentialsChanged();
          } catch {
            setStatus('This browser cannot keep access for this tab.');
          }
        }}
      >
        <label htmlFor="care-token">Access token</label>
        <input id="care-token" type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} required />
        <div className="d-row">
          <button className="d-btn d-btn-primary" type="submit">
            Connect
          </button>
          <button
            className="d-btn"
            type="button"
            onClick={() => {
              try {
                sessionStorage.removeItem('kaiku.clinician');
              } catch {
                /* nothing stored */
              }
              setStatus('Signed out.');
              credentialsChanged();
            }}
          >
            Sign out
          </button>
        </div>
        <p className="d-note">Access lasts for this browser tab only.</p>
        <p className="d-note" role="status">
          {status}
        </p>
      </form>
    </details>
  );
}
