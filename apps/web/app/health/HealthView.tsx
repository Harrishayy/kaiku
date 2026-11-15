'use client';

import { useEffect, useState } from 'react';
import type { Health, HealthOverview, Healthz } from '@contracts';
import { useApi } from '@/lib/api';
import { fmt, relTime } from '@/lib/format';
import { Chip } from '@/components/dash/kit';
import { Empty, ErrorBox, Loading, PageHead, StaleNote } from '@/components/ui';

const STALE_S = 15; // heartbeats every 5 s; report is considered stale after 3 missed

function chipFor(status: Health['status'] | 'stale') {
  const tone = status === 'ok' ? 'ok' : status === 'degraded' ? 'warn' : status === 'stale' ? 'ins' : 'call';
  return (
    <Chip tone={tone}>{status}</Chip>
  );
}

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

export function HealthView() {
  const cloud = useApi<Healthz>('/healthz', 5000);
  const homes = useApi<HealthOverview>('/v1/health', 5000);
  const now = useNow();

  return (
    <>
      <PageHead title="System health" lede="Heartbeats from every node, the hub’s uplink queue, and the last error each node reported." />

      <section className="card" aria-labelledby="cloud-h">
        <h2 id="cloud-h">Cloud</h2>
        {cloud.loading && !cloud.data && <Loading />}
        {cloud.error && !cloud.data && <ErrorBox error={cloud.error} onRetry={cloud.reload} what="/healthz" />}
        <StaleNote show={Boolean(cloud.error && cloud.data)} />
        {cloud.data && (
          <div className="stats">
            <div>
              <div className="stat-label">Status</div>
              {chipFor(cloud.error ? 'down' : cloud.data.status)}
            </div>
            <div>
              <div className="stat-label">Version</div>
              <code>{cloud.data.version}</code> · schema v{cloud.data.schema_version}
            </div>
            <div>
              <div className="stat-label">Database</div>
              {cloud.data.db ? 'reachable' : 'unavailable'}
            </div>
            <div>
              <div className="stat-label">Explanation writer</div>
              <code>{cloud.data.llm}</code>
            </div>
          </div>
        )}
      </section>

      <section className="card" aria-labelledby="homes-h">
        <h2 id="homes-h">Homes</h2>
        {homes.loading && !homes.data && <Loading />}
        {homes.error && !homes.data && <ErrorBox error={homes.error} onRetry={homes.reload} what="node health" />}
        <StaleNote show={Boolean(homes.error && homes.data)} />
        {homes.data && Object.keys(homes.data.homes).length === 0 && (
          <Empty>No hub has reported yet. Run <code>make hub</code> with <code>KAIKU_CLOUD_URL</code> set.</Empty>
        )}
        {homes.data &&
          Object.entries(homes.data.homes).map(([homeId, rep]) => {
            const ageS = (now - Date.parse(rep.reported_at)) / 1000;
            const stale = !(ageS < STALE_S);
            return (
              <div key={homeId} style={{ marginBottom: 'var(--k-space-4)' }}>
                <h3>
                  <code>{homeId}</code>{' '}
                  <span className="muted small">
                    reported {relTime(rep.reported_at, now)} · uplink queue {rep.uplink_queue ?? 0}
                    {typeof rep.uplink_lag_s === 'number' ? ` · lag ${fmt(rep.uplink_lag_s, 1)} s` : ''}
                  </span>
                </h3>
                {stale && (
                  <p className="stale">No report for {Math.round(ageS)} s — the hub may be offline. Statuses below are its last known values.</p>
                )}
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Node</th>
                        <th scope="col">Status</th>
                        <th scope="col">Version</th>
                        <th scope="col">Uptime</th>
                        <th scope="col">Last error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(rep.nodes)
                        .sort(([a], [b]) => a.localeCompare(b))
                        .map(([node, h]) => (
                          <tr key={node}>
                            <td>
                              <strong>{node}</strong>
                              {h.details && h.details.sim === true ? <span className="muted small"> (sim)</span> : null}
                            </td>
                            <td>{chipFor(stale && h.status === 'ok' ? 'stale' : h.status)}</td>
                            <td>
                              <code>{h.version}</code>
                            </td>
                            <td className="num">{fmt(h.uptime_s / 60, 1)} min</td>
                            <td className="small">{h.last_error ?? <span className="muted">—</span>}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}
      </section>
    </>
  );
}
