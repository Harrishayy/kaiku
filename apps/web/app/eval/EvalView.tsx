'use client';

import type { EvalResult } from '@contracts';
import { useApi } from '@/lib/api';
import { STATE_LABEL, fmt, pct, prettify, relTime, sourceLabel, type State } from '@/lib/format';
import { ErrorBox, Loading, PageHead, SimBadge } from '@/components/ui';

export function EvalView() {
  const { data, error, loading, reload } = useApi<EvalResult>('/v1/eval');

  return (
    <>
      <PageHead
        title="Simulation"
        lede="We simulate synthetic patients — some stable, some drifting from a known day — run the same consensus rule the dashboard uses, and measure how often “needs a call” is right, how early it comes, and what happens when one source goes missing."
      >
        <SimBadge />
      </PageHead>

      {loading && !data && <Loading label="Loading evaluation…" />}
      {error && !data && <ErrorBox error={error} onRetry={reload} what="evaluation results" />}

      {data && (
        <>
          <div className="stats">
            <div className="card stat">
              <div className="stat-value">{data.n_patients}</div>
              <div className="stat-label">synthetic patients</div>
            </div>
            <div className="card stat">
              <div className="stat-value">{fmt(data.false_needs_call_per_patient_month, 2)}</div>
              <div className="stat-label">false “needs a call” per patient-month</div>
            </div>
            <div className="card stat">
              <div className="stat-value">{data.median_lead_time_days === null ? '—' : `${fmt(data.median_lead_time_days, 1)} d`}</div>
              <div className="stat-label">median lead time vs. simulated onset</div>
            </div>
            <div className="card stat">
              <div className="stat-value">
                <code>{data.rule_version}</code>
              </div>
              <div className="stat-label">consensus rule</div>
            </div>
          </div>

          <section className="card" style={{ marginTop: 16 }} aria-labelledby="ps-h">
            <h2 id="ps-h">Per state</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">State</th>
                    <th scope="col">Precision</th>
                    <th scope="col">Recall</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.per_state).map(([state, s]) => (
                    <tr key={state}>
                      <td>{STATE_LABEL[state as State] ?? prettify(state)}</td>
                      <td className="num">{pct(s.precision)}</td>
                      <td className="num">{pct(s.recall)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {data.ablation && Object.keys(data.ablation).length > 0 && (
            <section className="card" aria-labelledby="ab-h">
              <h2 id="ab-h">Losing one source</h2>
              <p className="muted small">“Needs a call” precision and recall when that source is removed entirely.</p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Without</th>
                      <th scope="col">Precision</th>
                      <th scope="col">Recall</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(data.ablation).map(([src, s]) => (
                      <tr key={src}>
                        <td>{sourceLabel(src)}</td>
                        <td className="num">{pct(s.precision)}</td>
                        <td className="num">{pct(s.recall)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <p className="muted small" style={{ marginTop: 14 }}>
            Generated {relTime(data.generated_at)}. Synthetic patients, not clinical accuracy: these numbers check that the rule behaves
            as designed and show how it fails.
          </p>
        </>
      )}
    </>
  );
}
