"""Nightly mind job (plan 06 §2): POST /v1/admin/nightly-mind. Per home, inside the API process (one writer):

1. graph rebuild + Gemini Embedding 2 backfill of every memory/node without a fresh vector;
2. consolidation: deterministic proposals (same-type labels contained in each other) + Gemini 4 Argon proposals,
   both as diffs {op: merge|expire}; only `graph.validate_diffs` survivors are applied (node status only — the
   person's memories are never edited by a model);
3. the personalised line pre-render list (greetings with the person's name) for the voice cache.
The Argon judge over sampled companion-eval scenarios is NOT run here: the scenarios live in tools/companion_evals and
the cloud may not import tools/ (module boundary). Run `make eval-companion` (judge = gemini-4-argon) instead.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..llm import gemini
from ..llm.errors import LlmUnavailable
from ..store.db import Store
from . import graph, memory, router

SCHEMA = {"type": "object", "required": ["diffs"], "properties": {"diffs": {"type": "array", "items": {
    "type": "object", "required": ["op"], "properties": {
        "op": {"type": "string", "enum": ["merge", "expire"]}, "keep": {"type": "string"},
        "drop": {"type": "string"}, "node": {"type": "string"}}}}}}
SYSTEM = (
    "You tidy a small personal memory graph for a companion robot. Propose diffs only: merge two nodes that say "
    "the same thing (keep the clearer one), expire plans that are clearly over. Never merge different people. "
    "Use only the node ids given. If nothing needs tidying, return an empty list. JSON only."
)
JUDGE_NOTE = ("skipped: eval scenarios live in tools/companion_evals and the cloud may not import tools/; "
              "run `make eval-companion` (Argon judge) from CI or a laptop")


def prerender_lines(store: Store, home_id: str) -> list[dict[str, str]]:
    name = memory.first_name(store, home_id)
    if not name:
        return []
    return [{"key": f"greet_morning_{home_id}", "text": f"Good morning, {name}!"},
            {"key": f"greet_hello_{home_id}", "text": f"Hi {name}, nice to see you."},
            {"key": f"goodbye_{home_id}", "text": f"See you soon, {name}."}]


def consolidate(store: Store, home_id: str, now: datetime, gen: Any = None) -> dict[str, Any]:
    gen = gen or gemini.generate
    proposals = graph.rule_diffs(store, home_id)
    by = ["rule"]
    if gemini.available() and router.argon_left(store, home_id, now):
        nodes = [{"id": f"kg:{n['id']}", "type": n["type"], "label": n["label"]} for n in store.kg_nodes(home_id)
                 if n["status"] == "active" and n["type"] not in ("me", "activity") and router.clean_fact(n["label"])]
        if len(nodes) > 1:
            try:
                raw = json.loads(gen(json.dumps({"nodes": nodes}, ensure_ascii=False), tier="flagship", system=SYSTEM,
                                     schema=SCHEMA, timeout_s=40, task="consolidate", home_id=home_id, route="argon"))
                proposals += raw.get("diffs", []) if isinstance(raw, dict) else []
                by.append(gemini.model_for("flagship"))
            except (LlmUnavailable, json.JSONDecodeError):
                pass
    diffs = graph.validate_diffs(store, home_id, proposals)
    applied = graph.apply_diffs(store, home_id, diffs)
    return {"proposed": len(proposals), "applied": applied, "diffs": diffs, "by": by}


def run(store: Store, home_ids: list[str], now: datetime | None = None, gen: Any = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    homes: dict[str, Any] = {}
    for hid in home_ids:
        built = graph.rebuild(store, hid, now)
        embedded = graph.index(store, hid)
        cons = consolidate(store, hid, now, gen)
        lines = prerender_lines(store, hid)
        store.kv_set(f"prerender:{hid}", lines)
        homes[hid] = {"graph": built, "embedded": embedded, "consolidation": cons, "prerender": len(lines)}
    return {"homes": homes, "judge": JUDGE_NOTE}
