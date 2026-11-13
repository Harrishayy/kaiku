'use client';

import Link from 'next/link';
import { CONSENSUS_SOURCES, type PatientsResponse, type SourceBadge } from '@contracts';
import { useApi } from '@/lib/api';
import { consensusChip, verdictChip, VERDICT_WORD } from '@/lib/clinician.ts';
import { relTime, sortByState, sourceLabel, type State } from '@/lib/format';
import { Mascot } from '@/components/Mascot';

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
    <div className="ui k-cl" lang="en">
      <div className="k-cl-head">
        <Mascot state="idle" size={30} still tappable={false} />
        <div>
          <h1>Who needs a call</h1>
          <p className="meta">
            Ranked by consensus. Each person is seen by up to four independent sources, each compared with that person’s own
            usual. Safety comes only from a crisis trigger.
          </p>
        </div>
      </div>
      {data && (
        <div className="k-counts" aria-label="People per state">
          {ORDER.map((s) => (
            <span key={s} className={`k-chip ${consensusChip(s, 'agree').cls}`}>
              {consensusChip(s, 'agree').label} · <span className="num">{counts[s]}</span>
            </span>
          ))}
        </div>
      )}

      {loading && !data && (
        <p className="mut" role="status">
          Loading people…
        </p>
      )}
      {error && !data && (
        <div className="k-banner" role="alert">
          <div>
            <b>Can’t reach the Kaiku cloud.</b> Check the connection and try again.{' '}
            <button type="button" className="k-b k-b-soft k-b-small" onClick={reload}>
              Try again
            </button>
          </div>
        </div>
      )}
      {error && data && (
        <p className="xs mut" role="status">
          Connection lost. Showing the last data received; retrying.
        </p>
      )}
      {data && patients.length === 0 && (
        <div className="k-empty">No one is connected yet. People appear here once their Kaiku sends its first check-in.</div>
      )}

      {patients.length > 0 && (
        <ul className="k-plist">
          {patients.map((p) => {
            const chip = consensusChip(p.state, p.agreement);
            return (
              <li key={p.id}>
                <Link className="k-prow" href={`/clinician/patient/?id=${encodeURIComponent(p.id)}`}>
                  <div>
                    <div className="name">
                      {p.display_name.replace(/\s*\(SIMULATED\)$/, '')} {p.sim && <span className="k-sim">SIMULATED</span>}
                    </div>
                    <div className="head">
                      Last activity {relTime(p.last_activity_at)}
                      {p.safety_since ? ` · safety since ${relTime(p.safety_since)}` : ''}
                      {p.acknowledged ? ' · acknowledged' : ''}
                    </div>
                  </div>
                  <span className={`k-chip ${chip.cls}`}>{chip.label}</span>
                  <div className="k-minisrc">
                    {orderedSources(p.sources).map(({ source, badge }) => {
                      const v = verdictChip(badge?.verdict);
                      return (
                        <span key={source} className={`k-chip ${v.cls}`} title={badge ? `last data ${relTime(badge.last_data_at)}` : 'no data'}>
                          {sourceLabel(source)}: {VERDICT_WORD[badge?.verdict ?? 'insufficient']}
                        </span>
                      );
                    })}
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      {data && <p className="k-rule">Rule {data.rule_version}. Deterministic and auditable.</p>}
    </div>
  );
}
