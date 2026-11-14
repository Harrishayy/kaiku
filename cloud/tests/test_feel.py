"""Notice and act: the `feel` tool (detect -> register with the mind -> act), what it changes after the
conversation, the check-in as a passing chat, and tone as an observation with provenance."""
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from kaiku_cloud import account, course
from kaiku_cloud.llm import gemini, gemma_hosted
from kaiku_cloud.mind import affect, assemble, feel, live_token
from kaiku_cloud.mind.card import SUGGESTION
from kaiku_contracts import make
from kaiku_contracts.api import FeelPlan, PatientInsight
from kaiku_contracts.companion_tools import FEEL_KINDS, TOOLS, for_surface, validate_args

NOW = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=2)
HOME = "mira"
LOW = {"valence": "low", "energy": "low", "tone": ["flat"], "via": "voice"}
SISTER = "My sister cancelled again. I'd been looking forward to seeing her all week."


def post(client, events):
    rows = [e.model_dump(mode="json", exclude_none=True) for e in events]
    assert not client.post("/v1/events", json={"events": rows}).json()["rejected"]


def record(home=HOME, days=20):
    """A phone-only record: daylight walks were followed by clearly better days, breathing by middling ones."""
    out = []
    for d in range(days, 0, -1):
        ts = NOW - timedelta(days=d)
        out += [make("obs.self_report", {"item": "mood", "value": 4, "channel": "phone"}, source="phone", home_id=home, ts=ts),
                make("obs.outing", {"minutes": 30, "steps": 3000, "method": "steps"}, source="phone", home_id=home, ts=ts)]
        if d % 4 == 0:
            out.append(make("obs.nudge_outcome", {"arm": "daylight_walk", "accepted": True, "next_day": {"mood": 5, "energy": 4}},
                            source="phone", home_id=home, ts=ts))
        if d % 5 == 0:
            out.append(make("obs.nudge_outcome", {"arm": "breathe", "accepted": True, "next_day": {"mood": 4, "energy": 3}},
                            source="phone", home_id=home, ts=ts))
    return out


@pytest.fixture
def mira(client):
    post(client, record())
    return client


def session(client, home=HOME, **kw):
    r = client.post("/v1/companion/session", json={"home_id": home, "surface": "iphone", "intent": "talk", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def call(client, sid, home=HOME, name="feel", **args):
    r = client.post("/v1/companion/tool", json={"home_id": home, "surface": "iphone", "session_id": sid, "name": name,
                                                "args": args})
    assert r.status_code == 200, r.text
    return r.json()


def backdate(client, sid, days, home=HOME, hour=19):
    """Move a conversation and its summary to an earlier evening (the tool always writes 'now')."""
    store = client.app.state.store
    start = (NOW - timedelta(days=days)).replace(hour=hour).isoformat().replace("+00:00", "Z")
    rows = affect.rows(store, home)
    if sid in rows:
        rows[sid]["start"] = start
        store.kv_set(f"affect:{home}", rows)


# ---------------------------------------------------------------- contract
def test_feel_is_a_validated_non_blocking_cloud_tool_on_every_surface():
    spec = TOOLS["feel"]
    assert spec["executor"] == "cloud" and spec["behavior"] == "NON_BLOCKING"
    ok = {"kind": "sad_news", "heard": {"valence": "low", "energy": "low", "tone": ["flat", "tearful"], "via": "voice"},
          "about": "her sister", "said": "My sister cancelled."}
    assert validate_args(spec["parameters"], ok) == []
    bad = [({**ok, "kind": "depressed"}, "kind"), ({**ok, "heard": {"valence": "awful"}}, "heard.valence"),
           ({**ok, "heard": {"valence": "low", "tone": ["flat", "tense", "warm"]}}, "too many"),
           ({**ok, "heard": {"valence": "low", "tone": ["gloomy"]}}, "outside its enum"),
           ({**ok, "heard": {"valence": "low", "energy": "zero"}}, "heard.energy"),
           ({"kind": "flat"}, "missing heard"), ({**ok, "state": "watch"}, "unknown arg state")]
    for args, why in bad:
        assert any(why in p for p in validate_args(spec["parameters"], args)), (args, why)
    for surface in ("robot", "glasses", "iphone", "mac", "web"):
        decl = next(t for t in for_surface(surface) if t["name"] == "feel")
        assert decl["behavior"] == "NON_BLOCKING"
    setup = live_token.setup("gemini-3.8-live", "Aoede", "x", for_surface("iphone"))
    decls = {d["name"]: d for d in setup["tools"][0]["functionDeclarations"]}
    assert decls["feel"]["behavior"] == "NON_BLOCKING" and "behavior" not in decls["remember"]
    assert "enableAffectiveDialog" not in setup["generationConfig"]  # off: the model closed the socket with it on


def test_session_serves_the_tool_and_its_rule(mira):
    s = session(mira)
    tool = next(t for t in s["tools"] if t["name"] == "feel")
    assert tool["behavior"] == "NON_BLOCKING" and s["chat_shape"] is None
    assert "`feel`: call it once per clear shift" in s["system_instruction"]
    assert "## Notice and act" in s["system_instruction"] and "## Passing chat" in s["system_instruction"]


# ---------------------------------------------------------------- the deterministic plan
@pytest.mark.parametrize("kind,valence,stance", [
    ("sad_news", "low", "comfort"), ("lonely", "low", "comfort"), ("worried", "low", "steady"),
    ("angry", "low", "steady"), ("flat", "low", "give_space"), ("good_news", "bright", "celebrate"),
    ("proud", "bright", "celebrate"), ("relief", "bright", "celebrate"), ("other", "low", "comfort"),
    ("other", "bright", "celebrate"), ("other", "neutral", "explore")])
def test_stance_per_kind(kind, valence, stance):
    assert kind in FEEL_KINDS and feel.stance_of(kind, valence) == stance


@pytest.mark.parametrize("kind,heard,said,earlier,heavy,depth,why", [
    ("flat", {"valence": "low", "energy": "low"}, "Fine.", 0, 0, "brief", "ordinary"),
    ("other", {"valence": "neutral"}, "Not much, washing.", 0, 0, "brief", "ordinary"),
    ("sad_news", {"valence": "low"}, None, 0, 0, "stay", "news"),
    ("good_news", {"valence": "bright"}, None, 0, 0, "stay", "news"),
    ("worried", {"valence": "low", "tone": ["tearful"]}, None, 0, 0, "stay", "upset"),
    ("angry", {"valence": "low", "energy": "high"}, None, 0, 0, "stay", "upset"),
    ("proud", {"valence": "bright", "energy": "high"}, None, 0, 0, "stay", "very glad"),
    ("proud", {"valence": "bright", "energy": "medium"}, None, 0, 0, "brief", "ordinary"),
    ("flat", {"valence": "low"}, "Fine.", 0, 3, "stay", "heavy week"),
    ("flat", {"valence": "neutral"}, "Fine.", 0, 3, "stay", "heavy week"),  # flat counts without a "low" label
    ("other", {"valence": "neutral"}, "Fine.", 0, 3, "brief", "ordinary"),
    ("proud", {"valence": "bright"}, "Fine.", 0, 5, "brief", "ordinary"),
    ("flat", {"valence": "low"}, "Fine.", 1, 0, "stay", "came back to it"),
    ("other", {"valence": "neutral"}, "can we talk for a bit", 0, 0, "stay", "they are talking"),
    ("other", {"valence": "neutral"}, " ".join(["word"] * 31), 0, 0, "stay", "they are talking")])
def test_depth_is_a_rule_of_strength_repetition_and_how_much_they_say(kind, heard, said, earlier, heavy, depth, why):
    assert feel.depth_of(kind, heard, said, earlier, heavy) == (depth, why)


def test_offer_only_what_the_record_supports_once_and_never_for_good_news_or_anger():
    best = {"arm": "daylight_walk", "tries": 5, "mean": 0.8}
    what, note, activity = feel.offer_for("comfort", "sad_news", "steady", False, best)
    assert what == SUGGESTION["daylight_walk"] and activity == "walk"
    assert "a few times so far" in note and "A no is final" in note and "Sitting quietly" in note
    assert "once or twice" in feel.offer_for("comfort", "lonely", "steady", False, {**best, "tries": 2})[1]
    assert "most times" in feel.offer_for("comfort", "lonely", "steady", False, {**best, "tries": 9})[1]
    what, note, activity = feel.offer_for("comfort", "sad_news", "steady", False, None)  # nothing known: only quiet
    assert what == feel.QUIET and activity is None and note.startswith("Nothing in the record says what helps")
    assert feel.offer_for("comfort", "sad_news", "extra-gentle", False, best)[0] == feel.QUIET  # no suggestions today
    assert feel.offer_for("celebrate", "good_news", "steady", False, best) == (None, None, None)
    assert feel.offer_for("steady", "angry", "steady", False, best) == (None, None, None)
    what, note, _ = feel.offer_for("comfort", "sad_news", "steady", True, best)
    assert what is None and "already offered once" in note


def test_plan_names_a_heavy_week_only_when_the_record_shows_one():
    kw = {"earlier": 0, "cue": "steady", "offered": False, "best": None, "recall": None, "follow_up": False}
    heavy = feel.plan_from("flat", {"valence": "low"}, None, "Fine.", heavy=3, **kw)
    assert "heavy on 3 days this week" in heavy.reflect_hint and heavy.depth == "stay" and heavy.stance == "give_space"
    plain = feel.plan_from("flat", {"valence": "low"}, None, "Fine.", heavy=1, **kw)
    assert "heavy" not in plain.reflect_hint and plain.depth == "brief" and plain.scheduling == "WHEN_IDLE"
    glad = feel.plan_from("good_news", {"valence": "bright"}, "the job", None, heavy=5, **kw)
    assert "heavy" not in glad.reflect_hint and "Be glad out loud about the job" in glad.reflect_hint


# ---------------------------------------------------------------- the tool, end to end
def test_sad_news_registers_recalls_and_offers_the_known_helper_once(mira, monkeypatch):
    def no_model(*a, **k):
        raise AssertionError("no model call on the hot path")

    monkeypatch.setattr(gemma_hosted, "generate", no_model)
    monkeypatch.setattr(gemini, "generate", no_model)
    sid = session(mira)["session_id"]
    assert call(mira, None, name="remember", category="people", text="My sister Liisa rings in the evening")["ok"]
    r = call(mira, sid, kind="sad_news", heard=LOW, about="her sister cancelled the visit", said=SISTER)
    assert r["ok"] and r["executor"] == "cloud"
    plan = FeelPlan.model_validate(r["result"])
    assert (plan.stance, plan.depth) == ("comfort", "stay")
    assert plan.recall == 'They told you before: "My sister Liisa rings in the evening".'
    assert plan.may_offer == SUGGESTION["daylight_walk"] and plan.offer_activity == "walk"  # 5 good walks beat 4 middling breaths
    assert "a few times so far" in plan.offer_note and plan.follow_up_saved
    again = FeelPlan.model_validate(call(mira, sid, kind="lonely", heard=LOW, about="the empty flat",
                                         said="The flat just feels empty tonight.")["result"])
    assert again.may_offer is None and "already offered once" in again.offer_note and again.depth == "stay"
    store = mira.app.state.store
    row = affect.rows(store, HOME)[sid]
    assert row["heard"] == {"valence": "low", "energy": "low", "tone": ["flat"], "provenance": "model_heard", "moments": 2}
    assert row["valence"] == "low" and row["by"] == "model_heard" and row["themes"] == []
    everything = json.dumps([store.kv_get(f"feel:{HOME}"), affect.rows(store, HOME)])
    assert "looking forward" not in everything and "feels empty" not in everything  # their words are never stored
    ep = store.episode(sid)
    assert ep["tools"].count("feel") == 2
    # the follow-up is the open thread for next time
    nxt = session(mira)
    assert nxt["context_card"]["open_thread"] == "something hard: her sister cancelled the visit"


def test_an_empty_record_gets_no_claims(client):
    plan = FeelPlan.model_validate(call(client, None, home="new", kind="lonely", heard={"valence": "low"},
                                        about="a quiet week")["result"])
    assert plan.recall is None and plan.may_offer == feel.QUIET and plan.offer_activity is None
    assert plan.offer_note.startswith("Nothing in the record says what helps") and not plan.follow_up_saved
    assert plan.depth == "brief" and "heavy" not in plan.reflect_hint


def test_good_news_is_celebrated_connected_to_what_they_hoped_for_and_kept(mira):
    assert call(mira, None, name="remember", category="plans", text="Job interview at the library on Thursday")["ok"]
    sid = session(mira)["session_id"]
    said = "I got the job at the library! They rang this morning."
    plan = FeelPlan.model_validate(call(mira, sid, kind="good_news", about="she got the library job", said=said,
                                        heard={"valence": "bright", "energy": "high", "tone": ["warm"]})["result"])
    assert (plan.stance, plan.depth, plan.may_offer, plan.offer_note) == ("celebrate", "stay", None, None)
    assert plan.recall == 'They were hoping for this. They told you: "Job interview at the library on Thursday".'
    assert "Be glad out loud about she got the library job" in plan.reflect_hint and plan.follow_up_saved
    card = session(mira)["context_card"]
    assert card["open_thread"] == "their good news: she got the library job"
    assert card["last_reflection"]["valence"] == "bright" and card["tone"] == "steady"
    other = session(mira)["session_id"]  # the model may not pick a kind: a low or bright "other" is still followed up
    assert call(mira, other, kind="other", heard=LOW, about="the leaking roof", said="the roof is leaking again")["result"]["follow_up_saved"]
    assert not call(mira, session(mira)["session_id"], kind="other", heard={"valence": "neutral"}, about="the leaking roof",
                    said="the roof is leaking again")["result"]["follow_up_saved"]
    # a topic that is not in the person's own words is not kept, and neither is a health detail
    assert not call(mira, sid, kind="good_news", heard={"valence": "bright"}, about="a new puppy", said=said)["result"]["follow_up_saved"]
    assert not call(mira, sid, kind="sad_news", heard=LOW, about="her medication dose", said="my medication dose changed")["result"]["follow_up_saved"]


def test_remembering_off_still_helps_in_the_moment_and_keeps_nothing(mira):
    assert mira.put("/v1/me/memory_settings", params={"home_id": HOME}, json={"remember": False}).status_code == 200
    sid = session(mira)["session_id"]
    plan = FeelPlan.model_validate(call(mira, sid, kind="sad_news", heard=LOW, about="her sister cancelled the visit",
                                        said=SISTER)["result"])
    assert plan.stance == "comfort" and plan.may_offer and not plan.follow_up_saved and plan.recall is None
    store = mira.app.state.store
    assert affect.rows(store, HOME) == {} and store.kv_get(f"feel:{HOME}")[sid]["keep"] is False
    second = call(mira, sid, kind="lonely", heard=LOW)["result"]  # the conversation's own timeline still works
    assert "may_offer" not in second and second["depth"] == "stay"
    assert call(mira, sid, name="end_session", outcome="completed")["ok"]
    assert sid not in (store.kv_get(f"feel:{HOME}") or {})
    assert session(mira)["context_card"]["last_reflection"] is None


def test_crisis_words_never_reach_the_mind(mira):
    sid = session(mira)["session_id"]
    assert call(mira, sid, kind="lonely", heard=LOW)["ok"]
    r = call(mira, sid, kind="sad_news", heard=LOW, about="everything", said="I want to kill myself")
    assert r["crisis"] and not r["ok"] and r["result"]["stop_session"]
    store = mira.app.state.store
    assert sid not in affect.rows(store, HOME) and sid not in (store.kv_get(f"feel:{HOME}") or {})
    assert not call(mira, sid, kind="lonely", heard=LOW)["ok"]


def test_handler_is_fast_and_makes_no_model_call(mira, monkeypatch):
    def no_model(*a, **k):
        raise AssertionError("no model call on the hot path")

    monkeypatch.setattr(gemma_hosted, "generate", no_model)
    monkeypatch.setattr(gemini, "generate", no_model)
    sid = session(mira)["session_id"]
    store = mira.app.state.store
    ep = store.episode(sid)
    took = []
    for i in range(20):
        t = time.perf_counter()
        feel.act(store, HOME, "iphone", sid, ep, {"kind": "worried", "heard": LOW, "about": f"work {i}",
                                                  "said": f"work {i} keeps going round my head"})
        took.append(time.perf_counter() - t)
    assert sorted(took)[len(took) // 2] < 0.3, took


# ---------------------------------------------------------------- after the conversation
def test_after_a_low_evening_tomorrow_opens_gently_with_the_best_recorded_suggestion(mira):
    usual = mira.get("/v1/nudge", params={"home_id": HOME}).json()
    assert usual["probs"]["breathe"] > 0.05 and usual["probs"]["daylight_walk"] > 0.5  # ordinarily a draw: it explores
    assert session(mira)["context_card"]["tone"] == "steady"
    sid = session(mira)["session_id"]
    call(mira, sid, kind="flat", heard=LOW)
    backdate(mira, sid, 1)
    cards = [session(mira) for _ in range(8)]
    card = cards[0]["context_card"]
    assert {c["context_card"]["suggestion"] for c in cards} == {SUGGESTION["daylight_walk"]}  # not a random pick
    assert card["tone"] == "gentle" and card["last_reflection"]["when"] == "yesterday evening"
    assert card["last_reflection"]["heard"] == {"valence": "low", "energy": "low", "tone": ["flat"],
                                                "provenance": "model_heard", "moments": 1}
    assert card["recent_reflection"] == ("The talk yesterday evening sounded like a hard one (flat, quiet). "
                                         "Be gentle; do not quote it back.")
    n = mira.get("/v1/nudge", params={"home_id": HOME}).json()
    assert n["arm"] == "daylight_walk" and "has gone best for you so far, over 5 recent tries" in n["reason"]
    # a brighter talk since then: back to the ordinary learner and an ordinary tone
    sid2 = session(mira)["session_id"]
    call(mira, sid2, kind="proud", heard={"valence": "bright", "energy": "medium"})
    assert session(mira)["context_card"]["tone"] == "steady"


def test_the_third_low_evening_is_named_and_the_chat_stays(mira):
    for days in (2, 1):
        sid = session(mira)["session_id"]
        call(mira, sid, kind="flat", heard=LOW)
        backdate(mira, sid, days)
    s = session(mira, purpose="check_in")
    assert s["chat_shape"]["depth"] == "stay" and "in no hurry" in s["system_instruction"]
    # the voice model may call "Fine." neutral: a flat answer still counts towards the heavy few days
    plan = FeelPlan.model_validate(call(mira, s["session_id"], kind="flat", said="Fine.",
                                        heard={"valence": "neutral", "energy": "low"})["result"])
    assert plan.depth == "stay" and "heavy on 3 days this week" in plan.reflect_hint
    assert affect.rows(mira.app.state.store, HOME)[s["session_id"]]["heard"]["tone"] == ["flat"]
    assert plan.recall == "The talk yesterday evening sounded hard too." and plan.stance == "give_space"


# ---------------------------------------------------------------- the check-in as a passing chat
def test_check_in_purpose_shapes_the_chat_and_lists_open_items(mira):
    plain = session(mira)
    assert plain["chat_shape"] is None and "## The shape of this conversation" not in plain["system_instruction"]
    assert plain["context_card"]["open_items"] == [] and plain["context_card"]["purpose"] is None
    s = session(mira, purpose="check_in")
    shape, text = s["chat_shape"], s["system_instruction"]
    assert shape["purpose"] == "check_in" and shape["depth"] == "brief"
    assert set(shape["open_items"]) == {"mood", "energy", "sleep"} == set(s["context_card"]["open_items"])
    part = text.split("## The shape of this conversation\n", 1)[1].split("\n\n## ", 1)[0]
    assert "passing chat" in part and "within about four exchanges" in part and "never ask for a number" in part
    assert "weave ONE of these" in part and "how they slept" in part and "recording none is fine" in part
    post(mira, [make("obs.self_report", {"item": "sleep", "value": 4, "channel": "phone"}, source="phone", home_id=HOME),
                make("obs.self_report", {"item": "mood", "value": 4, "channel": "phone"}, source="phone", home_id=HOME)])
    assert session(mira, purpose="check_in")["chat_shape"]["open_items"] == ["energy"]
    talk = session(mira, purpose="talk")
    assert talk["chat_shape"] == {"purpose": "talk", "depth": "brief", "open_items": []}
    assert "## The shape of this conversation" not in talk["system_instruction"]
    walk = session(mira, purpose="walk", intent="walk")
    assert walk["chat_shape"]["purpose"] == "walk" and walk["context_card"]["chat_depth"] is None
    assert mira.post("/v1/companion/session", json={"home_id": HOME, "surface": "iphone", "purpose": "exam"}).status_code == 422
    with pytest.raises(ValueError):
        assemble.validate_card({"chat_depth": "long"})
    with pytest.raises(ValueError):
        assemble.validate_card({"open_items": ["weight"]})


def test_someone_else_in_the_room_gets_no_personal_items(mira):
    s = session(mira, purpose="check_in", others_present=True)
    assert s["chat_shape"]["open_items"] == [] and s["context_card"]["last_reflection"] is None


# ---------------------------------------------------------------- tone from their words (rules, then Gemma)
def test_tone_of_words_keyword_fallback_and_validated_gemma_label(mira, monkeypatch):
    low = affect.rule([{"role": "person", "text": "I'm exhausted and so worried about work, I can't stop thinking."}])
    assert low["valence"] == "low" and low["tone"] == ["tense"] and low["energy"] == "low" and low["by"] == "rule"
    flat = affect.rule([{"role": "person", "text": "Fine."}, {"role": "person", "text": "Nothing much."}])
    assert flat["tone"] == ["flat"] and flat["energy"] is None
    glad = affect.rule([{"role": "person", "text": "We laughed so much, it was lovely! I can't wait for Friday."}])
    assert glad["valence"] == "bright" and set(glad["tone"]) == {"playful", "warm"} and glad["energy"] == "high"
    assert affect.rule([{"role": "person", "text": "We went to the shop."}])["tone"] == []
    for bad in ({"valence": "low", "themes": [], "tone": ["gloomy"]}, {"valence": "low", "themes": [], "energy": "none"},
                {"valence": "low", "themes": [], "tone": ["flat", "tense", "calm"]}, {"valence": "sad", "themes": []}):
        with pytest.raises(ValueError):
            affect.checked(json.dumps(bad))
    assert affect.checked(json.dumps({"valence": "low", "themes": ["sleep"]})) == {
        "valence": "low", "themes": ["sleep"], "tone": [], "energy": None}
    # the episode route labels with Gemma after the response; an invalid answer leaves the rule label
    seen = []
    monkeypatch.setattr(gemma_hosted, "generate", lambda p, **kw: seen.append((p, kw)) or json.dumps(
        {"valence": "low", "themes": ["work", "worry"], "tone": ["tense", "tearful"], "energy": "low"}))
    start = NOW - timedelta(hours=1)
    body = {"home_id": HOME, "surface": "iphone", "intent": "talk", "start": start.isoformat(),
            "end": (start + timedelta(minutes=5)).isoformat(), "outcome": "completed", "tools_used": [],
            "transcript": [{"role": "person", "text": "Work was awful and I cried in the car."}]}
    eid = mira.post("/v1/companion/episode", json=body).json()["id"]
    store = mira.app.state.store
    row = affect.rows(store, HOME)[eid]
    assert len(seen) == 1 and seen[0][1]["task"] == "reflection_affect" and "tearful" in seen[0][0]
    assert (row["tone"], row["energy"], row["valence"]) == (["tense", "tearful"], "low", "low") and row["by"] != "rule"
    assert "cried in the car" not in json.dumps(affect.rows(store, HOME))
    assert not affect.label_episode(store, HOME, eid) and len(seen) == 1  # cached: labelled once
    monkeypatch.setattr(gemma_hosted, "generate", lambda p, **kw: json.dumps({"valence": "low", "themes": [], "tone": ["bleak"]}))
    body2 = {**body, "start": (start + timedelta(minutes=10)).isoformat(), "end": (start + timedelta(minutes=15)).isoformat()}
    eid2 = mira.post("/v1/companion/episode", json=body2).json()["id"]
    assert affect.rows(store, HOME)[eid2]["by"] == "rule" and affect.rows(store, HOME)[eid2]["tone"] == ["tearful"]
    # no transcript (no opt-in): nothing is sent to a model
    before = len(seen)
    mira.post("/v1/companion/episode", json={k: v for k, v in body.items() if k != "transcript"} | {
        "start": (start + timedelta(minutes=20)).isoformat(), "end": (start + timedelta(minutes=25)).isoformat()})
    assert len(seen) == before


# ---------------------------------------------------------------- where the care team sees it (only when shared)
def test_reported_tone_reaches_the_review_with_provenance_only_when_shared(mira):
    sid = session(mira)["session_id"]
    call(mira, sid, kind="lonely", heard=LOW, about="the empty flat", said="the flat feels empty")
    backdate(mira, sid, 1)
    typed = session(mira)["session_id"]
    call(mira, typed, kind="worried", heard={"valence": "low", "tone": ["tense"], "via": "text"})
    backdate(mira, typed, 2)

    def insight(**params):
        r = mira.get(f"/v1/patients/{HOME}/insight", params={"generate": "false", **params})
        assert r.status_code == 200, r.text
        return PatientInsight.model_validate(r.json())

    hidden = insight()
    assert hidden.reflections is None and "model_heard" not in hidden.model_dump_json() and "voice flat" not in hidden.model_dump_json()
    assert mira.put("/v1/me/sharing", params={"home_id": HOME}, json={"share_with_care_team": True}).status_code == 200
    out = insight()
    days = {d.date: d for d in out.reflections.days}
    heard = days[(NOW - timedelta(days=1)).date()]
    assert heard.valence == "low" and heard.heard.provenance == "model_heard" and heard.heard.tone == ["flat"]
    assert days[(NOW - timedelta(days=2)).date()].heard.provenance == "model_read"
    assert "As the model in the conversation reported in 2: tense in 1, flat in 1; sounded quiet in 1." in out.reflections.tone_summary
    assert out.reflections.tone_summary.endswith("Tone is a model's observation of a conversation, not a measurement.")
    account_day = next(d for d in out.days if d.date == (NOW - timedelta(days=1)).date())
    assert "evening reflection low, voice flat and quiet" in account_day.parts
    typed_day = next(d for d in out.days if d.date == (NOW - timedelta(days=2)).date())
    assert "evening reflection low, read as tense" in typed_day.parts
    cited = account.reflections(mira.app.state.store, HOME, datetime.now(UTC), True)[2]  # what Gemma may cite
    assert cited.id == "reflect:recent" and "sounded quiet in 1" in cited.detail and "not a measurement" in cited.detail
    assert account.reflections(mira.app.state.store, HOME, datetime.now(UTC), False)[2] is None
    assert "empty flat" not in out.model_dump_json()
    low_event = next(e for e in out.course.events if e.kind == "reflection_low")
    assert "Tone: read as tense (by the model, from typed words)." in low_event.text
    assert out.state == insight().state  # an observation: it never moves the consensus
    # "forget everything" also drops what the companion reported
    assert mira.delete("/v1/me/memories", params={"home_id": HOME}).status_code == 200
    assert affect.rows(mira.app.state.store, HOME) == {} and insight().reflections.days == []


def test_words_and_voice_are_reported_side_by_side():
    row = {"part": "evening", "valence": "low", "themes": ["sleep"], "tone": ["tense"], "energy": "low", "declined": False,
           "heard": {"valence": "low", "energy": "low", "tone": ["flat"], "provenance": "model_heard", "moments": 2}}
    assert account.talk_part(row) == "evening reflection low (sleep), words tense, voice flat and quiet"
    assert course._tone(row) == " Tone: words tense; voice flat and quiet (as heard by the voice model)."
    assert affect.sounded(row) == "sounded flat and quiet (as heard by the voice model)"
    assert account.talk_part({**row, "tone": [], "heard": None}) == "evening reflection low (sleep)"
    assert course._tone({"tone": [], "heard": None}) == ""
    assert affect.heard_of([{"valence": "low", "via": "text"}, {"valence": "bright", "via": "text"},
                            {"valence": "bright", "energy": "high", "tone": ["warm"], "via": "text"}]) == {
        "valence": "bright", "energy": "high", "tone": ["warm"], "provenance": "model_read", "moments": 3}


# ---------------------------------------------------------------- the plan does not hinge on the model's label
@pytest.mark.parametrize("label", ["sad_news", "other", "flat", "worried"])
def test_the_sister_sentence_gets_comfort_and_stay_under_any_label(mira, label):
    """The same sentence came back as `sad_news` in one real session and `other` in the next."""
    kw = {"earlier": 0, "heavy": 0, "cue": "steady", "offered": False, "best": None, "recall": None, "follow_up": False}
    plan = feel.plan_from(label, {"valence": "low", "energy": "low"}, "sister cancelled plans", SISTER, **kw)
    assert (plan.stance, plan.depth) == ("comfort", "stay")
    sid = session(mira)["session_id"]
    got = FeelPlan.model_validate(call(mira, sid, kind=label, heard={"valence": "low", "energy": "low"},
                                       about="her sister cancelled", said=SISTER)["result"])
    assert (got.stance, got.depth, got.follow_up_saved) == ("comfort", "stay", True)
    assert session(mira)["context_card"]["open_thread"] == "something hard: her sister cancelled"


def test_news_is_read_from_the_persons_words_and_checked_against_how_it_sounded():
    assert feel.cue_of("low", SISTER, None) == "loss" and feel.cue_of("neutral", "Mum is back in hospital.", None) == "loss"
    assert feel.cue_of("bright", "I got the job at the library!", None) == "win"
    assert feel.cue_of("neutral", None, "passed my driving test") == "win"
    assert feel.cue_of("bright", "They cancelled the dentist, thank goodness!", None) is None  # glad: not a loss
    assert feel.cue_of("low", "I got the job but I'm dreading it.", None) is None              # low: not a win
    assert feel.cue_of("low", "Fine. Nothing much.", None) is None
    assert feel.read_kind("other", "bright", "I got the job at the library!", None) == "good_news"
    assert feel.read_kind("lonely", "low", SISTER, None) == "lonely" and feel.read_kind("proud", "bright", "I passed my test", None) == "proud"
    kw = {"earlier": 0, "heavy": 0, "cue": "steady", "offered": False, "best": None, "recall": None, "follow_up": False}
    glad = feel.plan_from("other", {"valence": "bright"}, "the library job", "I got the job at the library!", **kw)
    assert (glad.stance, glad.depth, glad.may_offer) == ("celebrate", "stay", None)
    plain = feel.plan_from("other", {"valence": "low", "energy": "low"}, None, "Bit of a grey one.", **kw)
    assert (plain.stance, plain.depth) == ("comfort", "brief")  # no news, no strength, no history: a small moment


# ---------------------------------------------------------------- nothing about today that was not observed today
def test_an_empty_day_puts_no_fact_about_today_in_front_of_the_model(mira):
    from kaiku_cloud.mind.card import today_facts

    store = mira.app.state.store
    assert today_facts(store.events_for_home(HOME), datetime.now(UTC)) == []  # the last observation was yesterday
    s = session(mira, purpose="check_in")
    card, text = s["context_card"], s["system_instruction"]
    assert card["today_facts"] == [] and card["done_today"] == [] and card["weather_word"] is None
    assert card["source_context"] == ["The phone app reported an outing yesterday."]  # dated: never "recently"
    today = text.split("## Today\n", 1)[1].split("\n\n## ", 1)[0]
    assert "Already done today" not in today and "in their own ratings" not in today and "recently" not in text
    assert " today." not in today and "outing yesterday" in today
    fact = text.split("## What you may say as fact\n", 1)[1].split("\n\n## ", 1)[0]
    assert "Nothing is recorded for today yet: do not say or imply that they have done anything today." in fact
    assert "They are never facts about this person" in fact and "You are not told the weather" in fact
    assert "Something listed for yesterday or earlier is not about today." in fact
    shape = text.split("## The shape of this conversation\n", 1)[1].split("\n\n## ", 1)[0]
    assert "if it lists nothing, a plain greeting and one open question" in shape and "the weather outside" not in shape
    # once something was observed today, it is listed and the "nothing today" line goes
    post(mira, [make("obs.self_report", {"item": "sleep", "value": 2, "channel": "phone"}, source="phone", home_id=HOME)])
    s = session(mira, purpose="check_in")
    assert s["context_card"]["today_facts"] == ["a short night"]
    assert "Nothing is recorded for today yet" not in s["system_instruction"]
    assert assemble.render_grounding({"weather_word": "grey", "done_today": ["a walk"]}).count("\n") == 1


def test_remember_for_good_news_needs_the_fact_in_the_persons_own_words(mira):
    """In a real run the model called `remember` unprompted after good news: it is kept only when grounded."""
    sid = session(mira)["session_id"]
    said = "I got the job at the library! They rang this morning and I actually got it."
    kept = call(mira, sid, name="remember", category="plans", text="Got the job at the library", said=said)
    assert kept["ok"] and kept["result"]["action"] == "stored"
    for args in ({"text": "Got the job at the library"},                                # no words of theirs
                 {"text": "Got the job at the library", "said": ""},
                 {"text": "Got the job at the library", "said": "It was a nice day."},      # words without the fact
                 {"text": "Starts the library job on Monday", "said": said},                # a day they never said
                 {"text": "The library job starts soon", "said": said},                     # half theirs, half added
                 {"text": "The library manager is Pirjo", "said": said},                    # a name they never said
                 {"text": "Got the library job, 30 hours a week", "said": said}):           # a number they never said
        r = call(mira, sid, name="remember", category="plans", **args)
        assert not r["ok"] and r["error"].startswith("not stored: pass `said`"), args
    from kaiku_cloud.mind import memory

    assert memory.grounded("Sister is called Liisa", "My sister Liisa rings in the evening.")
    assert memory.grounded("Walks with Maija on Tuesdays", "I walk with Maija on Tuesdays, by the lake.")
    assert not memory.grounded("Walks with Maija on Tuesdays", "I walk with a friend sometimes.")
    texts = [m["text"] for m in mira.get("/v1/me/memories", params={"home_id": HOME}).json()["memories"]]
    assert texts == ["Got the job at the library"]

