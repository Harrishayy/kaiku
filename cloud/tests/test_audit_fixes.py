"""Audit fixes of 2026-11-15: a reset limited to one home, the crisis gate strictly first, the wording check on
both explanation paths, /v1/me for a new person, crisis contacts from config, no sleep after the last TTS try."""

from types import SimpleNamespace

from kaiku_cloud import service, voice
from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate
from kaiku_cloud.llm import explain
from kaiku_cloud.llm.template import template_explanation
from kaiku_cloud.settings import Settings
from kaiku_contracts import make
from kaiku_contracts.config import get

PATIENT = {p.home_id: p for p in DEMO_PATIENTS}


def seed(client, *homes):
    for h in homes:
        ev = generate(PATIENT[h])
        for i in range(0, len(ev), 400):
            r = client.post("/v1/events", json={"events": ev[i:i + 400]})
            assert r.status_code == 200 and not r.json()["rejected"], r.text


def tool(c, name, args=None, home="h1", surface="robot", session_id=None):
    r = c.post("/v1/companion/tool", json={"home_id": home, "surface": surface, "name": name, "args": args or {},
                                           "session_id": session_id})
    assert r.status_code == 200, r.text
    return r.json()


def mems(c, home):
    return [m["text"] for m in c.get(f"/v1/me/memories?home_id={home}").json()["memories"]]


# ---------------------------------------------------------------- 1. reset of one home
def test_reset_of_one_home_touches_only_that_home(client):
    store = client.app.state.store
    seed(client, "sim-onni", "sim-eero")
    assert tool(client, "remember", {"category": "likes", "text": "Likes the sauna"}, home="sim-onni")["ok"]
    # a second home with a memory and NO events, plus kv rows of both homes
    assert tool(client, "remember", {"category": "likes", "text": "Likes snow"}, home="quiet-home")["ok"]
    for home in ("sim-onni", "quiet-home"):
        store.kv_set(f"affect:{home}", {"e1": {"level": "low"}})
        store.kv_set(f"feel:{home}", {"s1": {"start": "x"}})
        store.kv_set(f"phq9_due:{home}:never", True)
        store.save_explanation(home, "hash", {"headline": "h"})
    with store._lock:
        for home in ("sim-onni", "quiet-home"):
            store._db.execute("INSERT INTO transcripts(episode_id,home_id,surface,intent,start,turns) VALUES"
                              " (?,?,?,?,?,?)", (f"ep-{home}", home, "robot", "talk", "2026-11-14T08:00:00Z", "[]"))
            store._db.execute("INSERT INTO kg_nodes(home_id,type,label,norm,origin,updated) VALUES (?,?,?,?,?,?)",
                              (home, "like", "Audit", "audit-node", "self", "2026-11-14T08:00:00Z"))
            store._db.execute("INSERT INTO kg_edges(home_id,src,dst,rel,weight,updated) VALUES (?,?,?,?,?,?)",
                              (home, 901, 902, "likes", 1.0, "2026-11-14T08:00:00Z"))
            store._db.execute("INSERT INTO embeddings(home_id,ref,model,text_hash,vector) VALUES (?,?,?,?,?)",
                              (home, "kg:901", "m", "h", b"0"))

    assert client.post("/v1/admin/reset", params={"home_id": "sim-onni"}).json()["deleted"] > 0

    assert [p["id"] for p in client.get("/v1/patients").json()["patients"]] == ["sim-eero"]
    assert mems(client, "sim-onni") == [] and mems(client, "quiet-home") == ["Likes snow"]
    with store._lock:
        for table in ("transcripts", "kg_nodes", "kg_edges", "embeddings", "memories", "episodes", "explanations"):
            left = {r[0] for r in store._db.execute(f"SELECT DISTINCT home_id FROM {table}")}
            assert "sim-onni" not in left, table
        for table in ("transcripts", "kg_nodes", "kg_edges", "embeddings", "memories", "explanations"):
            assert store._db.execute(f"SELECT 1 FROM {table} WHERE home_id='quiet-home'").fetchone(), table
    for key in ("affect", "feel"):
        assert store.kv_get(f"{key}:sim-onni") is None and store.kv_get(f"{key}:quiet-home") is not None
    assert store.kv_get("phq9_due:sim-onni:never") is None and store.kv_get("phq9_due:quiet-home:never") is True


def test_full_reset_still_clears_homes_without_events(client):
    seed(client, "sim-onni")
    assert tool(client, "remember", {"category": "likes", "text": "Likes snow"}, home="quiet-home")["ok"]
    assert client.post("/v1/admin/reset").json()["deleted"] > 0
    assert client.get("/v1/patients").json()["patients"] == [] and mems(client, "quiet-home") == []


# ---------------------------------------------------------------- 2. crisis gate strictly first
def test_crisis_phrase_with_another_homes_session_still_raises_the_flag(client):
    store = client.app.state.store
    sid = client.post("/v1/companion/session", json={"home_id": "h1", "surface": "robot"}).json()["session_id"]
    r = tool(client, "remember", {"category": "likes", "text": "Sometimes I want to die"}, home="h2", session_id=sid)
    assert r["crisis"] and r["result"]["stop_session"] and get("safety", "emergency_number") in r["result"]["script"]
    flags = [e for e in client.get("/v1/events?home_id=h2").json()["events"] if e["type"] == "obs.safety_flag"]
    assert len(flags) == 1
    assert store.episode(sid)["outcome"] is None  # the other home's conversation is not touched
    # ... and on another surface of the same home
    r = tool(client, "recall", {"topic": "I want to die"}, home="h1", surface="iphone", session_id=sid)
    assert r["crisis"] and store.episode(sid)["outcome"] == "crisis"


def test_later_call_on_a_crisis_session_gets_the_script_in_the_sessions_language(client):
    store = client.app.state.store
    sid = client.post("/v1/companion/session", json={"home_id": "h1", "surface": "robot"}).json()["session_id"]
    assert tool(client, "recall", {"topic": "I want to die"}, session_id=sid)["crisis"]
    gate = SimpleNamespace(check=lambda text: None, script=lambda lang: f"script in {lang}")
    from kaiku_cloud.mind import session as mind

    store.kv_set(mind._lang_key(sid), "fi")
    original = mind._gate
    mind._gate = lambda: gate
    try:
        r = tool(client, "recall", {"topic": "the lake"}, session_id=sid)
    finally:
        mind._gate = original
    assert r["crisis"] and r["result"]["script"] == "script in fi"


# ---------------------------------------------------------------- 3. wording check on both explanation paths
def _ctx(state="needs_call", **kw):
    sources = [{"source": s, "verdict": "worse" if s == "robot" else "as_usual", "evidence": [
        {"metric": "mood", "summary": "Mood lower than usual"}] if s == "robot" else []}
        for s in ("robot", "glasses", "laptop", "wearable")]
    return {"display_name": "Aino", "state": state, "agreement": "disagree", "sources": sources, "notes": [],
            "home_id": "demo-aino", **kw}


GOOD = '{"source_order": ["robot", "laptop", "wearable", "glasses"], "focus_metrics": []}'


def test_gemma_ordered_explanation_is_checked_for_banned_wording(monkeypatch):
    calls = []
    monkeypatch.setitem(explain.BACKENDS, "gemma_hosted", lambda prompt: calls.append(1) or GOOD)
    assert explain.make_explanation(_ctx(), Settings(llm="gemma_hosted")).by == "gemma"
    calls.clear()
    monkeypatch.setattr(explain, "BANNED", (*explain.BANNED, "mood lower"))  # only in the evidence summary
    ex = explain.make_explanation(_ctx(), Settings(llm="gemma_hosted"))
    assert ex.by == "template" and len(calls) == 2  # checked, retried once, then the template
    assert explain.contains_banned(ex.model_dump_json()) is None  # ... without the offending evidence line


def test_template_that_fails_the_wording_check_is_logged_not_raised(monkeypatch):
    monkeypatch.setattr(explain, "BANNED", ("aino",))  # nothing can remove the name: returned, never an error
    assert explain.make_explanation(_ctx(), Settings(llm="template")).by == "template"


def test_backend_registered_only_in_backends_needs_no_model_key(monkeypatch):
    monkeypatch.setitem(explain.BACKENDS, "custom", lambda prompt: GOOD)
    ex = explain.make_explanation(_ctx(), Settings(llm="custom"))
    assert ex.by == "gemma" and ex.model == "custom"
    monkeypatch.setitem(explain.BACKENDS, "custom", lambda prompt: "not json")
    assert explain.make_explanation(_ctx(), Settings(llm="custom")).by == "template"  # no KeyError on the way


# ---------------------------------------------------------------- 4, 5, 8. /v1/me
def test_me_does_not_tell_a_new_person_that_something_changed(client):
    assert client.get("/v1/me", params={"home_id": "nobody-yet"}).json()["summary"] == service.ME_FORMING
    ev = make("obs.self_report", {"item": "mood", "value": 3}, source="hub", home_id="young")
    client.post("/v1/events", json={"events": [ev.model_dump(mode="json", exclude_none=True)]})
    assert client.get("/v1/me", params={"home_id": "young"}).json()["summary"] == service.ME_FORMING


def test_me_summary_rules():
    worse = {"summary": {"state": "watch", "agreement": "low_coverage", "sources": [{"verdict": "worse"}]}}
    assert service.me_summary(worse) == service.ME_STATE["watch"]  # one source, away from usual: not "forming"
    agree = {"summary": {"state": "watch", "agreement": "agree", "sources": []}}
    assert service.me_summary(agree) == service.ME_STATE["watch"]
    assert service.me_summary({"summary": {"state": "stable"}}) == service.ME_STATE["stable"]
    safety = service.me_summary({"summary": {"state": "safety", "agreement": "low_coverage"}})
    for key in ("helpline_name", "helpline_number", "emergency_number"):
        assert get("safety", key) in safety


def test_me_makes_no_causal_claim_about_breathing(client):
    seed(client, "demo-aino", "sim-eero")
    for home in ("demo-aino", "sim-eero"):
        text = " ".join(client.get("/v1/me", params={"home_id": home}).json()["last_week"]).lower()
        assert "calmed" not in text and "hrv" not in text


# ---------------------------------------------------------------- 8. safety explanation says only what the flag says
def test_safety_explanation_says_shown_only_when_handled_locally(client):
    shown = template_explanation(_ctx("safety", safety_handled_locally=True)).text
    assert f"was shown the {get('safety', 'helpline_name')} and {get('safety', 'emergency_number')}" in shown
    raised = template_explanation(_ctx("safety")).text
    assert "was shown the" not in raised and "contact them today" in raised
    # end to end: the seeded PHQ-9 flag was handled on the device, a phrase caught by the cloud was not
    seed(client, "sim-lauri")
    assert "was shown the" in client.get("/v1/patients/sim-lauri/consensus").json()["explanation"]["text"]
    assert tool(client, "recall", {"topic": "I want to die"}, home="h9")["crisis"]
    text = client.get("/v1/patients/h9/consensus").json()["explanation"]["text"]
    assert "was shown the" not in text and "contact them today" in text


# ---------------------------------------------------------------- 6. TTS: no sleep after the last attempt
def test_tts_does_not_sleep_after_the_last_failed_attempt(monkeypatch):
    from kaiku_contracts import budget, genai_client

    def fail(**kwargs):
        raise OSError("synthetic provider unavailable")

    sleeps = []
    monkeypatch.setattr(genai_client, "available", lambda: True)
    monkeypatch.setattr(genai_client, "backend", lambda: "developer")
    monkeypatch.setattr(genai_client, "make_client", lambda **kw: SimpleNamespace(
        interactions=SimpleNamespace(create=fail)))
    monkeypatch.setattr(budget, "charge", lambda *a, **kw: None)
    monkeypatch.setattr(voice.time, "sleep", sleeps.append)
    try:
        voice.synthesize("Good morning.", "warm", "en")
    except voice.VoiceUnavailable as e:
        assert "OSError" in str(e)
    else:
        raise AssertionError("expected VoiceUnavailable")
    assert sleeps == [0.5]  # between the two attempts only
