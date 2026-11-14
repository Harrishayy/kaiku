"""Plan 02: /v1/me mascot + highlights + garden, and the /v1/voice endpoints (no TTS key in tests)."""

from datetime import UTC, date, datetime, timedelta

import pytest
from kaiku_cloud import companion, voice
from kaiku_cloud.jobs.synth import DEMO_PATIENTS, generate
from kaiku_cloud.llm.explain import BANNED
from kaiku_contracts import make
from kaiku_contracts.criteria import load_criteria

PATIENT = {p.home_id: p for p in DEMO_PATIENTS}


def seed(client, *homes):
    for h in homes:
        ev = generate(PATIENT[h])
        for i in range(0, len(ev), 400):
            r = client.post("/v1/events", json={"events": ev[i:i + 400]})
            assert r.status_code == 200 and not r.json()["rejected"], r.text


@pytest.mark.parametrize("state,hour,recent,mood,key", [
    ("stable", 8, False, "idle", "greet.morning"),
    ("stable", 15, True, "happy", "greet.afternoon"),
    ("stable", 1, False, "idle", "greet.night"),
    ("watch", 20, True, "cozy", "checkin.cozy"),
    ("needs_call", 9, True, "cozy", "needs_call.offer"),
    ("safety", 9, True, "crisis", None),
])
def test_mascot_is_a_pure_function_of_state(state, hour, recent, mood, key):
    m = companion.mascot_for(state, hour, recent)
    assert (m.mood, m.line_key) == (mood, key)


def test_every_mascot_line_and_person_text_is_safe():
    keys = set(voice.all_lines())
    for state in ("stable", "watch", "needs_call"):
        for hour in range(24):
            assert companion.mascot_for(state, hour, False).line_key in keys
    texts = [t for v in voice.all_lines().values() for k, t in v.items() if k != "style"]
    texts += [m.person_hard for m in load_criteria().metrics if m.person_hard] + list(companion.PLAY_TEXT.values())
    for t in texts:
        assert not any(b in t.lower() for b in BANNED), t
    for v in voice.all_lines().values():
        assert {"en", "fi", "sv"} <= set(v), v


def _ev(type_, payload, day, source="hub", hour=10):
    ts = datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=hour)
    return make(type_, payload, source=source, home_id="h", ts=ts).model_dump(mode="json", exclude_none=True)


def test_garden_counts_and_rests():
    today = date(2026, 11, 14)
    ev = [_ev("obs.outing", {"minutes": 20, "method": "location"}, today - timedelta(days=4), "glasses"),
          *[_ev("obs.self_report", {"item": i, "value": 4, "channel": "phone"}, today - timedelta(days=5), "phone")
            for i in ("mood", "energy", "sleep")],  # one weather check = one plant
          _ev("obs.drum_session", {"tempo_bpm": 90, "force_mean": 0.5, "duration_s": 30, "regularity": 0.8, "taps": 40},
              today - timedelta(days=20))]  # older than 14 days
    g = companion.garden_for(ev, today)
    assert g.plants == 2 and g.resting is True
    assert companion.garden_for(ev, today - timedelta(days=4)).resting is False
    assert companion.garden_for([], today).resting is False
    days = g.days
    assert len(days) == 14 and days[-1].date == today and days[0].date == today - timedelta(days=13)
    by = {d.date: d for d in days}
    assert by[today - timedelta(days=4)].kinds == ["outing"] and by[today - timedelta(days=5)].count == 1
    assert sum(d.count for d in days) == g.plants


def test_me_has_companion_fields_for_seeded_patients(client):
    seed(client, "demo-aino", "sim-eero")
    aino = client.get("/v1/me", params={"home_id": "demo-aino"}).json()
    assert aino["mascot"] == {"mood": "cozy", "line_key": "needs_call.offer"}
    assert aino["garden"]["plants"] > 0
    kinds = {h["kind"] for h in aino["highlights"]}
    assert "good" in kinds and "hard" in kinds  # Aino's later nights show as gentle notes
    assert sum(h["kind"] == "hard" for h in aino["highlights"]) <= companion.MAX_HARD
    dates = [h["date"] for h in aino["highlights"]]
    assert dates == sorted(dates, reverse=True)
    eero = client.get("/v1/me", params={"home_id": "sim-eero"}).json()
    assert eero["mascot"]["mood"] in ("idle", "happy")
    assert not any(h["source"] == "wearable" for h in eero["highlights"])  # no watch, nothing missing
    empty = client.get("/v1/me", params={"home_id": "nobody"}).json()
    assert {k: empty["garden"][k] for k in ("plants", "resting")} == {"plants": 0, "resting": False} and empty["highlights"] == []


def test_voice_lines_and_fail_soft_audio(client, monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("KAIKU_VOICE_CACHE", str(tmp_path))
    body = client.get("/v1/voice", params={"lang": "fi"}).json()
    assert body["lang"] == "fi" and body["voice"] and "greet.morning" in body["lines"]
    assert client.get("/v1/voice", params={"lang": "de"}).status_code == 422
    assert client.get("/v1/voice/nope.nope").status_code == 404
    r = client.get("/v1/voice/greet.morning", params={"lang": "en"})
    assert r.status_code == 503 and "hint" in r.json()
    # a cached render is served without any key (pre-rendered demo works offline)
    path = voice.cache_path("greet.morning", "en")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF....WAVE")
    r = client.get("/v1/voice/greet.morning", params={"lang": "en"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content.startswith(b"RIFF")


def test_voice_say_dynamic_line_cached_and_never_crisis(client, monkeypatch, tmp_path):
    monkeypatch.setenv("KAIKU_VOICE_CACHE", str(tmp_path))
    calls = []

    def fake(text, style, lang):
        calls.append((text, lang))
        return b"RIFF" + text.encode()

    monkeypatch.setattr(voice, "synthesize", fake)
    r = client.post("/v1/voice/say", json={"text": "I'm  back.\nShall we carry on?", "lang": "fi"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert client.post("/v1/voice/say", json={"text": "I'm back. Shall we carry on?", "lang": "fi"}).content == r.content
    assert calls == [("I'm back. Shall we carry on?", "fi")]  # whitespace-normalised, rendered once, then cached
    assert client.post("/v1/voice/say", json={"text": "", "lang": "en"}).status_code == 422
    assert client.post("/v1/voice/say", json={"text": "x" * 401}).status_code == 422
    assert client.post("/v1/voice/say", json={"text": "I want to kill myself"}).status_code == 422
    assert len(calls) == 1

    def down(*a):
        raise voice.VoiceUnavailable("no key")

    monkeypatch.setattr(voice, "synthesize", down)
    r = client.post("/v1/voice/say", json={"text": "Something new"})
    assert r.status_code == 503 and "hint" in r.json()
