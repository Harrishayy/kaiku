'use client';

/**
 * Web /me (design/ia.md "Web /me", look book "Web"): greeting + ambient Kaiku, garden, good & hard days, what helps,
 * this week's suggestion, What Kaiku remembers, What Kaiku saw today, pairing QR, two-weekly questions card.
 * Never shows scores, states or trends (persona hard limits). Copy: design/copy.json via useCopy().
 */

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import specJson from '@design/mascot.spec.json';
import type { DeletedResponse, LiveEventsResponse, MemoriesResponse, MemorySettings, MeResponse } from '@contracts';
import { api, useApi } from '@/lib/api';
import { makeEnvelope } from '@/lib/envelope';
import { useCopy } from '@/lib/i18n';
import { greetKey, nameFromHome, type Lang } from '@/lib/copy.ts';
import { ambientState, type MascotSpec, type MascotState } from '@/lib/mascot.ts';
import { usePairing } from '@/lib/params';
import { pairingUrl } from '@/lib/qr.ts';
import { localMidnightIso, sawToday, togetherDays } from '@/lib/saw.ts';
import { postEvents } from '@/lib/api';
import { Mascot } from '@/components/Mascot';
import { Garden } from '@/components/Garden';
import { QrCode } from '@/components/QrCode';
import { Icon } from '@/components/Icon';
import { CrisisScreen, useCrisis } from '@/components/CrisisScreen';

const SPEC = specJson as unknown as MascotSpec;
type T = (key: string, vars?: Record<string, string | number>) => string;

function useToast(): [string | null, (s: string) => void] {
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (!msg) return;
    const id = setTimeout(() => setMsg(null), 2200);
    return () => clearTimeout(id);
  }, [msg]);
  return [msg, setMsg];
}

export function MeView() {
  const pairing = usePairing();
  const { t, lang, setLang } = useCopy();
  const home = pairing?.homeId;
  const q = home ? encodeURIComponent(home) : null;
  const me = useApi<MeResponse>(q ? `/v1/me?home_id=${q}` : null, 60_000);
  const crisis = useCrisis(home, pairing?.token);
  const [toast, setToast] = useToast();
  const [wxOpen, setWxOpen] = useState(false);
  const [transient, setTransient] = useState<MascotState | null>(null);
  const [ear, setEar] = useState<number | null>(null);
  const [hour, setHour] = useState<number | null>(null);
  useEffect(() => setHour(new Date().getHours()), []);

  if (!pairing || hour === null) return <MeLoading t={t} lang={lang} />;
  const d = me.data;
  if (crisis.open || d?.mascot?.mood === 'crisis')
    return <CrisisScreen status={crisis.open ? crisis.status : null} />;

  const name = nameFromHome(pairing.homeId);
  const ambient = d ? ambientState(SPEC, d.mascot?.mood) : null;
  const sleepy = hour >= 23 || hour < 5;
  const mascotState: MascotState = transient ?? (!d ? 'thinking' : sleepy && ambient === 'idle' ? 'sleepy' : ambient ?? 'idle');
  const days = togetherDays(d?.highlights ?? []);

  return (
    <div className="ui" lang={lang}>
      <div className="k-langbar">
        <span className="lbl" id="lang-l">
          {t('me.lang')}
        </span>
        <div className="k-seg" role="group" aria-labelledby="lang-l">
          {(['en', 'fi'] as Lang[]).map((l) => (
            <button key={l} type="button" aria-pressed={lang === l} onClick={() => setLang(l)} lang={l}>
              {l === 'en' ? 'English' : 'Suomi'}
            </button>
          ))}
        </div>
      </div>
      <div className="k-me">
        <aside className="k-meside">
          <Mascot state={mascotState} size={190} ear={ear} label="Kaiku" />
          <h1>{t(me.data ? 'me.hi' : greetKey(hour), { name })}</h1>
          <p className="ink2 sm">{days > 0 ? t('me.together.n', { n: days }) : t('me.together.none')}</p>
          <button type="button" className="k-b k-b-pri k-b-block" onClick={() => setWxOpen(true)} aria-expanded={wxOpen}>
            {t('today.card.weather.t')}
          </button>
          <button type="button" className="k-notok k-notok-block" onClick={crisis.trigger}>
            {t('common.notok')}
          </button>
        </aside>

        <div className="k-memain">
          {me.error && !d && (
            <div className="k-banner" role="alert">
              <div>
                <b>{t('err.title')}</b>
                <p>{t('err.body')}</p>
                <button type="button" className="k-b k-b-soft k-b-small" onClick={me.reload} style={{ marginTop: 8 }}>
                  {t('err.retry')}
                </button>
              </div>
            </div>
          )}
          {wxOpen && (
            <WeatherCheck
              t={t}
              homeId={pairing.homeId}
              token={pairing.token}
              onEar={setEar}
              onClose={(sent) => {
                setWxOpen(false);
                setEar(null);
                if (sent) {
                  setToast(t('wx.thanks'));
                  setTransient('happy');
                  setTimeout(() => setTransient(null), 2800);
                  me.reload();
                }
              }}
            />
          )}
          {d?.phq9_due && (
            <section className="k-card tint-honey" aria-labelledby="phq-h">
              <h2 id="phq-h">{t('me.phq9.t')}</h2>
              <p className="sm ink2">{t('me.phq9.d')}</p>
              <Link className="k-b k-b-soft k-b-small" href="/phq9/" style={{ alignSelf: 'flex-start' }}>
                {t('me.phq9.cta')}
              </Link>
            </section>
          )}

          <section className="stack s8" aria-labelledby="week-h">
            <h2 className="lbl" id="week-h">
              {t('days.week')}
            </h2>
            <Highlights t={t} lang={lang} items={d?.highlights} loading={!d && !me.error} />
          </section>

          <div className="k-two">
            <section className="k-card" aria-labelledby="garden-h">
              <h2 className="lbl" id="garden-h">
                {t('tab.days')}
              </h2>
              <Garden plants={d?.garden?.plants ?? 0} resting={Boolean(d?.garden?.resting)} label={t('days.garden')} />
              <p className="xs mut">
                {d?.garden?.resting ? t('me.garden.resting') : t('me.garden.plants', { n: d?.garden?.plants ?? 0 })}
              </p>
            </section>
            <Pairing t={t} homeId={pairing.homeId} token={pairing.token} onCopied={() => setToast(t('me.pair.copied'))} />
          </div>

          {d?.next_suggestion && (
            <section className="k-card tint-sage" aria-labelledby="sug-h">
              <h2 className="lbl" id="sug-h">
                {t('me.suggest')}
              </h2>
              <p style={{ fontWeight: 800 }}>{t(`me.arm.${d.next_suggestion.arm}`)}</p>
              {lang === 'en' && d.next_suggestion.reason && <p className="sm ink2">{d.next_suggestion.reason}</p>}
            </section>
          )}

          <div className="k-list">
            <Link className="k-row" href="/play/firefly/">
              <span className="k-row-ic ic-honey">
                <Icon name="play" />
              </span>
              <span className="k-row-txt">
                <b>{t('game.firefly.t')}</b>
                <span>{t('game.firefly.d')}</span>
                <span>{t('game.time', { n: 1 })}</span>
              </span>
              <span className="k-row-end">
                <Icon name="chev" />
              </span>
            </Link>
          </div>

          <WhatHelps t={t} items={d?.what_helps} />
          <Memories t={t} homeId={pairing.homeId} onToast={setToast} />
          <SawToday t={t} homeId={pairing.homeId} />
        </div>
      </div>
      {toast && (
        <div className="k-toast" role="status">
          <Icon name="check" />
          <span>{toast}</span>
        </div>
      )}
    </div>
  );
}

function MeLoading({ t, lang }: { t: T; lang: Lang }) {
  return (
    <div className="ui k-me" lang={lang} role="status">
      <aside className="k-meside">
        <Mascot state="thinking" size={190} tappable={false} />
        <p className="ink2">{t('common.loading')}</p>
      </aside>
    </div>
  );
}

const WEEKDAY: Record<Lang, string> = { en: 'en-GB', fi: 'fi-FI' };

function Highlights({ t, lang, items, loading }: { t: T; lang: Lang; items?: MeResponse['highlights']; loading: boolean }) {
  if (loading) return <p className="sm mut">{t('common.loading')}</p>;
  if (!items || items.length === 0) return <div className="k-empty sm">{t('me.days.empty')}</div>;
  // Cloud sentences are English; in Finnish we show the kind of moment instead of an English sentence.
  return (
    <ul className="stack s8" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {items.slice(0, 7).map((h, i) => {
        const day = new Date(`${h.date}T12:00:00`).toLocaleDateString(WEEKDAY[lang], { weekday: 'long' });
        return (
          <li key={`${h.date}-${i}`} className="k-sent">
            <i style={{ background: h.kind === 'good' ? 'var(--k-sage)' : 'var(--k-sky)' }} aria-hidden="true" />
            <span>
              {lang === 'en' ? h.text : t(h.kind === 'good' ? 'me.days.good' : 'me.days.hard')}{' '}
              <span className="when">· {day}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function Pairing({ t, homeId, token, onCopied }: { t: T; homeId: string; token: string | null; onCopied: () => void }) {
  const url = useMemo(() => pairingUrl(window.location.origin, homeId, token), [homeId, token]);
  return (
    <section className="k-card" aria-labelledby="pair-h">
      <div className="k-qrcard">
        <QrCode text={url} label={t('me.pair.d')} />
        <div className="stack s8">
          <h2 id="pair-h" style={{ fontSize: '1.0625em', fontFamily: 'var(--k-font-body)', fontWeight: 800 }}>
            {t('me.pair')}
          </h2>
          <p className="sm mut">{t('me.pair.d')}</p>
        </div>
      </div>
      <p className="xs mut">{t('me.pair.mac')}</p>
      <div className="k-url" title={url}>
        {url}
      </div>
      <button
        type="button"
        className="k-b k-b-soft k-b-small"
        style={{ alignSelf: 'flex-start' }}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(url);
            onCopied();
          } catch {
            /* clipboard blocked; the link is visible above */
          }
        }}
      >
        {t('me.pair.copy')}
      </button>
    </section>
  );
}

function WhatHelps({ t, items }: { t: T; items?: MeResponse['what_helps'] }) {
  const sorted = [...(items ?? [])].sort((a, b) => (b.mean_effect ?? -1) - (a.mean_effect ?? -1)).slice(0, 5);
  const label = (a: string, fallback: string) => {
    const s = t(`me.act.${a}`);
    return s || fallback;
  };
  return (
    <section className="k-card" aria-labelledby="help-h">
      <h2 id="help-h">{t('me.helps')}</h2>
      {sorted.length === 0 ? (
        <p className="sm mut">{t('me.helps.empty')}</p>
      ) : (
        <div className="k-help">
          {sorted.map((h) => (
            <div key={h.activity} style={{ display: 'contents' }}>
              <span style={{ fontWeight: 700, minWidth: 0 }}>{label(h.activity, h.label)}</span>
              <span className="bar" aria-hidden="true">
                <span style={{ transform: `scaleX(${Math.max(0.06, Math.min(1, (h.mean_effect ?? 0) * 1.6))})` }} />
              </span>
              <span className="tries">{t('me.helps.tries', { n: h.tries })}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

const DIALS = ['mood', 'energy', 'sleep'] as const;
const EAR_RANGE: [number, number] = [-32, 32];

function WeatherCheck({
  t,
  homeId,
  token,
  onEar,
  onClose,
}: {
  t: T;
  homeId: string;
  token: string | null;
  onEar: (deg: number | null) => void;
  onClose: (sent: boolean) => void;
}) {
  const [vals, setVals] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(false);
  const all = DIALS.every((k) => vals[k]);
  const set = (k: string, v: number) => {
    setVals((s) => ({ ...s, [k]: v }));
    onEar(EAR_RANGE[0] + ((v - 1) / 4) * (EAR_RANGE[1] - EAR_RANGE[0]));
  };
  async function send() {
    setBusy(true);
    setErr(false);
    try {
      await postEvents(
        DIALS.map((item) =>
          makeEnvelope('obs.self_report', { item, value: vals[item], context: 'adhoc', channel: 'web' }, { source: 'laptop', homeId }),
        ),
        token,
      );
      onClose(true);
    } catch {
      setErr(true);
      setBusy(false);
    }
  }
  return (
    <section className="k-card" aria-labelledby="wx-h">
      <h2 id="wx-h">{t('wx.title')}</h2>
      <div className="k-wx">
        {DIALS.map((k) => (
          <div key={k} className="k-wx-item" role="radiogroup" aria-labelledby={`wx-${k}`}>
            <b id={`wx-${k}`}>{t(`wx.${k}`)}</b>
            <div className="k-seg">
              {[1, 2, 3, 4, 5].map((v) => (
                <button
                  key={v}
                  type="button"
                  role="radio"
                  aria-checked={vals[k] === v}
                  aria-pressed={vals[k] === v}
                  aria-label={t(`wx.${k}.${v}`)}
                  onClick={() => set(k, v)}
                >
                  {v}
                </button>
              ))}
            </div>
            <div className="k-wx-val" aria-live="polite">
              {vals[k] ? t(`wx.${k}.${vals[k]}`) : ''}
            </div>
          </div>
        ))}
      </div>
      {err && (
        <p className="sm" role="alert">
          {t('err.short')}
        </p>
      )}
      <div className="row-wrap">
        <button type="button" className="k-b k-b-pri" disabled={!all || busy} onClick={send}>
          {busy ? t('wx.sending') : t('wx.done')}
        </button>
        <button type="button" className="k-b k-b-ghost" onClick={() => onClose(false)}>
          {t('common.nottoday')}
        </button>
      </div>
    </section>
  );
}

function Memories({ t, homeId, onToast }: { t: T; homeId: string; onToast: (s: string) => void }) {
  const q = encodeURIComponent(homeId);
  const mem = useApi<MemoriesResponse>(`/v1/me/memories?home_id=${q}`);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(false);
  const list = mem.data?.memories ?? [];

  async function act(fn: () => Promise<unknown>, toast?: string) {
    setBusy(true);
    setErr(false);
    try {
      await fn();
      if (toast) onToast(toast);
      mem.reload();
    } catch {
      setErr(true);
    } finally {
      setBusy(false);
      setConfirm(false);
    }
  }

  return (
    <section className="stack" aria-labelledby="mem-h">
      <h2 id="mem-h">{t('you.remembers')}</h2>
      <p className="sm ink2">{t('mem.body')}</p>
      <div className="k-list">
        <div className="k-row top">
          <span className="k-row-ic ic-clay">
            <Icon name="memory" />
          </span>
          <span className="k-row-txt">
            <b id="mem-sw">{t('mem.remember.t')}</b>
            <span>{t('mem.remember.d')}</span>
          </span>
          <span className="k-row-end">
            <button
              type="button"
              className="k-sw"
              role="switch"
              aria-checked={mem.data?.remember ?? true}
              aria-labelledby="mem-sw"
              disabled={!mem.data || busy}
              onClick={() =>
                act(() =>
                  api<MemorySettings>(`/v1/me/memory_settings?home_id=${q}`, {
                    method: 'PUT',
                    body: JSON.stringify({ remember: !(mem.data?.remember ?? true) }),
                  }),
                )
              }
            />
          </span>
        </div>
      </div>
      {mem.loading && !mem.data && <p className="sm mut">{t('common.loading')}</p>}
      {mem.error && !mem.data && (
        <div className="k-banner" role="alert">
          <div>
            {t('err.title')}{' '}
            <button type="button" className="k-b k-b-ghost k-b-small" onClick={mem.reload}>
              {t('err.retry')}
            </button>
          </div>
        </div>
      )}
      {mem.data && list.length === 0 && <div className="k-empty sm">{t('mem.empty')}</div>}
      {list.length > 0 && (
        <ul className="k-list" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {list.map((m) => (
            <li key={m.id} className="k-memrow">
              <span>{m.text}</span>
              <button
                type="button"
                disabled={busy}
                aria-label={`${t('mem.delete')}: ${m.text}`}
                onClick={() => act(() => api<DeletedResponse>(`/v1/me/memories/${m.id}?home_id=${q}`, { method: 'DELETE' }), t('toast.deleted'))}
              >
                {t('mem.delete')}
              </button>
            </li>
          ))}
        </ul>
      )}
      {err && (
        <p className="sm" role="alert">
          {t('err.short')}
        </p>
      )}
      {list.length > 0 &&
        (confirm ? (
          <div className="k-card tint-honey" role="alertdialog" aria-labelledby="mem-confirm">
            <p id="mem-confirm" style={{ fontWeight: 700 }}>
              {t('mem.confirm')}
            </p>
            <div className="row-wrap">
              <button
                type="button"
                className="k-b k-b-pri k-b-small"
                disabled={busy}
                onClick={() => act(() => api<DeletedResponse>(`/v1/me/memories?home_id=${q}`, { method: 'DELETE' }), t('toast.deleted'))}
              >
                {t('mem.confirm.yes')}
              </button>
              <button type="button" className="k-b k-b-ghost k-b-small" onClick={() => setConfirm(false)}>
                {t('common.back')}
              </button>
            </div>
          </div>
        ) : (
          <button type="button" className="k-b k-b-soft k-b-block" onClick={() => setConfirm(true)} disabled={busy}>
            {t('mem.forgetall')}
          </button>
        ))}
    </section>
  );
}

function SawToday({ t, homeId }: { t: T; homeId: string }) {
  const since = useMemo(() => localMidnightIso(), []);
  const ev = useApi<LiveEventsResponse>(
    `/v1/events?home_id=${encodeURIComponent(homeId)}&since=${encodeURIComponent(since)}&limit=500`,
    120_000,
  );
  const lines = sawToday((ev.data?.events ?? []) as { type: string; payload?: Record<string, unknown> }[]);
  return (
    <section className="stack" aria-labelledby="saw-h">
      <h2 id="saw-h">{t('you.saw')}</h2>
      <div className="k-receipt">
        <div style={{ textAlign: 'center', color: 'var(--k-muted)' }}>{t('saw.head')}</div>
        <hr />
        {ev.loading && !ev.data ? (
          <p>{t('common.loading')}</p>
        ) : lines.length === 0 ? (
          <p>{t('saw.none')}</p>
        ) : (
          <ul>
            {lines.map((l) => (
              <li key={l.key}>
                <span aria-hidden="true">·</span>
                <span>{t(l.key, l.vars)}</span>
              </li>
            ))}
          </ul>
        )}
        <hr />
        <div style={{ color: 'var(--k-muted)' }}>{t('saw.never')}</div>
        <hr />
        <div style={{ textAlign: 'center', color: 'var(--k-muted)' }}>{t('saw.share')}</div>
      </div>
    </section>
  );
}
