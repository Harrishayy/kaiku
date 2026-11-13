'use client';

import Link from 'next/link';
import { CONSENSUS_SOURCES, type PatientsResponse, type SourceBadge } from '@contracts';
import { useApi } from '@/lib/api';
import { STATE_LABEL, relTime, sortByState, sourceLabel, type State } from '@/lib/format';
import { AgreementBadge, Empty, ErrorBox, Loading, PageHead, SimBadge, StaleNote, StateChip, VerdictChip } from '@/components/ui';

const ORDER: State[] = ['safety', 'needs_call', 'watch', 'stable'];

/** Source badges in a stable order: the known sources first, then any new source the cloud reports. */
function orderedSources(badges: SourceBadge[]): { source: string; badge?: SourceBadge }[] {
  const known = CONSENSUS_SOURCES.map((s) => ({ source: s as string, badge: badges.find((b) => b.source === s) }));
  const extra = badges.filter((b) => !(CONSENSUS_SOURCES as readonly string[]).includes(b.source));
  return [...known, ...extra.map((b) => ({ source: b.source as string, badge: b }))];
}

export function PatientList() {
  const { data, error, loading, reload } = useApi<PatientsResponse>('/v1/patients', 10_000);
  const patients = data ? sortByState(data.patients) : [];
  const counts = Object.fromEntries(ORDER.map((s) => [s, 0])) as Record<State, number>;
  patients.forEach((p) => (counts[p.state] += 1));

  return (
    <>
      <PageHead
        title="Who needs a call"
        lede={
          <>
            Ranked by consensus. Each person is observed by three independent sources; <strong>Needs a call</strong> means two
            or more report a change from that person’s usual. <strong>Safety</strong> comes only from a crisis trigger.
          </>
        }
      >
        {data &&
          ORDER.map((s) => (
            <span key={s} className="count">
              <StateChip state={s} /> <span className="num">{counts[s]}</span>
            </span>
          ))}
      </PageHead>

      {loading && !data && <Loading label="Loading patients…" />}
      {error && !data && <ErrorBox error={error} onRetry={reload} what="patients" />}
      <StaleNote show={Boolean(error && data)} />
      {data && patients.length === 0 && (
        <Empty>
          No patients yet. Seed the demo with <code>make seed</code> or run the hub with sims.
        </Empty>
      )}

      {patients.length > 0 && (
        <ul className="patients">
          {patients.map((p) => (
            <li key={p.id} className={`card patient s-${p.state}`}>
              <div>
                <Link className="patient-name" href={`/clinician/patient/?id=${encodeURIComponent(p.id)}`}>
                  {p.display_name}
                </Link>
                <SimBadge show={Boolean(p.sim)} />
                <p className="muted small" style={{ margin: '4px 0 0' }}>
                  {p.headline}
                </p>
              </div>
              <div className="patient-state">
                <StateChip state={p.state} />
                {p.acknowledged && <span className="tag">acknowledged</span>}
              </div>
              <div className="patient-meta">
                <AgreementBadge agreement={p.agreement} />
                {orderedSources(p.sources).map(({ source, badge }) => (
                  <span key={source} className="src-mini" title={badge ? `last data ${relTime(badge.last_data_at)}` : 'no data'}>
                    {sourceLabel(source)} <VerdictChip verdict={badge?.verdict ?? 'insufficient'} compact />
                    <span className="muted"> {badge ? relTime(badge.last_data_at) : ''}</span>
                  </span>
                ))}
                {p.safety_since && <span>Safety since {relTime(p.safety_since)}</span>}
                <span>Last activity {relTime(p.last_activity_at)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
      {data && (
        <p className="muted small" style={{ marginTop: 14 }}>
          Rule <code>{data.rule_version}</code> — deterministic and auditable. {STATE_LABEL.watch} = one source worse or only one source
          with enough data.
        </p>
      )}
    </>
  );
}
