'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CONSENSUS_SOURCES,
  SOURCE_OF,
  type Criteria,
  type CriteriaPreview,
  type CriteriaResponse,
  type CriteriaUpdate,
  type EvalResult,
  type MetricSpec,
  type RuleSpec,
} from '@contracts';
import { api, ApiError, detailLines, useApi } from '@/lib/api';
import { clone, criteriaToToml, diffPaths, groupBySource, normalizeCriteria, setIn } from '@/lib/criteria';
import { STATE_LABEL, VERDICT_LABEL, dateTime, fmt, pct, prettify, sourceLabel, type State, type Verdict } from '@/lib/format';
import { useAdminToken } from '@/lib/params';
import { Chip } from '@/components/dash/kit';
import { ErrorBox, Loading, PageHead, StateChip } from '@/components/ui';

/** Short help for criteria fields (field names come from the contract; unknown fields render without help). */
const HINT: Record<string, string> = {
  baseline_days: 'days in the rolling median + MAD baseline',
  baseline_min_days: 'fewer days of data → metric not enough data',
  z_threshold: '|robust z| in the worse direction counts as drifting',
  drift_days: 'drifting on at least this many days…',
  drift_window: '…of the last N days with data',
  min_mad: 'noise floor for MAD, in metric units',
  quality_min: 'ignore readings with quality below this',
  worse_min_weight: 'sum of drifting-metric weights needed for “worse”',
  better_min_weight: 'sum of improving-metric weights needed for “better”',
  min_confidence: 'below this the source is “not enough data” (no vote)',
  expected_per_week: 'days with data expected per week (for confidence)',
  needs_call_min_worse: 'sufficient sources “worse” needed for needs a call',
  watch_min_worse: 'sufficient sources “worse” needed for watch',
  watch_if_single_sufficient: 'only one source with enough data → watch',
  min_sufficient_for_stable: 'fewer sufficient sources can never be stable',
  hysteresis_stable_days: 'needs a call holds until acknowledged or N stable days',
  correlated_families: 'families treated as correlated (e.g. self_report) — comma separated',
  count_correlated_as_one: 'sources worse only via a correlated family count as ONE',
};
const RULE_KINDS: RuleSpec['kind'][] = ['at_least', 'at_most', 'rise_vs_previous', 'drop_vs_previous'];
type Path = (string | number)[];

export function TuneView() {
  const admin = useAdminToken();
  const currentEval = useApi<EvalResult>('/v1/eval');
  const [resp, setResp] = useState<CriteriaResponse | null>(null);
  const [loadErr, setLoadErr] = useState<ApiError | null>(null);
  const [draft, setDraft] = useState<Criteria | null>(null);
  const [by, setBy] = useState('');
  const [preview, setPreview] = useState<CriteriaPreview | null>(null);
  const [previewStale, setPreviewStale] = useState(false);
  const [busy, setBusy] = useState<null | 'preview' | 'apply' | 'reset'>(null);
  const [actionErr, setActionErr] = useState<ApiError | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [toml, setToml] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState('');

  const token = admin.token;
  const load = useCallback(async () => {
    setLoadErr(null);
    try {
      const r = await api<CriteriaResponse>('/v1/admin/criteria', { token });
      r.criteria = normalizeCriteria(r.criteria);
      setResp(r);
      setDraft(clone(r.criteria));
      setPreview(null);
    } catch (e) {
      setLoadErr(e as ApiError);
    }
  }, [token]);

  useEffect(() => {
    if (token !== undefined) void load();
  }, [token, load]);

  const dirty = useMemo(() => (resp && draft ? diffPaths(resp.criteria, draft) : []), [resp, draft]);
  const changed = (prefix: string) => dirty.some((p) => p === prefix || p.startsWith(`${prefix}.`));

  if (token === undefined) return <Loading />;

  const update = (path: Path, value: unknown) => {
    setDraft((d) => (d ? setIn(d, path, value) : d));
    setPreviewStale(true);
    setMsg(null);
  };

  async function run(kind: 'preview' | 'apply' | 'reset') {
    if (!draft) return;
    if (kind === 'apply' && !window.confirm(`Apply ${dirty.length} change(s) to the LIVE cloud? Every patient's state is recomputed with the new rule.`))
      return;
    if (kind === 'reset' && !window.confirm('Drop the live override and go back to config/criteria.toml?')) return;
    setBusy(kind);
    setActionErr(null);
    setMsg(null);
    const body: CriteriaUpdate = { criteria: kind === 'reset' ? null : draft, by: by.trim() || null };
    try {
      if (kind === 'preview') {
        const p = await api<CriteriaPreview>('/v1/admin/criteria/preview?eval=1', {
          method: 'POST',
          body: JSON.stringify(body),
          token,
          timeoutMs: 180_000,
        });
        setPreview(p);
        setPreviewStale(false);
      } else {
        const r = await api<CriteriaResponse>('/v1/admin/criteria', { method: 'PUT', body: JSON.stringify(body), token, timeoutMs: 60_000 });
        r.criteria = normalizeCriteria(r.criteria);
        setResp(r);
        setDraft(clone(r.criteria));
        setPreview(null);
        currentEval.reload();
        setMsg(kind === 'apply' ? `Applied — live rule is now ${r.rule_version}. Export TOML and commit to make it the ground truth.` : `Reset — live rule is ${r.rule_version} from config/criteria.toml.`);
      }
    } catch (e) {
      setActionErr(e as ApiError);
    } finally {
      setBusy(null);
    }
  }

  function exportToml() {
    if (!draft || !resp) return;
    const text = criteriaToToml(draft, [
      `Exported from /tune/ ${new Date().toISOString()}${by.trim() ? ` by ${by.trim()}` : ''} (live rule ${resp.rule_version}, ${dirty.length} unapplied edit(s)).`,
      'Paste over config/criteria.toml (keep the file’s explanatory header), run `make criteria && make tune`, commit.',
    ]);
    setToml(text);
    navigator.clipboard?.writeText(text).then(
      () => setMsg('TOML copied to the clipboard.'),
      () => setMsg('Copy failed — select the text below and copy it manually.'),
    );
  }

  const unauthorized = loadErr && (loadErr.status === 401 || loadErr.status === 403);

  return (
    <>
      <PageHead
        title="Tune the consensus"
        lede={
          <>
            Admin only. Edit how every signal is used, preview who would change state, then apply live. The ground truth stays{' '}
            <code>config/criteria.toml</code> — export and commit what you keep.
          </>
        }
      >
        {resp && (
          <span className="tune-version">
            <code>{resp.rule_version}</code>{' '}
            <span className={resp.origin === 'override' ? 'tag tag-disagree' : 'tag'}>{resp.origin === 'override' ? 'live override' : 'from file'}</span>
          </span>
        )}
      </PageHead>

      {(token === null || unauthorized) && (
        <section className="card" aria-labelledby="adm-h">
          <h2 id="adm-h">{unauthorized ? 'Admin token rejected' : 'Admin token'}</h2>
          <p className="muted small">
            Paste <code>KAIKU_ADMIN_TOKEN</code> (or open this page once with <code>?admin=…</code>). It is kept in this browser only and sent
            only to this service: the admin and debug routes, and the record routes when no care-team token is set. A local cloud without an admin token accepts requests without one.
          </p>
          <form
            className="btn-row"
            onSubmit={(e) => {
              e.preventDefault();
              admin.set(tokenInput);
              setTokenInput('');
            }}
          >
            <input type="password" aria-label="Admin token" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} style={{ maxWidth: 'calc(var(--k-space-8) * 5)' }} />
            <button className="d-btn d-btn-secondary" type="submit" disabled={!tokenInput.trim()}>
              Use token
            </button>
          </form>
        </section>
      )}
      {token && (
        <p className="small muted">
          Admin token stored in this browser.{' '}
          <button type="button" className="linkish" onClick={() => admin.set(null)}>
            Forget it
          </button>
        </p>
      )}

      {loadErr && !unauthorized && <ErrorBox error={loadErr} onRetry={load} what="the consensus criteria" />}
      {!resp && !loadErr && <Loading label="Loading criteria…" />}

      {resp && draft && (
        <>
          <p className="small muted">
            {resp.origin === 'override'
              ? `Live override set ${dateTime(resp.updated_at)}${resp.updated_by ? ` by ${resp.updated_by}` : ''} — not in git until someone exports and commits it.`
              : 'Running exactly what config/criteria.toml says.'}
          </p>

          <div className="grid-2">
            <section className="card" aria-labelledby="def-h">
              <h2 id="def-h">Defaults</h2>
              <p className="muted small">Apply to every metric unless the metric overrides them.</p>
              <Fields obj={draft.defaults ?? {}} path={['defaults']} update={update} changed={changed} />
            </section>
            <section className="card" aria-labelledby="state-h">
              <h2 id="state-h">How source verdicts combine into a state</h2>
              <Fields obj={draft.state ?? {}} path={['state']} update={update} changed={changed} />
            </section>
          </div>

          {groupBySource(draft, SOURCE_OF, CONSENSUS_SOURCES).map(([src, g]) => (
            <SourceSection
              key={src}
              src={src}
              draft={draft}
              metrics={g.metrics}
              rules={g.rules}
              update={update}
              changed={changed}
            />
          ))}

          <section className="card" aria-labelledby="prev-h">
            <h2 id="prev-h">Preview {previewStale && preview && <Chip tone="warn">out of date, preview again</Chip>}</h2>
            {!preview && <p className="muted small">Dry run: recompute every patient and the simulation under your edits. Nothing changes until you apply.</p>}
            {preview && <PreviewPanel p={preview} current={currentEval.data} />}
          </section>

          {toml && (
            <section className="card" aria-labelledby="toml-h">
              <h2 id="toml-h">Candidate as TOML</h2>
              <p className="muted small">Paste into <code>config/criteria.toml</code> (keep its header comment), then commit.</p>
              <textarea className="toml" readOnly rows={18} value={toml} onFocus={(e) => e.currentTarget.select()} />
            </section>
          )}

          <div className="tune-bar" role="region" aria-label="Criteria actions">
            <div className="tune-bar-inner">
              <span className="small">
                <strong>{dirty.length}</strong> unapplied edit{dirty.length === 1 ? '' : 's'}
              </span>
              <input type="text" placeholder="your initials" aria-label="Your initials" value={by} onChange={(e) => setBy(e.target.value)} maxLength={40} />
              <button type="button" className="d-btn d-btn-secondary" disabled={busy !== null} onClick={() => run('preview')}>
                {busy === 'preview' ? 'Previewing…' : 'Preview'}
              </button>
              <button type="button" className="d-btn d-btn-primary" disabled={busy !== null || dirty.length === 0} onClick={() => run('apply')}>
                {busy === 'apply' ? 'Applying…' : 'Apply live'}
              </button>
              <button type="button" className="d-btn" disabled={busy !== null || resp.origin === 'file'} onClick={() => run('reset')}>
                Reset to file
              </button>
              <button type="button" className="d-btn" onClick={exportToml}>
                Export TOML
              </button>
              <button
                type="button"
                className="d-btn"
                disabled={dirty.length === 0}
                onClick={() => {
                  setDraft(clone(resp.criteria));
                  setPreview(null);
                }}
              >
                Discard edits
              </button>
            </div>
            {actionErr && (
              <div className="tune-error" role="alert">
                <strong>{actionErr.status === 422 ? 'The cloud rejected these criteria:' : `Request failed (${actionErr.status ?? 'network'}):`}</strong>
                <ul>
                  {(detailLines(actionErr.detail).length ? detailLines(actionErr.detail) : [actionErr.message]).map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              </div>
            )}
            {msg && (
              <p className="small" role="status" style={{ margin: '6px 0 0' }}>
                {msg}
              </p>
            )}
          </div>
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------------------------------------ sections
function SourceSection({
  src,
  draft,
  metrics,
  rules,
  update,
  changed,
}: {
  src: string;
  draft: Criteria;
  metrics: { m: MetricSpec; i: number }[];
  rules: { r: RuleSpec; i: number }[];
  update: (p: Path, v: unknown) => void;
  changed: (prefix: string) => boolean;
}) {
  const spec = draft.sources?.[src];
  const d = draft.defaults ?? {};
  const disabled = spec?.enabled === false;
  return (
    <section className={`card tune-source${disabled ? ' off' : ''}`} aria-labelledby={`ts-${src}`}>
      <header className="source-head">
        <h2 id={`ts-${src}`}>{sourceLabel(src)}</h2>
        <span className="muted small">
          {metrics.filter((x) => x.m.enabled !== false).length}/{metrics.length} metrics on · {rules.length} rule{rules.length === 1 ? '' : 's'}
        </span>
      </header>
      {spec ? (
        <Fields obj={spec} path={['sources', src]} update={update} changed={changed} inline />
      ) : (
        <p className="small muted">No <code>[sources.{src}]</code> block — these metrics are not used in the vote.</p>
      )}

      {metrics.length > 0 && (
        <div className="table-wrap">
          <table className="tune-table">
            <thead>
              <tr>
                <th scope="col">On</th>
                <th scope="col">Metric</th>
                <th scope="col">Weight</th>
                <th scope="col">Worse when</th>
                <th scope="col">z threshold</th>
                <th scope="col">min MAD</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map(({ m, i }) => {
                const key = `metric.${m.name}`;
                return (
                  <tr key={m.name} className={`${changed(key) ? 'changed' : ''}${m.enabled === false ? ' off' : ''}`}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${m.label} enabled`}
                        checked={m.enabled !== false}
                        onChange={(e) => update(['metric', i, 'enabled'], e.target.checked)}
                      />
                    </td>
                    <td>
                      <strong>{m.label}</strong>
                      {m.unit ? <span className="muted small"> · {m.unit}</span> : null}
                      <div className="muted small">
                        <code>{m.name}</code> · {m.family ?? '—'} · <code>{m.obs.replace('obs.', '')}.{m.field}</code>
                        {m.agg ? ` · ${m.agg}` : ''}
                        {m.where ? ` · where ${Object.entries(m.where).map(([k, v]) => `${k}=${String(v)}`).join(', ')}` : ''}
                      </div>
                      {m.note && <div className="muted small">{m.note}</div>}
                    </td>
                    <td>
                      <Num label={`${m.label} weight`} value={m.weight ?? 1} min={0} step={0.5} required onChange={(v) => update(['metric', i, 'weight'], v)} />
                    </td>
                    <td>
                      <select aria-label={`${m.label} worse when`} value={m.worse_when} onChange={(e) => update(['metric', i, 'worse_when'], e.target.value)}>
                        <option value="down">lower</option>
                        <option value="up">higher</option>
                      </select>
                    </td>
                    <td>
                      <Num
                        label={`${m.label} z threshold`}
                        value={m.z_threshold ?? null}
                        placeholder={`${d.z_threshold ?? '—'} (default)`}
                        min={0}
                        step={0.1}
                        onChange={(v) => update(['metric', i, 'z_threshold'], v)}
                      />
                    </td>
                    <td>
                      <Num
                        label={`${m.label} min MAD`}
                        value={m.min_mad ?? null}
                        placeholder={`${d.min_mad ?? '—'} (default)`}
                        min={0}
                        onChange={(v) => update(['metric', i, 'min_mad'], v)}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {rules.length > 0 && (
        <>
          <h3 className="tune-sub">Direct “worse” rules</h3>
          <div className="table-wrap">
            <table className="tune-table">
              <thead>
                <tr>
                  <th scope="col">On</th>
                  <th scope="col">Rule</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Threshold</th>
                </tr>
              </thead>
              <tbody>
                {rules.map(({ r, i }) => (
                  <tr key={r.name} className={`${changed(`rule.${r.name}`) ? 'changed' : ''}${r.enabled === false ? ' off' : ''}`}>
                    <td>
                      <input type="checkbox" aria-label={`${r.label} enabled`} checked={r.enabled !== false} onChange={(e) => update(['rule', i, 'enabled'], e.target.checked)} />
                    </td>
                    <td>
                      <strong>{r.label}</strong>
                      <div className="muted small">
                        <code>{r.name}</code> · <code>{r.obs.replace('obs.', '')}.{r.field}</code>
                      </div>
                    </td>
                    <td>
                      <select aria-label={`${r.label} kind`} value={r.kind} onChange={(e) => update(['rule', i, 'kind'], e.target.value)}>
                        {RULE_KINDS.map((k) => (
                          <option key={k} value={k}>
                            {k.replace(/_/g, ' ')}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <Num label={`${r.label} threshold`} value={r.threshold} required onChange={(v) => update(['rule', i, 'threshold'], v)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function PreviewPanel({ p, current }: { p: CriteriaPreview; current: EvalResult | null }) {
  const cand = p.eval ?? null;
  return (
    <>
      <p className="small">
        Rule <code>{p.current_rule_version}</code> → <code>{p.candidate_rule_version}</code> · <strong>{p.changes.length}</strong> patient
        {p.changes.length === 1 ? '' : 's'} would change · {p.unchanged} unchanged
      </p>
      {p.changes.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Patient</th>
                <th scope="col">State</th>
                <th scope="col">Source verdicts that change</th>
              </tr>
            </thead>
            <tbody>
              {p.changes.map((c) => {
                const srcs = [...new Set([...Object.keys(c.from_sources), ...Object.keys(c.to_sources)])].filter(
                  (s) => c.from_sources[s] !== c.to_sources[s],
                );
                return (
                  <tr key={c.patient_id}>
                    <td>
                      {c.display_name}
                      <div className="muted small">
                        <code>{c.patient_id}</code>
                      </div>
                    </td>
                    <td className="nowrap">
                      {c.from_state === c.to_state ? (
                        <StateChip state={c.to_state as State} />
                      ) : (
                        <>
                          <StateChip state={c.from_state as State} /> → <StateChip state={c.to_state as State} />
                        </>
                      )}
                    </td>
                    <td className="small">
                      {srcs.length === 0
                        ? '—'
                        : srcs.map((s) => (
                            <div key={s}>
                              {sourceLabel(s)}: {verdictText(c.from_sources[s])} → <strong>{verdictText(c.to_sources[s])}</strong>
                            </div>
                          ))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <h3 className="tune-sub">Simulation (synthetic patients)</h3>
      {!cand && <p className="muted small">The cloud returned no simulation for this preview.</p>}
      {cand && <EvalCompare current={current} cand={cand} />}
    </>
  );
}

const verdictText = (v: string | undefined) => (v ? (VERDICT_LABEL[v as Verdict] ?? prettify(v)).toLowerCase() : 'no data');

function EvalCompare({ current, cand }: { current: EvalResult | null; cand: EvalResult }) {
  type Row = { label: string; cur: number | null | undefined; next: number | null | undefined; kind: 'pct' | 'num' | 'days'; better: 'up' | 'down' };
  const rows: Row[] = [
    { label: 'False “needs a call” per patient-month', cur: current?.false_needs_call_per_patient_month, next: cand.false_needs_call_per_patient_month, kind: 'num', better: 'down' },
    { label: 'Median lead time', cur: current?.median_lead_time_days, next: cand.median_lead_time_days, kind: 'days', better: 'up' },
  ];
  const states = [...new Set([...Object.keys(current?.per_state ?? {}), ...Object.keys(cand.per_state)])];
  for (const s of states) {
    const name = STATE_LABEL[s as State] ?? prettify(s);
    rows.push({ label: `${name} precision`, cur: current?.per_state?.[s]?.precision, next: cand.per_state[s]?.precision, kind: 'pct', better: 'up' });
    rows.push({ label: `${name} recall`, cur: current?.per_state?.[s]?.recall, next: cand.per_state[s]?.recall, kind: 'pct', better: 'up' });
  }
  const abl = [...new Set([...Object.keys(current?.ablation ?? {}), ...Object.keys(cand.ablation ?? {})])];
  for (const s of abl) {
    rows.push({ label: `Without ${sourceLabel(s)}: recall`, cur: current?.ablation?.[s]?.recall, next: cand.ablation?.[s]?.recall, kind: 'pct', better: 'up' });
  }
  const show = (v: number | null | undefined, k: Row['kind']) =>
    v === null || v === undefined ? '—' : k === 'pct' ? pct(v) : k === 'days' ? `${fmt(v, 1)} d` : fmt(v, 2);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th scope="col">Current {current ? <code>{current.rule_version}</code> : null}</th>
            <th scope="col">Candidate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const delta = typeof r.cur === 'number' && typeof r.next === 'number' ? r.next - r.cur : 0;
            const cls = Math.abs(delta) < 1e-9 ? '' : (delta > 0) === (r.better === 'up') ? 'delta-good' : 'delta-bad';
            return (
              <tr key={r.label}>
                <td>{r.label}</td>
                <td className="num">{show(r.cur, r.kind)}</td>
                <td className={`num ${cls}`}>{show(r.next, r.kind)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="muted small">Synthetic patients with known onset — tells you how the rule behaves, not clinical accuracy.</p>
    </div>
  );
}

// ------------------------------------------------------------------------------------------ generic fields
function Fields({
  obj,
  path,
  update,
  changed,
  inline = false,
}: {
  obj: object;
  path: Path;
  update: (p: Path, v: unknown) => void;
  changed: (prefix: string) => boolean;
  inline?: boolean;
}) {
  const entries = Object.entries(obj as Record<string, unknown>);
  // 'enabled' first, then numbers, booleans, lists, strings — so every block reads the same way
  const order = (v: unknown, k: string) => (k === 'enabled' ? 0 : typeof v === 'number' ? 1 : typeof v === 'boolean' ? 2 : Array.isArray(v) ? 3 : 4);
  entries.sort(([ka, va], [kb, vb]) => order(va, ka) - order(vb, kb));
  return (
    <div className={inline ? 'fields fields-inline' : 'fields'}>
      {entries.map(([k, v]) => {
        const p = [...path, k];
        const id = p.join('-');
        const cls = changed(p.join('.')) ? 'field changed' : 'field';
        if (typeof v === 'boolean')
          return (
            <label key={k} className={`${cls} field-bool`} htmlFor={id}>
              <input id={id} type="checkbox" checked={v} onChange={(e) => update(p, e.target.checked)} />
              <span>
                {prettify(k)}
                {HINT[k] && <span className="muted small"> — {HINT[k]}</span>}
              </span>
            </label>
          );
        return (
          <div key={k} className={cls}>
            <label htmlFor={id}>{prettify(k)}</label>
            {typeof v === 'number' ? (
              <Num id={id} label={prettify(k)} value={v} required onChange={(x) => update(p, x)} />
            ) : Array.isArray(v) ? (
              <input
                id={id}
                type="text"
                defaultValue={v.join(', ')}
                onBlur={(e) =>
                  update(
                    p,
                    e.target.value
                      .split(',')
                      .map((s) => s.trim())
                      .filter(Boolean),
                  )
                }
              />
            ) : (
              <input id={id} type="text" value={String(v ?? '')} onChange={(e) => update(p, e.target.value)} />
            )}
            {HINT[k] && <span className="muted small">{HINT[k]}</span>}
          </div>
        );
      })}
    </div>
  );
}

/** Number input that keeps a local text value (so "1." or "" can be typed) and reports number | null. */
function Num({
  id,
  label,
  value,
  onChange,
  placeholder,
  min,
  step,
  required = false,
}: {
  id?: string;
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  placeholder?: string;
  min?: number;
  step?: number;
  /** required: a blank input is ignored and restored on blur; optional: blank = null = "use the default" */
  required?: boolean;
}) {
  const [text, setText] = useState(value === null ? '' : String(value));
  useEffect(() => {
    setText((t) => (t === '' && value === null) || Number(t) === value ? t : value === null ? '' : String(value));
  }, [value]);
  return (
    <input
      id={id}
      aria-label={label}
      className="num-input"
      type="number"
      inputMode="decimal"
      step={step ?? 'any'}
      min={min}
      placeholder={placeholder}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        if (e.target.value === '') {
          if (!required) onChange(null);
        } else if (Number.isFinite(e.target.valueAsNumber)) onChange(e.target.valueAsNumber);
      }}
      onBlur={() => {
        if (required && text === '' && value !== null) setText(String(value));
      }}
    />
  );
}
