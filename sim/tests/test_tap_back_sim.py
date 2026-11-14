"""Tap it back with the sim twins (D51): the hub-driven head and the standalone head play the whole game on a real
broker, and the head's speaker twin records what it was sent (so the song is checked from the HEAD's side)."""

import asyncio
import json
import time
import wave

import numpy as np
import pytest
from kaiku_contracts.bus import Bus
from kaiku_contracts.topics import AUDIO_FRAME_BYTES

from sim.nodes import head_audio_sim, head_sim
from sim.nodes.head_audio_sim import MicTwin, SpeakerTwin
from sim.nodes.head_sim import HeadSim, StandaloneHeadSim

FRAME = np.full(320, 3000, dtype="<i2").tobytes()


def game_settings(tmp_path, **over):
    from kaiku_hub.perception.tap_back import TapBackConfig
    from kaiku_hub.settings import Settings

    s = Settings.load()
    s.cloud_url, s.home_id = None, "tap-back-sim"
    s.queue_path, s.state_path, s.store_path = tmp_path / "q.sqlite", tmp_path / "state.json", tmp_path / "s.sqlite"
    s.face_source, s.music, s.music_out = "off", "local", "head"       # the hub's own beat, out of the head's speaker
    s.greet_s, s.dial_s, s.breathe_s, s.nudge_s, s.post_mood_s = 0.3, 8, 0.4, 0.3, 5
    s.tap_back = TapBackConfig.from_dict({
        "mode": "tap_back", "level_bpm": [150, 200], "level_vary_bpm": [0, 0], "level_taps": [5, 6], "listen_s": 1.6,
        "replay_listen_s": 1.2, "first_tap_s": 4, "idle_end_s": 1.2, "cue_clear_s": 0.05, "result_s": 0.3, **over})
    return s


def beat_bpm(path, start_s: float, end_s: float) -> float:
    """The tempo of the ticks in a stretch of the twin's recording: the median gap between their onsets."""
    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        x = np.abs(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float))
    x = x[int(start_s * 16000):int(end_s * 16000)]
    loud = np.flatnonzero(x > 0.3 * x.max())
    onsets = loud[np.insert(np.diff(loud) > 16000 * 0.12, 0, True)]
    return float(60 / (np.median(np.diff(onsets)) / 16000))


# -------------------------------------------------------------------------------------- the audio twins alone
async def test_speaker_twin_plays_on_its_own_clock_drops_on_the_empty_message_and_records_it(tmp_path):
    path = tmp_path / "head.wav"
    tw = SpeakerTwin(str(path))
    run = asyncio.create_task(tw.run())
    tw.on_frame(b"\x01" * 100)                           # not a frame: ignored
    for i in range(10):                                  # 0.2 s of sound, sent as the hub sends it:
        tw.on_frame(FRAME)                               # four frames at once (the cushion), then one every 20 ms
        if i >= 3:
            await asyncio.sleep(0.02)
    await asyncio.sleep(0.3)                             # nothing sent: the head plays silence by itself
    for _ in range(40):                                  # a burst far larger than the ring: the newest are dropped
        tw.on_frame(FRAME)
    assert len(tw.ring) == head_audio_sim.RING_FRAMES and tw.overflows == 40 - head_audio_sim.RING_FRAMES + 1 - 1
    tw.on_frame(b"")                                     # "drop what you have buffered, now"
    assert not tw.ring and tw.flushes == 1
    await asyncio.sleep(0.2)
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)
    with wave.open(str(path)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    assert len(x) / 16000 == pytest.approx(0.7, abs=0.08)             # the wall clock, silence included
    stats = json.loads((tmp_path / "head.wav.json").read_text())
    (a, b), = stats["sound_spans_s"]
    # as the firmware plays: it starts once 120 ms is buffered (40 ms in, the way the hub sends), and what it feeds
    # the audio driver is heard 120 ms later
    assert a == pytest.approx(0.16, abs=0.05) and b - a == pytest.approx(0.2, abs=0.021)
    assert x[int(a * 16000) + 16:int(b * 16000) - 16].min() == 3000 and not x[int(b * 16000) + 400:].any()   # then quiet
    assert stats["frames_played"] == 10 and stats["wrong_size"] == 1 and stats["drop_messages"] == 1
    assert stats["glitches"] == 0


async def test_speaker_twin_still_plays_what_the_driver_holds_after_a_drop_message():
    """A zero-length message empties the ring; the 120 ms already handed to the audio driver are still heard."""
    tw = SpeakerTwin()
    run = asyncio.create_task(tw.run())
    for i in range(20):
        tw.on_frame(FRAME)
        if i >= 3:
            await asyncio.sleep(0.02)
    played = tw.played
    tw.on_frame(b"")
    assert not tw.ring and tw.quiet_s(time.monotonic()) == 0.0        # not quiet yet: the driver is still sounding
    await asyncio.sleep(0.2)
    assert 4 <= tw.played - played <= head_audio_sim.DRIVER_FRAMES + 1
    assert 0.0 < tw.quiet_s(time.monotonic()) < 0.15
    run.cancel()


class _MicBus:
    def __init__(self):
        self.sent: list[tuple[float, bytes]] = []

    async def publish_audio(self, data, *, stream="speaker"):
        assert stream == "mic"
        self.sent.append((time.monotonic(), data))


async def test_mic_twin_sends_only_while_held_open_and_never_while_the_speaker_plays(tmp_path, monkeypatch):
    monkeypatch.setattr(head_audio_sim, "MIC_HOLD_S", 0.3)
    voice = tmp_path / "question.wav"
    with wave.open(str(voice), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.full(16000 * 2 // 10, 7000, dtype="<i2").tobytes())   # 0.2 s of "speech"
    bus, speaker = _MicBus(), SpeakerTwin()
    mic = MicTwin(bus, speaker, str(voice), delay_s=0.1)
    tasks = [asyncio.create_task(mic.run()), asyncio.create_task(speaker.run())]
    await asyncio.sleep(0.1)
    assert bus.sent == []                                # closed: nothing leaves the head
    mic.on_cmd("open")
    await asyncio.sleep(0.2)
    mic.on_cmd("open")                                   # the hub holds it
    await asyncio.sleep(0.25)
    spoken = [d for _t, d in bus.sent if d != head_audio_sim.SILENCE]
    assert len(spoken) == 10 and all(len(d) == AUDIO_FRAME_BYTES for _t, d in bus.sent)   # the recording once, whole
    assert bus.sent[0][1] == head_audio_sim.SILENCE and bus.sent[-1][1] == head_audio_sim.SILENCE   # a quiet room around it
    gaps = np.diff([t for t, _d in bus.sent])
    assert (gaps < 0.005).sum() >= 3 and gaps.max() > 0.025   # as the firmware sends: one or two per 32 ms block
    assert len(bus.sent) / (bus.sent[-1][0] - bus.sent[0][0] + 0.02) == pytest.approx(50, rel=0.2)   # 50 a second all the same
    n = len(bus.sent)
    for _ in range(10):                                  # Kaiku speaks: 0.2 s out of the head's speaker
        speaker.on_frame(FRAME)
        mic.on_cmd("open")
        await asyncio.sleep(0.02)
    during = len(bus.sent) - n
    assert during <= 2                                   # half-duplex: (almost) nothing while it plays
    mic.on_cmd("open")
    for _ in range(30):                                  # until the driver has played the last of it
        await asyncio.sleep(0.02)
        if speaker.quiet_s(time.monotonic()) > 0:
            break
    t_quiet = time.monotonic()
    mic.on_cmd("open")
    await asyncio.sleep(0.5)
    after = [t for t, _d in bus.sent[n + during:]]
    assert after and after[0] - t_quiet >= 0.2           # ... nor for a quarter second after
    await asyncio.sleep(0.4)                             # no `open` for longer than the hold: it closes by itself
    n = len(bus.sent)
    await asyncio.sleep(0.15)
    assert len(bus.sent) == n
    mic.on_cmd("open")
    await asyncio.sleep(0.1)
    mic.on_cmd("close")
    n = len(bus.sent)
    await asyncio.sleep(0.1)
    assert len(bus.sent) <= n + 1
    for t in tasks:
        t.cancel()


# ------------------------------------------------------------------- the standalone twin's `drum: hold | end`
class _Capture:
    def __init__(self):
        self.events, self.node, self.log = [], "head", type("L", (), {"info": lambda *a, **k: None})()

    def on(self, *a, **k):
        return None

    def on_audio(self, *a, **k):
        return None

    async def publish(self, type_, payload, **k):
        from kaiku_contracts import make

        self.events.append(make(type_, payload, source=k.get("source") or "head", sim=True))

    async def publish_audio(self, *a, **k):
        return None


async def _cmd(head, **cmd):
    from kaiku_contracts import make

    await head._on_cmd(None, make("cmd.head", cmd, source="hub"))


def _chimes(head):
    return [e.payload.chime for e in head.bus.events if e.type == "cmd.sensors"]


async def test_standalone_twin_holds_its_drum_step_obeys_the_hub_and_lets_go_by_itself():
    head = StandaloneHeadSim(auto=False, time_scale=100.0, drum="knock")   # 10 real ms = 1 firmware second; a build
    head.bus = _Capture()                                             # with the UNO Q's knock switch (not this robot)
    head.HOLD_MS = 150                                                # real ms (the firmware: 10 s)
    await head._set_mode("drum")
    await _cmd(head, drum="hold", eyes="listening", pan_mode="sway", bpm=104.0, chest="pulse")
    assert head._held and head._sway and head.sway_bpm == 104.0
    assert head.eyes == "wide"                                        # the firmware's five faces: `listening` is wide
    await _cmd(head, drum="hold", eyes="soft", pan_mode="sway", bpm=104.0)   # what the hub sends it for the song
    assert head.eyes == "calm"
    for _ in range(12):                                               # 1.2 firmware minutes: far past its 60 s timer
        await head._tick()
        await asyncio.sleep(0.01)
        await _cmd(head, drum="hold")
    assert head.mode == "drum" and head._moving                       # still drumming; the sway counts as moving
    await head.tap()
    assert head.muted_knocks == 1                                     # ... so a knock during it is muted, as on the robot
    await _cmd(head, drum="hold", eyes="wide", pan_mode="still")
    await head._tick()
    assert not head._moving and head.eyes == "wide"
    await head.tap()
    assert [e.payload.src for e in head.bus.events if e.type == "raw.head.tap"] == ["knock"]
    await _cmd(head, drum="end", pan_mode="still")
    assert head.mode == "done" and _chimes(head)[-2:] == ["start_drum", "end_drum"] and not head._held

    # a hub that goes silent never strands the head: no `hold` for the hold time = its own timer, from then
    head = StandaloneHeadSim(auto=False, time_scale=100.0)
    head.bus = _Capture()
    head.HOLD_MS = 100
    await head._set_mode("drum")
    await _cmd(head, drum="hold")
    await asyncio.sleep(0.15)
    await head._tick()
    assert not head._held and head.mode == "drum"
    for _ in range(100):                                              # its own 60 s without a tap, from that moment
        await head._tick()
        if head.mode != "drum":
            break
        await asyncio.sleep(0.01)
    assert head.mode == "done" and _chimes(head)[-1] == "end_drum"
    # `hold` outside the drum step does nothing: no hold, no sway (the eyes are taken in any step, as before)
    head = StandaloneHeadSim(auto=False)
    head.bus = _Capture()
    await head._set_mode("mood")
    await _cmd(head, drum="hold", eyes="listening", pan_mode="sway", bpm=90.0)
    assert not head._held and not head._sway and head.eyes == "wide"
    health = [e for e in head.bus.events if e.type == "health"]
    assert health and health[-1].payload.details["step"] == "mood" and health[-1].payload.details["drum_held"] is False


async def test_both_head_twins_show_the_help_screen_when_told_and_take_it_down_as_the_firmware_does(monkeypatch):
    """`cmd.head {show: help}` (the hub's crisis path), as in the two firmwares: the helpline's numbers on the head's
    own screen, never a sound, the microphone shut, the motor still. Reported as `details.help_shown`."""
    head = StandaloneHeadSim(auto=False, imu=True, seed=3)
    head.bus = _Capture()
    await head._set_mode("drum")
    await _cmd(head, drum="hold", eyes="soft", pan_mode="sway", bpm=100.0)
    head.mic.on_cmd("open")
    assert head._held and head._sway and not head.help_shown and head.mic.open_until > 0
    n = len(head.bus.events)
    await _cmd(head, drum="end", pan_mode="still", show="help")       # what the hub sends in a crisis during a game
    assert head.help_shown and head.mode == "idle" and not head._held and not head._sway
    assert head.mic.open_until == 0.0                                 # the head shuts its microphone itself
    new = head.bus.events[n:]
    assert "cmd.sensors" not in [e.type for e in new]                 # the drum end is dropped: no end chime, and
    assert [e.payload.details["step"] for e in new if e.type == "health"] == ["idle"]   # no "done" on the way
    assert new[-1].payload.details["help_shown"] is True              # said at once, not at the next heartbeat

    head._quiet_until = 0.0
    head._tap_latch = head._face = True                               # a pat on the head, a face in front of it:
    await head._tick()
    assert head.mode == "idle" and head.help_shown                    # nothing wakes Kaiku under the help screen
    n = len(head.bus.events)
    await head.tap()
    assert not [e for e in head.bus.events[n:] if e.type == "raw.head.tap"]   # and it reports no tap
    await _cmd(head, eyes="soft", purr={"ms": 500}, pan={"target_deg": 30, "speed": 0.5})
    await head._tick()
    assert head.help_shown and not head._moving                       # another command neither takes it down nor
    await _cmd(head, show="none")                                     # moves the head; `none` takes it down
    assert not head.help_shown and head.bus.events[-1].payload.details["help_shown"] is False

    await _cmd(head, show="help")
    await head.press_ear()                                            # she presses its ear: a new greeting, and the
    assert head.mode == "greet" and not head.help_shown               # help screen makes way
    monkeypatch.setattr(head_sim, "HELP_S", 0.05)
    await _cmd(head, show="help")
    assert head.help_shown and head.mode == "idle"                    # (the greeting it interrupted ended quietly)
    await asyncio.sleep(0.08)                                         # ... or after its own ten minutes
    assert not head.help_shown

    # the firmware does not guard this, so neither does its twin: a `mic: open` after help opens the microphone under
    # the help screen. The hub must never send one after a crisis (hub/tests/test_follow_voice.py).
    monkeypatch.setattr(head_sim, "HELP_S", 600.0)
    await _cmd(head, show="help")
    await _cmd(head, mic="open")
    assert head.help_shown and head.mic.open_until > 0

    driven = HeadSim(auto=False)                                      # the hub-driven twin (the MQTT firmware)
    driven.bus = _Capture()
    await _cmd(driven, mic="open", pan={"target_deg": 40, "speed": 0.5})
    assert driven.target_deg == 40 and driven.mic.open_until > 0
    await _cmd(driven, show="help")
    assert driven.help_shown and driven.mic.open_until == 0.0 and driven.target_deg == driven.deg   # still, shut
    await _cmd(driven, pan={"target_deg": -40, "speed": 0.5}, gesture="shake")
    assert driven.target_deg == driven.deg and driven.help_shown      # never moves under it; a ritual does not clear
    await _cmd(driven, show="none")                                   # it either: only `none` (or ten minutes)
    assert not driven.help_shown
    await _cmd(driven, pan={"target_deg": -40, "speed": 0.5})
    assert driven.target_deg == -40


async def test_standalone_twin_says_its_step_at_once_and_mutes_its_own_taps_as_the_firmware_does(monkeypatch):
    """This robot (D55): the head's orientation sensor is the only tap source. One message per tap, from the head,
    with force; none while the motor runs or 400 ms after, none within 120 ms of the last, none while its speaker
    plays PCM or 150 ms after; and the head counts its own taps."""
    head = StandaloneHeadSim(auto=False, seed=2)                      # [robot] drum_input = "imu"
    head.bus = _Capture()
    assert head.drum == "imu" and head.imu
    await head._set_mode("drum")                                      # health goes out now, not on the next 5 s beat
    assert [e.type for e in head.bus.events] == ["cmd.sensors", "health"]
    assert head.bus.events[-1].payload.details["step"] == "drum"

    def taps():
        return [e for e in head.bus.events if e.type == "raw.head.tap"]

    await head.tap()
    (first,) = taps()
    assert (first.source, first.payload.src) == ("head", "imu") and first.payload.force > 0   # never a knock, never
    await head._tick()                                                                        # from the UNO Q
    assert head.taps == 1                                             # the head's own drum count
    await asyncio.sleep(0.06)
    await head.tap()                                                  # 60 ms later: at most one per 120 ms
    assert len(taps()) == 1 and head.imu_muted_taps == 1
    await asyncio.sleep(0.13)
    head.speaker.on_frame(FRAME)                                      # PCM is playing: none
    await head.tap()
    assert len(taps()) == 1
    head.speaker.ring.clear()
    head.speaker.last_real = time.monotonic()                         # ... nor for 150 ms after its last sound
    await asyncio.sleep(0.05)
    await head.tap()
    assert len(taps()) == 1
    await asyncio.sleep(0.13)
    await head.tap()
    assert len(taps()) == 2
    await asyncio.sleep(0.13)
    head._moving = True                                               # the motor turns or sways: none
    await head.tap()
    head._moving = False
    await asyncio.sleep(0.25)
    await head.tap()                                                  # ... nor for 400 ms after it stopped
    assert len(taps()) == 2
    await asyncio.sleep(0.2)
    await head.tap()
    assert len(taps()) == 3 and {e.source for e in taps()} == {"head"}

    idle = StandaloneHeadSim(auto=False, seed=2)                      # a pat on the head wakes it, by its own sensor
    idle.bus = _Capture()
    idle._quiet_until = 0.0
    await idle.tap()
    await idle._tick()
    assert idle.mode == "greet"


async def test_a_build_with_the_knock_switch_reports_one_tap_from_both_boards_on_two_clocks():
    head = StandaloneHeadSim(auto=False, imu=True, seed=1, drum="knock")
    head.bus = _Capture()
    await head.tap()
    taps = [e for e in head.bus.events if e.type == "raw.head.tap"]
    assert [(e.source, e.payload.src, e.payload.force is None) for e in taps] == [
        ("sensors", "knock", True), ("head", "imu", False)]
    assert taps[1].payload.t_ms - taps[0].payload.t_ms == head.IMU_CLOCK_MS


# ---------------------------------------------------------------------------- the whole game on a real broker
async def _until(what, seconds: float):
    for _ in range(int(seconds / 0.05)):
        if what():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_hub_driven_head_twin_plays_the_game_and_hears_it_from_its_own_speaker(broker, tmp_path, monkeypatch):
    """`make sim` + `make hub`: a ritual still completes with the drum step as Tap it back. Here with the hub's own
    beat (no key, no model), out of the head's speaker over the bus, recorded by the twin."""
    from kaiku_hub.live.base import OffVoice
    from kaiku_hub.main import Hub

    wav = tmp_path / "head.wav"
    monkeypatch.setenv("KAIKU_SIM_HEAD_AUDIO", str(wav))
    monkeypatch.setenv("KAIKU_HOME_ID", "tap-back-sim")
    monkeypatch.delenv("KAIKU_MUSIC_FILE", raising=False)
    s = game_settings(tmp_path)
    seen = []

    async def on_obs(_t, env):
        seen.append(env)

    head = HeadSim(mood=3, seed=5, dial="ear", drum="knock", tap_back_errors=[0.01, 0.25, 0.03])
    head.tap_back_react_s = 1.1
    watch = Bus("sim", home_id="tap-back-sim", sim=True, heartbeat=False)
    watch.on("obs/#", on_obs)
    hub = Hub(s, voice=OffVoice(), read_stdin=False)
    assert hub.music.name == "local" and hub.music.audio is hub.speaker
    stop, head_stop = asyncio.Event(), asyncio.Event()
    async with watch:
        hub_task = asyncio.create_task(hub.run(stop))
        head_task = asyncio.create_task(head.run(head_stop))
        await asyncio.wait_for(hub.bus.connected.wait(), 5)
        await head.bus.connected.wait()
        await watch.publish("raw.head.ear", {"value": 3, "delta": 0, "pressed": True}, source="head")
        hub.start_ritual("test")
        t0 = time.monotonic()
        assert await _until(lambda: any(e.type == "obs.ritual" and e.payload.step == "close"
                                        and e.payload.status == "completed" for e in seen), 45), [e.type for e in seen]
        took = time.monotonic() - t0
        sent = hub.speaker.stats()
        head_stop.set()
        await asyncio.wait_for(head_task, 5)
        stop.set()
        await asyncio.wait_for(hub_task, 8)

    (obs,) = [e for e in seen if e.type == "obs.tap_back"]
    p = obs.payload
    assert [(lv.target_bpm, lv.band, lv.tries) for lv in p.levels] == [(150, "perfect", 1), (200, "perfect", 2)]
    assert p.song == "beat" and p.levels_passed == 2 and obs.sim
    assert not [e for e in seen if e.type == "obs.drum_session"]
    post = [e.payload for e in seen if e.type == "obs.self_report" and e.payload.context == "post_activity"]
    assert len(post) == 1 and post[0].value == 4                       # the twin answered the mood question after it
    steps = [(e.payload.step, e.payload.status) for e in seen if e.type == "obs.ritual"]
    assert ("drum", "completed") in steps and steps[-1] == ("close", "completed")

    # from the HEAD's side: what its speaker was sent, on its own clock
    stats = json.loads((tmp_path / "head.wav.json").read_text())
    assert stats["overflows"] == 0 and stats["wrong_size"] == 0 and stats["glitches"] == 0, json.dumps(stats)
    assert stats["max_buffered_ms"] <= 160 and 16 <= stats["interval_mean_ms"] <= 21   # (each sound's first 4 come at once)
    assert sent["ahead_max_ms"] <= 120 and sent["frames"] == stats["frames_received"]
    assert sent["interval_mean_ms"] == pytest.approx(20, abs=1.5)        # the hub's clock, frame by frame
    spans = [(a, b) for a, b in stats["sound_spans_s"] if b - a >= 1.0]      # the three songs (chimes are shorter)
    assert len(spans) == 3, stats["sound_spans_s"]
    assert [round(beat_bpm(wav, a, b)) for a, b in spans] == [150, 200, 200]  # each level's tempo, in order
    for (_a, end), (start, _b) in zip(spans, spans[1:], strict=False):
        assert start - end >= 1.5                                            # her turn: no song
    with wave.open(str(wav)) as w:
        assert w.getnframes() / 16000 == pytest.approx(took, abs=6)          # real time, not faster


async def test_standalone_head_twin_is_held_plays_the_game_and_goes_on_with_its_ritual(broker, tmp_path, monkeypatch):
    """The head runs its own ritual (D44); the hub follows it, holds its drum step, runs the game there with the
    taps the head's orientation sensor reports (the only tap source on this robot, D55), and lets it go."""
    from kaiku_hub.live.base import OffVoice
    from kaiku_hub.main import Hub

    monkeypatch.setenv("KAIKU_HOME_ID", "tap-back-sim")
    monkeypatch.delenv("KAIKU_MUSIC_FILE", raising=False)
    monkeypatch.delenv("KAIKU_SIM_HEAD_AUDIO", raising=False)
    s = game_settings(tmp_path)
    seen, cmds = [], []

    async def on_obs(_t, env):
        seen.append(env)

    async def on_cmd(_t, env):
        cmds.append(env.payload.model_dump(exclude_none=True))

    head = StandaloneHeadSim(mood=7, energy=4, sleep=5, seed=2, time_scale=12.0, health_s=0.5,
                             tap_back_errors=[0.02, 0.06])              # [robot] drum_input = "imu": no knock switch
    head.tap_back_react_s = 1.1
    watch = Bus("sensors", home_id="tap-back-sim", sim=True, heartbeat=False)
    watch.on("obs/#", on_obs)
    watch.on("cmd/head", on_cmd)
    hub = Hub(s, voice=OffVoice(), read_stdin=False)
    stop, head_stop = asyncio.Event(), asyncio.Event()
    async with watch:
        hub_task = asyncio.create_task(hub.run(stop))
        head_task = asyncio.create_task(head.run(head_stop))
        await asyncio.wait_for(hub.bus.connected.wait(), 5)
        assert await _until(lambda: hub.following, 5)
        await watch.publish("raw.hub.face", {"x_norm": 0.0, "y_norm": 0.0, "size": 0.25, "confidence": 0.9})
        assert await _until(lambda: any(e.type == "obs.ritual" and e.payload.step == "close"
                                        and e.payload.status == "completed" for e in seen), 60), [e.type for e in seen]
        played = head.speaker.played
        head_stop.set()
        await asyncio.wait_for(head_task, 5)
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.wait_for(hub_task, 8)

    (obs,) = [e for e in seen if e.type == "obs.tap_back"]
    p = obs.payload
    assert [(lv.target_bpm, lv.band, lv.taps) for lv in p.levels] == [(150, "perfect", 5), (200, "great", 6)]
    assert p.rejected_taps == 0 and hub.tap_source.dropped == 0         # this robot: one tap source only,
    assert hub.tap_source.src == "head/imu"                             # the head's orientation sensor (D55)
    assert not [e for e in seen if e.type == "obs.drum_session"]
    steps = [(e.payload.step, e.payload.status) for e in seen if e.type == "obs.ritual"]
    assert steps[-4:] == [("drum", "started"), ("drum", "completed"), ("close", "started"), ("close", "completed")]
    assert cmds and all("drum" in c for c in cmds)                      # nothing else was ever sent to this head
    assert cmds[-1] == {"drum": "end", "pan_mode": "still"} and sum(c["drum"] == "hold" for c in cmds) >= 6
    assert played > 100                                                 # the beat reached the head's speaker
    assert head.results["drum"]["taps"] >= 11 and head.mode in ("done", "idle")
