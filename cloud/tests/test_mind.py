"""Companion mind: session bootstrap, tool endpoint, memory rules, open thread, routines, tone cue, live token.

Edge cases come in near-identical pairs with different outcomes (the point of the rules)."""

import json
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from kaiku_cloud.api.main import create_app
from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate
from kaiku_cloud.mind import card as card_mod
from kaiku_cloud.mind import live_token, memory
from kaiku_cloud.mind.session import record_episode
from kaiku_cloud.settings import TZ, Settings
from kaiku_contracts import wording
from kaiku_contracts.api import EpisodeIn
from kaiku_contracts.companion_tools import SURFACES, TOOLS, for_surface

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)  # a Thursday


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    """All 8 seeded demo patients in one cloud (seeding is the slow part, so once per module)."""
    s = Settings(demo_mode=True, db_path=str(tmp_path_factory.mktemp("mind") / "t.sqlite"), web_dir=None)
    c = TestClient(create_app(s))
    for p in DEMO_PATIENTS:
        ev = generate(p)
        for i in range(0, len(ev), 400):
            assert c.post("/v1/events", json={"events": ev[i:i + 400]}).status_code == 200
    return c


def tool(c, name, args=None, home="h1", surface="robot", session_id=None):
    r = c.post("/v1/companion/tool", json={"home_id": home, "surface": surface, "name": name, "args": args or {},
                                           "session_id": session_id})
    assert r.status_code == 200, r.text
    return r.json()


def mems(c, home="h1"):
    return c.get(f"/v1/me/memories?home_id={home}").json()


def session(c, home="h1", surface="robot", intent="talk", **kw):
    r = c.post("/v1/companion/session", json={"home_id": home, "surface": surface, "intent": intent, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def today_section(instruction):
    return instruction.split("## Today\n", 1)[1].split("\n\n## ", 1)[0]


# ---------------------------------------------------------------- registry
def test_registry_matches_surfaces_toml_and_exports():
    from kaiku_cloud.mind import assemble

    _, surfaces = assemble.load_files()
    for name, s in surfaces.items():
        served = {t["name"] for t in for_surface(name, walk=False)}
        # surfaces.toml lists what the prompt describes; the registry may add forget (memory control) everywhere
        assert set(s["tools"]) <= served and served - set(s["tools"]) <= {"forget", "ask_mind"}, name
        on_a_walk = {t["name"] for t in for_surface(name, walk=True)} - served  # served only in a walk session
        assert on_a_walk == ({"set_walk_goal", "log_walk_moment"} if name == "iphone" else set()), name
        assert {t["name"] for t in for_surface(name)} == served | on_a_walk
    assert set(SURFACES) == set(surfaces)
    assert {"look_at_this"} & {t["name"] for t in for_surface("robot")} == set()
    exported = json.loads((assemble.ROOT / "contracts/schemas/companion_tools.json").read_text())
    assert set(exported["tools"]) == set(TOOLS)


# ---------------------------------------------------------------- session bootstrap
def test_session_shape_for_aino(cohort):
    j = session(cohort, "demo-aino", "robot", "ritual")
    assert j["model"] == "gemini-3.8-live" and j["voice"] == "Sulafat" and j["live_token"] is None
    assert j["persona_version"].startswith("persona+") and j["safety_phrases_version"].startswith("safety+")
    names = [t["name"] for t in j["tools"]]
    assert "send_friend_ping" in names and "look_at_this" not in names and "remember" in names
    assert "## Who Kaiku is" in j["system_instruction"] and "About this file" not in j["system_instruction"]
    assert j["context_card"]["tone"] == "extra-gentle"  # Aino needs a call -> extra gentle, never the word
    g = session(cohort, "demo-aino", "glasses", "walk")
    assert "look_at_this" in [t["name"] for t in g["tools"]] and "send_friend_ping" not in [t["name"] for t in g["tools"]]


def test_session_for_unknown_home_and_bad_surface(client):
    j = session(client, "nobody-yet", "iphone")
    assert j["context_card"]["tone"] == "steady" and j["context_card"]["memories"] == []
    assert client.post("/v1/companion/session", json={"home_id": "x", "surface": "toaster"}).status_code == 422


def test_session_needs_home_token_when_set(make_client):
    c = make_client(home_token="secret", home_id="h1")
    body = {"home_id": "h1", "surface": "robot"}
    assert c.post("/v1/companion/session", json=body).status_code == 401
    assert c.post("/v1/companion/session", json=body, headers={"Authorization": "Bearer secret"}).status_code == 200


@pytest.mark.parametrize("state,agreement,tone", [
    ("stable", "agree", "steady"), ("watch", "disagree", "gentle"), ("needs_call", "agree", "extra-gentle"),
    ("safety", "agree", "extra-gentle"), ("watch", "low_coverage", "steady"),  # thin data never looks worse
])
def test_tone_cue_mapping(state, agreement, tone):
    assert card_mod.tone_for({"summary": {"state": state, "agreement": agreement}}) == tone


def test_tone_cue_insufficient_data_is_steady():
    assert card_mod.tone_for(None) == card_mod.tone_for({}) == "steady"


@pytest.mark.parametrize("home,tone", [("sim-eero", "steady"), ("sim-helmi", "gentle"), ("sim-kaisa", "steady"),
                                       ("sim-lauri", "extra-gentle"), ("demo-aino", "extra-gentle")])
def test_tone_cue_for_seeded_patients(cohort, home, tone):
    assert session(cohort, home, "iphone")["context_card"]["tone"] == tone


STATE_WORDS = re.compile(r"needs_call|needs a call|stable|insufficient|consensus|verdict|worse|baseline|score|"
                         r"safety|watch|sleep|heart|hrv|steps|\d", re.I)


@pytest.mark.parametrize("surface,intent", [("robot", "ritual"), ("glasses", "walk"), ("iphone", "checkin"),
                                            ("mac", "break"), ("web", "talk")])
def test_card_never_carries_state_numbers_or_wearable_data(cohort, surface, intent):
    for p in DEMO_PATIENTS:
        j = session(cohort, p.home_id, surface, intent)
        card_json = json.dumps({k: v for k, v in j["context_card"].items() if k not in ("tone", "phq9_due")})
        today = today_section(j["system_instruction"]).replace("start_phq9", "the questionnaire tool")
        for text in (card_json, today):
            assert not STATE_WORDS.search(text), (p.home_id, STATE_WORDS.search(text).group(0), text)
            assert not wording.codes(wording.lint(text, max_questions=None)) & {"state_talk", "clinical_term",
                                                                                "wearable_data"}, (p.home_id, text)


# ---------------------------------------------------------------- memory rules
def test_remember_then_dont_remember_that(client):
    assert tool(client, "remember", {"category": "people", "text": "My sister is Maija"})["result"]["action"] == "stored"
    assert [m["text"] for m in mems(client)["memories"]] == ["My sister is Maija"]
    r = tool(client, "remember", {"category": "people", "text": "Don't remember that"})
    assert r["ok"] and r["result"]["action"] == "forgot"
    assert mems(client)["memories"] == []


def test_forget_tool_last_vs_all(client):
    for t in ("Likes the lake", "My sister is Maija", "Tea helps"):
        tool(client, "remember", {"category": "likes", "text": t})
    tool(client, "forget", {"scope": "last"})
    assert [m["text"] for m in mems(client)["memories"]] == ["My sister is Maija", "Likes the lake"]
    tool(client, "forget", {"scope": "all"})
    assert mems(client)["memories"] == []


def test_same_fact_twice_is_one_memory(client):
    a = tool(client, "remember", {"category": "people", "text": "My sister is Maija"})
    b = tool(client, "remember", {"category": "people", "text": "  my   SISTER is maija. "})
    assert a["result"]["id"] == b["result"]["id"] and b["result"]["action"] == "duplicate"
    c = tool(client, "remember", {"category": "people", "text": "My sister is Maija Virtanen"})
    assert c["result"]["action"] == "stored"  # a different fact is kept
    assert len(mems(client)["memories"]) == 2


@pytest.mark.parametrize("category,ok", [("people", True), ("preference", True), ("health", False),
                                         ("mood", False), ("diagnosis", False)])
def test_category_rules(client, category, ok):
    r = tool(client, "remember", {"category": category, "text": "Likes the window seat"})
    assert r["ok"] is ok and (len(mems(client)["memories"]) == (1 if ok else 0))


@pytest.mark.parametrize("text,kept", [
    ("Likes walking by the lake", True),
    ("Takes sertraline 50 mg in the morning", False),
    ("The TMS sessions were on Mondays", False),
    ("Has been feeling depressed lately", False),
    ("Therapy on Thursdays helps", False),
    ("Thursdays with Maija help", True),
    ("Their watch says they slept badly", False),
])
def test_health_details_are_never_kept(client, text, kept):
    r = tool(client, "remember", {"category": "what_helps", "text": text})
    assert r["ok"] is kept
    assert (text in [m["text"] for m in mems(client)["memories"]]) is kept


def test_remember_off_is_respected_and_reversible(client):
    tool(client, "remember", {"category": "likes", "text": "Likes rain"})
    assert client.put("/v1/me/memory_settings?home_id=h1", json={"remember": False}).status_code == 200
    r = tool(client, "remember", {"category": "likes", "text": "Likes snow"})
    assert not r["ok"] and "off" in r["error"]
    assert mems(client)["remember"] is False
    card = session(client, "h1", "iphone")["context_card"]
    assert card["dont_remember"] and card["memories"] == []
    client.put("/v1/me/memory_settings?home_id=h1", json={"remember": True})
    assert tool(client, "remember", {"category": "likes", "text": "Likes snow"})["ok"]


def test_dont_remember_things_turns_remembering_off(client):
    r = tool(client, "remember", {"category": "preference", "text": "Please don't remember things"})
    assert r["result"]["action"] == "remember_off" and mems(client)["remember"] is False
    assert not tool(client, "remember", {"category": "likes", "text": "Likes rain"})["ok"]


def test_finnish_text_stored_and_recalled(client):
    tool(client, "remember", {"category": "places", "text": "Tykkää kävellä järven rannalla"})
    tool(client, "remember", {"category": "people", "text": "Sisko on Maija"})
    assert "Tykkää kävellä järven rannalla" in [m["text"] for m in mems(client)["memories"]]
    for topic in ("järven", "jarven"):
        assert tool(client, "recall", {"topic": topic})["result"]["memories"] == ["Tykkää kävellä järven rannalla"]


def test_crisis_phrase_through_tool_writes_no_memory(client):
    r = tool(client, "remember", {"category": "likes", "text": "Sometimes I want to die"})
    assert r["crisis"] and not r["ok"] and "112" in r["result"]["script"] and r["result"]["stop_session"]
    assert mems(client)["memories"] == []
    flags = [e for e in client.get("/v1/events?home_id=h1").json()["events"] if e["type"] == "obs.safety_flag"]
    assert len(flags) == 1 and flags[0]["source"] == "cloud" and flags[0]["payload"]["trigger"] == "phrase"
    # near-identical, harmless text is just a memory
    assert tool(client, "remember", {"category": "likes", "text": "Wants to dye their hair blue"})["ok"]
    # Finnish crisis phrase inside another tool's args
    assert tool(client, "recall", {"topic": "en jaksa enää"})["crisis"]


def test_plans_expire_after_seven_days(client):
    store = client.app.state.store
    memory.remember(store, "h1", "plans", "Visit the lake on Saturday", NOW - timedelta(days=6))
    memory.remember(store, "h1", "plans", "Call Maija about the cabin", NOW - timedelta(days=8))
    memory.remember(store, "h1", "likes", "Likes the old cabin", NOW - timedelta(days=30))  # not a plan: stays
    texts = [m["text"] for m in memory.listing(store, "h1", NOW)]
    assert texts == ["Visit the lake on Saturday", "Likes the old cabin"]


def test_recall_prefers_relevant_memory_for_intent(client):
    store = client.app.state.store
    memory.remember(store, "h1", "places", "Likes walking by the lake", NOW - timedelta(days=5))
    memory.remember(store, "h1", "people", "Brother Eetu lives in Tampere", NOW - timedelta(days=1))  # newer
    walk = memory.recall(store, "h1", "", intent="walk", fill=True, now=NOW)
    assert walk[0]["text"] == "Likes walking by the lake"
    assert memory.recall(store, "h1", "Eetu", now=NOW)[0]["text"].startswith("Brother Eetu")
    assert memory.recall(store, "h1", "piano", now=NOW) == []  # recall without fill: only matches


def test_delete_one_and_all_memories(client):
    for t in ("Likes rain", "Likes snow"):
        tool(client, "remember", {"category": "likes", "text": t})
    first = mems(client)["memories"][0]["id"]
    assert client.delete(f"/v1/me/memories/{first}?home_id=h1").json() == {"deleted": 1}
    assert client.delete(f"/v1/me/memories/{first}?home_id=h1").status_code == 404
    assert client.delete(f"/v1/me/memories/{first + 1}?home_id=other").status_code == 404  # other home's id
    assert client.delete("/v1/me/memories?home_id=h1").json() == {"deleted": 1}


def test_clinicians_never_see_memories(cohort):
    tool(cohort, "remember", {"category": "people", "text": "Neighbour Ritva bakes pulla"}, home="sim-eero")
    for path in ("/v1/patients", "/v1/patients/sim-eero/consensus", "/v1/patients/sim-eero/timeline",
                 "/v1/patients/sim-eero/phq9", "/v1/events?home_id=sim-eero"):
        assert "Ritva" not in cohort.get(path).text, path


# ---------------------------------------------------------------- tools: surface + schema
def test_tool_surface_and_args_checks(client):
    assert tool(client, "look_at_this", surface="robot")["error"] == "not on this surface"
    assert tool(client, "look_at_this", surface="glasses")["executor"] == "device"
    assert not tool(client, "record_dial", {"item": "mood", "value": 9})["ok"]
    assert tool(client, "record_dial", {"item": "mood", "value": 3})["ok"]
    assert tool(client, "teleport")["error"] == "unknown tool"
    assert tool(client, "suggest_nudge")["result"]["suggestion"]


# ---------------------------------------------------------------- open thread across surfaces
def test_thread_from_robot_shows_on_glasses_until_closed(client):
    robot = session(client, "h1", "robot", "ritual")
    r = tool(client, "end_session", {"outcome": "completed",
                                     "follow_up": {"skill": "walk_companion", "topic": "the walk by the lake"}},
             session_id=robot["session_id"])
    assert r["ok"] and r["result"]["closed"]
    glasses = session(client, "h1", "glasses", "walk")
    assert glasses["context_card"]["open_thread"] == "the walk by the lake"
    assert "the walk by the lake" in today_section(glasses["system_instruction"])
    # an ended-early walk keeps it open; a completed one closes it
    tool(client, "end_session", {"outcome": "ended_early"}, surface="glasses", session_id=glasses["session_id"])
    again = session(client, "h1", "glasses", "walk")
    assert again["context_card"]["open_thread"] == "the walk by the lake"
    tool(client, "end_session", {"outcome": "completed"}, surface="glasses", session_id=again["session_id"])
    assert session(client, "h1", "iphone")["context_card"]["open_thread"] is None
    ep = client.app.state.store.episode(again["session_id"])
    assert ep["outcome"] == "completed" and ep["tools"] == ["end_session"]


def test_thread_expires_and_others_present_hides_it(client):
    store = client.app.state.store
    memory.open_thread(store, "h1", "breathe", "the slow breaths", NOW - timedelta(days=4))
    assert memory.current_thread(store, "h1", NOW) is None
    memory.open_thread(store, "h1", "breathe", "the slow breaths", NOW - timedelta(days=2))
    assert memory.current_thread(store, "h1", NOW)["topic"] == "the slow breaths"
    assert session(client, "h1", "robot", others_present=True)["context_card"]["open_thread"] is None


def test_episode_endpoint_idempotent_and_opens_thread(client):
    body = {"home_id": "h1", "surface": "iphone", "intent": "checkin", "id": "ep-1",
            "start": "2026-11-12T08:00:00Z", "end": "2026-11-12T08:03:00Z", "tools_used": ["record_dial"],
            "outcome": "offline", "open_thread": {"skill": "weather_check", "topic": "the cabin weekend"}}
    assert client.post("/v1/companion/episode", json=body).json() == {"ok": True, "id": "ep-1", "transcript_stored": False}
    assert client.post("/v1/companion/episode", json=body).status_code == 200
    assert len(client.app.state.store.episodes("h1")) == 1
    bad = body | {"id": "ep-2", "open_thread": {"skill": "weather_check", "topic": "the medication change"}}
    assert client.post("/v1/companion/episode", json=bad).status_code == 422
    assert client.post("/v1/companion/episode", json=body | {"home_id": "h2"}).status_code == 422


@pytest.mark.parametrize("close_thread", [False, True])
def test_completed_episode_retries_preserve_newer_cross_device_thread_after_restart(client, close_thread):
    now = datetime.now(UTC)
    body = {"home_id": "h1", "surface": "robot", "intent": "ritual", "id": "durable-thread-episode",
            "start": (now - timedelta(minutes=1)).isoformat(), "end": now.isoformat(), "outcome": "completed",
            "close_thread": close_thread, "open_thread": {"skill": "walk_companion", "topic": "the lake walk"}}
    assert client.post("/v1/companion/episode", json=body).status_code == 200
    store = client.app.state.store
    initial = memory.current_thread(store, "h1", now)
    assert initial["topic"] == "the lake walk"
    assert client.post("/v1/companion/episode", json=body).status_code == 200
    assert memory.current_thread(store, "h1", now)["id"] == initial["id"]
    newer = memory.open_thread(store, "h1", "walk_companion", "the phone's next walk", now)
    restarted = TestClient(create_app(client.app.state.settings))
    assert restarted.post("/v1/companion/episode", json=body).status_code == 200
    assert memory.current_thread(restarted.app.state.store, "h1", now)["id"] == newer


def test_tool_completion_and_device_upload_share_thread_phases(client):
    now = datetime.now(UTC)
    robot = session(client, "h1", "robot", "ritual")
    follow_up = {"skill": "walk_companion", "topic": "the lake walk"}
    first = tool(client, "end_session", {"outcome": "completed", "follow_up": follow_up},
                 session_id=robot["session_id"])
    store = client.app.state.store
    first_thread = first["result"]["thread_id"]
    newer = memory.open_thread(store, "h1", "walk_companion", "the phone's next walk", now)
    body = {"home_id": "h1", "surface": "robot", "intent": "ritual", "id": robot["session_id"],
            "start": now.isoformat(), "outcome": "completed", "open_thread": follow_up}
    assert client.post("/v1/companion/episode", json=body).status_code == 200
    replay = tool(client, "end_session", {"outcome": "completed", "follow_up": follow_up},
                  session_id=robot["session_id"])
    assert replay["result"]["thread_id"] == first_thread
    assert memory.current_thread(store, "h1", now)["id"] == newer


def test_later_completion_can_apply_close_phase_without_reopening_follow_up(client):
    now = datetime.now(UTC)
    body = {"home_id": "h1", "surface": "iphone", "intent": "checkin", "id": "two-phase-episode",
            "start": now.isoformat(), "outcome": "ended_early",
            "open_thread": {"skill": "walk_companion", "topic": "the lake walk"}}
    assert client.post("/v1/companion/episode", json=body).status_code == 200
    store = client.app.state.store
    follow_up_id = memory.current_thread(store, "h1", now)["id"]
    # A later completion closes a weather-check thread, but must not replay its previously opened walk.
    newer = memory.open_thread(store, "h1", "walk_companion", "the next phone walk", now)
    body["outcome"] = "completed"
    assert client.post("/v1/companion/episode", json=body).status_code == 200
    assert newer != follow_up_id and memory.current_thread(store, "h1", now)["id"] == newer


# ---------------------------------------------------------------- routines (count rule)
def _walks(store, days):
    for i, d in enumerate(days):
        start = datetime.combine(d, datetime.min.time(), TZ).replace(hour=17)
        record_episode(store, EpisodeIn(home_id="h1", surface="glasses", intent="walk", id=f"w{i}", start=start,
                                        end=start + timedelta(minutes=25), outcome="completed"))


def test_three_tuesday_walks_make_a_routine(client):
    store = client.app.state.store
    tuesdays = [(NOW - timedelta(days=2 + 7 * k)).date() for k in range(3)]  # NOW is Thursday
    assert all(d.weekday() == 1 for d in tuesdays)
    _walks(store, tuesdays)
    assert memory.routines(store, "h1", NOW, TZ) == ["usually walks on Tuesdays"]
    card = card_mod.build_card(store, client.app.state.settings, "h1", intent="walk", now=NOW)
    assert card.routines == ["usually walks on Tuesdays"]


def test_two_tuesdays_or_mixed_days_are_not_a_routine(client):
    store = client.app.state.store
    _walks(store, [(NOW - timedelta(days=2 + 7 * k)).date() for k in range(2)]
           + [(NOW - timedelta(days=3)).date()])  # 2 Tuesdays + a Monday
    assert memory.routines(store, "h1", NOW, TZ) == []


# ---------------------------------------------------------------- done today, any surface
def test_done_today_from_obs_and_episodes():
    ts = NOW.isoformat().replace("+00:00", "Z")
    events = [{"type": "obs.self_report", "source": "phone", "ts": ts, "payload": {"item": "mood", "channel": "phone"}},
              {"type": "obs.self_report", "source": "phone", "ts": ts, "payload": {"item": "sleep", "channel": "phone"}},
              {"type": "obs.outing", "source": "glasses", "ts": ts, "payload": {"minutes": 20}},
              {"type": "obs.play_session", "source": "phone", "ts": ts, "payload": {"game": "pebbles"}},
              {"type": "obs.outing", "source": "glasses", "ts": "2026-11-01T09:00:00Z", "payload": {"minutes": 20}}]
    eps = [{"intent": "talk", "surface": "mac", "outcome": "completed", "start": NOW.isoformat()}]
    assert card_mod.done_today(events, eps, NOW) == ["a weather check on the phone", "a walk on the glasses",
                                                     "the pebbles game on the phone", "a chat on the computer"]


# ---------------------------------------------------------------- live token
def test_live_setup_locks_kaiku_and_turns_on_continuous_vad(cohort):
    j = session(cohort, "demo-aino", "iphone")
    s = j["live_setup"]  # Kaiku's recommended setup, built even without a key (the token locks only the model)
    assert s["model"] == "models/gemini-3.8-live"
    assert s["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == j["voice"]
    assert s["systemInstruction"]["parts"][0]["text"] == j["system_instruction"]
    ric = s["realtimeInputConfig"]
    assert ric["automaticActivityDetection"]["disabled"] is False  # Gemini takes turns: continuous conversation
    assert ric["activityHandling"] == "START_OF_ACTIVITY_INTERRUPTS"  # barge-in
    assert "inputAudioTranscription" in s and "outputAudioTranscription" in s  # the safety gate reads the input
    assert s["inputAudioTranscription"] == {"languageCodes": ["en-US"]}  # her speech is heard as English, not guessed
    assert "the person speaks English" in j["system_instruction"]
    assert live_token.transcription("fi") == {"languageCodes": ["fi-FI"]} and live_token.transcription(None) == {}
    assert "enableAffectiveDialog" not in s["generationConfig"]  # breaks constrained sessions (config/kaiku.toml)
    assert {d["name"] for d in s["tools"][0]["functionDeclarations"]} == {t["name"] for t in j["tools"]}


def test_every_surface_and_intent_hears_english_through_the_one_setup(cohort):
    """Robot, iPhone, Mac and glasses, every intent and the walk (proactive audio, camera frames): one builder
    (`live_token.setup` in `open_session`), so none of them is left on automatic language detection."""
    from kaiku_contracts.api import CompanionSessionRequest
    fields = CompanionSessionRequest.model_fields
    surfaces, intents = fields["surface"].annotation.__args__, fields["intent"].annotation.__args__
    assert {"robot", "iphone", "mac", "glasses"} <= set(surfaces)
    seen = 0
    for surface in surfaces:
        for intent in intents:
            r = cohort.post("/v1/companion/session", json={"home_id": "demo-aino", "surface": surface, "intent": intent})
            if r.status_code != 200:
                continue  # a pair the cloud does not offer (answered 4xx): no session, nothing to hear
            seen += 1
            j = r.json()
            assert j["live_setup"]["inputAudioTranscription"] == {"languageCodes": ["en-US"]}, (surface, intent)
            assert "the person speaks English" in j["system_instruction"], (surface, intent)
    walk = session(cohort, "demo-aino", "glasses", "walk", purpose="walk")
    assert walk["live_setup"]["proactivity"] == {"proactiveAudio": True}
    assert walk["live_setup"]["inputAudioTranscription"] == {"languageCodes": ["en-US"]}
    assert seen >= len(surfaces)


def test_live_token_none_without_key():
    assert live_token.mint("gemini-3.8-live", api_key="") is None


def test_live_token_minted_with_mock_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("KAIKU_SPEND_DB", str(tmp_path / "spend.sqlite"))
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"], seen["key"] = json.loads(req.content), req.headers["x-goog-api-key"]
        return httpx.Response(200, json={"name": "auth_tokens/abc"})

    t = live_token.mint("gemini-3.8-live", api_key="k", now=NOW, transport=httpx.MockTransport(handler))
    assert t.token == "auth_tokens/abc" and t.expires_at == NOW + timedelta(minutes=5)
    assert seen["key"] == "k" and seen["body"]["uses"] == 1
    assert seen["body"]["bidiGenerateContentSetup"]["model"] == "models/gemini-3.8-live"
    assert seen["body"]["fieldMask"] == "model"  # lock only the model, never the device's setup
    assert "liveConnectConstraints" not in seen["body"]  # the SDK's name: the REST API answers 400
    down = httpx.MockTransport(lambda r: httpx.Response(500))
    assert live_token.mint("gemini-3.8-live", api_key="k", transport=down) is None
