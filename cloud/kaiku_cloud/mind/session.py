"""POST /v1/companion/session, /v1/companion/tool, /v1/companion/episode, /v1/companion/close — the companion
mind's use-cases.

session: persona + surface + context card (+ the surface's tools) -> one system instruction; an episode row is
opened (no transcript ever). tool: devices forward the model's tool calls; the crisis phrase check runs on every
string argument FIRST (hit -> nothing stored, obs.safety_flag raised, scripted message returned), then surface +
schema checks, then the deterministic effect (`ask_mind` -> mind/router.py). episode: closes a session (or records one run offline).
close: the device reports how long a conversation ran, so its Live budget reservation settles to that (live_token).
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from kaiku_contracts import budget, make, uuid7
from kaiku_contracts.api import (
    ChatShape,
    CompanionSessionRequest,
    CompanionSessionResponse,
    CompanionTool,
    CompanionToolCall,
    CompanionToolResult,
    EpisodeIn,
    SessionClose,
    SessionCloseResult,
)
from kaiku_contracts.companion_tools import TOOLS, allowed, for_surface, validate_args
from kaiku_contracts.config import load_config
from kaiku_contracts.jlog import get_logger
from kaiku_contracts.safety import SafetyCheck
from kaiku_contracts.safety import version as safety_version

from .. import service
from ..settings import Settings
from ..store.db import Store
from . import affect, assemble, feel, graph, live_token, memory, router, walk
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
    previous = store.episode(req.resume_session_id) if req.resume_session_id else None
    if req.resume_session_id and (previous is None or previous["home_id"] != req.home_id or
                                  previous["surface"] != req.surface or previous["end"] is not None or
                                  previous["outcome"] is not None):
        raise ValueError("only an open session belonging to this home and surface can resume")
    live = load_config().get("live", {})
    walking = walk.is_walk(req.purpose, req.intent)
    # A talk on the phone or Mac is like a call and a walk is a walk: the person sets the length. Everything else
    # (a check-in, a break, an activity, the robot's ritual) keeps the short limit.
    calling = req.surface in ("iphone", "mac") and (req.purpose == "talk" or (req.purpose is None and req.intent == "talk"))
    cap = live.get("walk_max_minutes" if walking else "talk_max_minutes" if calling else "session_max_minutes", 5)
    max_seconds = int(float(cap) * 60)
    if previous:
        started = datetime.fromisoformat(previous["start"].replace("Z", "+00:00"))
        max_seconds -= int((now - started).total_seconds())
        if max_seconds <= 0:
            raise ValueError("session duration limit reached")
    style = walk.style_of(req.walk_style) if walking else None
    card = build_card(store, settings, req.home_id, intent=req.intent, language=req.language,
                      others_present=req.others_present, now=now, purpose=req.purpose, walk_style=style)
    feel.prepare(store, req.home_id, now)  # so the `feel` tool answers without scanning the record mid-conversation
    persona, surfaces = assemble.load_files()
    tools = for_surface(req.surface, walk=walking)
    instruction = assemble.assemble(persona, surfaces, req.surface, card_dict(card), tools=[t["name"] for t in tools])
    sid = req.resume_session_id or str(uuid7())
    if not previous:
        store.episode_upsert({"id": sid, "home_id": req.home_id, "surface": req.surface, "intent": req.intent,
                              "start": memory.iso(now), "tools": []})
    model, voice = models()
    pv = assemble.persona_version(persona)
    setup = live_token.setup(model, voice, instruction, tools)
    # Robot is a trusted server-side adapter with its own budgeted key; apps receive one reserved token.
    # One token and its budget reservation cover at most `token_minutes`; a longer call resumes and gets the next.
    token_minutes = min(max_seconds / 60, float(live.get("token_minutes", 10)))
    if previous:  # the token before this one was in use until now: settle it before the next one is reserved
        live_token.settle(store, sid, via="resume")
    token = None if req.surface == "robot" else mint(model, live_setup=setup, home_id=req.home_id,
                                                     minutes=token_minutes, session_id=sid)
    log.info("companion_session", req.intent, home=req.home_id, surface=req.surface, persona=pv, live=token is not None)
    return CompanionSessionResponse(
        session_id=sid, model=model, voice=voice, system_instruction=instruction,
        tools=[CompanionTool(**t) for t in tools], context_card=card, persona_version=pv,
        safety_phrases_version=safety_version(), live_token=token, live_setup=setup,
        max_session_seconds=max_seconds,
        walk=walk.guide(style) if style else None,
        idle_end_s=int(live.get("walk_idle_end_s" if walking else "idle_end_s", 0)) or None,
        chat_shape=ChatShape(purpose=card.purpose, depth=card.chat_depth or "brief", open_items=card.open_items)
        if card.purpose else None,
        context_refresh_seconds=int(live.get("context_refresh_seconds", 15)))


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
        live_token.seen(store, session_id)  # the conversation was alive now: no settlement may end it earlier


def _crisis(store: Store, settings: Settings, call: CompanionToolCall, hit_lang: str) -> CompanionToolResult:
    env = make("obs.safety_flag", {"trigger": "phrase", "handled_locally": False}, source="cloud",
               home_id=call.home_id)
    store.insert_events([env.model_dump(mode="json", exclude_none=True)])
    service.recompute_home(store, settings, call.home_id)
    ep = store.episode(call.session_id) if call.session_id else None
    if ep:
        store.episode_upsert({**ep, "end": memory.iso(datetime.now(UTC)), "outcome": "crisis"})
        affect.forget(store, call.home_id, ep["id"])  # nothing of a crisis conversation is summarised
        feel.close(store, call.home_id, ep["id"], crisis=True)
        live_token.settle(store, ep["id"], via="crisis",  # the device stops the conversation and shows the script
                          grace_s=float(load_config().get("live", {}).get("settle_grace_s", 10)))
    log.warning("companion_tool_crisis", call.name, home=call.home_id, surface=call.surface)
    return CompanionToolResult(ok=False, name=call.name, crisis=True, error="crisis",
                               result={"stop_session": True, "script": _gate().script(hit_lang)})


def run_tool(store: Store, settings: Settings, call: CompanionToolCall,
             now: datetime | None = None) -> CompanionToolResult:
    now = now or datetime.now(UTC)
    name = call.name
    episode = store.episode(call.session_id) if call.session_id else None
    if episode and (episode["home_id"] != call.home_id or episode["surface"] != call.surface):
        return CompanionToolResult(ok=False, name=name, error="session does not belong to this home and surface")
    if episode and episode["outcome"] == "crisis":
        return CompanionToolResult(ok=False, name=name, crisis=True, error="crisis",
                                   result={"stop_session": True, "script": _gate().script("en")})
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
            if episode and not memory.grounded(a["text"], a.get("said")):
                # In a live conversation the model must show the person's own words the fact comes from. The cloud
                # never hears the audio, so this is the check it can make: no words, or words that do not contain
                # the fact, store nothing.
                return CompanionToolResult(ok=False, name=name, error=(
                    "not stored: pass `said` with the person's own words that contain this fact, and only keep "
                    "what they told you and want kept. Ask them first if unsure."))
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
            if a["scope"] == "all":
                affect.forget_heard(store, home)
        elif name == "recall":
            res = {"memories": [m["text"] for m in memory.recall(store, home, a["topic"], now=now)]}
        elif name == "suggest_nudge":
            n = service.nudge(store, settings, home)
            res = {"arm": n.arm, "suggestion": SUGGESTION.get(n.arm)}
        elif name == "feel":
            res = feel.act(store, home, call.surface, call.session_id, episode, a, now)
        elif name == "end_session":
            res = end_session(store, call, a, now)
            feel.close(store, home, call.session_id)
            # the goodbye is still being spoken: a few seconds' grace, and a later close or episode can only add
            live_token.settle(store, call.session_id, via="end_session",
                              grace_s=float(load_config().get("live", {}).get("settle_grace_s", 10)))
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
    res: dict[str, Any] = {"closed": ep is not None}
    follow_up = a.get("follow_up")
    def open_follow_up():
        return memory.open_thread(store, call.home_id, follow_up["skill"], follow_up["topic"], now)
    if ep:
        effects = store.episode_thread_effects(
            call.home_id, ep["id"],
            close=(lambda: memory.close_threads_for(store, call.home_id, ep["intent"], now)) if outcome == "completed" else None,
            open_thread=open_follow_up if follow_up else None)
        if "open" in effects:
            res["thread_id"] = effects["open"]
    elif follow_up:
        res["thread_id"] = open_follow_up()
    return res


def close_session(store: Store, body: SessionClose) -> SessionCloseResult:
    """The device says a conversation stopped and how long it ran. Only the meter: nothing else about the
    session changes (the episode is recorded by its own route). KeyError: not this home's session."""
    ep = store.episode(body.session_id)
    if ep is None or ep["home_id"] != body.home_id:
        raise KeyError(body.session_id)
    rows = live_token.settle(store, body.session_id, via="close", elapsed_s=body.elapsed_s)
    return SessionCloseResult(ok=True, session_id=body.session_id, settled=len(rows),
                              billed_minutes=budget_minutes(body.session_id))


def budget_minutes(session_id: str) -> float:
    try:
        return float(budget.session_minutes(session_id))
    except Exception:  # the ledger is a brake, not a dependency
        return 0.0


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
    crisis = ep.outcome == "crisis" or bool(old and old["outcome"] == "crisis") or any(
        _gate().check(turn.text) for turn in ep.transcript or [])
    store.episode_upsert({"id": eid, "home_id": ep.home_id, "surface": ep.surface, "intent": ep.intent,
                          "start": memory.iso(ep.start), "end": memory.iso(end), "outcome": "crisis" if crisis else ep.outcome,
                          "tools": sorted({*(old["tools"] if old else []), *ep.tools_used})})
    if not crisis:
        def close_threads():
            if ep.close_thread:
                return store.thread_close(ep.home_id, memory.iso(end))
            return memory.close_threads_for(store, ep.home_id, ep.intent, end)
        store.episode_thread_effects(
            ep.home_id, eid, close=close_threads if ep.close_thread or ep.outcome == "completed" else None,
            open_thread=(lambda: memory.open_thread(store, ep.home_id, ep.open_thread.skill, ep.open_thread.topic, end))
            if ep.open_thread else None)
    if not crisis and transcript_allowed(ep):
        stored = store.transcript_upsert({"episode_id": eid, "home_id": ep.home_id, "surface": ep.surface, "intent": ep.intent,
                                 "start": memory.iso(ep.start),
                                 "turns": [t.model_dump() for t in ep.transcript or []]})
        if stored:
            log.info("transcript_stored", ep.surface, home=ep.home_id, turns=len(ep.transcript or []))  # never the text
    feel.close(store, ep.home_id, eid, crisis=crisis)
    # A recorded episode says how long the conversation ran (the device's own start and end).
    live_token.settle(store, eid, via="episode",
                      elapsed_s=(ep.end - ep.start).total_seconds() if ep.end else None)
    affect.on_episode(store, ep.home_id, eid, start=memory.iso(ep.start), surface=ep.surface, intent=ep.intent,
                      outcome=ep.outcome, crisis=crisis,
                      turns=[t.model_dump() for t in ep.transcript] if ep.transcript and not crisis else None)
    return eid
