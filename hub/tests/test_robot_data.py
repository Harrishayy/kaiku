"""Robot sensor data -> useful data -> stored: raw-stream edge cases (flat / noisy / flicker / camera pulse, very
fast drumming, silent distance stream), the multi-cue engagement summary and the local session store."""

import asyncio
import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from kaiku_contracts import make, parse_topic
from kaiku_hub.cloudlink import local_nudge
from kaiku_hub.live.base import OffMusic, Voice
from kaiku_hub.main import Hub
from kaiku_hub.perception.engagement import FACE_MAX_SHARE, EngagementTracker, fuse
from kaiku_hub.perception.hrv import PpgBuffer
from kaiku_hub.perception.presence import PresenceTracker
from kaiku_hub.perception.taps import TapAnalyzer
from kaiku_hub.store import SessionStore, list_sessions, open_readonly, read_session

BAND, CLEAN = (0.7, 3.5), 0.7
T0 = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


def feed(buf: PpgBuffer, sig, fs=100.0, batch=25, quality=0.9):
    for i in range(0, len(sig) - batch + 1, batch):
        buf.add(fs, [int(v) for v in sig[i:i + batch]], t0_ms=i / fs * 1000, quality=quality)


# ---------------------------------------------------------------- pulse: measured, or honestly not measured
def test_finger_pulse_is_measured_with_method_and_beats(ppg):
    buf = PpgBuffer()
    feed(buf, ppg([820, 870, 800, 860] * 15))
    payload, quality, pre, post = buf.session(6, 50, BAND, CLEAN)
    assert payload and payload["method"] == "finger" and payload["beats"] > 40 and "rmssd_pre_ms" in payload
    assert quality <= 0.9 and buf.reason == ""


@pytest.mark.parametrize("signal, why", [
    ([16000] * 2000, "flat"),                                                        # unwired / no finger
    (np.random.default_rng(3).normal(16000, 900, 2000), "noise"),                    # noise only
    ([16000 + 600 * math.sin(2 * math.pi * 1.95 * i / 100) for i in range(3000)], "too regular"),  # D39 flicker
])
def test_pulse_not_measured_is_missing_never_guessed(signal, why):
    buf = PpgBuffer()
    feed(buf, signal)
    payload, _q, pre, post = buf.session(6, 30, BAND, CLEAN)
    assert payload is None and pre is None and post is None
    assert why in buf.reason


def test_low_sensor_quality_is_not_measured(ppg):
    buf = PpgBuffer()
    feed(buf, ppg([820, 870] * 30), quality=0.3)
    assert buf.session(6, 50, BAND, CLEAN)[0] is None and "sensor quality" in buf.reason


def test_camera_backup_gives_heart_rate_only_at_wobbling_frame_rate():
    """~15 Hz with a different measured rate every batch (firmware camera.py): resampled, HR only, quality <= 0.6."""
    rng = np.random.default_rng(1)
    buf, t = PpgBuffer(), 0.0
    for _ in range(40):
        fs = round(15 + rng.uniform(-1.2, 1.2), 2)
        n = int(round(fs))
        ts = t + np.arange(n) / fs
        samples = (12000 + 40 * np.sin(2 * np.pi * 1.1 * ts) + rng.normal(0, 2, n)).astype(int).tolist()  # 66 bpm
        buf.add(fs, samples, t0_ms=t * 1000, quality=0.6)
        t += n / fs
    assert buf.restarts == 0 and buf.method == "camera"
    payload, quality, pre, post = buf.session(6, 40, BAND, CLEAN)
    assert payload and payload["method"] == "camera" and payload["hr_bpm"] == pytest.approx(66, abs=4)
    assert "rmssd_pre_ms" not in payload and "rmssd_post_ms" not in payload and quality <= 0.6
    assert pre.rmssd_ms is None and post.rmssd_ms is None


def test_switch_from_finger_to_camera_restarts_and_never_mixes(ppg):
    buf = PpgBuffer()
    feed(buf, [16000] * 400)                      # flat KY-039 for 4 s ...
    buf.add(15.0, [12000] * 15, t0_ms=99_000, quality=0.6)   # ... then the UNO Q falls back to the camera
    assert buf.method == "camera" and buf.seconds == pytest.approx(1.0) and buf.quality == 0.6 and buf.restarts == 1


# ---------------------------------------------------------------- drum
def test_drum_features_show_change_over_the_session():
    taps, t = TapAnalyzer(), 0.0
    for i in range(30):
        taps.add(int(t))
        t += 600 - 10 * i  # speeds up from 100 to ~190 bpm
    s = taps.summary((taps.times[-1] - taps.times[0]) / 1000)
    assert s["tempo_end_bpm"] > s["tempo_start_bpm"] + 30 and s["pauses"] == 0 and s["rejected_taps"] == 0
    assert s["taps_per_s"] == pytest.approx(30 / s["duration_s"], abs=0.01) and s["force_mean"] is None
    assert taps.quality() == 1.0
    make("obs.drum_session", {k: v for k, v in s.items() if v is not None}, source="hub")


def test_very_fast_drumming_is_capped_and_flagged_low_quality():
    taps = TapAnalyzer(refractory_ms=80)
    for i in range(100):
        taps.add(i * 45)  # 1333 bpm: faster than the switch resolves
    s = taps.summary(4.5)
    assert s["tempo_bpm"] <= 400 and s["rejected_taps"] == 50 and taps.quality() == 0.25
    make("obs.drum_session", {k: v for k, v in s.items() if v is not None}, source="hub", quality=taps.quality())


def test_short_drum_has_no_made_up_change():
    taps = TapAnalyzer()
    for i in range(5):
        taps.add(i * 500)
    s = taps.summary(2.0)
    assert s["tempo_start_bpm"] is None and s["tempo_end_bpm"] is None and taps.quality() < 1


# ---------------------------------------------------------------- presence (distance comes from the face box)
def test_face_turned_away_briefly_is_not_a_departure_but_silence_is_unknown():
    p = PresenceTracker(near_cm=80, leave_s=6, stale_s=5)
    for i in range(12):
        arrival = p.update(40, T0 + timedelta(seconds=i * 0.2)) or None
        if arrival:
            break
    assert p.present
    for i in range(20):  # looks down at the drum for 4 s: camera reports far_cm
        p.update(300, T0 + timedelta(seconds=3 + i * 0.2))
    assert p.present
    for i in range(40):
        p.update(300, T0 + timedelta(seconds=7 + i * 0.2))
    assert not p.present and p.visit_s > 0
    q = PresenceTracker(near_cm=80, stale_s=5)
    for i in range(12):
        q.update(40, T0 + timedelta(seconds=i * 0.2))
    assert q.present and not q.expire(T0 + timedelta(seconds=6))
    assert q.expire(T0 + timedelta(seconds=8)) and not q.present  # UNO Q / camera went silent
    assert not q.expire(T0 + timedelta(seconds=9))


# ---------------------------------------------------------------- engagement: no single cue decides
def tracker(**kw) -> EngagementTracker:
    t = EngagementTracker(camera_seen=True)
    for _ in range(kw.get("looks", 0)):
        t.look(kw.get("faces", 1), {"x_norm": 0.0, "y_norm": 0.0, "size": 0.3, "confidence": 0.9})
    return t


def test_face_alone_never_gives_a_level():
    t = tracker(looks=200)
    s = t.summary("s1")
    assert s["cues_available"] == 1 and "level" not in s and s["confidence"] == 0
    make("obs.engagement", s, source="hub")


def test_face_share_is_capped_and_cannot_outvote_the_dial():
    t = tracker(looks=200)                       # face says 1.0 ...
    t.on_obs("obs.self_report", {"item": "mood", "value": 1, "context": "ritual"}, None)
    t.on_obs("obs.self_report", {"item": "energy", "value": 1, "context": "ritual"}, None)  # ... the person says 1/5
    s = t.summary()
    assert s["level"] == pytest.approx(FACE_MAX_SHARE, abs=0.001) and s["agreement"] == 0.0
    make("obs.engagement", s, source="hub")


def test_missing_cues_are_missing_not_zero_and_pulse_is_never_guessed():
    t = EngagementTracker()  # no camera at all
    t.on_obs("obs.self_report", {"item": "mood", "value": 4, "context": "ritual"}, None)
    t.on_obs("obs.self_report", {"item": "mood", "value": 1, "context": "post_activity"}, None)  # not a dial answer
    t.on_obs("obs.drum_session", {"tempo_bpm": 120, "taps": 40, "taps_per_s": 2.0}, 1.0)
    t.hrv_reason = "flat signal"
    s = t.summary()
    by = {c["cue"]: c for c in s["cues"]}
    assert not by["face"]["available"] and by["face"]["basis"] == "no camera data" and "level" not in by["face"]
    assert not by["pulse"]["available"] and "flat signal" in by["pulse"]["basis"]
    assert not by["voice"]["available"] and by["dial"]["level"] == 0.75 and by["dial"]["confidence"] == 0.7
    assert s["cues_available"] == 2 and 0 < s["level"] < 1
    make("obs.engagement", s, source="hub")


def test_two_people_or_a_mostly_absent_face_make_the_face_cue_missing():
    two = tracker(looks=100, faces=2)._face()
    assert not two["available"] and "more than one person" in two["basis"]
    t = tracker(looks=5)
    for _ in range(95):
        t.look(0)
    assert not t._face()["available"]


def test_fusion_is_deterministic_and_three_cues_cap_at_half():
    cues = [{"cue": "dial", "available": True, "level": 1.0, "confidence": 1.0},
            {"cue": "drum", "available": True, "level": 0.0, "confidence": 0.1},
            {"cue": "ritual", "available": True, "level": 0.0, "confidence": 0.1}]
    level, conf, agreement = fuse(cues)
    assert level == 0.5 and agreement == 0.0 and fuse(cues) == (level, conf, agreement)
    assert fuse(cues[:1]) == (None, 0.0, None)


# ---------------------------------------------------------------- local store
def test_store_keeps_raw_numbers_links_obs_and_prunes(tmp_path):
    path = tmp_path / "s.sqlite"
    st = SessionStore(path, retention_days=30)
    st.begin("old", "test", home_id="h", now=T0 - timedelta(days=40))
    st.end(outcome="completed", now=T0 - timedelta(days=40))
    st.begin("s1", "button", home_id="h", sim=True, now=T0)
    st.add_raw(make("raw.head.tap", {"t_ms": 10, "src": "knock"}, source="sensors", sim=True))
    st.add_raw(make("raw.sensors.ppg", {"t0_ms": 0, "fs_hz": 100, "samples": [1, 2, 3]}, source="sensors", quality=0.9))
    st.add_raw(make("obs.ritual", {"step": "dial", "status": "started"}, source="hub"))  # not raw: ignored
    obs = make("obs.drum_session", {"tempo_bpm": 90, "duration_s": 3, "regularity": 0.9, "taps": 5}, source="hub")
    st.add_obs(obs)
    st.end(outcome="completed", episode_id="ep-1", summary={"notes": {"pulse_not_measured": {"reason": "flat"}}})
    st.add_raw(make("raw.head.tap", {"t_ms": 99, "src": "knock"}, source="sensors"))  # outside a session: not kept
    st.close()
    db = open_readonly(path)
    sessions = list_sessions(db)
    assert [s["id"] for s in sessions] == ["s1"]  # the 40-day-old session was pruned when s1 began
    session, samples, linked = read_session(db, "s1")
    assert session["episode_id"] == "ep-1" and session["sim"] and session["outcome"] == "completed"
    assert [r["type"] for r in samples] == ["raw.head.tap", "raw.sensors.ppg"]
    assert samples[1]["payload"]["samples"] == [1, 2, 3] and samples[1]["quality"] == 0.9
    assert [o["id"] for o in linked] == [str(obs.id)]
    text = path.read_bytes()
    assert b"image" not in text and b"audio" not in text


def test_store_size_cap_and_fail_soft(tmp_path):
    st = SessionStore(tmp_path / "s.sqlite", max_mb=0.2)
    for n in range(4):
        st.begin(f"s{n}", "test", now=T0 + timedelta(minutes=n))
        for i in range(300):
            st.add_raw(make("raw.sensors.ppg", {"t0_ms": i, "fs_hz": 100, "samples": list(range(100))}, source="sensors"))
        st.end(outcome="completed")
    st.begin("last", "test", now=T0 + timedelta(hours=1))
    ids = [r[0] for r in st.db.execute("SELECT id FROM sessions ORDER BY started")]
    assert "s0" not in ids and "last" in ids and st.size_mb() <= 0.25
    off = SessionStore(None)
    off.begin("x", "test")
    off.add_raw(make("raw.head.tap", {"t_ms": 1}, source="head"))
    off.end(outcome="completed")
    assert not off.enabled
    bad = SessionStore(tmp_path)  # a directory: cannot open -> disabled, never raises
    assert not bad.enabled and bad.error


# ---------------------------------------------------------------- through the Hub
class QuietVoice(Voice):
    name = "rec"

    def __init__(self):
        self.said, self.verbatim = [], []

    async def say(self, text):
        self.said.append(text)

    async def say_verbatim(self, text):
        self.verbatim.append(text)


@pytest.fixture
def hub(settings):
    s = settings
    s.greet_s, s.dial_s, s.breathe_s, s.drum_s, s.nudge_s, s.post_mood_s, s.drum_idle_end_s = 0.05, 2, 0.3, 2, 0.05, 0.1, 0.15
    return Hub(s, voice=QuietVoice(), music=OffMusic(), read_stdin=False)


async def raw(hub, type_, payload, **kw):
    env = make(type_, payload, source=kw.pop("source", "sensors"), home_id=hub.settings.home_id, **kw)
    kind, *name = type_.split(".")
    await hub.on_raw(parse_topic(f"kaiku/v1/{hub.settings.home_id}/{kind}/{'/'.join(name)}"), env)


async def run_ritual(hub, reason="test"):
    hub.start_ritual(reason)
    for _ in range(100):
        await asyncio.sleep(0.02)
        if hub.machine.state == "dial":
            break
    for value in (4, 3, 2):
        await raw(hub, "raw.head.ear", {"value": value, "delta": 0, "pressed": True}, source="head", sim=True)
    for _ in range(100):
        await asyncio.sleep(0.02)
        if hub.machine.state == "drum":
            break
    for i in range(12):
        await raw(hub, "raw.head.tap", {"t_ms": 1000 + i * 400, "src": "knock"}, sim=True)
    for _ in range(300):
        await asyncio.sleep(0.02)
        if not hub.machine.running:
            break
    await asyncio.sleep(0.05)


async def test_ritual_is_stored_and_summarised_with_every_obs_linked(hub):
    await run_ritual(hub)
    hub.store.flush()
    eng = [e for e in hub.emitted if e.type == "obs.engagement"]
    assert len(eng) == 1 and eng[0].sim and eng[0].quality == eng[0].payload.confidence
    cues = {c.cue: c for c in eng[0].payload.cues}
    assert cues["dial"].available and cues["drum"].available and cues["ritual"].available
    assert not cues["pulse"].available and "not measured" in cues["pulse"].basis   # no PPG arrived: never guessed
    assert not cues["face"].available and not cues["voice"].available
    assert not [e for e in hub.emitted if e.type == "obs.hrv_session"]
    db = open_readonly(hub.settings.store_path)
    (session,) = list_sessions(db)
    _s, samples, linked = read_session(db, session["id"])
    assert session["outcome"] == "completed" and session["sim"] and session["home_id"] == hub.settings.home_id
    assert sum(r["type"] == "raw.head.tap" for r in samples) == 12 and sum(r["type"] == "raw.head.ear" for r in samples) == 3
    assert {o["id"] for o in linked} == {str(e.id) for e in hub.emitted}       # every uplinked obs is linked
    assert session["summary"]["engagement"]["cues_available"] == 3
    assert session["summary"]["notes"]["pulse_not_measured"]["reason"] == "no signal"
    assert hub.uplink.size() == len(hub.emitted)
    drum = next(e for e in hub.emitted if e.type == "obs.drum_session")
    assert drum.payload.taps == 12 and drum.payload.taps_per_s and drum.payload.force_mean is None and drum.quality == 1.0


async def test_no_summary_without_consent_or_after_a_crisis(hub):
    hub.start_ritual("command")          # a cloud invitation nobody accepted: greet times out, skipped
    for _ in range(100):
        await asyncio.sleep(0.02)
        if not hub.machine.running:
            break
    await asyncio.sleep(0.05)
    assert not [e for e in hub.emitted if e.type == "obs.engagement"]
    hub.start_ritual("test")
    await asyncio.sleep(0.2)
    await hub.on_utterance("I want to die")
    await asyncio.sleep(0.1)
    assert [e.type for e in hub.emitted].count("obs.safety_flag") == 1
    assert not [e for e in hub.emitted if e.type == "obs.engagement"]
    hub.store.flush()
    sessions = list_sessions(open_readonly(hub.settings.store_path))
    assert [s["outcome"] for s in sessions] == ["skipped", "crisis"] and all(not s["summary"]["engagement"] for s in sessions)


async def test_raw_outside_a_ritual_is_not_stored_and_store_off_still_works(hub, settings):
    await raw(hub, "raw.sensors.distance", {"cm": 40.0})
    hub.store.flush()
    assert hub.store.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0
    settings.store_path = None
    off = Hub(settings, voice=QuietVoice(), music=OffMusic(), read_stdin=False)
    await run_ritual(off)
    assert [e for e in off.emitted if e.type == "obs.engagement"] and not off.store.enabled


async def test_silent_distance_stream_drops_presence(hub):
    hub.presence.stale = timedelta(seconds=5)
    now = datetime.now().astimezone()
    for i in range(12):
        hub.presence.update(40, now - timedelta(seconds=20 - i * 0.2))
    hub.attention.set_present(True)
    assert hub.presence.present
    await hub.attention_step(now)
    assert not hub.presence.present and not hub.attention.present


def test_offline_nudge_only_offers_what_this_build_can_do():
    from kaiku_contracts.config import get
    enabled = set(get("ritual", "enabled_nudges"))
    assert {local_nudge()[0] for _ in range(60)} <= enabled and "friend_ping" not in enabled


def test_store_never_holds_media_fields(tmp_path):
    """The store takes validated raw.* envelopes only; none of those contracts can carry an image or audio."""
    from kaiku_contracts.registry import RAW
    for model in RAW.values():
        fields = " ".join(model.model_fields).lower()
        assert not any(w in fields for w in ("image", "audio", "frame", "pcm", "jpeg", "transcript"))


async def test_valid_message_on_the_wrong_topic_is_ignored(hub):
    env = make("raw.head.tap", {"t_ms": 1}, source="head", home_id=hub.settings.home_id)
    await hub.on_raw(parse_topic(f"kaiku/v1/{hub.settings.home_id}/raw/hub/face"), env)  # must not raise
    assert not hub.attention.faces_seen


def test_drumming_faster_than_the_contract_ceiling_halves_quality():
    taps = TapAnalyzer()
    for i in range(40):
        taps.add(i * 120)  # 500 bpm, every tap resolved
    assert taps.summary(4.7)["tempo_bpm"] == 400 and taps.rejected == 0 and taps.quality() == 0.5
