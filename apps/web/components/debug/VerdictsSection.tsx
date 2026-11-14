'use client';

import { Fragment, useState } from 'react';
import type { DebugDay } from '@contracts';
import { Chip } from '@/components/dash/kit';
import { verdictChip } from '@/lib/labels';
import { anchorOf, localStamp, signed, usableOf } from '@/lib/debug';
import { Against, Chevron, Empty, Mono, Tag, type Nav } from './bits';

/** Each signal group's verdict with the numbers that made it: confidence and both weights against their thresholds. */
export function VerdictsBody({ day, nav }: { day: DebugDay; nav: Nav }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (s: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(s)) next.add(s);
      return next;
    });
  if (!day.verdicts.length) return <Empty>No signal group gave a verdict for this day.</Empty>;
  return (
    <div className="dbg-scroll">
      <table className="dbg-table" aria-label="Signal-group verdicts of this day">
        <thead>
          <tr>
            <th scope="col">Signal group</th>
            <th scope="col">Verdict</th>
            <th scope="col" title="Verdict the day before">
              Day before
            </th>
            <th scope="col" title="Confidence against the group’s minimum: below it the verdict is insufficient">
              Confidence ≥ min
            </th>
            <th scope="col" className="dbg-num" title="Of this group’s scored metrics, how many have a status other than insufficient on this day (a count made by this page from the metrics below)">
              Usable
            </th>
            <th scope="col" title="Sum of the weights of its drifting metrics against the weight that reads as a change">
              Worse weight ≥ min
            </th>
            <th scope="col" title="Sum of the weights of its improved metrics against the weight that reads as better">
              Better weight ≥ min
            </th>
            <th scope="col">Rules fired</th>
            <th scope="col" className="dbg-num" title="Days with data in the baseline window up to this day">
              Days
            </th>
            <th scope="col">Last data</th>
          </tr>
        </thead>
        <tbody>
          {day.verdicts.map((v) => {
            const chip = verdictChip(v.verdict);
            const anchor = anchorOf.verdict(v.source);
            const evidence = v.evidence ?? [];
            const rules = v.rules_fired ?? [];
            const isOpen = open.has(v.source);
            const use = usableOf(v.source, day.metrics);
            return (
              <Fragment key={v.source}>
                <tr id={anchor} tabIndex={-1} className={`${v.verdict === 'worse' ? 'is-flagged' : ''}${nav.hit === anchor ? ' is-hit' : ''}` || undefined}>
                  <th scope="row">
                    <button type="button" className="dbg-rowbtn" aria-expanded={isOpen} onClick={() => toggle(v.source)}>
                      <Chevron open={isOpen} />
                      {v.label}
                    </button>{' '}
                    <Mono>{v.source}</Mono>
                  </th>
                  <td>
                    <Chip tone={chip.tone}>{chip.label}</Chip> <Mono>{v.verdict}</Mono>
                  </td>
                  <td>{v.previous ? <Mono>{v.previous}</Mono> : <span className="dbg-dim">none</span>}{v.previous && v.previous !== v.verdict && <Tag tone="warn">changed</Tag>}</td>
                  <td>
                    <Against value={v.confidence} min={v.min_confidence} hot="unmet" tone="ins" />
                  </td>
                  <td className="dbg-num">
                    <span className={use.usable === 0 ? 'dbg-against is-hot is-ins' : undefined}>
                      {use.usable}/{use.scored}
                    </span>
                  </td>
                  <td>
                    <Against value={v.worse_weight} min={v.worse_min_weight} hot="met" tone="warn" />
                  </td>
                  <td>
                    <Against value={v.better_weight} min={v.better_min_weight} hot="met" tone="ok" />
                  </td>
                  <td>
                    {rules.length ? (
                      <span className="dbg-inline">
                        {rules.map((r) => (
                          <Tag key={r} tone="warn">
                            {r}
                          </Tag>
                        ))}
                      </span>
                    ) : (
                      <span className="dbg-dim">none</span>
                    )}
                  </td>
                  <td className="dbg-num">{v.days_with_data ?? 0}</td>
                  <td className="dbg-mono dbg-nowrap">{v.last_data_at ? localStamp(v.last_data_at, day.timezone) : <span className="dbg-dim">never</span>}</td>
                </tr>
                {isOpen && (
                  <tr className="dbg-sub">
                    <td colSpan={10}>
                      {evidence.length ? (
                        <table className="dbg-table dbg-table-inner">
                          <caption className="dbg-caption">Evidence the verdict carries ({evidence.length})</caption>
                          <thead>
                            <tr>
                              <th scope="col">Metric or rule</th>
                              <th scope="col" className="dbg-num">
                                z
                              </th>
                              <th scope="col">Direction</th>
                              <th scope="col" className="dbg-num">
                                Days
                              </th>
                              <th scope="col">Summary</th>
                            </tr>
                          </thead>
                          <tbody>
                            {evidence.map((e) => {
                              const known = day.metrics.some((m) => m.metric === e.metric);
                              return (
                                <tr key={e.metric}>
                                  <td>
                                    {known ? (
                                      <button type="button" className="dbg-cite" onClick={() => nav.jump({ section: 'metrics', anchor: anchorOf.metric(e.metric) })}>
                                        {e.metric}
                                      </button>
                                    ) : (
                                      <Mono>{e.metric}</Mono>
                                    )}
                                  </td>
                                  <td className="dbg-num">{signed(e.z)}</td>
                                  <td className="dbg-mono">{e.direction}</td>
                                  <td className="dbg-num">{e.days}</td>
                                  <td>{e.summary}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      ) : (
                        <Empty>This verdict carries no evidence rows.</Empty>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
