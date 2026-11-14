'use client';

import { useMemo } from 'react';
import {
  SOURCE_OF,
  type Consensus,
  type KnowledgeGraph,
  type LiveEventsResponse,
  type MetricSeries,
  type PatientInsight,
  type PatientSummary,
  type Phq9History,
  type TimelineResponse,
  type WeekSummary,
} from '@contracts';
import { type ApiError, useApi } from '@/lib/api';
import { sourceLabel } from '@/lib/format';
import { insightView, recordedDays, trimLeading, type InsightView, type ObsEvent } from '@/lib/insight';

export interface DashData {
  patient: PatientSummary;
  consensus: Consensus;
  series: MetricSeries[];
  recorded: ReturnType<typeof recordedDays>;
  week: WeekSummary | null;
  phq9: Phq9History | null;
  events: ObsEvent[];
  view: InsightView;
  /** the intelligence layer is still working on the review */
  insightLoading: boolean;
  insightError: ApiError | null;
  reloadInsight: () => void;
  reload: () => void;
  /** last poll failed: showing the last data received */
  stale: boolean;
}

const POLL = 30_000;

/** Everything one record needs. Consensus and timeline are required; the rest degrade panel by panel. */
export function useRecord(patient: PatientSummary | null): {
  data: DashData | null;
  loading: boolean;
  error: ApiError | null;
  reload: () => void;
} {
  const base = patient ? `/v1/patients/${encodeURIComponent(patient.id)}` : null;
  const consensus = useApi<Consensus>(base && `${base}/consensus`, POLL);
  const timeline = useApi<TimelineResponse>(base && `${base}/timeline?days=60`, POLL * 2);
  const week = useApi<WeekSummary>(base && `${base}/week`, POLL * 4);
  const graph = useApi<KnowledgeGraph>(base && `${base}/graph`, POLL * 4);
  const phq9 = useApi<Phq9History>(base && `${base}/phq9`, POLL * 4);
  const events = useApi<LiveEventsResponse>(patient && `/v1/events?home_id=${encodeURIComponent(patient.id)}&limit=1000`, POLL * 2);
  // Two steps: the rule-based insight first (no model, fast), then the generated review, which upgrades the
  // Review and trace in place. If the second call fails the rule-based one stays, and the panel says so.
  const quick = useApi<PatientInsight>(base && `${base}/insight?generate=false`, POLL * 2);
  const full = useApi<PatientInsight>(base && `${base}/insight`, POLL * 10, 60_000);
  const insight = { data: full.data ?? quick.data, loading: full.loading, error: full.error, reload: full.reload };

  const data = useMemo<DashData | null>(() => {
    if (!patient || !consensus.data || !timeline.data) return null;
    const series = trimLeading(timeline.data.series);
    const obs = (events.data?.events ?? []) as unknown as ObsEvent[];
    return {
      patient,
      consensus: consensus.data,
      series,
      recorded: recordedDays(series),
      week: week.data,
      phq9: phq9.data,
      events: obs,
      view: insightView(insight.data, consensus.data, series, week.data, graph.data, obs, SOURCE_OF, sourceLabel),
      insightLoading: insight.loading,
      insightError: insight.error,
      reloadInsight: insight.reload,
      reload: () => {
        consensus.reload();
        timeline.reload();
        week.reload();
        graph.reload();
        phq9.reload();
        events.reload();
        quick.reload();
        full.reload();
      },
      stale: Boolean(consensus.error || timeline.error),
    };
      // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patient, consensus.data, consensus.error, timeline.data, timeline.error, week.data, graph.data, phq9.data, events.data, insight.data, insight.loading, insight.error]);

  return {
    data,
    loading: consensus.loading || timeline.loading,
    error: data ? null : (consensus.error ?? timeline.error),
    reload: () => {
      consensus.reload();
      timeline.reload();
    },
  };
}
