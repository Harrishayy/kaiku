'use client';

import Link from 'next/link';
import type { MeResponse } from '@contracts';
import { useApi } from '@/lib/api';
import { activityLabel } from '@/lib/format';
import { usePairing } from '@/lib/params';
import { NotOkButton } from '@/components/NotOkButton';
import { ErrorBox, Loading, PageHead, SimBadge } from '@/components/ui';

/** Person-facing view. Plain, warm language — no states, scores or alarming wording. */
export function MeView() {
  const pairing = usePairing();
  const me = useApi<MeResponse>(pairing ? `/v1/me?home_id=${encodeURIComponent(pairing.homeId)}` : null);
  if (!pairing) return <Loading />;
  const d = me.data;

  return (
    <>
      <PageHead title="Your week" lede="A gentle look at the last few days, in your own terms — compared only with your usual.">
        <SimBadge show={Boolean(d?.sim)} />
      </PageHead>
      {me.loading && !d && <Loading />}
      {me.error && !d && <ErrorBox error={me.error} onRetry={me.reload} what="your week" />}
      {d && (
        <div className="grid-2">
          <div>
            <section className="card">
              <p className="me-summary">{d.summary}</p>
              {d.last_week && d.last_week.length > 0 && (
                <ul className="me-lines">
                  {d.last_week.map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              )}
            </section>
            {d.next_suggestion && (
              <section className="card">
                <h2>Something to try today</h2>
                <p className="me-suggest">{activityLabel(d.next_suggestion.arm)}</p>
                <p className="muted">{d.next_suggestion.reason}</p>
              </section>
            )}
          </div>
          <div>
            {d.phq9_due && (
              <section className="card due">
                <h2>Your two-weekly questionnaire is due</h2>
                <p className="muted small">Nine short questions, about two minutes.</p>
                <Link className="btn" href="/phq9/">
                  Start PHQ-9
                </Link>
              </section>
            )}
            <section className="card">
              <h2>What seems to help you</h2>
              {d.what_helps && d.what_helps.length > 0 ? (
                <ul className="helps">
                  {[...d.what_helps]
                    .sort((a, b) => (b.mean_effect ?? -1) - (a.mean_effect ?? -1))
                    .map((h) => (
                      <li key={h.activity}>
                        <span>{h.label || activityLabel(h.activity)}</span>
                        <span className="bar" aria-hidden="true">
                          <span style={{ transform: `scaleX(${Math.max(0, Math.min(1, h.mean_effect ?? 0))})` }} />
                        </span>
                        <span className="muted small">tried {h.tries}×</span>
                      </li>
                    ))}
                </ul>
              ) : (
                <p className="muted small">Kaiku is still learning what helps you. Each breathing, drumming or walk adds to this.</p>
              )}
            </section>
            <section className="card">
              <h2>Your 2-minute session</h2>
              <p className="muted small">Optional, a few times a week. Nothing is recorded.</p>
              <Link className="btn btn-ghost" href="/session/">
                Start a session
              </Link>
            </section>
            <section className="card">
              <p className="small">If today feels like too much, you don’t have to handle it alone.</p>
              <NotOkButton homeId={pairing.homeId} token={pairing.token} />
            </section>
          </div>
        </div>
      )}
    </>
  );
}
