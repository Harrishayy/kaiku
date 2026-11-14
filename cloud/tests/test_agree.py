"""An activity agreed in one place shows up everywhere (D50): the `agree_activity` tool and its rules, the `agreed`
list read with the invitation, answers, completion by observation, expiry at local midnight, a crisis clearing it,
what the next conversation is told, and the events the home's stream carries."""
import json
import tomllib
from datetime import UTC, datetime, timedelta

import pytest
from kaiku_cloud import stream, voice
from kaiku_cloud.llm.explain import BANNED
from kaiku_cloud.mind import agree, assemble, feel
from kaiku_cloud.mind import session as mind_session
from kaiku_cloud.mind.assemble import ROOT
from kaiku_cloud.settings import TZ
from kaiku_contracts import make
from kaiku_contracts.api import (
    AgreedActivity,
    AgreedResult,
    CompanionToolCall,
    InvitationResponse,
    StreamAgreed,
)
from kaiku_contracts.companion_tools import (
    ACTIVITIES,
    AGREE_WHEN,
    SURFACES,
    TOOLS,
    for_surface,
    validate_args,
)
from kaiku_contracts.config import load_config
from kaiku_contracts.registry import EXAMPLES

HOME = "vera"
SURFACE_TABLES = tomllib.loads((ROOT / "config" / "surfaces.toml").read_text())["surface"]
YES = "Yes, let's do that."


def noon(days: int = 0) -> datetime:
    """Midday today in the home's own time zone: far from midnight, so a day never turns under a test."""
    local = datetime.now(TZ).replace(hour=12, minute=0, second=0, microsecond=0) + timedelta(days=days)
    return local.astimezone(UTC)


def post(client, *rows):
    body = {"events": [e.model_dump(mode="json", exclude_none=True) for e in rows]}
    r = client.post("/v1/events", json=body)
    assert r.status_code == 200 and not r.json()["rejected"], r.text


def obs(type_, payload, source="phone", minutes=5, home=HOME, when=None):
    return make(type_, payload, source=source, home_id=home, ts=(when or datetime.now(UTC)) + timedelta(minutes=minutes))


def session(client, surface="robot", intent="ritual", home=HOME, **kw):
    r = client.post("/v1/companion/session", json={"home_id": home, "surface": surface, "intent": intent, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def tool(client, name="agree_activity", surface="robot", sid=None, home=HOME, **args):
    r = client.post("/v1/companion/tool", json={"home_id": home, "surface": surface, "session_id": sid, "name": name,
                                                "args": args})
    assert r.status_code == 200, r.text
    return r.json()


def read(client, surface="iphone", home=HOME):
    r = client.get("/v1/me/invitation", params={"home_id": home, "surface": surface})
    assert r.status_code == 200, r.text
    return InvitationResponse.model_validate(r.json())


def answer(client, ident, reply, surface="iphone", home=HOME):
    return client.post("/v1/me/agreed/answer", params={"home_id": home, "surface": surface},
                       json={"id": ident, "answer": reply})


def heard(client, home=HOME) -> list[dict]:
    """Every event the home's stream holds, oldest first (the replay buffer every listener is fed from)."""
    hub = stream.of(client.app.state.store)
    return [{"event": e.name, **json.loads(e.data)} for e in hub._buffers.get(home, ())]


@pytest.fixture
def home(client):
    """A person with the phone and the Mac app: both have asked for today's invitation, as they do when opened."""
    read(client, "iphone")
    read(client, "mac")
    return client


# ---------------------------------------------------------------- contract
def test_the_tool_is_a_cloud_tool_on_every_surface_and_every_surface_lists_it():
    spec = TOOLS["agree_activity"]
    assert spec["executor"] == "cloud" and set(spec["surfaces"]) == set(SURFACES) and "behavior" not in spec
    props = spec["parameters"]["properties"]
    assert spec["parameters"]["required"] == ["kind"] and props["kind"]["enum"] == list(ACTIVITIES)
    assert props["said"]["maxLength"] == 300 and props["line"]["maxLength"] == 80
    assert props["when"]["enum"] == list(AGREE_WHEN) == ["now", "later"]
    for surface, table in SURFACE_TABLES.items():
        assert "agree_activity" in table["tools"], surface
        assert "agree_activity" in [t["name"] for t in for_surface(surface)], surface
    assert not validate_args(spec["parameters"], {"kind": "walk", "said": YES, "when": "later", "line": "A walk after lunch"})
    assert validate_args(spec["parameters"], {"kind": "walk", "when": "tomorrow"})
    desc = spec["description"]  # when to call it, when not, and that it says where it is
    for words in ("clearly said yes", "own words", "maybe", "start_activity", "questionnaire", "`where`"):
        assert words in desc, words


def test_the_instruction_says_when_to_call_it_and_what_this_body_cannot_start(client):
    robot, glasses, phone = (session(client, s, i)["system_instruction"]
                             for s, i in (("robot", "ritual"), ("glasses", "walk"), ("iphone", "talk")))
    for text in (robot, glasses, phone):
        assert "`agree_activity`: when they clearly say yes" in text and "is not a yes" in text
    assert "anything this body cannot start itself: tell, walk, lantern, seeds, watering, pebbles, firefly." in robot
    assert "cannot start itself: breathe, tell, lantern, seeds, watering, pebbles, firefly." in glasses
    assert "cannot start itself" not in phone  # the phone has every screen: only "for later today" applies
    assert "agree_activity" in [t["name"] for t in session(client, "robot", "ritual")["tools"]]


def test_the_questionnaire_can_never_be_agreed(home):
    assert "phq9" not in ACTIVITIES and "questionnaire" not in ACTIVITIES
    for kind in ("phq9", "questionnaire", "start_phq9"):
        out = tool(home, kind=kind, said=YES)
        assert not out["ok"] and "not in enum" in out["error"]
    assert read(home).agreed == []


# ---------------------------------------------------------------- only on their own yes
@pytest.mark.parametrize("said,reads", [
    ("Yes, let's do that after lunch.", "yes"), ("Okay.", "yes"), ("Sure, why not", "yes"), ("That sounds good", "yes"),
    ("I'd like that", "yes"), ("Yeah, go on then", "yes"), ("I’ll do it tonight", "yes"), ("mm, okay then", "yes"),
    ("Can we play the lantern game later?", "asked"), ("I want to go for a walk after lunch", "asked"),
    ("Remind me to breathe tonight", "asked"),
    ("Maybe", "hedge"), ("Okay, maybe later", "hedge"), ("I don't know", "hedge"), ("Not today", "hedge"),
    ("We'll see", "hedge"), ("I'm not sure", "hedge"), ("No thanks", "hedge"), ("No.", "hedge"),
    ("I'd rather not", "hedge"), ("It was a long night", "none"), ("Hmm", "none"), ("", "none"), (None, "none"),
])
def test_what_their_words_carry_is_read_by_code(said, reads):
    assert agree.read_words(said) == reads


@pytest.mark.parametrize("args,reason", [
    ({}, "no_words"), ({"said": "  "}, "no_words"), ({"said": "Maybe"}, "not_a_yes"),
    ({"said": "Okay, maybe later"}, "not_a_yes"), ({"said": "No thanks"}, "not_a_yes"),
    ({"said": "It was a long night"}, "not_a_yes"),
])
def test_without_a_clear_yes_in_their_own_words_nothing_is_kept(home, args, reason):
    out = tool(home, kind="walk", **args)
    assert not out["ok"] and out["result"] == {"agreed": False, "reason": reason}
    assert "Not kept" in out["error"] and "do not say it is on any device" in out["error"].lower()
    assert read(home).agreed == [] and heard(home) == []
    assert home.app.state.store.kv_get(f"agree:{HOME}") is None  # nothing was written at all


def test_a_yes_becomes_a_fact_with_where_it_is_and_the_words_are_never_stored(home):
    out = tool(home, kind="walk", said="Yes, a walk after lunch sounds good.", when="later", line="A walk after lunch")
    assert out["ok"] and out["executor"] == "cloud"
    res = AgreedResult.model_validate(out["result"])
    assert (res.kind, res.name, res.when, res.on, res.where, res.already) == ("walk", "a walk", "later", ["iphone"],
                                                                              "your phone", False)
    (item,) = read(home).agreed
    assert item.id == res.id and item.state == "open" and item.surface == "robot" and item.when == "later"
    assert item.line == "A walk after lunch" and item.day == datetime.now(TZ).date()
    stored = json.dumps(home.app.state.store.kv_get(f"agree:{HOME}"))
    assert "sounds good" not in stored and "said" not in stored  # `said` is checked, never kept
    game = AgreedResult.model_validate(tool(home, surface="glasses", kind="lantern", said=YES)["result"])
    assert game.where == "your phone and your Mac" and game.on == ["iphone", "mac"] and game.name == "Lantern"


def test_a_line_that_breaks_the_wording_rules_is_left_out_not_shown(home):
    tool(home, kind="lantern", said=YES, line="This will fix your depression symptoms")
    assert read(home).agreed[0].line is None


# ---------------------------------------------------------------- the person's screens
def test_a_kind_with_no_screen_on_their_phone_or_mac_is_refused_with_a_reason_the_voice_can_say(home):
    for kind in ("drum", "light_hunt"):  # the robot's and the walk's own: no screen on a phone or Mac
        out = tool(home, kind=kind, said=YES)
        assert out["result"] == {"agreed": False, "reason": "no_screen"}, kind
        assert agree.name_of(kind) in out["error"] and "Do not say it is on a device" in out["error"]
    assert read(home).agreed == []


def test_only_screens_this_home_really_uses_count(client):
    # nobody: no app has ever asked and nothing came from a phone or a Mac
    out = tool(client, kind="lantern", said=YES)
    assert out["result"]["reason"] == "no_screen" and "no phone or Mac app" in out["error"]
    # a Mac only (its app sent screen activity): a game goes there, a walk has nowhere to go
    post(client, obs("obs.screen_activity", EXAMPLES["obs.screen_activity"], source="laptop", minutes=-5))
    assert tool(client, kind="lantern", said=YES)["result"]["on"] == ["mac"]
    walk = tool(client, kind="walk", said=YES)
    assert walk["result"]["reason"] == "no_screen" and "a walk has no screen" in walk["error"]
    # the phone app is opened: from now on the walk has a home, and the game agreed before gets its button there
    (lantern,) = read(client, "iphone").agreed
    assert lantern.opens_here and lantern.on == ["iphone", "mac"]
    res = tool(client, kind="walk", said=YES)["result"]
    assert res["on"] == ["iphone"] and res["where"] == "your phone"


def test_a_screen_not_seen_for_a_long_time_no_longer_counts(home):
    store = home.app.state.store
    assert agree.screens(store, HOME, noon()) == ["iphone", "mac"]
    assert agree.screens(store, HOME, noon(days=load_config()["agree"]["screen_days"] + 1)) == []


# ---------------------------------------------------------------- one open item per kind, a few at most
def test_one_open_item_per_kind_and_a_limit_on_how_many(home):
    first = tool(home, kind="walk", said=YES)["result"]
    again = tool(home, surface="glasses", kind="walk", said="Okay, yes.")["result"]
    assert again["id"] == first["id"] and again["already"] and not first["already"]
    assert len(read(home).agreed) == 1 and len([e for e in heard(home) if e["event"] == "agreed"]) == 1
    assert load_config()["agree"]["max_open"] == 3
    for kind in ("lantern", "tell"):
        assert tool(home, kind=kind, said=YES)["ok"]
    out = tool(home, kind="pebbles", said=YES)
    assert out["result"] == {"agreed": False, "reason": "too_many"} and len(read(home).agreed) == 3
    # once one is done there is room again, and the same kind may be agreed anew
    post(home, obs("obs.outing", {"minutes": 20, "steps": 2000, "method": "steps"}))
    assert tool(home, kind="pebbles", said=YES)["ok"]
    new_walk = tool(home, kind="walk", said=YES)
    assert not new_walk["ok"] and new_walk["result"]["reason"] == "too_many"  # three open again


# ---------------------------------------------------------------- an extra-gentle day
def test_on_an_extra_gentle_day_only_what_they_asked_for_themselves_is_kept(home, monkeypatch):
    monkeypatch.setattr(agree, "tone_for", lambda row: "extra-gentle")  # what the card's tone is on such a day
    out = tool(home, kind="walk", said="Yes, okay.")
    assert out["result"] == {"agreed": False, "reason": "gentle_day"} and "offers nothing" in out["error"]
    assert read(home).agreed == []
    asked = tool(home, kind="walk", said="Can we go for a walk after lunch?")
    assert asked["ok"] and read(home).agreed[0].kind == "walk"
    monkeypatch.setattr(agree, "tone_for", lambda row: "gentle")  # an ordinary gentler day keeps a plain yes
    assert tool(home, kind="lantern", said="Yes, okay.")["ok"]


def test_the_rule_is_one_pure_decision():
    both = ["iphone", "mac"]
    assert agree.decide("lantern", YES, tone="steady", screens=both, open_kinds=[]) == (both, False)
    assert agree.decide("walk", "Could we walk later?", tone="extra-gentle", screens=both, open_kinds=[]) == (["iphone"], True)
    assert agree.decide("walk", YES, tone="steady", screens=both, open_kinds=["walk", "tell", "lantern"]) == (["iphone"], False)
    for kw, code in ((dict(said=None), "no_words"), (dict(said="maybe"), "not_a_yes"), (dict(screens=[]), "no_screen"),
                     (dict(screens=["mac"]), "no_screen"), (dict(tone="extra-gentle"), "gentle_day"),
                     (dict(open_kinds=["tell", "lantern", "seeds"]), "too_many")):
        args = {"said": YES, "tone": "steady", "screens": both, "open_kinds": []} | kw
        with pytest.raises(agree.Refused) as e:
            agree.decide("walk", args.pop("said"), **args)
        assert e.value.code == code and "Not kept" in str(e.value)


# ---------------------------------------------------------------- the read, the sentence, the invitation
def test_the_sentence_is_a_template_around_the_activity_and_where_it_was_agreed(home):
    tool(home, surface="glasses", kind="lantern", said=YES)
    tool(home, surface="robot", kind="walk", said=YES)
    tool(home, surface="iphone", kind="tell", said="I'll do it tonight", when="later")
    lantern, walk, tell = read(home).agreed  # oldest first
    assert lantern.text == "On your walk you said yes to Lantern. Ready when you are." and lantern.voice_key == "agreed.glasses"
    assert walk.text == "With the robot you said yes to a walk. Ready when you are." and walk.voice_key == "agreed.robot"
    assert tell.text == "On your phone you said yes to Tell Kaiku. Ready when you are."
    mac = {a.kind: a for a in read(home, "mac").agreed}
    assert mac["walk"].text == walk.text and not mac["walk"].opens_here and walk.opens_here  # same item, no walk screen on a Mac
    assert mac["lantern"].opens_here and mac["lantern"].on == ["iphone", "mac"]
    for key, line in voice.all_lines().items():
        if key.startswith("agreed."):
            assert voice.is_template(line) and key not in voice.lines("en")  # never rendered or listed on its own
            assert {"en", "fi", "sv"} <= set(line) and not any(b in line["en"].lower() for b in BANNED), key
            assert not any(ch.isdigit() for ch in line["en"])
    assert set(load_config()["agree"]["names"]) == set(ACTIVITIES)
    assert AgreedActivity.model_validate(lantern.model_dump()).name == "Lantern"


def test_the_daily_invitation_waits_behind_an_agreed_item(home):
    rows = []
    for d in range(20, 0, -1):
        ts = datetime.now(UTC) - timedelta(days=d)
        rows += [make("obs.self_report", {"item": "mood", "value": 4, "channel": "phone"}, source="phone", home_id=HOME, ts=ts),
                 make("obs.outing", {"minutes": 30, "steps": 3000, "method": "steps"}, source="phone", home_id=HOME, ts=ts)]
        if d % 4 == 0:
            rows.append(make("obs.nudge_outcome", {"arm": "breathe", "accepted": True, "next_day": {"mood": 5, "energy": 4}},
                             source="phone", home_id=HOME, ts=ts))
    post(home, *rows)
    store = home.app.state.store
    ident = tool(home, kind="lantern", said=YES)["result"]["id"]
    waiting = read(home)
    assert waiting.invitation is None and [a.state for a in waiting.agreed] == ["open"]
    assert store.kv_get(f"invite:{HOME}") is None  # not picked behind its back: the day's one invitation is unused
    assert answer(home, ident, "opened").status_code == 200
    assert read(home, "mac").invitation is None  # started is still theirs to finish
    after = InvitationResponse.model_validate(answer(home, ident, "put_aside").json())
    assert after.agreed[0].state == "put_aside" and after.invitation is not None
    assert after.invitation.activity == "breathe" and read(home).invitation == after.invitation


# ---------------------------------------------------------------- answers
def test_a_device_says_it_was_opened_or_put_aside(home):
    ident = tool(home, kind="lantern", said=YES)["result"]["id"]
    assert answer(home, "nothing-like-this", "opened").status_code == 404
    assert answer(home, ident, "done").status_code == 422  # done is not an answer: the observation does that
    opened = InvitationResponse.model_validate(answer(home, ident, "opened", surface="mac").json())
    assert opened.agreed[0].state == "started" and opened.agreed[0].state_at is not None and opened.agreed[0].opens_here
    assert answer(home, ident, "opened").json()["agreed"][0]["state"] == "started"  # twice is harmless
    assert answer(home, ident, "put_aside").json()["agreed"][0]["state"] == "put_aside"
    assert answer(home, ident, "opened").json()["agreed"][0]["state"] == "put_aside"  # final for today
    post(home, obs("obs.play_session", {"game": "lantern", "device": "mac", "duration_s": 60}, source="laptop"))
    assert read(home).agreed[0].state == "put_aside"  # they said so; it is not turned into something else
    states = [e["state"] for e in heard(home) if e["event"] == "agreed"]
    assert states == ["open", "started", "put_aside"]


# ---------------------------------------------------------------- done without anyone tapping anything
DONE_BY = [
    ("walk", "obs.outing", {"minutes": 22, "steps": 2400, "method": "steps"}, "phone"),
    ("walk", "obs.outing", {"minutes": 25, "method": "dat_imu", "cadence_spm": 104}, "glasses"),
    ("breathe", "obs.play_session", {"game": "breathe", "device": "phone", "duration_s": 90}, "phone"),
    ("breathe", "obs.hrv_session", EXAMPLES["obs.hrv_session"], "hub"),
    ("breathe", "obs.ritual", {"step": "breathe", "status": "completed", "duration_s": 60}, "hub"),
    ("tell", "obs.play_session", {"game": "tell", "device": "mac", "duration_s": 120}, "laptop"),
    ("lantern", "obs.play_session", {"game": "lantern", "device": "phone", "duration_s": 60}, "phone"),
    ("seeds", "obs.play_session", {"game": "seeds", "device": "phone", "duration_s": 60}, "phone"),
    ("watering", "obs.play_session", {"game": "watering", "device": "mac", "duration_s": 60}, "laptop"),
    ("pebbles", "obs.play_session", {"game": "pebbles", "device": "phone", "duration_s": 60}, "phone"),
    ("firefly", "obs.play_session", {"game": "firefly", "device": "phone", "duration_s": 60}, "phone"),
]


@pytest.mark.parametrize("kind,type_,payload,source", DONE_BY)
def test_the_activitys_own_observation_completes_it(home, kind, type_, payload, source):
    ident = tool(home, kind=kind, said=YES)["result"]["id"]
    post(home, obs(type_, payload, source=source))
    (item,) = read(home).agreed
    assert (item.id, item.state) == (ident, "done") and item.state_at is not None
    assert [e["state"] for e in heard(home) if e["event"] == "agreed"] == ["open", "done"]
    assert answer(home, ident, "put_aside").json()["agreed"][0]["state"] == "done"  # done stays done


def test_every_kind_a_screen_has_can_be_completed_by_some_observation():
    rules = load_config()["agree"]["done_by"]
    for kind in {a for s in ("iphone", "mac") for a in SURFACE_TABLES[s]["activities"]}:
        assert any(r["kind"] == kind for r in rules), kind
    assert {r["type"] for r in rules} <= set(EXAMPLES)  # only observation types that exist


def test_only_that_activity_that_day_and_after_the_yes_counts(home):
    store = home.app.state.store
    at = noon()
    call = CompanionToolCall(home_id=HOME, surface="robot", name="agree_activity", args={"kind": "walk", "said": YES})
    ident = mind_session.run_tool(store, home.app.state.settings, call, now=at).result["id"]
    row = lambda **kw: obs(**kw).model_dump(mode="json", exclude_none=True)  # noqa: E731
    outing = {"minutes": 20, "steps": 2000, "method": "steps"}
    state = lambda: next(i["state"] for i in agree.todays(store, HOME, at) if i["id"] == ident)  # noqa: E731
    # another activity; this morning's walk uploaded late; a walk stamped tomorrow: none of them is this walk
    for e in (row(type_="obs.play_session", payload={"game": "lantern", "device": "phone", "duration_s": 60}, when=at),
              row(type_="obs.outing", payload=outing, when=at, minutes=-180),
              row(type_="obs.outing", payload=outing, when=at, minutes=24 * 60)):
        assert agree.on_events(store, HOME, [e], now=at + timedelta(minutes=10)) == [] and state() == "open"
    # a device clock a little behind still counts ([agree].clock_slack_s), then the real thing
    assert agree.on_events(store, HOME, [row(type_="obs.outing", payload=outing, when=at, minutes=-1)],
                           now=at + timedelta(minutes=10)) == [ident]
    assert state() == "done"


# ---------------------------------------------------------------- it belongs to its local day
def test_it_expires_at_local_midnight(home):
    store, settings = home.app.state.store, home.app.state.settings
    late = datetime.now(TZ).replace(hour=23, minute=50, second=0, microsecond=0).astimezone(UTC)
    call = CompanionToolCall(home_id=HOME, surface="robot", name="agree_activity", args={"kind": "lantern", "said": YES})
    out = mind_session.run_tool(store, settings, call, now=late)
    assert out.ok and [a.state for a in agree.listing(store, HOME, "iphone", late + timedelta(minutes=9))] == ["open"]
    after = late + timedelta(minutes=11)  # 00:01 the next local day
    assert agree.listing(store, HOME, "iphone", after) == [] and not agree.waiting(store, HOME, after)
    assert agree.card_lines(store, HOME, after) == []  # and the next conversation is not told about it
    played = obs("obs.play_session", {"game": "lantern", "device": "phone", "duration_s": 60}, when=after)
    assert agree.on_events(store, HOME, [played.model_dump(mode="json", exclude_none=True)], now=after) == []
    with pytest.raises(KeyError):
        agree.answer(store, HOME, out.result["id"], "opened", now=after)
    # the new day starts clean: the same kind can be agreed again
    again = mind_session.run_tool(store, settings, call, now=after)
    assert again.ok and not again.result["already"] and again.result["id"] != out.result["id"]


# ---------------------------------------------------------------- a crisis clears it
def test_a_crisis_phrase_takes_every_open_item_off_every_screen(home):
    sid = session(home)["session_id"]
    walk = tool(home, sid=sid, kind="walk", said=YES)["result"]["id"]
    done = tool(home, sid=sid, kind="lantern", said=YES)["result"]["id"]
    post(home, obs("obs.play_session", {"game": "lantern", "device": "phone", "duration_s": 60}))
    out = tool(home, sid=sid, kind="tell", said="I want to end my life")
    assert out["crisis"] and not out["ok"] and out["result"]["stop_session"]
    left = read(home)
    assert [(a.id, a.state) for a in left.agreed] == [(done, "done")]  # what was done stays done; nothing is asked
    events = heard(home)
    assert {"event": "agreed", "id": walk, "state": "removed"}.items() <= events[-2].items()
    assert events[-1]["event"] == "day" and events[-1]["types"] == [] and events[-1]["sources"] == ["cloud"]
    assert "safety" not in json.dumps(events) and "crisis" not in json.dumps(events)  # the stream never says why
    assert answer(home, walk, "opened").status_code == 404
    assert not tool(home, sid=sid, kind="walk", said=YES)["ok"]  # the conversation is over


def test_a_safety_flag_from_any_device_clears_them_too(home):
    walk = tool(home, kind="walk", said=YES)["result"]["id"]
    post(home, obs("obs.safety_flag", {"trigger": "phrase", "handled_locally": True}, source="hub", minutes=0))
    assert read(home).agreed == []
    assert [(e["event"], e.get("state")) for e in heard(home)][-2:] == [("agreed", "removed"), ("day", None)]
    assert heard(home)[-2]["id"] == walk and heard(home)[-1]["types"] == []


# ---------------------------------------------------------------- the next conversation
def test_the_next_conversation_on_any_surface_is_told_once_per_state(home):
    robot = session(home)
    assert robot["context_card"]["agreed"] == []
    tool(home, sid=robot["session_id"], kind="walk", said="Yes, after lunch.", when="later")
    home.post("/v1/companion/tool", json={"home_id": HOME, "surface": "robot", "session_id": robot["session_id"],
                                          "name": "end_session", "args": {}})
    phone = session(home, "iphone", "talk")
    assert phone["context_card"]["agreed"] == ["a walk (they said yes with the robot): not done yet"]
    text = phone["system_instruction"]
    assert "They said yes to this today: a walk (they said yes with the robot): not done yet." in text
    assert "you may ask about it gently, once" in text and "never press" in text
    assert session(home, "mac", "talk")["context_card"]["agreed"] == []  # asked once, not in every conversation
    post(home, obs("obs.outing", {"minutes": 20, "steps": 2000, "method": "steps"}))
    glasses = session(home, "glasses", "walk")
    assert glasses["context_card"]["agreed"] == ["a walk (they said yes with the robot): done since"]
    assert "be glad about it in a few words" in glasses["system_instruction"]
    assert session(home, "iphone", "talk")["context_card"]["agreed"] == []  # glad once


def test_the_card_never_carries_the_conversations_own_item_a_put_aside_one_or_anything_with_company(home):
    talk = session(home, "iphone", "talk")
    ident = tool(home, surface="iphone", sid=talk["session_id"], kind="lantern", said="I'll play it tonight", when="later")["result"]["id"]
    resumed = session(home, "iphone", "talk", resume_session_id=talk["session_id"])
    assert resumed["context_card"]["agreed"] == []  # a long call resumes: it is not asked about what it just agreed
    assert session(home, "robot", "ritual", others_present=True)["context_card"]["agreed"] == []
    assert session(home, "robot", "ritual")["context_card"]["agreed"] == ["Lantern (they said yes on the phone): not done yet"]
    tool(home, kind="tell", said=YES)
    tell = read(home).agreed[1].id
    answer(home, tell, "put_aside")
    answer(home, ident, "opened")  # opening it is not news
    assert session(home, "mac", "talk")["context_card"]["agreed"] == []
    assert assemble.render_card({"tone": "steady", "language": "en", "agreed": ["x"] * 3})
    with pytest.raises(ValueError):
        assemble.render_card({"tone": "steady", "language": "en", "agreed": ["x"] * 4})


# ---------------------------------------------------------------- from the offer to the yes
def test_an_offer_this_body_cannot_start_names_where_it_can_be_kept():
    best = {"arm": "daylight_walk", "tries": 5}
    low = {"valence": "low", "energy": "low"}
    kw = dict(earlier=0, heavy=0, cue="steady", offered=False, best=best, recall=None, follow_up=False)
    robot = feel.plan_from("lonely", low, "the quiet flat", "The flat feels empty.", can=["breathe", "drum"], **kw)
    assert robot.may_offer and robot.offer_activity is None and robot.offer_elsewhere == "walk"
    phone = feel.plan_from("lonely", low, "the quiet flat", "The flat feels empty.", can=SURFACE_TABLES["iphone"]["activities"], **kw)
    assert phone.offer_activity == "walk" and phone.offer_elsewhere is None
    drum = feel.plan_from("lonely", low, None, None, can=["walk"], **(kw | {"best": {"arm": "drum", "tries": 5}}))
    assert drum.offer_activity is None and drum.offer_elsewhere is None  # no phone or Mac screen for drumming


# ---------------------------------------------------------------- the whole path, and the reset
def test_a_yes_on_the_robot_is_an_item_an_event_and_on_both_reads(home):
    """The lead's sentence: say yes to the robot, and the Mac and the phone have it at once."""
    robot = session(home)
    out = tool(home, sid=robot["session_id"], kind="lantern", said="Yes, I'd like that.", line="A round of Lantern")
    assert out["ok"] and out["result"]["where"] == "your phone and your Mac"
    (event,) = heard(home)
    assert StreamAgreed.model_validate({k: v for k, v in event.items() if k != "event"}).state == "open"
    assert event == {"event": "agreed", "id": out["result"]["id"], "kind": "lantern", "state": "open",
                     "surface": "robot", "when": "now", "on": ["iphone", "mac"],
                     "day": datetime.now(TZ).date().isoformat()}  # ids and kinds: not the line, not the sentence
    for surface in ("iphone", "mac"):
        (item,) = read(home, surface).agreed
        assert item.id == event["id"] and item.surface == "robot" and item.opens_here and item.line == "A round of Lantern"
        assert item.text == "With the robot you said yes to Lantern. Ready when you are."
    assert "agree_activity" in home.app.state.store.episode(robot["session_id"])["tools"]


def test_resetting_a_persons_simulated_data_takes_their_agreed_items_too(home):
    post(home, make("obs.self_report", {"item": "mood", "value": 4, "channel": "phone"}, source="phone", home_id=HOME,
                    sim=True))
    tool(home, kind="lantern", said=YES)
    store = home.app.state.store
    assert store.kv_get(f"agree:{HOME}") and store.kv_get(f"screens:{HOME}")
    assert home.post("/v1/admin/reset", params={"home_id": HOME}).status_code == 200
    assert store.kv_get(f"agree:{HOME}") is None and store.kv_get(f"screens:{HOME}") is None
