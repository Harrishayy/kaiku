"""The robot head's own speaker and microphone over the bus (plan 07 section 4): the resampler, the 20 ms frames, the
hub's clock, one sender at a time, the drop message, the microphone, and a hub with no sound device at all."""

import asyncio
import subprocess
import sys
import threading
import time

import numpy as np
import pytest
from kaiku_contracts.topics import AUDIO_FRAME_BYTES, AUDIO_FRAME_SAMPLES
from kaiku_hub.live.head_audio import AutoAudio, HeadAudio, HeadPcm, HeadSpeaker, Resampler


def sine(freq: float, rate: int, seconds: float, amp: float = 0.5) -> np.ndarray:
    return amp * np.sin(2 * np.pi * freq * np.arange(int(rate * seconds)) / rate)


def level_db(x: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)


def stereo48(value: int, seconds: float) -> bytes:
    return np.full(int(48000 * seconds) * 2, value, dtype="<i2").tobytes()


# ------------------------------------------------------------------------------------------------ the resampler
def test_48k_to_16k_keeps_what_the_head_can_play_and_removes_what_would_fold_back():
    rs = Resampler(48000, 16000)
    assert (rs.up, rs.down) == (1, 3)
    for freq in (200, 1000, 3000, 6000):
        y = Resampler(48000, 16000).process(sine(freq, 48000, 0.5))[200:]
        assert y.size == pytest.approx(8000 - 200, abs=2)
        assert level_db(y) == pytest.approx(level_db(sine(freq, 16000, 0.5)), abs=0.3), freq   # flat in the passband
        spectrum = np.abs(np.fft.rfft(y * np.hanning(y.size)))
        assert np.argmax(spectrum) * 16000 / y.size == pytest.approx(freq, abs=5)              # and still that note
    for freq in (9000, 10000, 12000, 15000, 20000):     # above the head's 8 kHz: would alias to 7, 6, 4, 1, 4 kHz
        y = rs.process(sine(freq, 48000, 0.5))[200:]
        assert level_db(y) < level_db(sine(freq, 48000, 0.5)) - 60, freq


def test_resampling_in_pieces_is_the_same_as_in_one_go():
    x = sine(440, 48000, 1.0) + sine(2500, 48000, 1.0, 0.2)
    whole = Resampler(48000, 16000).process(x)
    rs = Resampler(48000, 16000)
    parts = np.concatenate([rs.process(x[a:b]) for a, b in ((0, 1000), (1000, 1001), (1001, 12345), (12345, 48000))])
    assert parts.size == whole.size == 16000 and np.allclose(parts, whole, atol=1e-9)


def test_live_voice_rate_24k_to_16k():
    rs = Resampler(24000, 16000)
    assert (rs.up, rs.down) == (2, 3)
    y = rs.process(sine(1000, 24000, 0.5))[200:]
    assert y.size == pytest.approx(8000 - 200, abs=2) and level_db(y) == pytest.approx(level_db(sine(1000, 16000, 0.5)), abs=0.3)
    assert level_db(Resampler(24000, 16000).process(sine(10000, 24000, 0.5))[200:]) < -60 + level_db(sine(10000, 24000, 0.5))


def test_frames_are_640_bytes_mono_with_headroom_and_the_remainder_waits():
    pcm = HeadPcm(48000, 2, gain=0.8)
    frames = pcm.feed(stereo48(10000, 0.25))            # a quarter second: 12.5 frames
    assert len(frames) == 12 and all(len(f) == AUDIO_FRAME_BYTES for f in frames)
    assert len(pcm.feed(stereo48(10000, 0.25))) == 13   # the half frame was kept, not dropped and not padded
    settled = np.frombuffer(frames[-1], dtype="<i2")
    assert settled.size == AUDIO_FRAME_SAMPLES and np.all(np.abs(settled - 8000) <= 2)   # mixed down, at 0.8
    left_right = np.empty(48000, dtype="<i2")
    left_right[0::2], left_right[1::2] = 20000, -20000  # opposite channels cancel: it is a real mix-down
    assert np.abs(np.frombuffer(HeadPcm(48000, 2).feed(left_right.tobytes())[-1], dtype="<i2")).max() <= 1
    loud = np.frombuffer(HeadPcm(48000, 2, gain=3.0).feed(stereo48(30000, 0.1))[-1], dtype="<i2")
    assert loud.max() == 32767                          # clipped, never wrapped around
    pcm = HeadPcm(16000, 1, gain=1.0)                   # already the head's format: passed through
    assert pcm.feed(np.arange(400, dtype="<i2").tobytes()) == [np.arange(320, dtype="<i2").tobytes()]
    tail = np.frombuffer(pcm.tail(), dtype="<i2")
    assert tail.size == 320 and list(tail[:80]) == list(range(320, 400)) and not tail[80:].any() and pcm.tail() is None


# --------------------------------------------------------------------------------------------- the hub's clock
class Wire:
    """What leaves the hub on the speaker topic, with the time each message left."""

    def __init__(self):
        self.sent: list[tuple[float, bytes]] = []

    async def publish(self, data: bytes) -> bool:
        self.sent.append((time.monotonic(), data))
        return True

    @property
    def frames(self) -> list[tuple[float, bytes]]:
        return [(t, d) for t, d in self.sent if d]

    def values(self) -> list[int]:
        """The level of each frame (the tests' sources are constant tones), 0 for a drop message."""
        return [int(round(np.frombuffer(d, dtype="<i2")[160] / 100.0)) * 100 if d else 0 for _t, d in self.sent]


async def test_one_frame_every_20_ms_a_little_ahead_of_the_clock_and_never_far():
    wire = Wire()
    speaker = HeadSpeaker(wire.publish, lead_ms=80, gain=1.0)
    out = speaker.RawOutputStream(samplerate=48000, channels=2, dtype="int16")
    out.start()
    t0 = time.monotonic()
    for _ in range(6):
        await asyncio.to_thread(out.write, stereo48(4000, 0.25))        # 1.5 s of sound, as the music player writes it
    took = time.monotonic() - t0
    await asyncio.sleep(0.05)
    times = [t - t0 for t, _d in wire.frames]
    assert len(times) == 75 and all(len(d) == AUDIO_FRAME_BYTES for _t, d in wire.frames)
    assert took == pytest.approx(1.5 - 0.08, abs=0.06)                  # a write lasts as long as its sound
    assert times[3] < 0.03                                              # the first four at once: the head's cushion
    gaps = np.diff(times[4:])
    assert np.mean(gaps) == pytest.approx(0.020, abs=0.001) and gaps.max() < 0.045
    ahead = [(i + 1) * 0.02 - t for i, t in enumerate(times)]           # sound sent minus time passed
    assert max(ahead) <= 0.12 and min(ahead[4:]) > 0.04                 # never above 120 ms, never run dry
    s = speaker.stats()
    assert s["frames"] == 75 and s["ahead_max_ms"] <= 120 and s["clock_restarts"] == 1 and s["drop_messages"] == 0
    assert s["interval_mean_ms"] == pytest.approx(20, abs=1.5)


async def test_after_a_silence_the_clock_restarts_and_the_cushion_is_rebuilt():
    wire = Wire()
    speaker = HeadSpeaker(wire.publish, lead_ms=60, gain=1.0)
    out = speaker.RawOutputStream(samplerate=48000, channels=2, dtype="int16")
    await asyncio.to_thread(out.write, stereo48(4000, 0.2))
    await asyncio.sleep(0.3)                                            # her turn: nothing is sent, the head plays silence
    assert not speaker.playing
    n = len(wire.frames)
    t1 = time.monotonic()
    await asyncio.to_thread(out.write, stereo48(4000, 0.2))
    await asyncio.sleep(0.02)
    again = [t - t1 for t, _d in wire.frames[n:]]
    assert len(again) == 10 and again[2] < 0.03 and speaker.stats()["clock_restarts"] == 2


async def test_stop_drops_the_heads_buffer_and_nothing_in_flight_is_sent_after_it():
    wire = Wire()
    speaker = HeadSpeaker(wire.publish, gain=1.0)
    out = speaker.RawOutputStream(samplerate=48000, channels=2, dtype="int16")
    writer = asyncio.create_task(asyncio.to_thread(out.write, stereo48(4000, 1.0)))
    await asyncio.sleep(0.2)
    out.stop()                                                          # the end of the music, a crisis: now
    await writer
    await asyncio.sleep(0.05)
    assert wire.sent[-1][1] == b"" and 8 <= len(wire.frames) <= 16      # about 0.2 s went out, not the whole second
    assert not speaker.playing and speaker.stats()["drop_messages"] == 1


async def test_flush_lets_the_faded_end_play_out_before_the_drop_message():
    wire = Wire()
    speaker = HeadSpeaker(wire.publish, lead_ms=80, gain=1.0)
    out = speaker.RawOutputStream(samplerate=48000, channels=2, dtype="int16")
    await asyncio.to_thread(out.write, stereo48(4000, 0.1))
    await asyncio.to_thread(out.write, stereo48(4000, 0.03))            # the 30 ms faded tail: a frame and a half
    t = time.monotonic()
    await asyncio.to_thread(out.flush)
    await asyncio.sleep(0.02)
    assert [len(d) for _t, d in wire.sent] == [640] * 7 + [0]           # the half frame is padded and sent, then the drop
    assert wire.sent[-1][0] - t >= 0.05                                 # after what the head still held had played


def voice_of(seconds: float, value: int = 9000):
    """A Live adapter's playback callback with this much "speech" waiting to be pulled."""
    said = bytearray(np.full(int(24000 * seconds), value, dtype="<i2").tobytes())
    lock = threading.Lock()

    def fill(outdata, frames, timing, status):
        with lock:
            n = min(len(outdata), len(said))
            outdata[:n] = said[:n]
            outdata[n:] = bytes(len(outdata) - n)
            del said[:n]

    return said, fill


async def test_a_sound_that_starts_while_kaiku_speaks_waits_and_loses_nothing():
    """A song or a chime wants the speaker while Kaiku's voice has it: its audio is delayed until 150 ms after the
    voice's last frame, whole. Frames of the two never interleave."""
    wire = Wire()
    speaker = HeadSpeaker(wire.publish, lead_ms=60, gain=1.0, release_ms=150)
    music = speaker.RawOutputStream(samplerate=48000, channels=2, dtype="int16")
    said, fill = voice_of(0.4)
    with speaker.RawOutputStream(samplerate=24000, channels=1, dtype="int16", callback=fill):
        await asyncio.sleep(0.05)
        await asyncio.to_thread(music.write, stereo48(4000, 0.3))
        await asyncio.sleep(0.1)
    values = [v for v in wire.values() if v]
    assert values.count(4000) == 15 and values.count(9000) >= 19        # all of both (the voice's edges ramp)
    first_song = values.index(4000)
    assert 4000 not in values[:first_song] and all(v == 4000 for v in values[first_song:])   # voice whole, then song
    assert wire.frames[first_song][0] - wire.frames[first_song - 1][0] >= 0.15   # the voice had finished sounding
    assert speaker.stats()["sender_changes"] == 2 and speaker.stats()["taken_by_voice"] == 0


async def test_kaikus_voice_never_waits_behind_the_music_and_the_two_never_interleave():
    """Music is playing (free drumming) and Kaiku has something to say: the voice takes the speaker at once, the
    head is told to drop the music it has buffered, and the music goes on only after the voice."""
    wire = Wire()
    speaker = HeadSpeaker(wire.publish, lead_ms=60, gain=1.0, release_ms=150)
    music = speaker.RawOutputStream(samplerate=48000, channels=2, dtype="int16")
    said, fill = voice_of(0.3)
    song = asyncio.create_task(asyncio.to_thread(music.write, stereo48(4000, 0.5)))
    await asyncio.sleep(0.1)
    t_voice = time.monotonic()
    with speaker.RawOutputStream(samplerate=24000, channels=1, dtype="int16", callback=fill):
        await song
        await asyncio.sleep(0.1)
    sent = [(t, d) for t, d in wire.sent]
    kinds = ["drop" if not d else "voice" if int(np.frombuffer(d, "<i2")[160]) != 4000 else "song" for _t, d in sent]
    first_voice = kinds.index("voice")
    assert kinds[first_voice - 1] == "drop" and set(kinds[:first_voice - 1]) == {"song"}   # song, the drop, then voice
    assert sent[first_voice][0] - t_voice < 0.08                        # at once: Kaiku's words are never late
    last_voice = len(kinds) - 1 - kinds[::-1].index("voice")
    assert set(kinds[first_voice:last_voice + 1]) == {"voice"}          # nothing of the song inside the voice
    rest = [k for k in kinds[last_voice + 1:] if k != "drop"]
    assert rest and set(rest) == {"song"} and kinds.count("song") == 25  # the song goes on after, none of it skipped
    assert sent[last_voice + 1][0] - sent[last_voice][0] >= 0.15
    assert speaker.stats()["taken_by_voice"] == 1


async def test_cutting_the_voice_drops_the_buffer_and_what_was_pulled_is_not_sent():
    wire = Wire()
    speaker = HeadSpeaker(wire.publish, gain=1.0)
    said = bytearray(np.full(24000 * 2, 9000, dtype="<i2").tobytes())   # two seconds of speech

    def fill(outdata, frames, timing, status):
        n = min(len(outdata), len(said))
        outdata[:n] = said[:n]
        outdata[n:] = bytes(len(outdata) - n)
        del said[:n]

    with speaker.RawOutputStream(samplerate=24000, channels=1, dtype="int16", callback=fill) as out:
        await asyncio.sleep(0.2)
        said.clear()                                                    # the adapter clears its audio (the ear was pressed)
        out.cut()
        await asyncio.sleep(0.1)
        n = len(wire.frames)
        assert b"" in [d for _t, d in wire.sent] and 8 <= n <= 18
        await asyncio.sleep(0.1)
        assert len(wire.frames) == n and not speaker.playing            # silence is not sent: the head may listen
    assert wire.sent[-1][1] == b""


# ----------------------------------------------------------------------------------------------- the microphone
async def test_the_microphone_is_held_open_by_commands_and_frames_reach_only_an_open_conversation():
    cmds: list[dict] = []

    async def command(**cmd):
        cmds.append(cmd)

    head = HeadAudio(HeadSpeaker(Wire().publish), command, renew_s=0.05)
    blocks: list[tuple[bytes, int]] = []
    frame = np.arange(320, dtype="<i2").tobytes()
    head.on_mic_frame(frame)                                            # nobody is listening: dropped unread
    assert head.mic_frames == 0
    with pytest.raises(ValueError):
        head.RawInputStream(samplerate=48000, channels=1, dtype="int16", blocksize=1600, callback=print)
    with head.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1600,
                             callback=lambda data, n, t, status: blocks.append((bytes(data), n))):
        await asyncio.sleep(0.12)
        assert cmds[0] == {"mic": "open"} and cmds.count({"mic": "open"}) >= 3   # held open, again and again
        for _ in range(7):
            head.on_mic_frame(frame)
        head.on_mic_frame(b"\x00" * 100)                                # not a frame of ours: ignored, never padded
        assert len(blocks) == 1 and blocks[0] == (frame * 5, 1600)      # five frames = one 100 ms block for Live
        for _ in range(3):
            head.on_mic_frame(frame)
        assert len(blocks) == 2
    await asyncio.sleep(0.02)
    assert cmds[-1] == {"mic": "close"}
    head.on_mic_frame(frame)
    assert len(blocks) == 2 and head.mic_frames == 11                   # closed: nothing reaches anyone (11 = the 10 + the odd one)


async def test_a_phone_beside_the_robot_is_its_microphone_and_is_not_heard_while_the_speaker_plays():
    async def command(**cmd):
        pass

    speaker = HeadSpeaker(Wire().publish)
    head = HeadAudio(speaker, command, renew_s=0.05, phone_tail_ms=60, phone_fresh_s=0.1)
    blocks: list[bytes] = []
    voice, zeros = np.full(320, 7, dtype="<i2").tobytes(), bytes(640)
    head.on_phone_frame(voice)                                          # nobody is listening: dropped unread
    assert head.phone_frames == 0 and head.mic_source == "phone"
    await asyncio.sleep(0.12)
    assert head.mic_source == "head"                                    # the phone went quiet: the head's own again
    with head.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=320,
                             callback=lambda data, n, t, status: blocks.append(bytes(data))):
        head.on_mic_frame(zeros)                                        # no phone yet: the head's microphone counts
        head.on_phone_frame(voice)
        head.on_mic_frame(zeros)                                        # a phone is the ear: the head's is not mixed in
        head.on_phone_frame(b"\x01" * 100)                              # not a frame: ignored
        assert blocks == [zeros, voice] and head.mic_source == "phone"
        speaker._play_until = time.monotonic() + 0.05                   # the head's speaker has sound of ours
        head.on_phone_frame(voice)
        await asyncio.sleep(0.07)
        head.on_phone_frame(voice)                                      # over, but inside the tail: still Kaiku's echo
        assert len(blocks) == 2 and head.phone_muted == 2
        await asyncio.sleep(0.06)
        head.on_phone_frame(voice)
        assert len(blocks) == 3 and head.phone_frames == 2


def test_auto_picks_the_head_when_one_is_alive_as_the_conversation_opens():
    class Device:
        def __init__(self, name):
            self.name, self.opened = name, []

        def RawInputStream(self, **kw):  # noqa: N802
            self.opened.append("in")
            return self

        def RawOutputStream(self, **kw):  # noqa: N802
            self.opened.append("out")
            return self

    head, local, alive = Device("head"), Device("local"), [False]
    auto = AutoAudio(head, local, lambda: alive[0])
    assert auto.name == "auto"
    auto.RawInputStream()
    auto.RawOutputStream()
    assert local.opened == ["in", "out"] and auto.name == "local"
    alive[0] = True
    auto.RawInputStream()                                               # the next conversation: the head is there now
    auto.RawOutputStream()
    assert head.opened == ["in", "out"] and auto.name == "head"         # both directions on the same body


# ------------------------------------------------------------------------------- no sound device on the hub
def test_the_hub_imports_and_builds_with_no_sounddevice_for_music_and_voice():
    """The hub runs on the robot's own computer (the UNO Q): no sound card, no `sounddevice`. Music and voice go
    through the head."""
    code = """
import os, sys
sys.modules["sounddevice"] = None            # `import sounddevice` now raises ImportError, as on the robot
os.environ.update(KAIKU_NO_DOTENV="1", KAIKU_MUSIC="lyria", KAIKU_VOICE="gemini", GEMINI_API_KEY="test-key-not-real",
                  KAIKU_MUSIC_OUT="head", KAIKU_VOICE_AUDIO="head", KAIKU_HUB_STORE_ENABLED="false")
os.environ.pop("KAIKU_MUSIC_FILE", None)
import kaiku_hub.live.lyria as lyria, kaiku_hub.live.gemini_live as live
from kaiku_hub.main import Hub
from kaiku_hub.settings import Settings
assert lyria.sd is None and live.sd is None
s = Settings.load()
s.cloud_url = None
hub = Hub(s, read_stdin=False)
assert hub.music.name == "lyria" and hub.music.audio is hub.speaker, (hub.music.name, hub.music.audio)
assert hub.voice.name == "gemini" and hub.voice.audio is hub.head_audio and hub.voice.audio_name == "head"
os.environ["KAIKU_VOICE_AUDIO"] = "auto"     # auto with no sound card here: the head too
hub2 = Hub(Settings.load(), read_stdin=False)
assert hub2.voice.name == "gemini" and hub2.voice.audio is hub2.head_audio
print("ok")
"""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), r.stderr[-1500:]
