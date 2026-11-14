'use client';

import { useEffect, useState } from 'react';
import type { ClinicianAskRequest, ClinicianAskResponse } from '@contracts';
import { api, type ApiError } from '@/lib/api';
import type { DashData } from '../data';
import { Busy, Chip } from '../kit';
import { Citation } from './ReviewPanel';

const STARTERS = ['What changed this week compared with their usual?', 'Which routines were kept?', 'What seems to help, and how sure is that?'];

interface Turn {
  q: string;
  a: ClinicianAskResponse | null;
  error: string | null;
}

export function AskPanel({ data, onMetric }: { data: DashData; onMetric: (m: string) => void }) {
  const [q, setQ] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => setTurns([]), [data.patient.id]);

  const ask = async (question: string) => {
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setQ('');
    try {
      const body: ClinicianAskRequest = { question: text };
      const a = await api<ClinicianAskResponse>(`/v1/patients/${encodeURIComponent(data.patient.id)}/ask`, { method: 'POST', body: JSON.stringify(body), timeoutMs: 45_000 });
      setTurns((t) => [{ q: text, a, error: null }, ...t]);
    } catch (e) {
      setTurns((t) => [{ q: text, a: null, error: (e as ApiError).status === null ? 'The service did not answer in time. Ask again in a moment.' : 'This question could not be answered from the record.' }, ...t]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="d-stack">
      <form
        className="d-ask"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(q);
        }}
      >
        <label className="d-field d-field-block">
          <span className="d-field-k">Question about this record</span>
          <textarea rows={2} maxLength={400} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Answers come only from this person’s recorded data" />
        </label>
        <button type="submit" className="d-btn d-btn-primary" disabled={busy || !q.trim()}>
          Ask
        </button>
      </form>
      {turns.length === 0 && !busy && (
        <ul className="d-starters" aria-label="Example questions">
          {STARTERS.map((s) => (
            <li key={s}>
              <button type="button" className="d-cite" onClick={() => void ask(s)}>
                {s}
              </button>
            </li>
          ))}
        </ul>
      )}
      {busy && <Busy label="Reading the record…" />}
      <ol className="d-findings" aria-live="polite">
        {turns.map((t, i) => (
          <li key={`${t.q}-${turns.length - i}`} className="d-finding">
            <p className="d-strong">{t.q}</p>
            {t.error ? (
              <p className="d-callout d-callout-warn">{t.error}</p>
            ) : t.a ? (
              <>
                <p className="d-answer">{t.a.answer}</p>
                <div className="d-byline">
                  <Chip tone={t.a.by === 'gemma' ? 'info' : 'neutral'}>{t.a.by === 'gemma' ? 'Written by Gemma' : 'Rule-based answer'}</Chip>
                  <span className="d-meta">
                    {t.a.model ?? ''}
                    {t.a.cached ? ' · from cache' : ''}
                  </span>
                </div>
                {(t.a.citations ?? []).length > 0 ? (
                  <div className="d-citelist" aria-label="Cited records">
                    {(t.a.citations ?? []).map((c) => (
                      <Citation key={c.id} e={c} onMetric={c.metric && data.series.some((s) => s.metric === c.metric) ? onMetric : undefined} />
                    ))}
                  </div>
                ) : (
                  <p className="d-muted">No record was cited for this answer.</p>
                )}
              </>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
