"""The walk companion (three styles, nudges, what it may connect to), activity cards by tool call, the call-length
and idle limits, the invitation, and one mind across phone, Mac, robot and glasses."""
import json
import tomllib
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from kaiku_cloud import voice
from kaiku_cloud.jobs import single_person
from kaiku_cloud.llm.explain import BANNED
from kaiku_cloud.mind import assemble, invite, live_token, walk
from kaiku_cloud.mind import session as mind_session
from kaiku_cloud.mind.assemble import ROOT
from kaiku_cloud.settings import TZ
from kaiku_contracts import budget, make
from kaiku_contracts.api import ActivityCardResult, Invitation, WalkGoalResult, WalkMomentResult
from kaiku_contracts.companion_tools import ACTIVITIES, TOOLS, WALK_STYLES, for_surface, validate_args
from kaiku_contracts.config import load_config

NOW = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=2)
HOME = "vera"
LOW = {"valence": "low", "energy": "low", "tone": ["flat"], "via": "voice"}
CHERRY = "The cherry tree by the lake is my favourite"
SURFACES = tomllib.loads((ROOT / "config" / "surfaces.toml").read_text())["surface"]


def post(client, events):
    rows = [e.model_dump(mode="json", exclude_none=True) for e in events]
    assert not client.post("/v1/events", json={"events": rows}).json()["rejected"]


def record(home=HOME, days=20, games=()):
    """A phone record where breathing was followed by clearly better days, plus the games they came back to."""
    out = []
    for d in range(days, 0, -1):
        ts = NOW - timedelta(days=d)
        out += [make("obs.self_report", {"item": "mood", "value": 4, "channel": "phone"}, source="phone", home_id=home, ts=ts),
                make("obs.outing", {"minutes": 30, "steps": 3000, "method": "steps"}, source="phone", home_id=home, ts=ts)]
        if d % 4 == 0:
            out.append(make("obs.nudge_outcome", {"arm": "breathe", "accepted": True, "next_day": {"mood": 5, "energy": 4}},
                            source="phone", home_id=home, ts=ts))
    for i, game in enumerate(games):
        out.append(make("obs.play_session", {"game": game, "device": "phone", "duration_s": 60}, source="phone",
                        home_id=home, ts=NOW - timedelta(days=2 + i)))
    return out


def session(client, home=HOME, surface="glasses", intent="walk", **kw):
    r = client.post("/v1/companion/session", json={"home_id": home, "surface": surface, "intent": intent, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def call(client, sid, name, home=HOME, surface="glasses", **args):
    r = client.post("/v1/companion/tool", json={"home_id": home, "surface": surface, "session_id": sid, "name": name,
                                                "args": args})
    assert r.status_code == 200, r.text
    return r.json()


def names(body):
    return {t["name"] for t in body["tools"]}


# ---------------------------------------------------------------- contract
def test_the_activity_list_is_the_screens_that_exist_and_each_surface_lists_only_its_own():
    assert ACTIVITIES == ("breathe", "tell", "walk", "lantern", "seeds", "watering", "pebbles", "firefly", "drum",
                          "light_hunt")
    assert SURFACES["iphone"]["activities"] == ["breathe", "tell", "walk", "lantern", "seeds", "watering", "pebbles", "firefly"]
    assert SURFACES["mac"]["activities"] == [a for a in SURFACES["iphone"]["activities"] if a != "walk"]
    assert SURFACES["robot"]["activities"] == ["breathe", "drum"] and SURFACES["glasses"]["activities"] == ["walk", "light_hunt"]
    for name, cfg in SURFACES.items():
        assert set(cfg.get("activities", [])) <= set(ACTIVITIES), name
        assert assemble.surface_activities(name) == cfg.get("activities", [])
    assert TOOLS["start_activity"]["parameters"]["properties"]["kind"]["enum"] == list(ACTIVITIES)


def test_card_and_walk_goal_tools_are_device_tools_on_the_right_surfaces():
    card, goal, moment = TOOLS["suggest_activity"], TOOLS["set_walk_goal"], TOOLS["log_walk_moment"]
    assert {t["executor"] for t in (card, goal, moment)} == {"device"}
    assert card["surfaces"] == ["iphone", "mac"] and goal["surfaces"] == moment["surfaces"] == ["glasses", "iphone"]
    assert validate_args(card["parameters"], {"kind": "lantern", "line": "A round of the lantern game?"}) == []
    assert validate_args(card["parameters"], {"kind": "chess"}) and validate_args(card["parameters"], {"line": "x"})
    assert validate_args(card["parameters"], {"kind": "tell", "line": "x" * 81})
    assert validate_args(goal["parameters"], {"thing": "red things", "target": 3}) == []
    for bad in ({"thing": "red things", "target": 0}, {"thing": "red things", "target": 6}, {"thing": "x" * 31, "target": 2},
                {"thing": "red things"}, {"target": 2}, {"thing": "red things", "target": 2.5}):
        assert validate_args(goal["parameters"], bad), bad
    # a phone talk does not carry the walk tools; a phone walk and the glasses do
    talk, on_walk = {t["name"] for t in for_surface("iphone", walk=False)}, {t["name"] for t in for_surface("iphone", walk=True)}
    assert on_walk - talk == {"set_walk_goal", "log_walk_moment"} and "suggest_activity" in talk
    glasses = {t["name"] for t in for_surface("glasses", walk=True)}
    assert {"set_walk_goal", "log_walk_moment", "feel", "remember"} <= glasses and "suggest_activity" not in glasses
    assert "suggest_activity" not in {t["name"] for t in for_surface("robot")}
    assert ActivityCardResult(ok=True, shown=True) and WalkGoalResult(thing="red things", target=3, found=0, left=3)
    assert WalkMomentResult(ok=True, thing="red things", found=1, target=3, left=2).left == 2
    assert WalkMomentResult(ok=True).thing is None  # a moment outside a game


# ---------------------------------------------------------------- the walk session
def test_walk_style_defaults_from_config_and_only_means_something_on_a_walk(client):
    cfg = load_config()["walk"]
    body = session(client)
    assert body["walk"]["style"] == cfg["default_style"] == "quiet" and body["context_card"]["walk_style"] == "quiet"
    assert session(client, purpose="walk", intent="talk", walk_style="chatty")["walk"]["style"] == "chatty"
    talk = session(client, surface="iphone", intent="talk", purpose="talk", walk_style="playful")
    assert talk["walk"] is None and talk["context_card"]["walk_style"] is None
    assert "## This walk" not in talk["system_instruction"] and "## Walking together" not in talk["system_instruction"]
    assert talk["context_card"]["outdoor_likes"] == []
    r = client.post("/v1/companion/session", json={"home_id": HOME, "surface": "glasses", "intent": "walk", "walk_style": "loud"})
    assert r.status_code == 422
    assert walk.style_of(None) == "quiet" and walk.style_of("playful") == "playful"


@pytest.mark.parametrize("style", WALK_STYLES)
def test_each_style_gets_its_nudges_limits_and_rules_from_config(client, style):
    cfg, limits = load_config()["walk"][style], SURFACES["glasses"]["styles"][style]
    body = session(client, walk_style=style)
    guide = body["walk"]
    assert guide["style"] == style and guide["look_every_s"] == cfg["look_every_s"] and guide["look_prompt"] == cfg["look_prompt"]
    assert guide["quiet_after_s"] == (cfg["quiet_after_s"] or None)
    assert guide["quiet_prompt"] == (cfg.get("quiet_prompt") or None)
    assert "silence" in guide["look_prompt"]  # the nudge itself allows no answer
    text = body["system_instruction"]
    assert "## This walk" in text and "## Walking together" in text
    assert f"Aim for about {limits['target_words']} words" in text
    assert f"never more than {limits['max_words']}" in text
    for rule in limits["rules"]:
        assert rule in text
    for other in set(WALK_STYLES) - {style}:
        assert SURFACES["glasses"]["styles"][other]["rules"][0] not in text
    assert "make no sound at all" in text and "`feel`" in text
    assert body["live_setup"]["proactivity"] == {"proactiveAudio": True}  # how a nudge can be answered with silence
    assert {"set_walk_goal", "log_walk_moment", "feel", "remember", "look_at_this"} <= names(body)
    styled = assemble.styled(assemble.parse_surfaces((ROOT / "config" / "surfaces.toml").read_text()), "glasses", style)
    assert styled["max_words"] == limits["max_words"] and styled["rules"][0] == limits["rules"][0]


def test_an_extra_gentle_day_comes_before_a_playful_style():
    card = {"language": "en", "tone": "extra-gentle", "intent": "walk", "walk_style": "playful"}
    assert "Today's tone comes before the style: start no game" in assemble.render_walk(card)
    assert "comes before the style" not in assemble.render_walk(card | {"tone": "steady"})
    assert "comes before the style" not in assemble.render_walk(card | {"walk_style": "quiet"})  # quiet offers none anyway
    assert assemble.render_walk({"language": "en", "tone": "steady"}) is None


def test_quiet_never_speaks_into_a_silence_and_the_others_wait_longer_than_they_look():
    cfg = load_config()["walk"]
    assert walk.guide("quiet").quiet_after_s is None and walk.guide("quiet").quiet_prompt is None
    for style in ("playful", "chatty"):
        g = walk.guide(style)
        assert g.quiet_after_s and g.quiet_prompt and g.quiet_after_s > g.look_every_s
    assert cfg["chatty"]["quiet_after_s"] < cfg["playful"]["quiet_after_s"]
    words = {s: SURFACES["glasses"]["styles"][s]["max_words"] for s in WALK_STYLES}
    assert words["quiet"] < words["playful"] <= words["chatty"]


def test_a_walk_and_a_call_may_run_long_a_check_in_stays_short(client):
    live = load_config()["live"]
    out = session(client)
    assert out["max_session_seconds"] == live["walk_max_minutes"] * 60 == 1800 and out["idle_end_s"] == live["walk_idle_end_s"] == 900
    talk = session(client, surface="iphone", intent="talk", purpose="talk")
    assert talk["max_session_seconds"] == live["talk_max_minutes"] * 60 == 1800 and talk["idle_end_s"] == live["idle_end_s"] == 180
    mac = session(client, surface="mac", intent="talk")
    assert mac["max_session_seconds"] == 1800 and mac["idle_end_s"] == 180
    check = session(client, surface="iphone", intent="checkin", purpose="check_in")
    assert check["max_session_seconds"] == live["session_max_minutes"] * 60 == 300 and check["idle_end_s"] == 180
    assert session(client, surface="robot", intent="ritual")["max_session_seconds"] == 300
    assert session(client, surface="glasses", intent="talk")["max_session_seconds"] == 300  # not a walk, not a call
    assert "like a call" in talk["system_instruction"] and "as long as they want" in talk["system_instruction"]
    for body in (out, talk):  # what lets Gemini keep a long conversation: both are in the setup the device sends
        assert body["live_setup"]["contextWindowCompression"] == {"slidingWindow": {}}
        assert body["live_setup"]["sessionResumption"] == {}


def test_one_token_covers_a_few_minutes_and_a_long_call_resumes_onto_the_next(client):
    store, settings = client.app.state.store, client.app.state.settings
    per_token = load_config()["live"]["token_minutes"]
    minted = []

    def mint(model, **kw):
        minted.append(kw["minutes"])

    def start(now, **kw):
        req = mind_session.CompanionSessionRequest(home_id=HOME, **kw)
        return mind_session.start_session(store, settings, req, now=now, mint=mint)

    call_ = start(NOW, surface="iphone", intent="talk", purpose="talk")
    start(NOW, surface="glasses", intent="walk")
    start(NOW, surface="iphone", intent="checkin", purpose="check_in")
    start(NOW, surface="robot", intent="ritual")  # the robot's adapter has its own key: no token
    assert minted == [per_token, per_token, per_token] and per_token == 5
    # twelve minutes in, the call asks for its next token: the same conversation, the time left, one more token
    later = start(NOW + timedelta(minutes=12), surface="iphone", intent="talk", purpose="talk",
                  resume_session_id=call_.session_id)
    assert later.session_id == call_.session_id and later.max_session_seconds == 18 * 60 and minted[-1] == per_token
    last = start(NOW + timedelta(minutes=28), surface="iphone", intent="talk", purpose="talk",
                 resume_session_id=call_.session_id)
    assert last.max_session_seconds == 120 and minted[-1] == 2.0  # never a token past the end of the call
    with pytest.raises(ValueError, match="duration limit"):
        start(NOW + timedelta(minutes=31), surface="iphone", intent="talk", purpose="talk",
              resume_session_id=call_.session_id)


def test_token_lifetime_and_reservation_follow_the_minutes_asked_for(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIKU_SPEND_DB", str(tmp_path / "spend.sqlite"))
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"name": "auth_tokens/abc"})

    t = live_token.mint("gemini-3.8-live", api_key="k", now=NOW, transport=httpx.MockTransport(handler), minutes=10)
    assert t.expires_at == NOW + timedelta(minutes=10) and seen["body"]["uses"] == 1
    assert budget.spent() == pytest.approx(budget.estimate("gemini-3.8-live", audio_min=10))


def test_a_check_in_never_carries_the_questionnaire_hint_but_a_talk_may(client):
    post(client, record())
    talk = session(client, surface="iphone", intent="talk", purpose="talk")
    check = session(client, surface="iphone", intent="checkin", purpose="check_in")
    assert talk["context_card"]["phq9_due"] is True and check["context_card"]["phq9_due"] is False
    assert "start_phq9 only after a clear yes" in talk["system_instruction"]
    assert "start_phq9 only after a clear yes" not in check["system_instruction"]


# ---------------------------------------------------------------- what it may connect to
def test_outdoor_favourites_reach_the_walk_card_and_the_instruction_says_how_to_use_them(client):
    sid = session(client, surface="iphone", intent="talk")["session_id"]
    assert call(client, sid, "remember", surface="iphone", category="places", text=CHERRY, said=f"{CHERRY}.")["ok"]
    call(client, sid, "remember", surface="iphone", category="likes", text="Likes strong coffee", said="I like strong coffee")
    call(client, sid, "remember", surface="iphone", category="likes", text="Loves watching the swans", said="I love watching the swans")
    out = session(client, walk_style="chatty")
    card = out["context_card"]
    assert card["outdoor_likes"] == ["Loves watching the swans", CHERRY]  # newest first; coffee is not out here
    text = out["system_instruction"]
    assert CHERRY in text and "as a question" in text and "category places" in text
    assert "Never describe, identify or judge people in view" in text
    assert session(client, surface="iphone", intent="talk")["context_card"]["outdoor_likes"] == []  # only on a walk
    client.put(f"/v1/me/memory_settings?home_id={HOME}", json={"remember": False})
    assert session(client)["context_card"]["outdoor_likes"] == []


def test_outdoor_filter_keeps_places_and_likes_about_being_outside():
    assert walk.OUTDOOR.search("The lake loop past the old sauna") and walk.OUTDOOR.search("Feeding the ducks")
    assert not walk.OUTDOOR.search("Strong coffee") and not walk.OUTDOOR.search("Her sister Maija")


def test_the_seeded_person_has_an_outdoor_favourite_on_the_walk_card(client):
    end = date(2026, 11, 13)
    store = client.app.state.store
    single_person.populate(store, single_person.build(end), end)
    assert any(c == "places" and walk.OUTDOOR.search(t) for c, t in single_person.NOTES)
    card = session(client, home=single_person.HOME)["context_card"]
    assert "The lake loop past the old sauna" in card["outdoor_likes"]


def test_a_favourite_said_on_a_walk_is_kept_only_in_their_own_words(client):
    sid = session(client)["session_id"]
    said = "Oh, that's my favourite bench, the green one by the pond."
    no = call(client, sid, "remember", category="places", text="Favourite bench is the green one by the pond")
    assert not no["ok"] and "said" in no["error"]
    ok = call(client, sid, "remember", category="places", text="Favourite bench is the green one by the pond", said=said)
    assert ok["ok"] and ok["result"]["action"] == "stored"
    assert session(client)["context_card"]["outdoor_likes"] == ["Favourite bench is the green one by the pond"]


def test_walk_goal_and_moment_are_device_tools_the_cloud_only_counts_the_call(client):
    sid = session(client, walk_style="playful")["session_id"]
    for name, args in (("set_walk_goal", {"thing": "red things", "target": 3}), ("log_walk_moment", {"kind": "red things"})):
        out = call(client, sid, name, **args)
        assert out["ok"] and out["executor"] == "device" and out["result"] == {"device": True}
    assert not call(client, sid, "set_walk_goal", thing="red things", target=9)["ok"]
    assert not call(client, sid, "suggest_activity", kind="lantern")["ok"]  # no cards on the glasses
    phone = session(client, surface="iphone", intent="talk")["session_id"]
    assert call(client, phone, "suggest_activity", surface="iphone", kind="lantern", line="A round of the lantern game?")["ok"]
    assert not call(client, phone, "suggest_activity", surface="iphone", kind="chess")["ok"]
    store = client.app.state.store
    assert store.events_for_home(HOME) == []  # nothing is derived from a walk game or a card (D43: no observation)


def test_card_rule_is_only_on_surfaces_with_cards(client):
    phone = session(client, surface="iphone", intent="talk")["system_instruction"]
    assert assemble.CARD_RULE in phone and "It opens nothing" in assemble.CARD_RULE and "that is a no" in assemble.CARD_RULE
    for surface, intent in (("glasses", "walk"), ("robot", "ritual")):
        assert "suggest_activity" not in session(client, surface=surface, intent=intent)["system_instruction"]


def test_a_feel_offer_only_names_an_activity_this_surface_has(client):
    post(client, record())
    said = "My sister cancelled again. I'd been looking forward to seeing her all week."
    phone = session(client, surface="iphone", intent="talk")["session_id"]
    plan = call(client, phone, "feel", surface="iphone", kind="sad_news", heard=LOW, about="your sister cancelling", said=said)["result"]
    assert plan["offer_activity"] == "breathe" and plan["may_offer"]
    post(client, record("vera2"))
    walk_sid = session(client, home="vera2")["session_id"]
    plan = call(client, walk_sid, "feel", home="vera2", kind="sad_news", heard=LOW, about="your sister cancelling", said=said)["result"]
    assert plan["may_offer"] and plan.get("offer_activity") is None  # the words stay; the glasses have no breathing screen


# ---------------------------------------------------------------- one mind
def test_one_mind_what_a_walk_hears_reaches_the_phone_and_the_robot_and_back(client):
    post(client, record())
    # on the glasses: a favourite place, and a hard thing said mid-walk
    sid = session(client, walk_style="playful")["session_id"]
    call(client, sid, "remember", category="places", text=CHERRY, said=f"{CHERRY}, you know.")
    said = "My brother is moving to Oulu next month. I'll miss him."
    plan = call(client, sid, "feel", kind="sad_news", heard=LOW, about="your brother moving to Oulu", said=said)["result"]
    assert plan["stance"] == "comfort" and plan["follow_up_saved"]
    client.post("/v1/companion/episode", json={
        "home_id": HOME, "id": sid, "surface": "glasses", "intent": "walk", "outcome": "completed",
        "start": (NOW - timedelta(minutes=20)).isoformat(), "end": NOW.isoformat(), "tools_used": ["feel", "remember"]})
    # next: Talk on the phone and the morning ritual on the robot both know
    for surface, intent in (("iphone", "talk"), ("mac", "talk"), ("robot", "ritual")):
        out = session(client, surface=surface, intent=intent)
        card = out["context_card"]
        assert card["open_thread"] == "something hard: your brother moving to Oulu", surface
        assert CHERRY in card["memories"], surface
        assert "a walk" in " ".join(card.get("done_today", [])), surface
        assert "your brother moving to Oulu" in out["system_instruction"], surface
    # and back: something told to the robot is there on the next walk
    robot = session(client, surface="robot", intent="ritual")["session_id"]
    assert call(client, robot, "remember", surface="robot", category="places", text="Loves the path along the river",
                said="I love the path along the river")["ok"]
    card = session(client, walk_style="chatty")["context_card"]
    assert card["outdoor_likes"][0] == "Loves the path along the river" and CHERRY in card["outdoor_likes"]
    assert card["open_thread"] == "something hard: your brother moving to Oulu"


# ---------------------------------------------------------------- the invitation
def invitation(client, home=HOME, surface="iphone"):
    r = client.get("/v1/me/invitation", params={"home_id": home, "surface": surface})
    assert r.status_code == 200, r.text
    return r.json()["invitation"]


def answer(client, ident, reply, home=HOME):
    return client.post("/v1/me/invitation/answer", params={"home_id": home}, json={"id": ident, "answer": reply})


def test_invitation_brings_up_what_was_left_open_in_their_own_words(client):
    assert invitation(client) is None  # nothing known, nothing to bring up
    sid = session(client)["session_id"]
    call(client, sid, "feel", kind="sad_news", heard=LOW, about="her brother moving to Oulu",
         said="My brother is moving to Oulu next month. I'll miss him.")
    got = invitation(client)
    assert got["kind"] == "talk_about" and got["topic"] == "your brother moving to Oulu" and got["activity"] is None
    assert got["text"] == "You mentioned your brother moving to Oulu earlier today. Want to talk about it?"
    assert got["voice_key"] == "invite.talk.hard" and got["id"].startswith("thread:")
    assert invitation(client, surface="mac") == got  # the same one on every device, all day
    assert answer(client, "thread:999", "yes").status_code == 404
    assert answer(client, got["id"], "not_now").json() == {"home_id": HOME, "invitation": None, "agreed": []}
    assert invitation(client) is None  # a not-now is final, and there is no second invitation today
    store = client.app.state.store
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    assert invite.current(store, HOME, "iphone", now=tomorrow) is None  # still open, still declined


def test_invitation_wording_for_good_news_and_other_threads():
    today = datetime.now(UTC).astimezone(TZ).date()

    def thread(topic, days):
        return {"id": 7, "topic": topic, "created": (datetime.now(UTC) - timedelta(days=days)).isoformat()}

    good = invite._talk(thread("their good news: she got the library job", 1), today)
    assert good.text == "You told me about the library job yesterday. Want to tell me more?" and good.voice_key == "invite.talk.good"
    other = invite._talk(thread("the story about the heron", 3), today)
    assert other.text == "We left off at the story about the heron. Want to pick it up?" and other.id == "thread:7"
    assert invite.to_them("her sister's visit") == "your sister's visit" and invite.to_them("His knee") == "your knee"
    assert invite.to_them("the leaking roof") == "the leaking roof" and invite.to_them("she got the job") == "the job"
    stuck = invite._talk(thread("something hard: she barely slept after the call", 1), today)
    assert stuck.voice_key == "invite.talk.plain" and "she" not in stuck.text and stuck.topic  # never a wrong sentence
    assert voice.is_template(voice.all_lines()["invite.talk.hard"]) and "invite.talk.hard" not in voice.lines("en")
    assert "greet.morning" in voice.lines("en") and "invite.talk.plain" in voice.lines("en")  # a finished line
    with pytest.raises(voice.UnknownLine):
        voice.cache_path("invite.talk.hard", "en")  # a template is never rendered as audio
    for key, line in voice.all_lines().items():
        if key.startswith("invite."):
            assert {"en", "fi", "sv"} <= set(line) and not any(b in line["en"].lower() for b in BANNED), key
            assert not any(ch.isdigit() for ch in line["en"])


def test_invitation_offers_what_has_gone_best_then_a_game_they_come_back_to(client):
    post(client, record(games=("lantern", "lantern", "pebbles")))
    store = client.app.state.store
    first = invitation(client)
    assert first == {"id": first["id"], "kind": "activity", "activity": "breathe", "topic": None,
                     "text": "Want to take a few slow breaths together?", "voice_key": "invite.activity.breathe"}
    assert answer(client, first["id"], "yes").status_code == 200 and invitation(client) is None  # one a day
    assert answer(client, first["id"], "yes").status_code == 200  # answering twice is harmless
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    again = invite.current(store, HOME, "iphone", now=tomorrow)
    assert again.activity == "breathe" and again.id != first["id"]  # an activity may be offered on another day
    # the same choice every time it is asked: no sampling
    picks = {invite.select(store, HOME, "iphone", NOW, []).activity for _ in range(5)}
    assert picks == {"breathe"}
    today = NOW.astimezone(TZ).date().isoformat()
    game = invite.select(store, HOME, "iphone", NOW, [f"activity:breathe:{today}"])
    assert game.activity == "lantern" and game.text == "Fancy a round of the lantern game now?"
    assert Invitation.model_validate(game.model_dump()).voice_key == "invite.activity.game"
    # already done today: not offered again
    post(client, [make("obs.play_session", {"game": "lantern", "device": "phone", "duration_s": 60}, source="phone",
                       home_id=HOME, ts=NOW)])
    assert invite.select(store, HOME, "iphone", NOW, [f"activity:breathe:{today}"]) is None  # pebbles was played once


def test_invitation_makes_no_offer_on_an_extra_gentle_day_but_may_still_bring_up_their_own_thing(client, monkeypatch):
    post(client, record())
    store = client.app.state.store
    assert invite.select(store, HOME, "iphone", NOW, []).kind == "activity"
    monkeypatch.setattr(invite, "tone_for", lambda row: "extra-gentle")  # what the card's tone is on such a day
    assert invite.select(store, HOME, "iphone", NOW, []) is None
    sid = session(client)["session_id"]
    call(client, sid, "feel", kind="good_news", heard={"valence": "bright", "via": "voice"}, about="the library job",
         said="I got the library job!")
    got = invite.select(store, HOME, "iphone", NOW, [])
    assert got.kind == "talk_about" and got.topic == "the library job"


def test_invitation_respects_dont_remember_and_unknown_homes(client):
    sid = session(client)["session_id"]
    call(client, sid, "feel", kind="sad_news", heard=LOW, about="the leaking roof", said="The roof is leaking again.")
    client.put(f"/v1/me/memory_settings?home_id={HOME}", json={"remember": False})
    assert invitation(client) is None
    assert invitation(client, home="nobody") is None
    assert client.get("/v1/me/invitation", params={"home_id": HOME, "surface": "glasses"}).status_code == 422


# ---------------------------------------------------------------- who may answer with silence (D49)
def test_only_a_walk_may_leave_an_input_unanswered(client):
    """Proactive audio lets the Live model decline to answer. Right for a walk's own nudges; in a real check-in it
    left "it has been a hard day" unanswered. So the setup carries it for the walk purpose only, on every surface."""
    assert load_config()["live"]["proactive_audio_purposes"] == ["walk"] and "proactive_audio" not in load_config()["live"]
    walks = [session(client), session(client, surface="iphone"), session(client, surface="iphone", purpose="walk", intent="talk"),
             session(client, walk_style="playful"), session(client, walk_style="chatty")]
    for body in walks:
        assert body["live_setup"]["proactivity"] == {"proactiveAudio": True}
    others = [dict(surface=s, intent=i, **({"purpose": p} if p else {}))
              for s in ("iphone", "mac", "glasses", "robot", "web")
              for i, p in (("talk", "talk"), ("checkin", "check_in"), ("talk", None), ("ritual", "ritual"), ("breathe", None))]
    for kw in others:
        r = client.post("/v1/companion/session", json={"home_id": HOME, **kw})
        if r.status_code != 200:  # a surface that does not open this kind of session at all
            continue
        setup = r.json()["live_setup"]
        assert "proactivity" not in setup, kw
        assert setup["realtimeInputConfig"]["activityHandling"] == "START_OF_ACTIVITY_INTERRUPTS"  # the rest is unchanged
    assert sum(client.post("/v1/companion/session", json={"home_id": HOME, **kw}).status_code == 200 for kw in others) >= 12
    for body in (session(client, surface="iphone", intent="talk", purpose="talk"),
                 session(client, surface="iphone", intent="checkin", purpose="check_in"),
                 session(client, surface="robot", intent="ritual")):
        text = body["system_instruction"]
        assert "Always answer what the person says" in text and "never nothing" in text
    assert "never let one pass in silence" in session(client, surface="iphone", intent="checkin", purpose="check_in")["system_instruction"]
    assert live_token.proactive("walk") and not any(live_token.proactive(p) for p in ("talk", "check_in", "ritual", None))
    assert "proactivity" not in live_token.setup("gemini-3.8-live", "Sulafat", "x", [])  # off unless a caller turns it on
    assert live_token.setup("gemini-3.8-live", "Sulafat", "x", [], proactive_audio=True)["proactivity"] == {"proactiveAudio": True}
