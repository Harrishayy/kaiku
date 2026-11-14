'use client';

import { useEffect, useState } from 'react';
import type { ActionRequest, ActionResult } from '@contracts';
import { api, type ApiError } from '@/lib/api';
import { stateChip } from '@/lib/labels';
import { ACTION_LABEL, dateTime } from '@/lib/format';
import type { DashData } from '../data';
import { Chip } from '../kit';

type Action = ActionRequest['action'];
const ACTIONS: { action: Action; hint: string }[] = [
  { action: 'acknowledge', hint: 'Marks the current state as seen by the care team.' },
  { action: 'send_message', hint: 'Kaiku passes your note to the person at home.' },
  { action: 'flag_booster', hint: 'Adds a flag for the treating clinic.' },
  { action: 'flag_icbt_referral', hint: 'Adds a referral flag.' },
];
const BY_KEY = 'kaiku.dashboard.by';

interface Logged {
  at: string;
  action: Action;
  note: string;
  by: string;
  state: string;
}

export function CarePanel({ data }: { data: DashData }) {
  const [note, setNote] = useState('');
  const [by, setBy] = useState('');
  const [busy, setBusy] = useState<Action | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<Logged[]>([]);
  useEffect(() => {
    try {
      setBy(window.localStorage.getItem(BY_KEY) ?? '');
    } catch {
      /* storage blocked */
    }
  }, []);
  useEffect(() => setLog([]), [data.patient.id]);

  const run = async (action: Action) => {
    if (action === 'send_message' && !note.trim()) {
      setError('Write the message in the note first.');
      return;
    }
    setBusy(action);
    setError(null);
    try {
      const body: ActionRequest = { action, note: note.trim() || null, by: by.trim() || null };
      const r = await api<ActionResult>(`/v1/patients/${encodeURIComponent(data.patient.id)}/actions`, { method: 'POST', body: JSON.stringify(body) });
      try {
        window.localStorage.setItem(BY_KEY, by.trim());
      } catch {
        /* storage blocked */
      }
      setLog((l) => [{ at: new Date().toISOString(), action, note: note.trim(), by: by.trim(), state: stateChip(r.state, data.consensus.agreement).label }, ...l]);
      setNote('');
      data.reload();
    } catch (e) {
      setError((e as ApiError).status === null ? 'The service did not answer. Nothing was recorded; try again.' : 'The action was not recorded. Try again.');
    } finally {
      setBusy(null);
    }
  };

  // the record's own log when the service sends it; otherwise what was recorded in this visit
  const history: Logged[] = data.view.actions.length
    ? [...data.view.actions].reverse().map((x) => ({ at: x.ts, action: x.action, note: x.note ?? '', by: x.by ?? '', state: '' }))
    : log;
  const suggested = (data.consensus.explanation?.suggested_actions ?? []).filter((a) => a !== 'none');

  return (
    <div className="d-stack">
      {suggested.length > 0 && (
        <div className="d-chips" aria-label="Suggested by the consensus">
          <span className="d-meta">Suggested</span>
          {suggested.map((a) => (
            <Chip key={a} tone="info">
              {ACTION_LABEL[a] ?? a}
            </Chip>
          ))}
        </div>
      )}
      <label className="d-field d-field-block">
        <span className="d-field-k">Note</span>
        <textarea rows={3} maxLength={600} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What you saw and what you decided" />
      </label>
      <label className="d-field d-field-block">
        <span className="d-field-k">Your name or initials</span>
        <input type="text" maxLength={40} value={by} onChange={(e) => setBy(e.target.value)} autoComplete="off" />
      </label>
      <ul className="d-actions">
        {ACTIONS.map((a) => (
          <li key={a.action}>
            <button type="button" className={a.action === 'acknowledge' ? 'd-btn d-btn-primary' : 'd-btn'} disabled={busy !== null} onClick={() => run(a.action)}>
              {busy === a.action ? 'Recording…' : ACTION_LABEL[a.action]}
            </button>
            <span className="d-muted">{a.hint}</span>
          </li>
        ))}
      </ul>
      {error && (
        <p className="d-callout d-callout-warn" role="alert">
          {error}
        </p>
      )}
      <section aria-label="Care action log">
        <h3 className="d-h3">Care action log</h3>
        {history.length === 0 ? (
          <p className="d-muted">Nothing recorded yet. Actions are saved to the record with your note.</p>
        ) : (
          <ul className="d-rows" role="status">
            {history.map((l) => (
              <li key={`${l.at}-${l.action}`} className="d-row-item">
                <div className="d-row-head">
                  <span className="d-row-title">{ACTION_LABEL[l.action]}</span>
                  <span className="d-meta">{dateTime(l.at)}</span>
                </div>
                {l.note && <p>{l.note}</p>}
                <p className="d-meta">
                  {l.by ? `By ${l.by}` : 'Name not given'}
                  {l.state ? ` · consensus after this: ${l.state}` : ''}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
