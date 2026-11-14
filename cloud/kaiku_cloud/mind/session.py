"""POST /v1/companion/session, /v1/companion/tool, /v1/companion/episode — the companion mind's use-cases.

session: persona + surface + context card (+ the surface's tools) -> one system instruction; an episode row is
opened (no transcript ever). tool: devices forward the model's tool calls; the crisis phrase check runs on every
string argument FIRST (hit -> nothing stored, obs.safety_flag raised, scripted message returned), then surface +
schema checks, then the deterministic effect (`ask_mind` -> mind/router.py). episode: closes a session (or records one run offline).
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from kaiku_contracts import make, uuid7
from kaiku_contracts.api import (
    CompanionSessionRequest,
    CompanionSessionResponse,
    CompanionTool,
    CompanionToolCall,
    CompanionToolResult,
    EpisodeIn,
)
from kaiku_contracts.companion_tools import TOOLS, allowed, for_surface, validate_args
from kaiku_contracts.config import load_config
from kaiku_contracts.jlog import get_logger
from kaiku_contracts.safety import SafetyCheck
from kaiku_contracts.safety import version as safety_version

from .. import service
from ..settings import Settings
from ..store.db import Store
from . import assemble, graph, live_token, memory, router
from .card import SUGGESTION, build_card, card_dict, done_today

log = get_logger("cloud.mind")


@lru_cache(maxsize=1)
def _gate() -> SafetyCheck:
    return SafetyCheck.from_file()


def models() -> tuple[str, str]:
    cfg = load_config()
    return str(cfg.get("models", {}).get("gemini_live", "")), str(cfg.get("voice", {}).get("name", ""))


def start_session(store: Store, settings: Settings, req: CompanionSessionRequest,
                  now: datetime | None = None, mint=live_token.mint) -> CompanionSessionResponse:
    now = now or datetime.now(UTC)
    card = build_card(store, settings, req.home_id, intent=req.intent, language=req.language,
                      others_present=req.others_present, now=now)
    persona, surfaces = assemble.load_files()
    tools = for_surface(req.surface)
    instruction = assemble.assemble(persona, surfaces, req.surface, card_dict(card), tools=[t["name"] for t in tools])
    sid = str(uuid7())
    store.episode_upsert({"id": sid, "home_id": req.home_id, "surface": req.surface, "intent": req.intent,
                          "start": memory.iso(now), "tools": []})
    model, voice = models()
    pv = assemble.persona_version(persona)
    setup = live_token.setup(model, voice, instruction, tools)
    token = mint(model, live_setup=setup)
    log.info("companion_session", req.intent, home=req.home_id, surface=req.surface, persona=pv, live=token is not None)
    return CompanionSessionResponse(
        session_id=sid, model=model, voice=voice, system_instruction=instruction,
        tools=[CompanionTool(**t) for t in tools], context_card=card, persona_version=pv,
        safety_phrases_version=safety_version(), live_token=token, live_setup=setup)


def _strings(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    return []


def _log_tool(store: Store, session_id: str | None, name: str) -> None:
    ep = store.episode(session_id) if session_id else None
    if ep:
        store.episode_upsert({**ep, "tools": [*ep["tools"], name]})


def _crisis(store: Store, settings: Settings, call: CompanionToolCall, hit_lang: str) -> CompanionToolResult:
    env = make("obs.safety_flag", {"trigger": "phrase", "handled_locally": False}, source="cloud",
               home_id=call.home_id)
    store.insert_events([env.model_dump(mode="json", exclude_none=True)])
    service.recompute_home(store, settings, call.home_id)
    ep = store.episode(call.session_id) if call.session_id else None
    if ep:
        store.episode_upsert({**ep, "end": memory.iso(datetime.now(UTC)), "outcome": "crisis"})
    log.warning("companion_tool_crisis", call.name, home=call.home_id, surface=call.surface)
    return CompanionToolResult(ok=False, name=call.name, crisis=True, error="crisis",
                               result={"stop_session": True, "script": _gate().script(hit_lang)})


def run_tool(store: Store, settings: Settings, call: CompanionToolCall,
             now: datetime | None = None) -> CompanionToolResult:
    now = now or datetime.now(UTC)
    name = call.name
    for s in _strings(call.args):
        hit = _gate().check(s)
        if hit:
            return _crisis(store, settings, call, hit.language)
    if name not in TOOLS:
        return CompanionToolResult(ok=False, name=name, error="unknown tool")
    spec = TOOLS[name]
    if not allowed(name, call.surface):
        return CompanionToolResult(ok=False, name=name, executor=spec["executor"], error="not on this surface")
    problems = validate_args(spec["parameters"], call.args)
    if problems:
        return CompanionToolResult(ok=False, name=name, executor=spec["executor"], error="; ".join(problems))
    _log_tool(store, call.session_id, name)
    log.info("companion_tool", name, home=call.home_id, surface=call.surface)  # name only, never the args' text
    if spec["executor"] == "device":
        return CompanionToolResult(ok=True, name=name, executor="device", result={"device": True})
    a, home = call.args, call.home_id
    try:
        if name == "remember":
            res = memory.remember(store, home, a["category"], a["text"], now)
            if res["action"] in ("stored", "forgot"):
                graph.on_memory_write(store, home)
        elif name == "ask_mind":
            today = done_today(store.events_for_home(home), store.episodes(home), now)
            res = router.ask(store, settings, home, a["question"], a["kind"], done_today=today,
                             now=now).model_dump(mode="json")
        elif name == "forget":
            res = memory.forget(store, home, a["scope"])
            graph.on_memory_write(store, home)
        elif name == "recall":
            res = {"memories": [m["text"] for m in memory.recall(store, home, a["topic"], now=now)]}
        elif name == "suggest_nudge":
            n = service.nudge(store, settings, home)
            res = {"arm": n.arm, "suggestion": SUGGESTION.get(n.arm)}
        elif name == "end_session":
            res = end_session(store, call, a, now)
        else:  # pragma: no cover - every cloud tool is handled above
            return CompanionToolResult(ok=False, name=name, error="not implemented")
    except memory.MemoryRefused as e:
        return CompanionToolResult(ok=False, name=name, error=str(e))
    return CompanionToolResult(ok=True, name=name, result=res)


def end_session(store: Store, call: CompanionToolCall, a: dict[str, Any], now: datetime) -> dict[str, Any]:
    ep = store.episode(call.session_id) if call.session_id else None
    outcome = a.get("outcome", "completed")
    if ep:
        store.episode_upsert({**ep, "end": memory.iso(now), "outcome": outcome})
        if outcome == "completed":
            memory.close_threads_for(store, call.home_id, ep["intent"], now)
    res: dict[str, Any] = {"closed": ep is not None}
    if a.get("follow_up"):
        res["thread_id"] = memory.open_thread(store, call.home_id, a["follow_up"]["skill"], a["follow_up"]["topic"],
                                              now)
    return res


def transcript_allowed(ep: EpisodeIn) -> bool:
    """An opt-in transcript is kept unless the conversation touched a crisis: then nothing of it is stored."""
    if not ep.transcript or ep.outcome == "crisis":
        return False
    return not any(_gate().check(t.text) for t in ep.transcript)


def record_episode(store: Store, ep: EpisodeIn) -> str:
    eid = ep.id or str(uuid7())
    old = store.episode(eid)
    if old and old["home_id"] != ep.home_id:
        raise ValueError("episode id belongs to another home")
    end = ep.end or datetime.now(UTC)
    store.episode_upsert({"id": eid, "home_id": ep.home_id, "surface": ep.surface, "intent": ep.intent,
                          "start": memory.iso(ep.start), "end": memory.iso(end), "outcome": ep.outcome,
                          "tools": sorted({*(old["tools"] if old else []), *ep.tools_used})})
    if ep.close_thread or ep.outcome == "completed":
        if ep.close_thread:
            store.thread_close(ep.home_id, memory.iso(end))
        else:
            memory.close_threads_for(store, ep.home_id, ep.intent, end)
    if ep.open_thread:
        memory.open_thread(store, ep.home_id, ep.open_thread.skill, ep.open_thread.topic, end)
    if transcript_allowed(ep):
        store.transcript_upsert({"episode_id": eid, "home_id": ep.home_id, "surface": ep.surface, "intent": ep.intent,
                                 "start": memory.iso(ep.start),
                                 "turns": [t.model_dump() for t in ep.transcript or []]})
        log.info("transcript_stored", ep.surface, home=ep.home_id, turns=len(ep.transcript or []))  # never the text
    return eid
