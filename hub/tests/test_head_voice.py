"""Kaiku's Live voice through the robot head's own speaker and microphone (plan 07 section 4): the production adapter
(`GeminiLiveVoice`) on the real `HeadAudio`, with the model and the bus faked. What the head changes: half-duplex
(a gap in the microphone is never filled with silence), the ear press that stops Kaiku, one sender on the speaker."""

import asyncio
import io
import time
import wave
from types import SimpleNamespace as NS

import httpx
import numpy as np
import pytest
from kaiku_contracts import make, parse_topic
from kaiku_contracts.topics import AUDIO_FRAME_BYTES
from kaiku_hub.live import lines
from kaiku_hub.live.gemini_live import GeminiLiveVoice
from kaiku_hub.live.head_audio import HeadAudio, HeadSpeaker
from kaiku_hub.main import Hub

from hub.tests.test_head_audio import Wire
from hub.tests.test_live_integration import Client, Meter, settle

MIC_FRAME = np.full(320, 5000, dtype="<i2").tobytes()


def answer(seconds: float, value: int = 9000, *, done: bool = False):
    """A piece of the model's spoken answer: 24 kHz mono PCM, as Live sends it."""
    parts = [NS(inline_data=NS(data=np.full(int(24000 * seconds), value, dtype="<i2").tobytes()))]
    return NS(server_content=NS(model_turn=NS(parts=parts), turn_complete=done))


def turn_complete():
    return NS(server_content=NS(turn_complete=True))


class Robot:
    """The adapter with the head as its only audio device: what leaves on the speaker topic (`wire`), the
    `cmd.head` it sends (`cmds`), the fake model session."""

    def __init__(self, *, gap_s: float = 0.15, renew_s: float = 0.05):
        self.wire, self.cmds = Wire(), []

        async def command(**cmd):
            self.cmds.append(cmd)

        self.speaker = HeadSpeaker(self.wire.publish, lead_ms=80, gain=1.0)
        self.head = HeadAudio(self.speaker, command, renew_s=renew_s)
        self.client = Client()
        self.voice = GeminiLiveVoice("fake-live", client=self.client, audio=self.head, meter_factory=Meter, stall_s=0.01)
        self.voice.mic_gap_end_s = gap_s

    async def open(self):
        assert await self.voice.open_session("Test persona", [])
        await settle(lambda: self.head.mic is not None and self.voice._out is not None)
        return self.client.connections[-1].session

    async def hear(self, frames: int, *, bursts: bool = True) -> None:
        """Microphone frames as the firmware sends them: one or two every 32 ms (512-sample capture blocks)."""
        sent, t0 = 0, time.monotonic()
        while sent < frames:
            due = min(frames, int((time.monotonic() - t0) / 0.02) + 1) if bursts else sent + 1
            for _ in range(due - sent):
                self.head.on_mic_frame(MIC_FRAME)
            sent = due
            await asyncio.sleep(0.032 if bursts else 0.02)

    def voice_frames(self) -> int:
        return len(self.wire.frames)


def sent_audio(session) -> list[bytes]:
    return [kw["audio"].data for kw in session.audio if "audio" in kw]


def stream_ends(session) -> int:
    return sum(1 for kw in session.audio if kw.get("audio_stream_end"))


async def test_the_live_voice_listens_and_speaks_through_the_head_only():
    r = Robot()
    assert r.voice.audio_name == "head"
    session = await r.open()
    await settle(lambda: {"mic": "open"} in r.cmds)                    # the head's microphone is asked for, and held
    await r.hear(25)                                                   # half a second of her voice
    await settle(lambda: len(sent_audio(session)) == 5)
    blobs = session.audio[:5]
    assert all(kw["audio"].mime_type == "audio/pcm;rate=16000" and kw["audio"].data == MIC_FRAME * 5 for kw in blobs)
    assert stream_ends(session) == 0                                   # bursts of frames are not gaps

    await session.incoming.put(answer(0.5, done=True))                 # Kaiku answers
    await settle(lambda: r.voice_frames() >= 25, timeout=3)
    frames = r.wire.frames
    assert all(len(d) == AUDIO_FRAME_BYTES for _t, d in frames)        # 16 kHz mono 20 ms frames, resampled from 24 kHz
    assert abs(int(np.frombuffer(frames[10][1], "<i2")[160]) - 9000) < 200
    assert frames[-1][0] - frames[0][0] == pytest.approx(0.5 - 0.08, abs=0.08)   # in real time, the cushion ahead
    assert r.cmds.count({"mic": "open"}) >= 3                          # held open again and again while it lasts

    await r.voice.close_session()
    await asyncio.sleep(0.03)
    assert r.cmds[-1] == {"mic": "close"} and r.head.mic is None       # the conversation is over: the microphone too
    assert r.wire.sent[-1][1] == b""                                   # and whatever the head still held is dropped
    n = len(session.audio)
    r.head.on_mic_frame(MIC_FRAME)                                     # a late frame reaches nobody
    await asyncio.sleep(0.02)
    assert len(session.audio) == n


async def test_a_gap_in_the_heads_microphone_is_a_gap_never_silence_and_the_server_is_told_once():
    """While the head speaks it sends no microphone frames. Nothing is made up for that time (silence would look
    like the end of her turn): after `mic_gap_end_s` the server hears once that the stream paused."""
    r = Robot(gap_s=0.15)
    session = await r.open()
    await r.hear(15)
    await settle(lambda: len(sent_audio(session)) == 3)
    await asyncio.sleep(0.5)                                           # the head is speaking: no frames at all
    assert len(sent_audio(session)) == 3 and stream_ends(session) == 1   # no blob of silence; one "paused", not three
    assert all(blob.count(MIC_FRAME) == 5 for blob in sent_audio(session))
    await r.hear(10)                                                   # she speaks again: the stream resumes by itself
    await settle(lambda: len(sent_audio(session)) == 5)
    await asyncio.sleep(0.4)
    assert stream_ends(session) == 2                                   # and the next gap is told once again
    await r.voice.close_session()


async def test_a_press_of_the_ear_stops_what_kaiku_is_saying_and_the_rest_of_that_answer():
    """No voice barge-in on the robot (its microphone is shut while it speaks): the ear press is the way."""
    r = Robot()
    session = await r.open()
    await session.incoming.put(answer(2.0))                            # a long answer begins
    await settle(lambda: r.voice_frames() >= 8, timeout=3)
    r.voice.quiet()
    await asyncio.sleep(0.08)
    n = r.voice_frames()
    assert r.wire.sent[-1][1] == b"" and n < 30                        # the head drops its buffer; most was never sent
    await session.incoming.put(answer(1.0, done=True))                 # the rest of the same answer still arrives
    await asyncio.sleep(0.25)
    assert r.voice_frames() == n and not r.speaker.playing             # ... and is not played
    assert r.voice._session is not None and r.head.mic is not None     # the conversation stays open
    await session.incoming.put(answer(0.2, 7000, done=True))           # her next question gets its answer aloud
    await settle(lambda: r.voice_frames() >= n + 9, timeout=3)
    assert abs(int(np.frombuffer(r.wire.frames[-3][1], "<i2")[160]) - 7000) < 200
    r.voice.quiet()                                                    # nothing is being said: nothing is skipped later
    await session.incoming.put(answer(0.2, 6000, done=True))
    await settle(lambda: abs(int(np.frombuffer(r.wire.frames[-3][1], "<i2")[160]) - 6000) < 200, timeout=3)
    await r.voice.close_session()


async def test_the_hub_quiets_kaiku_when_the_ear_is_pressed(settings):
    class Voice:
        name, wants_session, quieted = "gemini", False, 0
        on_partial_utterance = on_completed_utterance = on_speech_features = None

        def quiet(self):
            self.quieted += 1

        async def start(self, *a, **k): ...
        async def say(self, text): ...
        async def send_context(self, text): ...
        async def close_session(self): ...
        async def stop(self): ...

    settings.cloud_url = None
    hub = Hub(settings, voice=Voice(), read_stdin=False)

    async def raw(payload):
        env = make("raw.head.ear", payload, source="head", home_id=settings.home_id)
        await hub.on_raw(parse_topic(f"kaiku/v1/{settings.home_id}/raw/head/ear"), env)

    await raw({"value": 3, "delta": 1, "pressed": False})              # a turn of the ear is not a press
    assert hub.voice.quieted == 0
    await raw({"value": 3, "delta": 0, "pressed": True})
    assert hub.voice.quieted == 1


async def test_music_and_the_live_voice_share_the_heads_speaker_without_interleaving():
    """The real adapter and a music stream on the one `HeadSpeaker`: Kaiku's words go out at once, whole, with
    nothing of the song inside them; the song goes on after."""
    r = Robot()
    session = await r.open()
    music = r.speaker.RawOutputStream(samplerate=48000, channels=2, dtype="int16")
    song = asyncio.create_task(asyncio.to_thread(music.write, np.full(int(48000 * 0.6) * 2, 4000, dtype="<i2").tobytes()))
    await asyncio.sleep(0.1)
    await session.incoming.put(answer(0.3, done=True))
    await song
    await asyncio.sleep(0.1)
    kinds = ["drop" if not d else "song" if abs(int(np.frombuffer(d, "<i2")[160]) - 4000) < 100 else "voice"
             for _t, d in r.wire.sent]
    first, last = kinds.index("voice"), len(kinds) - 1 - kinds[::-1].index("voice")
    assert kinds[first - 1] == "drop" and set(kinds[:first - 1]) == {"song"}
    assert set(kinds[first:last + 1]) == {"voice"} and kinds.count("voice") >= 14
    assert kinds.count("song") == 30 and set(k for k in kinds[last + 1:] if k != "drop") == {"song"}
    assert r.speaker.stats()["taken_by_voice"] == 1
    await r.voice.close_session()


# ------------------------------------------------------------------ scripted lines in Kaiku's cached voice
def spoken_wav(seconds: float, value: int = 8000, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.full(int(rate * seconds), value, dtype="<i2").tobytes())
    return buf.getvalue()


async def test_a_scripted_line_is_heard_from_the_heads_speaker_not_from_this_computer(monkeypatch):
    """The cached Gemini voice (the lines said when no Live conversation is open) used to be played by this
    machine's `afplay`/`aplay`. On the robot it goes out as frames to the head, like everything else."""
    played_here: list[int] = []

    async def local_player(data):
        played_here.append(len(data))

    monkeypatch.setattr(lines, "_play_wav", local_player)
    wire = Wire()
    speaker = HeadSpeaker(wire.publish, lead_ms=80, gain=1.0)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=spoken_wav(0.3),
                                                             headers={"content-type": "audio/wav"}))
    on_head = [True]
    lp = lines.LinePlayer(cloud_url="http://cloud", transport=transport, play_audio=True, head=speaker,
                          on_head=lambda: on_head[0])
    t = time.monotonic()
    await lp.say_line("greet.morning", "en")
    assert time.monotonic() - t >= 0.25                                # heard to its end before the ritual goes on
    await asyncio.sleep(0.03)
    assert len(wire.frames) == 15 and all(len(d) == AUDIO_FRAME_BYTES for _t, d in wire.frames)
    assert abs(int(np.frombuffer(wire.frames[7][1], "<i2")[160]) - 8000) < 200
    assert wire.sent[-1][1] == b"" and played_here == []
    await lp.say_text("Something Kaiku says that is not a keyed line.")   # POST /v1/voice/say: the same way out
    await asyncio.sleep(0.03)
    assert len(wire.frames) == 30 and played_here == []
    on_head[0] = False                                                 # [voice] audio = "local": this machine's player
    await lp.say_line("greet.morning", "en")
    assert len(played_here) == 1 and len(wire.frames) == 30


def test_scripted_lines_follow_the_voice_audio_setting(settings, monkeypatch):
    settings.cloud_url = None
    settings.voice_audio = "head"
    hub = Hub(settings, read_stdin=False)
    assert hub.lines.head is hub.speaker and hub._lines_on_head()
    settings.voice_audio = "local"
    assert not hub._lines_on_head()
    settings.voice_audio = "auto"
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    assert not hub._lines_on_head()                                    # no head on the bus, a player here
    hub.node_health["head"] = {"status": "ok", "details": {"sim": True}}
    assert not hub._lines_on_head()                                    # a simulated head is not a body to speak through
    hub.node_health["head"] = {"status": "ok", "details": {"firmware": "standalone"}}
    assert not hub._lines_on_head()                                    # nor a real one whose firmware cannot sound
    hub.node_health["head"] = {"status": "ok", "details": {"firmware": "standalone", "audio": {"rx": 0}}}
    assert hub._lines_on_head()                                        # a real one with the sound firmware is
    hub.node_health["head"] = {"status": "down"}
    assert not hub._lines_on_head()
    hub.node_health.clear()
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert hub._lines_on_head()                                        # the robot's own computer: nothing else to play on
