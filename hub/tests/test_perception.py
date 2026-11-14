from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from kaiku_hub.perception.hrv import PpgBuffer, analyze_ppg
from kaiku_hub.perception.light import LightAggregator
from kaiku_hub.perception.presence import PresenceTracker
from kaiku_hub.perception.speech import speech_features
from kaiku_hub.perception.taps import TapAnalyzer


# ---------------------------------------------------------------- taps
def test_tap_tempo_force_regularity():
    a = TapAnalyzer(refractory_ms=80, force_max_g=4.0)
    for i in range(20):
        a.add(1000 + i * 500, 2.0)  # 120 bpm, perfectly regular
    s = a.summary(10)
    assert s["tempo_bpm"] == pytest.approx(120, abs=0.5)
    assert s["regularity"] == pytest.approx(1.0)
    assert s["force_mean"] == pytest.approx(0.5)
    assert s["taps"] == 20


def test_tap_refractory_and_irregular():
    a = TapAnalyzer(refractory_ms=80)
    assert a.add(0, 1) and not a.add(50, 1) and a.add(130, 1)  # 50 ms bounce rejected
    b = TapAnalyzer()
    for t in [0, 400, 1000, 1300, 2100, 2400]:
        b.add(t, 1.0)
    assert 0 < b.regularity() < 0.8
    assert TapAnalyzer().summary(0)["tempo_bpm"] == 0


def test_tap_pauses_excluded_from_tempo():
    a = TapAnalyzer()
    for t in [0, 500, 1000, 1500, 6000, 6500, 7000]:
        a.add(t, 1.0)
    assert a.tempo_bpm() == pytest.approx(120)


def test_recent_tempo_follows_a_change_the_session_tempo_hides():
    """20 taps at 100 bpm, then she speeds up to 130: after four fast taps the recent tempo is the new one,
    while the session's tempo (the observation) still says 100."""
    a = TapAnalyzer()
    t = 0
    for _ in range(20):
        a.add(t, None)
        t += 600
    assert a.recent_tempo_bpm() == pytest.approx(100) and a.tempo_bpm() == pytest.approx(100)
    t = a.times[-1]
    for _ in range(4):
        t += 460
        a.add(t, None)
    assert a.recent_tempo_bpm() == pytest.approx(60000 / 460, abs=0.1)
    assert a.tempo_bpm() == pytest.approx(100)
    assert TapAnalyzer().recent_tempo_bpm() == 0.0


# ---------------------------------------------------------------- hrv
def test_hrv_rmssd_known_ibis(ppg):
    ibis = [800, 850] * 30  # successive differences all 50 ms -> RMSSD 50
    r = analyze_ppg(ppg(ibis), fs=100)
    assert r.ok, r.reason
    assert r.hr_bpm == pytest.approx(60000 / 825, abs=1.5)
    assert r.rmssd_ms == pytest.approx(50, abs=8)
    assert r.clean_ratio >= 0.9


def test_hrv_quality_gate_rejects_noise():
    rng = np.random.default_rng(1)
    r = analyze_ppg((16000 + rng.normal(0, 2000, 3000)).astype(int), fs=100)
    assert not r.ok
    assert analyze_ppg([16000] * 100, fs=100).ok is False  # too short


def test_ppg_buffer_session(ppg):
    buf = PpgBuffer()
    sig = ppg([900, 950] * 40)
    for i in range(0, len(sig) - 25, 25):
        buf.add(100.0, sig[i:i + 25].tolist())
    payload, q, pre, post = buf.session(6, 60, (0.7, 3.5), 0.7, window_s=30)
    assert payload and payload["hr_bpm"] > 0 and "rmssd_pre_ms" in payload and "rmssd_post_ms" in payload
    assert q > 0.7 and pre.ok and post.ok


def test_ppg_pre_post_windows_use_first_and_last_30s(ppg):
    buf = PpgBuffer()
    calm, varied = ppg([1000] * 40, seed=1), ppg([800, 1000] * 25, seed=2)  # ~40 s steady, then ~45 s variable
    for chunk in (calm, varied):
        for i in range(0, len(chunk) - 25, 25):
            buf.add(100.0, chunk[i:i + 25].tolist())
    pre, post = buf.pre_post(30, (0.7, 3.5), 0.0)
    assert pre.ok and post.ok and post.rmssd_ms > pre.rmssd_ms


# ---------------------------------------------------------------- presence / light
T0 = datetime(2026, 11, 14, 7, 30, tzinfo=UTC)


def _approach(p: PresenceTracker, start: datetime):
    out = []
    for i in range(30):
        r = p.update(200 - i * 10 if i < 15 else 50, start + timedelta(seconds=0.2 * i))
        if r:
            out.append(r)
    return out


def test_presence_first_of_day():
    p = PresenceTracker(near_cm=80, first_of_day_after_h=4, confirm_s=1.0)
    arrivals = _approach(p, T0)
    assert len(arrivals) == 1 and arrivals[0]["first_of_day"] is True
    # leave, come back 1 hour later: not first of day
    for i in range(10):
        p.update(200, T0 + timedelta(seconds=10 + i * 0.2))
    assert not p.present
    again = _approach(p, T0 + timedelta(hours=1))
    assert len(again) == 1 and again[0]["first_of_day"] is False
    # next morning -> first of day again
    for i in range(10):
        p.update(200, T0 + timedelta(hours=2, seconds=i * 0.2))
    nxt = _approach(p, T0 + timedelta(days=1))
    assert nxt[0]["first_of_day"] is True


def test_presence_ignores_single_spike():
    p = PresenceTracker(confirm_s=1.0)
    for i in range(20):
        cm = 40 if i == 5 else 200
        assert p.update(cm, T0 + timedelta(seconds=0.2 * i)) is None


def test_light_window():
    agg = LightAggregator(window_min=1)
    assert agg.add(100, T0) is None
    assert agg.add(300, T0 + timedelta(seconds=30)) is None
    out = agg.add(50, T0 + timedelta(seconds=61))
    assert out == {"lux_est": 200.0, "window_min": 1}


def test_speech_features_shape():
    sr = 16000
    t = np.arange(0, 3, 1 / sr)
    bursts = (np.sin(2 * np.pi * 4 * t) > 0).astype(float)  # 4 Hz on/off "syllables"
    audio = 0.3 * np.sin(2 * np.pi * 200 * t) * bursts
    f = speech_features(audio, sr)
    assert f is not None and 0.2 < f["pause_ratio"] < 0.8 and f["duration_s"] == 3.0
    assert speech_features(np.zeros(100), sr) is None


def test_knock_taps_have_no_force_mean():
    from kaiku_hub.perception.taps import TapAnalyzer

    t = TapAnalyzer()
    for i in range(6):
        t.add(1000 + i * 500)
    s = t.summary(2.5)
    assert s["force_mean"] is None and s["taps"] == 6 and s["tempo_bpm"] == 120


def test_press_counter_one_answer_per_run():
    from kaiku_hub.perception.presses import PressCounter

    c = PressCounter(window_s=4.0)
    for t in (0.0, 0.4, 0.8):
        c.add(t)
    assert not c.due(3.0) and c.due(4.9)
    assert c.ear_event() == {"value": 3, "delta": 0, "pressed": True}
    for t in range(7):
        c.add(10.0 + t * 0.3)
    assert c.take() == 5  # capped at 5
    c.add(20.0)
    c.add(30.0)  # gap longer than the window starts a new answer
    assert c.take() == 1


def test_speech_window_has_no_audio_and_suppresses_invalid_evidence():
    from kaiku_hub.perception.speech import SpeechWindow

    sr = 16000
    t = np.arange(sr * 3) / sr
    pcm = (10000 * np.sin(2 * np.pi * 200 * t) * (np.sin(2 * np.pi * 4 * t) > 0)).astype('<i2').tobytes()
    window = SpeechWindow()
    for chunk in (pcm[i:i+3200] for i in range(0, len(pcm), 3200)):
        window.add(chunk)
    assert len(window.energy) == 150 and isinstance(window.energy[0], float)
    assert window.finish(heard=True)['duration_s'] == 3
    assert len(window.energy) == 0
    for unusable in (bytes(sr * 4), b'\xff\x7f' * sr * 2):
        window.add(unusable)
        assert window.finish(heard=True) is None
    window.add(pcm)
    assert window.finish(heard=False) is None
    window.add(pcm)
    window.add(pcm, usable=False)
    assert window.finish(heard=True) is None
    for _ in range(11):
        window.add(pcm)
    assert len(window.energy) == 1500 and window.finish(heard=True) is None
    assert speech_features(np.zeros(sr * 2), sr) is None


def test_light_preserves_capture_order_and_sensor_quality():
    agg = LightAggregator(window_min=1)
    assert agg.add(100, T0, .8) is None
    assert agg.add(1000, T0 - timedelta(seconds=1), .9) is None
    assert agg.add(1000, T0 + timedelta(seconds=10), .1) is None
    assert agg.add(200, T0 + timedelta(seconds=30), .6) is None
    assert agg.add(300, T0 + timedelta(seconds=61), .9)['lux_est'] == 150
    assert agg.closed_at == T0 + timedelta(seconds=30) and agg.closed_quality == .6
