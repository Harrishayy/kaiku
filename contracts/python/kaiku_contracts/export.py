"""Export JSON Schemas (and a combined bundle for TS generation) from the pydantic models.

    uv run python -m kaiku_contracts.export            # writes contracts/schemas/
    uv run python -m kaiku_contracts.export --check    # exit 1 if schemas on disk are stale

The pydantic models are the single source of truth; contracts/schemas/ is generated and committed
so non-Python modules (firmware, web, glasses) can read it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic.json_schema import models_json_schema

from . import api, companion_tools
from .envelope import SCHEMA_VERSION, SOURCES, Envelope
from .registry import EXAMPLES, REGISTRY
from .sources import CONSENSUS_SOURCES, SOURCE_LABELS, SOURCE_OF

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "schemas"

API_MODELS = [
    api.APIDiscoveryResponse,
    api.ClinicianAskRequest, api.RecordCitation, api.ClinicianAskResponse,
    api.TaskObservationsResponse,
    api.EventsBatch, api.EventsResult, api.CommandsResponse, api.CommandAckResult, api.VerdictEvidence, api.SourceVerdict,
    api.SourceNote, api.Explanation, api.Consensus, api.SourceBadge, api.PatientSummary, api.PatientsResponse,
    api.TimelinePoint, api.MetricSeries, api.TimelineResponse, api.Phq9Entry, api.Phq9History,
    api.ActionRequest, api.ActionResult, api.NudgeResponse, api.HelpStat, api.Mascot, api.Highlight, api.Garden,
    api.MeResponse, api.VoiceLinesResponse, api.VoiceSayRequest, api.StateScore,
    api.EvalResult, api.Healthz, api.LiveEventsResponse, api.NodeHealthReport, api.HealthOverview,
    api.CriteriaResponse, api.CriteriaUpdate, api.PreviewChange, api.CriteriaPreview,
    api.LastReflection, api.ContextCard, api.CompanionSessionRequest, api.LiveToken, api.CompanionTool, api.CompanionSessionResponse,
    api.CompanionToolCall, api.CompanionToolResult, api.Memory, api.MemoriesResponse, api.MemorySettings,
    api.DeletedResponse, api.ThreadIn, api.TranscriptTurn, api.EpisodeIn, api.EpisodeResult,
    api.Transcript, api.TranscriptsResponse,
    api.MindAnswer, api.ModelUsageRow, api.IntelligenceHealth, api.ConstellationNode, api.ConstellationEdge,
    api.ConstellationResponse, api.PostcardRequest, api.PostcardResponse, api.BriefSection, api.ClinicianBrief,
    api.CareSharing, api.SourceCount, api.SourceWeek, api.NextStep, api.Routine, api.WeekItem, api.WeekSummary, api.GraphNode, api.GraphEdge, api.KnowledgeGraph,
    api.ReviewFinding, api.PatientReview, api.AgentStep, api.MetricComparison, api.GroupComparison,
    api.PeriodComparison, api.HelpEffect, api.LearnedRoutine, api.InsightNode, api.InsightEdge, api.InsightGraph,
    api.ObsTypeCoverage, api.GroupCoverage, api.DataCoverage, api.CourseEvent, api.Course, api.DayAccount, api.ReflectionDay, api.ReflectionOverview, api.StateDay, api.CareAction, api.PatientInsight,
]


def _path_for(type_: str) -> str:
    kind, _, rest = type_.partition(".")
    if not rest:
        return f"{kind}.schema.json"
    return f"{kind}/{rest}.schema.json"


def build() -> dict[str, Any]:
    """Return {relative_path: json_obj} for every generated file."""
    files: dict[str, Any] = {}
    files["envelope.schema.json"] = Envelope[dict[str, Any]].model_json_schema()
    index: dict[str, Any] = {}
    for type_, model in REGISTRY.items():
        rel = _path_for(type_)
        schema = Envelope[model].model_json_schema()  # type: ignore[valid-type]
        schema["title"] = f"Envelope<{type_}>"
        files[rel] = schema
        kind, _, rest = type_.partition(".")
        topic = f"kaiku/v1/<home_id>/{kind}/" + (rest.replace(".", "/") if rest else "<source>")
        index[type_] = {"schema": rel, "topic": topic, "payload_model": model.__name__}
    for m in API_MODELS:
        files[f"api/{m.__name__}.schema.json"] = m.model_json_schema()
    files["../ts/index.ts"] = build_ts_index()
    files["companion_tools.json"] = companion_tools.export()
    files["index.json"] = {"schema_version": SCHEMA_VERSION, "types": index}
    files["examples.json"] = EXAMPLES
    files["sources.json"] = {"consensus_sources": list(CONSENSUS_SOURCES), "source_labels": SOURCE_LABELS,
                             "source_of": SOURCE_OF}

    # Combined bundle with every payload + API model in $defs (input for TS generation).
    _, bundle = models_json_schema(
        [(m, "validation") for m in {*REGISTRY.values(), *API_MODELS}],
        ref_template="#/$defs/{model}",
    )
    for d in bundle.get("$defs", {}).values():
        _strip_titles(d, keep=True)
    bundle["title"] = "KaikuContracts"
    bundle["type"] = "object"
    files["bundle.schema.json"] = bundle
    return files


def _strip_titles(node: Any, keep: bool = False) -> None:
    """Drop nested schema titles so TS generation inlines primitives instead of aliasing them."""
    if isinstance(node, list):
        for v in node:
            _strip_titles(v)
        return
    if not isinstance(node, dict):
        return
    if not keep:
        node.pop("title", None)
    for k, v in node.items():
        if k == "properties" and isinstance(v, dict):
            for prop_schema in v.values():  # keys here are field names, never strip them
                _strip_titles(prop_schema)
        elif k != "$defs":
            _strip_titles(v)


def build_ts_index() -> str:
    """Hand-off-free TS: Envelope<T>, the type -> payload map, and topic helpers."""
    lines = [
        "/* GENERATED by `make contracts` from contracts/python (pydantic). Do not edit. */",
        "import type * as M from './models';",
        "export * from './models';",
        "",
        f"export const SCHEMA_VERSION = {SCHEMA_VERSION};",
        "export type Source = " + " | ".join(f"'{s}'" for s in SOURCES) + ";",
        "",
        "export interface Envelope<P = unknown, T extends string = string> {",
        "  v: 1;",
        "  id: string; // UUIDv7, idempotency key",
        "  ts: string; // UTC ISO-8601 with ms, e.g. 2026-11-14T08:12:03.120Z",
        "  home_id: string;",
        "  source: Source;",
        "  type: T;",
        "  payload: P;",
        "  quality?: number | null;",
        "  sim?: boolean;",
        "}",
        "",
        "export interface PayloadByType {",
    ]
    for type_, model in REGISTRY.items():
        lines.append(f"  '{type_}': M.{model.__name__};")
    lines += [
        "}",
        "export type MessageType = keyof PayloadByType;",
        "export type Message<T extends MessageType = MessageType> = { [K in T]: Envelope<PayloadByType[K], K> }[T];",
        "",
        "export const CONSENSUS_SOURCES = " + json.dumps(list(CONSENSUS_SOURCES)) + " as const;",
        "export type ConsensusSource = (typeof CONSENSUS_SOURCES)[number];",
        "/** obs type -> consensus source | learner | adherence | override (mirrors kaiku_contracts.sources). */",
        "export const SOURCE_OF: Record<string, string> = " + json.dumps(SOURCE_OF) + ";",
        "/** Display labels for consensus sources (\"laptop\" is shown as \"Apps\"). */",
        "export const SOURCE_LABELS: Record<ConsensusSource, string> = " + json.dumps(SOURCE_LABELS) + ";",
        "",
        "/** Companion tool registry (mirrors kaiku_contracts.companion_tools): tools, surfaces, intents, skills. */",
        "export const COMPANION_TOOLS = " + json.dumps(companion_tools.export()) + " as const;",
        "",
        "/** MQTT topic for a message (mirrors kaiku_contracts.topic_for). */",
        "export function topicFor(env: Pick<Envelope, 'home_id' | 'type' | 'source'>): string {",
        "  const [kind, ...rest] = env.type.split('.');",
        "  const name = kind === 'health' || kind === 'log' ? env.source : rest.join('/');",
        "  return `kaiku/v1/${env.home_id}/${kind}/${name}`;",
        "}",
        "",
    ]
    return "\n".join(lines)


def _dump(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="fail if files on disk differ")
    args = ap.parse_args(argv)
    files = build()
    stale = []
    for rel, obj in files.items():
        path = args.out / rel
        text = _dump(obj)
        if args.check:
            if not path.exists() or path.read_text() != text:
                stale.append(rel)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if args.check:
        if stale:
            print("stale schemas (run `make contracts`):", *stale, sep="\n  ", file=sys.stderr)
            return 1
        print(f"schemas up to date ({len(files)} files)")
        return 0
    print(f"wrote {len(files)} files to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
