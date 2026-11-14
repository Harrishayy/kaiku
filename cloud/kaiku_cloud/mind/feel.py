"""Notice and act: what Kaiku's mind does when the companion reports a feeling or news (`feel` tool).

The voice model is the only part of Kaiku that hears the person. When it notices a clear feeling it calls `feel`
with enums (kind, valence, energy, tone), a short topic and the person's own words. This module answers in code
only (no model call, a few small reads):

1. register: the moment joins the conversation's timeline (kv `feel:<home>`); while the person lets Kaiku
   remember things it is also kept with the conversation's summary (mind/affect.py, `heard`). With remembering
   off the timeline lives for the conversation only. The person's words (`said`) are never stored.
2. follow up: good news or a hard thing becomes the open thread for next time, when remembering is on and the
   topic is contained in the person's own words (the same guard `remember` uses) and is not a health detail.
3. plan: stance, depth (brief | stay), a reflect hint, one recall from what this person told Kaiku or recorded
   themselves, and at most one small thing to offer, once per conversation: the suggestion with the best recorded
   response for this person (with how sure that is), or sitting quietly. Nothing is offered or claimed that the
   record does not support.

Crisis phrases never arrive here: `session.run_tool` runs the safety gate on every argument first. Nothing in
this module reads or changes the consensus state; the practitioner flag stays with the rule engine.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from kaiku_contracts.api import FeelPlan
from kaiku_contracts.config import get

from .. import service
from ..analytics.metrics import parse_ts
from ..settings import TZ
from ..store.db import Store
from . import affect, memory
from .card import SUGGESTION, today_facts, tone_for

STANCE = {"sad_news": "comfort", "lonely": "comfort", "worried": "steady", "angry": "steady", "flat": "give_space",
          "good_news": "celebrate", "proud": "celebrate", "relief": "celebrate"}
BY_VALENCE = {"low": "comfort", "bright": "celebrate", "neutral": "explore"}
HARD_KINDS = {"sad_news", "lonely", "worried", "angry", "flat"}
FOLLOW = {"good_news": "their good news: ", "proud": "their good news: ", "relief": "their good news: ",
          "sad_news": "something hard: ", "worried": "something hard: ", "lonely": "something hard: "}
OTHER_FOLLOW = {"low": "something hard: ", "bright": "their good news: "}  # kind "other": by how it sounded
HINT = {
    "comfort": "Give back the thing and its feeling in their own words, slowly and softly. Then leave room: no "
               "fixing, no silver lining.",
    "steady": "Stay calm and plain. Give back what it is in their words; do not solve it, soothe it or argue.",
    "give_space": "Few words, ask for nothing. Let them know saying little is fine, and stay.",
    "celebrate": "Be glad out loud about {about}. Ask what it was like, or what the best bit was, and stay with it.",
    "explore": "Give back what you heard and ask one open question about it.",
}
# What the person's own words say happened, whatever label the voice model picked for it. The same sentence came
# back as `sad_news` in one real session and `other` in the next; the plan must not hinge on that.
LOSS = re.compile(
    r"\b(?:cancel\w*|called off|stood me up|let me down|didn'?t (?:come|show|turn up|call|ring|get (?:it|the|in))|"
    r"won'?t be (?:coming|able)|can'?t (?:come|make it)|died|passed away|funeral|put down|in(?:to)? hospital|"
    r"back in hospital|broke up|split up|left me|moved? away|moving away|lost (?:my|the|her|his|our)|"
    r"got (?:fired|sacked|rejected|turned down)|laid off|redundan\w*|rejected|turned (?:me )?down|"
    r"failed|bad news|an accident|fell out|not speaking to me)\b", re.I)
WIN = re.compile(
    r"\b(?:got (?:the|a|my) (?:job|place|flat|part|grant|offer)|got (?:in|accepted|engaged|promoted)|got it\b|"
    r"passed (?:my|the|it)|promot\w*|engaged|expecting a baby|was born|won\b|good news|accepted me|"
    r"offered me|finished (?:my|the|it)|finally (?:did|finished|made|managed)|for the first time|"
    r"(?:is|are) coming to (?:visit|see me|stay)|came to (?:visit|see me)|all clear)\b", re.I)
ARM_ACTIVITY = {"breathe": "breathe", "drum": "drum", "daylight_walk": "walk"}
QUIET = "sitting quietly together for a minute"
ASK_MORE = re.compile(r"can we (?:talk|keep talking)|i (?:need|want) to talk|tell you (?:more|about)|"
                      r"stay (?:a bit|with me)|don'?t go", re.I)
HEAVY_DAYS = 3  # a talk sounded low on this many of the last 7 days: "it has been a heavy few days"
LONG_WORDS = 30  # the person is telling a story, not answering in passing
KEEP_SESSIONS = 30
EPHEMERAL_HOURS = 2
PREP_MINUTES = 30
_STOP = {"that", "this", "with", "have", "been", "were", "they", "them", "then", "just", "really", "about", "again",
         "today", "yesterday", "very", "going", "still", "what", "when", "from", "would", "could", "there", "their"}


def _key(home_id: str) -> str:
    return f"feel:{home_id}"


def _terms(*texts: str | None) -> list[str]:
    words = re.findall(r"[^\W\d_]{4,}", memory.norm(" ".join(t for t in texts if t)))
    return list(dict.fromkeys(w for w in words if w not in _STOP))[:12]


# ------------------------------------------------------------------ prepared per session (kept off the hot path)
def prepare(store: Store, home_id: str, now: datetime) -> dict[str, Any]:
    """What the plan needs from the whole record: the best recorded helper and today's own ratings in words.
    Computed when a session starts and cached for its length, so `act` never scans the event history."""
    known = home_id in store.home_ids()
    data = service.patient_data(store, home_id, service.active_criteria(store)) if known else None
    best = service.best_response(data, service.nudge_arms(store, home_id)) if data else None
    prep = {"at": memory.iso(now), "help": best,
            "facts": today_facts(store.events_for_home(home_id), now) if known else []}
    store.kv_set(f"feel-prep:{home_id}", prep)
    return prep


def prepared(store: Store, home_id: str, now: datetime) -> dict[str, Any]:
    prep = store.kv_get(f"feel-prep:{home_id}")
    if isinstance(prep, dict) and now - parse_ts(prep["at"]) < timedelta(minutes=PREP_MINUTES):
        return prep
    return prepare(store, home_id, now)


# ------------------------------------------------------------------ the deterministic choices
def cue_of(valence: str, said: str | None, about: str | None) -> str | None:
    """loss | win | None, from the person's words (and the topic), only when how it sounded does not contradict it."""
    text = " ".join(t for t in (said, about) if t)
    if valence != "bright" and LOSS.search(text):
        return "loss"
    if valence != "low" and WIN.search(text):
        return "win"
    return None


def read_kind(kind: str, valence: str, said: str | None, about: str | None) -> str:
    """The kind the plan uses: the person's own words outrank the model's label when they clearly carry news."""
    cue = cue_of(valence, said, about)
    if cue == "loss" and kind not in ("sad_news", "lonely"):
        return "sad_news"
    if cue == "win" and kind not in ("good_news", "proud", "relief"):
        return "good_news"
    return kind


def stance_of(kind: str, valence: str) -> str:
    return STANCE.get(kind) or BY_VALENCE[valence]


def depth_of(kind: str, heard: dict[str, Any], said: str | None, earlier: int, heavy: int) -> tuple[str, str]:
    """(brief | stay, why). Brief is the default: a chat on the street. Stay when the feeling is clearly strong
    either way, when it has been building this week, or when the person keeps talking or asks for more.
    `kind` is the one `read_kind` settled on, so news in the person's own words counts whatever the label was."""
    valence, energy, tone = heard["valence"], heard.get("energy"), heard.get("tone") or []
    if kind in ("sad_news", "good_news"):
        return "stay", "news"
    if valence == "low" and ("tearful" in tone or energy == "high"):
        return "stay", "upset"
    if valence == "bright" and energy == "high":
        return "stay", "very glad"
    if heavy >= HEAVY_DAYS and (valence == "low" or kind == "flat" and valence != "bright"):
        return "stay", "heavy week"
    if earlier and valence != "neutral":
        return "stay", "came back to it"
    if said and (len(said.split()) >= LONG_WORDS or ASK_MORE.search(said)):
        return "stay", "they are talking"
    return "brief", "ordinary"


def how_sure(tries: int) -> str:
    if tries < int(get("insight", "help_early_tries", 3)):
        return "tried only once or twice, so it is a guess"
    return "a few times so far" if tries < int(get("insight", "help_consistent_tries", 8)) else "most times they tried it"


def recall_for(store: Store, home_id: str, stance: str, about: str | None, said: str | None, now: datetime,
               facts: list[str], before: dict[str, Any] | None) -> str | None:
    """One thing the record already knows that fits this moment, or nothing."""
    terms = _terms(about, said)
    mems = store.memory_search(home_id, terms, 6) if terms and memory.remembering(store, home_id) else []
    if stance == "celebrate":
        thread = memory.current_thread(store, home_id, now)
        if thread and set(_terms(thread["topic"])) & set(terms):
            return f'This is what was left open last time: "{thread["topic"]}".'
        hoped = next((m for m in mems if m["category"] == "plans"), None)
        if hoped:
            return f'They were hoping for this. They told you: "{hoped["text"]}".'
        mem = next((m for m in mems if m["category"] in ("people", "likes", "places")), None)
        return f'They told you before: "{mem["text"]}".' if mem else None
    helps = next((m for m in mems if m["category"] == "what_helps"), None) or next(
        (m for m in store.memories(home_id) if m["category"] == "what_helps"), None) \
        if memory.remembering(store, home_id) else None
    if helps:
        return f'They told you this helps them: "{helps["text"]}".'
    person = next((m for m in mems if m["category"] == "people"), None)
    if person:
        return f'They told you before: "{person["text"]}".'
    if before and affect.is_low(before):
        return f"The talk {before['when']} sounded hard too."
    night = next((f for f in facts if f == "a short night"), None)
    return f"They rated last night as {night}." if night else None


def offer_for(stance: str, kind: str, cue: str, offered: bool, best: dict[str, Any] | None
              ) -> tuple[str | None, str | None, str | None]:
    """(may_offer, offer_note, offer_activity). One thing, once per conversation, only for a hard moment."""
    if stance in ("celebrate", "explore") or kind == "angry":
        return None, None, None
    if offered:
        return None, "You already offered once in this conversation. Do not offer again; just be with them.", None
    rule = "Offer it once, as a question, only after they feel heard. A no is final; start nothing unasked."
    if cue == "extra-gentle" or not best:
        why = "Nothing in the record says what helps them yet. " if not best else ""
        return QUIET, f"{why}{rule}", None
    what = SUGGESTION[best["arm"]]
    return what, (f"It has gone well for them before ({how_sure(best['tries'])}). {rule} "
                  f"Sitting quietly together is always fine instead."), ARM_ACTIVITY.get(best["arm"])


def save_follow_up(store: Store, home_id: str, kind: str, valence: str, about: str | None, said: str | None,
                   now: datetime) -> bool:
    """Good news or a hard thing becomes the thread to ask about next time, under the rules `remember` follows:
    remembering on, the topic contained in the person's own words, no health detail."""
    kind = read_kind(kind, valence, said, about)
    prefix = FOLLOW.get(kind) or (OTHER_FOLLOW.get(valence) if kind == "other" else None)
    if not prefix or not about or not memory.remembering(store, home_id) or not memory.grounded(about, said):
        return False
    try:
        memory.open_thread(store, home_id, "weather_check", (prefix + about)[:80], now)
    except memory.MemoryRefused:
        return False
    return True


def plan_from(kind: str, heard: dict[str, Any], about: str | None, said: str | None, *, earlier: int, heavy: int,
              cue: str, offered: bool, best: dict[str, Any] | None, recall: str | None, follow_up: bool) -> FeelPlan:
    """The whole decision as one pure function of the moment and what the record knows (the companion evals run
    exactly this with a fixture record)."""
    kind = read_kind(kind, heard["valence"], said, about)
    stance = stance_of(kind, heard["valence"])
    depth, _why = depth_of(kind, heard, said, earlier, heavy)
    hint = HINT[stance].format(about=about or "it")
    if heavy >= HEAVY_DAYS and heard["valence"] != "bright" and (heard["valence"] == "low" or kind in HARD_KINDS):
        hint += f" It has sounded heavy on {heavy} days this week: you may say, once, that it has been a heavy few days."
    may_offer, note, activity = offer_for(stance, kind, cue, offered, best)
    return FeelPlan(stance=stance, depth=depth, reflect_hint=hint, recall=recall,  # type: ignore[arg-type]
                    may_offer=may_offer, offer_note=note, offer_activity=activity,  # type: ignore[arg-type]
                    follow_up_saved=follow_up, scheduling=str(get("live", "feel_scheduling", "WHEN_IDLE")))  # type: ignore[arg-type]


# ------------------------------------------------------------------ the tool
def _sessions(store: Store, home_id: str, now: datetime) -> dict[str, Any]:
    """Conversation timelines; ones that may not be kept go once their conversation is over."""
    old = memory.iso(now - timedelta(hours=EPHEMERAL_HOURS))
    live = {k: v for k, v in (store.kv_get(_key(home_id)) or {}).items() if v.get("keep") or v["start"] > old}
    return dict(sorted(live.items(), key=lambda kv: kv[1]["start"])[-KEEP_SESSIONS:])


def act(store: Store, home_id: str, surface: str, session_id: str | None, episode: dict[str, Any] | None,
        args: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    kind, heard = args["kind"], args["heard"]
    about, said = (args.get("about") or "").strip() or None, args.get("said")
    keep = memory.remembering(store, home_id)
    sid = session_id or f"loose-{surface}-{now.astimezone(TZ).date().isoformat()}"
    sessions = _sessions(store, home_id, now)
    state = sessions.get(sid) or {"start": episode["start"] if episode else memory.iso(now), "moments": [],
                                  "offered": False}
    state["keep"] = keep
    earlier = sum(1 for m in state["moments"] if m["valence"] == heard["valence"] != "neutral")
    before = affect.latest(store, home_id, now, exclude=sid)  # how the talk before this one went
    tone = list(heard.get("tone") or [])
    if kind == "flat" and "flat" not in tone:
        tone = ["flat", *tone][:2]  # the kind says so even when no tone tag came with it
    moment = {"ts": memory.iso(now), "kind": kind, "valence": heard["valence"], "energy": heard.get("energy"),
              "tone": tone, "via": heard.get("via", "voice")}
    state["moments"] = [*state["moments"], moment][-affect.MOMENTS:]
    if keep:
        affect.note_heard(store, home_id, sid, start=state["start"], surface=surface,
                          intent=episode["intent"] if episode else "talk", moment=moment)
    prep = prepared(store, home_id, now)
    plan = plan_from(
        kind, heard, about, said, earlier=earlier, heavy=affect.heavy_days(store, home_id, now),
        cue=tone_for(store.home_summary(home_id)),  # no row yet -> steady
        offered=state["offered"], best=prep.get("help"),
        recall=recall_for(store, home_id, stance_of(read_kind(kind, heard["valence"], said, about), heard["valence"]),
                          about, said, now,
                          prep.get("facts") or [], before),
        # one thread per conversation: what they opened with stays the thing to ask about next time
        follow_up=not state.get("followed") and save_follow_up(store, home_id, kind, heard["valence"], about, said, now))
    state["offered"] = state["offered"] or plan.may_offer is not None
    state["followed"] = bool(state.get("followed")) or plan.follow_up_saved
    sessions[sid] = state
    store.kv_set(_key(home_id), sessions)
    return plan.model_dump(mode="json", exclude_none=True)


def close(store: Store, home_id: str, session_id: str | None, *, crisis: bool = False) -> None:
    """The conversation is over. A timeline that may not be kept (remembering off, or a crisis) goes now."""
    sessions = store.kv_get(_key(home_id)) or {}
    state = sessions.get(session_id or "")
    if state and (crisis or not state.get("keep")):
        del sessions[session_id]
        store.kv_set(_key(home_id), sessions)


def forget(store: Store, home_id: str) -> None:
    store.kv_delete(_key(home_id))
    store.kv_delete(f"feel-prep:{home_id}")
