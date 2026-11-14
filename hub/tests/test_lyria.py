"""The drum music's playback rules, on a fake Lyria session and a fake speaker (no network, no sound)."""

import asyncio
import time
from array import array
from types import SimpleNamespace

import pytest

pytest.importorskip("google.genai")
from kaiku_hub.live import lyria, sounds  # noqa: E402

SECOND = 48000 * 4  # bytes of one second: 48 kHz, stereo, 16-bit


def tone(value: int, seconds: float = 1.0) -> bytes:
    return array("h", [value] * int(48000 * 2 * seconds)).tobytes()


class Session:
    def __init__(self):
        self.calls: list[str] = []
        self.incoming: asyncio.Queue = asyncio.Queue()

    async def set_weighted_prompts(self, prompts):
        self.calls.append("prompts")

    async def set_music_generation_config(self, config):
        self.calls.append(f"config bpm={config.bpm}")

    async def play(self):
        self.calls.append("play")

    async def reset_context(self):
        self.calls.append("reset")

    async def pause(self):
        self.calls.append("pause")

    async def stop(self):
        self.calls.append("stop")

    async def receive(self):
        while True:
            data = await self.incoming.get()
            yield SimpleNamespace(server_content=SimpleNamespace(audio_chunks=[SimpleNamespace(data=data)]))

    def send(self, data: bytes) -> None:
        self.incoming.put_nowait(data)


class Client:
    def __init__(self, session: Session):
        outer = self

        class _CM:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *a):
                return None

        self.aio = SimpleNamespace(live=SimpleNamespace(music=SimpleNamespace(connect=lambda model: _CM())))
        self.session = outer.session = session


class Speaker:
    """A device that takes `slice_s` of wall time for every quarter second of audio (a real one takes 0.25 s)."""

    def __init__(self, slice_s: float = 0.01):
        self.slice_s, self.played = slice_s, []

    def RawOutputStream(self, samplerate, channels, dtype):  # noqa: N802
        return self

    def start(self):
        return None

    def stop(self):
        return None

    def write(self, data: bytes) -> None:
        time.sleep(self.slice_s * len(data) / lyria.SLICE_BYTES)
        self.played.append(data)

    def seconds_of(self, value: int) -> float:
        return sum(len(d) for d in self.played if max(abs(x) for x in array("h", d)) == value) / SECOND


class Meter:
    def __init__(self, *a):
        pass

    def open(self):
        return None

    def start(self, on_cap):
        return None

    def stop(self):
        return None


async def started(speaker: Speaker) -> tuple[lyria.LyriaMusic, Session]:
    session = Session()
    music = lyria.LyriaMusic("fake-lyria", client=Client(session), audio=speaker, meter_factory=Meter)
    await music.start(4)
    assert session.calls == ["prompts", "config bpm=90", "play"]
    return music, session


async def test_audio_from_before_a_tempo_change_is_not_played():
    """Lyria sends seconds ahead: three seconds at the old tempo are waiting when she speeds up. The new tempo must
    be what is heard next, not three seconds later."""
    speaker = Speaker()
    music, session = await started(speaker)
    for _ in range(3):
        session.send(tone(1000))
    await asyncio.sleep(0.035)  # about three quarter-second pieces of the old tempo get played
    await music.set_tempo(130, 0.6)
    session.send(tone(2000))
    await asyncio.sleep(0.12)
    await music.stop()
    assert "config bpm=130" in session.calls and session.calls.index("reset") > session.calls.index("config bpm=130")
    assert speaker.seconds_of(2000) == pytest.approx(1.0, abs=0.01)  # all of the new tempo (its first piece fades in)
    assert speaker.seconds_of(1000) <= 1.5  # and not the three seconds that were waiting


async def test_a_cut_between_tempos_fades_out_and_in():
    speaker = Speaker()
    music, session = await started(speaker)
    session.send(tone(1000, 2.0))
    await asyncio.sleep(0.025)
    await music.set_tempo(130, 0.6)
    session.send(tone(2000))
    await asyncio.sleep(0.1)
    await music.stop()
    tails = [array("h", d) for d in speaker.played if len(d) == lyria.FADE_BYTES]
    assert tails and tails[0][-1] == 0 and tails[0][0] > 900  # the old tempo ends on silence
    first_new = next(array("h", d) for d in speaker.played if max(array("h", d)) > 1000)
    assert first_new[0] == 0 and first_new[-1] == 2000  # the new one starts from silence


async def test_a_slow_speaker_never_holds_the_hub():
    """A speaker write blocks for as long as the audio lasts. Taps and the bus must not wait behind it."""
    speaker = Speaker(slice_s=0.1)
    music, session = await started(speaker)
    session.send(tone(1000))
    ticks = 0
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.3:
        await asyncio.sleep(0.01)
        ticks += 1
    await music.stop()
    assert ticks >= 15


async def test_a_new_session_follows_from_its_own_start():
    """The tempo of yesterday's drumming must not hide today's first change."""
    music, session = await started(Speaker())
    await music.set_tempo(120, 0.6)
    await music.stop()
    session2 = Session()
    music.client = Client(session2)
    await music.start(3)
    await music.set_tempo(121, 0.6)  # one beat from yesterday's last tempo, far from today's opening 90
    await music.stop()
    assert "config bpm=121" in session2.calls


def test_faded_ramps():
    up = array("h", lyria.faded(tone(1000, 0.1), rising=True))
    assert up[0] == 0 and up[-1] == 1000 and up[48 * 15 * 2] == pytest.approx(500, abs=20)
    down = array("h", lyria.faded(tone(1000, 0.1), rising=False))
    assert down[-1] == 0 and down[0] == 1000


def test_wav_out_writes_the_session_to_a_file(tmp_path):
    out = lyria.WavOut(str(tmp_path / "m.wav")).RawOutputStream(samplerate=48000, channels=2, dtype="int16")
    out.start()
    out.write(tone(500, 0.5))
    out.stop()
    import wave

    with wave.open(str(tmp_path / "m.wav")) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (48000, 2, 24000)


# ------------------------------------------------------------------------------------------- Tap it back (D51)
async def test_song_sets_the_tempo_with_the_full_config_then_a_reset_and_drops_what_was_waiting():
    speaker = Speaker()
    music, session = await started(speaker)
    assert music.can_play_songs and music.tempo_by() == "music"
    for _ in range(3):
        session.send(tone(1000))                       # the opening groove, seconds ahead
    await asyncio.sleep(0.02)
    assert await music.song(104) == "music"
    assert session.calls[3:] == ["config bpm=104", "reset"]            # not paused: no second `play`
    session.send(tone(2000, 2.0))
    await asyncio.sleep(0.15)
    assert music.heard_s() == pytest.approx(2.0, abs=0.01)             # only the song counts as heard, all of it
    assert speaker.seconds_of(1000) <= 1.0
    await music.stop()


async def test_hush_pauses_the_session_goes_quiet_and_the_next_song_plays_again():
    speaker = Speaker()
    music, session = await started(speaker)
    await music.song(100)
    session.send(tone(1000, 4.0))                      # four seconds of song, sent ahead of time
    await asyncio.sleep(0.03)                          # under a second of it is played
    await music.hush()
    assert session.calls[-1] == "pause"
    session.send(tone(3000))                           # a chunk that was already on its way: never played
    await asyncio.sleep(0.1)
    assert speaker.seconds_of(1000) < 1.5 and speaker.seconds_of(3000) == 0
    assert music.heard_s() == 0.0 and music.can_play_songs            # quiet, but the session is still there
    tails = [array("h", d) for d in speaker.played if len(d) == lyria.FADE_BYTES]
    assert tails and tails[-1][-1] == 0                # it went quiet on a fade, not a click
    assert await music.song(126) == "music"
    assert session.calls[-3:] == ["config bpm=126", "reset", "play"]   # measured order: the new tempo from its first chunk
    session.send(tone(2000))
    await asyncio.sleep(0.08)
    assert speaker.seconds_of(2000) == pytest.approx(1.0, abs=0.01) and music.heard_s() == pytest.approx(1.0, abs=0.01)
    await music.stop()
    assert not music.can_play_songs


async def test_a_cue_is_played_on_the_same_output_after_the_song_went_quiet():
    speaker = Speaker()
    music, session = await started(speaker)
    await music.song(100)
    session.send(tone(1000, 2.0))
    await asyncio.sleep(0.02)
    await music.hush()
    seconds = await music.chime("your_turn")
    assert 0.2 < seconds < 0.8 and await music.chime("no such cue") == 0.0
    await asyncio.sleep(0.1)
    played = b"".join(speaker.played)
    assert sounds.chime("your_turn")[lyria.FADE_BYTES:] in played   # whole, after the song's faded end
    await music.stop()


async def test_a_dead_stream_is_not_a_song_and_the_hubs_own_beat_stands_in():
    """The receive loop ended under us (network, server): `can_play_songs` must say so, or auto mode would ask
    her to tap back a song that never plays."""
    speaker = Speaker()
    music, session = await started(speaker)

    async def ended():
        return
        yield  # pragma: no cover

    session.receive = ended
    music._task.cancel()
    music._task = asyncio.create_task(music._receive_loop())
    await asyncio.sleep(0.01)
    assert not music.can_play_songs and music.tempo_by() == "beat"
    assert await music.song(100) == "beat"             # forced mode still gets a tempo to tap back
    await asyncio.sleep(0.05)
    assert "config bpm=100" not in session.calls and music.heard_s() > 0
    assert any(max(array("h", d)) > 1000 for d in speaker.played)
    await music.stop()


async def test_a_session_that_never_started_cannot_play_songs():
    music = lyria.LyriaMusic("fake-lyria", client=Client(Session()), audio=Speaker(), meter_factory=Meter)
    assert not music.can_play_songs and music.heard_s() == 0.0
    await music.hush()                                 # no session: nothing to pause, nothing raised
    assert await music.chime("perfect") == 0.0         # no player yet: the cue is not claimed to have sounded
    await music.stop()


def test_the_adapter_needs_no_sound_device_when_the_music_goes_to_the_head(monkeypatch):
    monkeypatch.setattr(lyria, "sd", None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.delenv("KAIKU_MUSIC_FILE", raising=False)
    assert lyria.available("lyria-realtime-exp", "head") == (True, "")
    assert lyria.available("lyria-realtime-exp", "file") == (True, "")
    ok, why = lyria.available("lyria-realtime-exp", "speaker")
    assert not ok and "sounddevice" in why
    monkeypatch.delenv("GEMINI_API_KEY")
    assert not lyria.available("lyria-realtime-exp", "head")[0]


def test_a_realtime_file_is_a_record_of_when_things_were_heard(tmp_path):
    """`[music] out = "file"`: a write takes as long as its audio, and time without a write is silence in the file
    (so her turn is a silent stretch, as on a speaker)."""
    import wave

    out = lyria.WavOut(str(tmp_path / "m.wav"), realtime=True).RawOutputStream(samplerate=48000, channels=2, dtype="int16")
    t0 = time.monotonic()
    out.write(tone(500, 0.2))
    assert time.monotonic() - t0 == pytest.approx(0.2, abs=0.05)
    time.sleep(0.3)                                    # nothing playing
    out.write(tone(700, 0.1))
    out.stop()
    with wave.open(str(tmp_path / "m.wav")) as w:
        a = array("h", w.readframes(w.getnframes()))
    seconds = len(a) / 2 / 48000
    assert seconds == pytest.approx(0.6, abs=0.05)
    assert a[0] == 500 and a[-1] == 700 and a[int(48000 * 2 * 0.35)] == 0
