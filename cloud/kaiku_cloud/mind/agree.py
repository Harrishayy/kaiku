"""An activity agreed in one place shows up everywhere (D50): the `agree_activity` tool, the `agreed` list the apps
read with the invitation, the answer route, completion by observation, and what the next conversation is told.

The voice model is the only part that hears the person. When they clearly say yes to an activity that is not
starting here and now on that device (a game agreed with the robot, a walk agreed for after lunch), it calls
`agree_activity` with the kind and their own words. Whether that becomes a fact is decided here, by code:

    no words, a hedge or a no     refused: `said` must carry a yes or their own ask ([agree] yes / ask / hedge / no)
    no screen for it              refused: the kind must have a screen on a phone or Mac this home really uses
    an extra-gentle day           refused unless they asked for it themselves (their words match [agree].ask)
    already open today            the same item comes back (`already`), nothing is added: one open item per kind
    too many open                 refused beyond [agree].max_open
    the questionnaire             cannot be agreed: it is not an activity (the tool's enum has no such kind)

An item lives for the local day it was agreed on: `open` -> `started` (a device opened it) -> `done` (an
observation for that activity arrived the same day, [[agree.done_by]]) or `put_aside` (the person said so on a
screen). After local midnight it is not shown or mentioned again. A crisis removes every open item at once.
`said` is checked and never stored. Each change is announced on the home's stream (ids and kinds only).

State: kv `agree:<home>` (a short list), kv `screens:<home>` (which of phone / Mac asked lately). No model call.
"""

from __future__ import annotations

import re
import threading
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any

from kaiku_contracts import uuid7, wording
from kaiku_contracts.api import AgreedActivity, AgreedResult, InvitationResponse
from kaiku_contracts.config import load_config
from kaiku_contracts.jlog import get_logger

from .. import stream, voice
from ..analytics.metrics import parse_ts
from ..settings import TZ
from ..store.db import Store
from . import assemble, invite, memory
from .card import tone_for

log = get_logger("cloud.mind")
SCREENS = ("iphone", "mac")  # the surfaces with a display the person carries or sits at
SCREEN_OF_SOURCE = {"phone": "iphone", "laptop": "mac"}
WAITING = ("open", "started")  # states that keep the daily invitation waiting
SAID_WHERE = {"robot": "with the robot", "glasses": "on a walk", "iphone": "on the phone", "mac": "on the computer",
              "web": "on the computer"}  # for the model's card, not a sentence the person reads
_LOCK = threading.RLock()  # the home's list is read, changed and written back: one change at a time


class Refused(ValueError):
    """Nothing was kept. `str(e)` is written for the voice model: what happened and what it may say."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def cfg() -> dict[str, Any]:
    return load_config().get("agree", {})


def _key(home_id: str) -> str:
    return f"agree:{home_id}"


def _today(now: datetime) -> date:
    return now.astimezone(TZ).date()


def name_of(kind: str) -> str:
    return str(cfg().get("names", {}).get(kind, kind))


def where_words(on: list[str]) -> str:
    words = [str(cfg().get("where", {}).get(s, s)) for s in on]
    return " and ".join(words)


# ------------------------------------------------------------------ did they say yes? (their words, by code)
@lru_cache(maxsize=8)
def _rx(patterns: tuple[str, ...]) -> re.Pattern[str]:
    """One pattern for a config list; each entry is matched as whole words."""
    return re.compile("|".join(rf"(?<!\w)(?:{p})(?!\w)" for p in patterns) or r"(?!x)x", re.I)


def _matches(key: str, text: str) -> bool:
    return bool(_rx(tuple(cfg().get(key, []))).search(text))


def read_words(said: str | None) -> str:
    """yes | asked | hedge | none: what the person's own words carry. A hedge or a no anywhere wins over a yes
    ("okay, maybe later" is not a yes); their own ask ("can we play that game later?") counts without a yes."""
    text = memory.norm(said or "")
    if not text:
        return "none"
    if _matches("hedge", text) or _matches("no", text):
        return "hedge"
    if _matches("ask", text):
        return "asked"
    return "yes" if _matches("yes", text) else "none"


# ------------------------------------------------------------------ the person's screens
def can_open(kind: str) -> list[str]:
    """Which of phone and Mac have a screen for this activity (config/surfaces.toml `activities`)."""
    return [s for s in SCREENS if kind in assemble.surface_activities(s)]


def saw_screen(store: Store, home_id: str, surface: str | None, now: datetime | None = None) -> None:
    """A phone or Mac app asked for this home (the invitation read, the stream): it is one of their screens.
    Written at most once a day per screen."""
    if surface not in SCREENS:
        return
    now = now or datetime.now(UTC)
    with _LOCK:
        seen = _seen(store, home_id, now)
        if seen.get(surface) != _today(now).isoformat():
            store.kv_set(f"screens:{home_id}", {**seen, surface: _today(now).isoformat()})


def _seen(store: Store, home_id: str, now: datetime) -> dict[str, str]:
    """Screen -> the last local day it was seen. The first time, what the home's record already shows."""
    seen = store.kv_get(f"screens:{home_id}")
    if seen is None:
        today = _today(now).isoformat()
        seen = {SCREEN_OF_SOURCE[s]: today for s in {e["source"] for e in store.events_for_home(home_id)}
                if s in SCREEN_OF_SOURCE}
        seen |= {ep["surface"]: today for ep in store.episodes(home_id) if ep["surface"] in SCREENS}
        store.kv_set(f"screens:{home_id}", seen)
    return seen


def screens(store: Store, home_id: str, now: datetime) -> list[str]:
    """The phone and Mac this home really uses: an app that asked in the last [agree].screen_days, or one that
    sent observations. Nothing known = no screen: the voice must not say something is on a device nobody has."""
    with _LOCK:
        seen = _seen(store, home_id, now)
    oldest = (_today(now) - timedelta(days=int(cfg().get("screen_days", 30)))).isoformat()
    live = set(stream.of(store).listening(home_id))
    return [s for s in SCREENS if seen.get(s, "") >= oldest or s in live]


# ------------------------------------------------------------------ the decision (pure; the evals run this too)
def decide(kind: str, said: str | None, *, tone: str, screens: list[str], open_kinds: list[str],
           can: list[str] | None = None) -> tuple[list[str], bool]:
    """(the screens it goes on, whether the person asked for it themselves) or `Refused`. `open_kinds`: what is
    already open today. An already open kind passes: the caller hands the same item back."""
    name = name_of(kind)
    words = read_words(said)
    if words == "none" and not (said or "").strip():
        raise Refused("no_words", "Not kept: pass `said` with the person's own words of the yes. Only call this "
                      "after they clearly said yes. Do not say it is on any device.")
    if words in ("hedge", "none"):
        raise Refused("not_a_yes", "Not kept: those words are not a clear yes. A maybe or a not now is fine: leave "
                      "it there, offer nothing more, and do not say it is on any device.")
    on = [s for s in (can_open(kind) if can is None else can) if s in screens]
    if not on:
        if not screens:
            raise Refused("no_screen", "Not kept: no phone or Mac app of theirs has connected to Kaiku, so there "
                          "is nowhere to show it. Do not say it is on a device; they can simply do it.")
        raise Refused("no_screen", f"Not kept: {name} has no screen on their phone or Mac. Do not say it is on a "
                      "device.")
    if tone == "extra-gentle" and words != "asked":
        raise Refused("gentle_day", "Not kept: today Kaiku offers nothing and keeps no offers. Do not say it is on "
                      "a device. If they bring up an activity themselves, call this again with those words.")
    if kind not in open_kinds and len(open_kinds) >= int(cfg().get("max_open", 3)):
        raise Refused("too_many", "Not kept: they already have enough agreed for today. Do not add more and do "
                      "not say it is on a device.")
    return on, words == "asked"


# ------------------------------------------------------------------ storage
def _items(store: Store, home_id: str) -> list[dict[str, Any]]:
    return list((store.kv_get(_key(home_id)) or {}).get("items", []))


def _save(store: Store, home_id: str, items: list[dict[str, Any]]) -> None:
    store.kv_set(_key(home_id), {"items": items[-int(cfg().get("keep", 40)):]})


def todays(store: Store, home_id: str, now: datetime) -> list[dict[str, Any]]:
    """Today's items, oldest first. Yesterday's are over, whatever state they were left in."""
    today = _today(now).isoformat()
    return [i for i in _items(store, home_id) if i["day"] == today and i["state"] != "removed"]


def waiting(store: Store, home_id: str, now: datetime) -> bool:
    return any(i["state"] in WAITING for i in todays(store, home_id, now))


def _announce(store: Store, home_id: str, item: dict[str, Any]) -> None:
    stream.publish(store, home_id, "agreed", {"id": item["id"], "kind": item["kind"], "state": item["state"],
                                              "surface": item["surface"], "when": item["when"], "on": item["on"],
                                              "day": item["day"]})


def _set_state(store: Store, home_id: str, ident: str, state: str, now: datetime, only_from: tuple[str, ...]) -> bool:
    with _LOCK:
        items = _items(store, home_id)
        for i in items:
            if i["id"] == ident and i["state"] in only_from:
                i["state"], i["state_at"] = state, memory.iso(now)
                _save(store, home_id, items)
                _announce(store, home_id, i)
                return True
    return False


def _clean_line(line: str | None) -> str | None:
    """Kaiku's own short line is shown on a screen, so it passes the wording rules or is left out."""
    line = (line or "").strip()
    if not line or memory.health_detail(line) or wording.lint(line, max_questions=None):
        return None
    return line[:80]


# ------------------------------------------------------------------ the tool
def act(store: Store, home_id: str, surface: str, session_id: str | None, args: dict[str, Any],
        now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    kind, when = args["kind"], args.get("when") or "now"
    with _LOCK:
        open_now = [i for i in todays(store, home_id, now) if i["state"] in WAITING]
        on, asked = decide(kind, args.get("said"), tone=tone_for(store.home_summary(home_id)),
                           screens=screens(store, home_id, now), open_kinds=[i["kind"] for i in open_now])
        item = next((i for i in open_now if i["kind"] == kind), None)
        already = item is not None
        if item is None:
            item = {"id": str(uuid7()), "kind": kind, "line": _clean_line(args.get("line")), "surface": surface,
                    "at": memory.iso(now), "day": _today(now).isoformat(), "when": when, "state": "open",
                    "state_at": None, "on": on, "asked": asked, "session": session_id}
            _save(store, home_id, [*_items(store, home_id), item])
            _announce(store, home_id, item)
            log.info("agreed_activity", kind, home=home_id, surface=surface, when=when)  # never the words
    return AgreedResult(id=item["id"], kind=kind, name=name_of(kind), when=item["when"], on=item["on"],
                        where=where_words(item["on"]), already=already,
                        listening=[s for s in stream.of(store).listening(home_id) if s in item["on"]]
                        ).model_dump(mode="json")


# ------------------------------------------------------------------ the read (with the invitation)
def _text(item: dict[str, Any]) -> tuple[str, str]:
    key = f"agreed.{item['surface']}"
    lines = voice.all_lines()
    key = key if key in lines else "agreed.plain"
    return key, lines[key]["en"].format(activity=name_of(item["kind"]))[:200]  # this release speaks English only


def listing(store: Store, home_id: str, surface: str, now: datetime) -> list[AgreedActivity]:
    """Today's items for one asking screen. `on` is worked out now, not when it was agreed: a Mac that was first
    opened after the yes still gets its open button."""
    items = todays(store, home_id, now)
    mine = screens(store, home_id, now) if items else []
    out = []
    for i in items:
        key, text = _text(i)
        has = can_open(i["kind"])
        out.append(AgreedActivity(
            id=i["id"], kind=i["kind"], name=name_of(i["kind"]), text=text, voice_key=key, line=i.get("line"),
            surface=i["surface"], at=parse_ts(i["at"]), day=i["day"], when=i["when"], state=i["state"],
            state_at=parse_ts(i["state_at"]) if i.get("state_at") else None,
            on=[s for s in has if s in mine or s == surface], opens_here=surface in has))
    return out


def response(store: Store, home_id: str, surface: str, now: datetime | None = None) -> InvitationResponse:
    """What Today asks for in one request. An agreed item comes before the daily invitation: while one is open
    or started the invitation waits (and is not picked, so the day's one invitation is not used up unseen)."""
    now = now or datetime.now(UTC)
    saw_screen(store, home_id, surface, now)
    agreed = listing(store, home_id, surface, now)
    waits = any(a.state in WAITING for a in agreed)
    return InvitationResponse(home_id=home_id, agreed=agreed,
                              invitation=None if waits else invite.current(store, home_id, surface, now))


def answer(store: Store, home_id: str, ident: str, reply: str, now: datetime | None = None) -> None:
    """opened: a device opened its screen. put_aside: final for today. KeyError: not one of today's items.
    Answering an item that is already done or put aside changes nothing."""
    now = now or datetime.now(UTC)
    if not any(i["id"] == ident for i in todays(store, home_id, now)):
        raise KeyError(ident)
    if reply == "opened":
        _set_state(store, home_id, ident, "started", now, ("open",))
    else:
        _set_state(store, home_id, ident, "put_aside", now, WAITING)


# ------------------------------------------------------------------ completion and crisis (on ingest)
def _fits(event: dict[str, Any], rule: dict[str, Any]) -> bool:
    return event["type"] == rule.get("type") and all(
        event["payload"].get(k) == v for k, v in rule.items() if k not in ("kind", "type"))


def completes(kind: str, event: dict[str, Any]) -> bool:
    return any(r.get("kind") == kind and _fits(event, r) for r in cfg().get("done_by", []))


def on_events(store: Store, home_id: str, events: list[dict[str, Any]], now: datetime | None = None) -> list[str]:
    """New observations of one home were stored. A crisis flag removes every open item; an observation for an
    agreed activity, stamped the same local day and not before the yes, makes it done. Returns the ids changed."""
    now = now or datetime.now(UTC)
    for source in {e["source"] for e in events} & set(SCREEN_OF_SOURCE):
        saw_screen(store, home_id, SCREEN_OF_SOURCE[source], now)
    if any(e["type"] == "obs.safety_flag" for e in events):
        return clear(store, home_id, now)
    slack = timedelta(seconds=float(cfg().get("clock_slack_s", 120)))
    changed = []
    for item in [i for i in todays(store, home_id, now) if i["state"] in WAITING]:
        for e in events:
            at = parse_ts(e["ts"])
            if (completes(item["kind"], e) and at.astimezone(TZ).date().isoformat() == item["day"]
                    and at >= parse_ts(item["at"]) - slack):
                if _set_state(store, home_id, item["id"], "done", now, WAITING):
                    changed.append(item["id"])
                break
    return changed


def ingested(store: Store, home_id: str, events: list[dict[str, Any]], now: datetime | None = None) -> None:
    """Called once per home after its new observations are stored (POST /v1/events, the cloud's own crisis flag):
    agreed activities are completed or cleared, then every open screen of that home is told the day changed.
    Never fails the write that caused it."""
    try:
        on_events(store, home_id, events, now)
    except Exception as e:  # pragma: no cover - the observations are saved; this is the convenience on top
        log.warning("agreed_ingest_failed", type(e).__name__, home=home_id)
    stream.day_changed(store, home_id, events)


def clear(store: Store, home_id: str, now: datetime | None = None) -> list[str]:
    """A crisis: nothing that was agreed is asked of them any more. Open items go from every screen at once."""
    now = now or datetime.now(UTC)
    with _LOCK:
        items, gone = _items(store, home_id), []
        for i in items:
            if i["state"] in WAITING:
                i["state"], i["state_at"] = "removed", memory.iso(now)
                gone.append(i)
        if gone:
            _save(store, home_id, items)
            for i in gone:
                _announce(store, home_id, i)
    return [i["id"] for i in gone]


# ------------------------------------------------------------------ the next conversation's card
def card_lines(store: Store, home_id: str, now: datetime, *, session_id: str | None = None,
               mark: bool = True) -> list[str]:
    """What was agreed today and whether it was done, for the next conversation on any surface: once per state,
    so Kaiku is glad about a done one once and asks about an open one once. Never the one agreed in this very
    conversation, and nothing about one they put aside."""
    with _LOCK:
        items = _items(store, home_id)
        today, out = _today(now).isoformat(), []
        for i in items:
            phase = "done" if i["state"] == "done" else "waiting"  # opening it is not news for the next talk
            if i["day"] != today or i["state"] not in (*WAITING, "done") or i.get("told") == phase:
                continue
            if session_id and i.get("session") == session_id:
                continue
            out.append(f"{name_of(i['kind'])} (they said yes {SAID_WHERE.get(i['surface'], 'earlier')}): "
                       + ("done since" if phase == "done" else "not done yet"))
            if mark:
                i["told"] = phase
            if len(out) == 3:
                break
        if out and mark:
            _save(store, home_id, items)
    return out
