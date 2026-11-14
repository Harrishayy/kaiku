"""The drum step with real Lyria RealTime music: does it start, does it follow the taps?

    uv run python tools/drum_music_check.py                 # the music goes to logs/drum-music/<ts>/drum-music.wav
    uv run --extra live python tools/drum_music_check.py --speaker    # the music plays on this computer

Runs one whole ritual on the real hub over its own throwaway broker (ports 1883 and 8000 are never touched, the
cloud is off), with a stand-in head that answers the dial and drums in real time: 20 taps at 100 bpm, then 30 at
130. The music is the real model (`[models].lyria_realtime`, GEMINI_API_KEY from `.env`): one paid session of about
30 s on the spend ledger (`KAIKU_SPEND_DB`, default the project's). Prints when each thing happened, and for a
file the tempo that is actually in the audio, six seconds at a time.

Exit code 0 when the music started, both tempos were sent and (file mode) the audio holds both tempos in order.

    uv run python tools/drum_music_check.py --tap-back          # Tap it back (D51) with the real model
    uv run python tools/drum_music_check.py --tap-back --beat   # the same with the hub's own beat: no model, no cost

`--tap-back` runs a whole ritual whose drum step is the game, through the path the robot uses: the hub sends the
song as PCM frames on the bus (`[music] out = "head"`), and the sim's head twin (`sim/nodes/head_sim.py`) is the
person and the head: it answers the dials, taps each level back (level 1 within 2 %, level 2 about 7 % off, level
3 about 22 % off and then 3 % off on the replay) and records what its SPEAKER was sent into `head-speaker.wav`
(16 kHz mono, on the wall clock). One paid session of about 90 s (two started minutes). Checked from the head's
side: every level's song at its tempo, in order; no sound from her first tap of a turn until the band, and none for
at least 0.3 s before it (the head sends no tap around its own sound); frames in real time. Exit code 0 when the
bands are perfect / great / again-then-perfect and the audio agrees.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SLOW_BPM, FAST_BPM = 100, 130
TAP_BACK_ERRORS = [0.015, 0.07, 0.22, 0.03]  # how far off the stand-in taps, turn by turn


def onset_strength(x, sr: int):
    """Spectral flux of a mono signal: how much new sound starts in each 10 ms. Returns (flux, frames per second)."""
    import numpy as np

    n, hop = (2048, 512) if sr >= 32000 else (1024, 160)
    if len(x) < n + hop:
        return np.zeros(0), sr / hop
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    flux = np.maximum(0, np.diff(np.log1p(50 * np.abs(np.fft.rfft(frames, axis=1))), axis=0)).sum(axis=1)
    fps = sr / hop
    return np.maximum(flux - np.convolve(flux, np.ones(int(fps)) / int(fps), mode="same"), 0), fps


def tempo_near(x, sr: int, target: float, span: float = 0.15) -> tuple[float, float, float]:
    """The tempo the audio holds near `target`: the best-fitting tempo within +-`span` of it (quarter-bpm steps),
    its fit, and the best tempo anywhere from 55 to 200 bpm. The fit of a tempo is the autocorrelation of the
    onsets at one, two and four of its beats. Generated grooves also repeat at 3/4 and 4/3 of their beat (dotted
    and triplet figures), so "the best anywhere" can be such a relative: what is asked here is only whether the
    song runs at the tempo it was given, to the beat per minute."""
    import numpy as np

    flux, fps = onset_strength(x, sr)
    if flux.size < 4 * fps:
        return 0.0, 0.0, 0.0
    seg = flux - flux.mean()
    ac = np.correlate(seg, seg, "full")[len(seg) - 1:]
    ac = ac / (ac[0] + 1e-9)

    def fit(bpm: float) -> float:
        lag = 60 / bpm * fps
        lags = [lag * k for k in (1, 2, 4) if lag * k < len(ac) - 1]
        return float(sum(np.interp(lg, np.arange(len(ac)), ac) for lg in lags) / 3)

    near = max(np.arange(target * (1 - span), target * (1 + span) + 0.01, 0.25), key=fit)
    return float(near), fit(float(near)), float(max(np.arange(55, 200.5, 0.5), key=fit))


def tempo_windows(path: Path, candidates: tuple[int, ...] = (90, SLOW_BPM, FAST_BPM)) -> list[tuple[float, int]]:
    """(window start in s, the candidate tempo that fits it best) for every 6 s window, 2 s apart.
    Onsets by spectral flux, then the autocorrelation at each candidate's beat, its double and its fourfold."""
    import numpy as np

    with wave.open(str(path)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, w.getnchannels()).mean(axis=1) / 32768
    n, hop = 2048, 512
    if len(x) < 8 * sr:
        return []
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    flux = np.maximum(0, np.diff(np.log1p(50 * np.abs(np.fft.rfft(frames, axis=1))), axis=0)).sum(axis=1)
    fps = sr / hop
    flux = np.maximum(flux - np.convolve(flux, np.ones(int(fps)) / int(fps), mode="same"), 0)
    win, step, out = int(6 * fps), int(2 * fps), []
    for a in range(0, len(flux) - win + 1, step):
        seg = flux[a:a + win] - flux[a:a + win].mean()
        ac = np.correlate(seg, seg, "full")[len(seg) - 1:]
        ac = ac / (ac[0] + 1e-9)

        def score(bpm: int, ac=ac) -> float:
            lag = 60 / bpm * fps
            return float(sum(ac[int(round(lag * k))] for k in (1, 2, 4) if int(round(lag * k)) < len(ac)) / 3)

        out.append((round(a / fps, 1), max(candidates, key=score)))
    return out


async def run(out: Path, speaker: bool) -> int:
    from kaiku_contracts import config

    config.load_dotenv()
    exe = shutil.which("mosquitto") or next((p for p in ("/opt/homebrew/sbin/mosquitto", "/usr/local/sbin/mosquitto",
                                                         "/usr/sbin/mosquitto") if Path(p).exists()), None)
    if not exe:
        print("mosquitto is not installed (make setup)")
        return 2
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    tmp = Path(tempfile.mkdtemp(prefix="kaiku-drum-"))
    (tmp / "m.conf").write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n")
    broker = subprocess.Popen([exe, "-c", str(tmp / "m.conf")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ.update(MQTT_HOST="127.0.0.1", MQTT_PORT=str(port))
    os.environ.pop("MQTT_USER", None)
    time.sleep(0.6)
    wav = out / "drum-music.wav"
    try:
        from kaiku_contracts.bus import Bus
        from kaiku_hub.live import lyria
        from kaiku_hub.live.base import OffVoice
        from kaiku_hub.main import Hub
        from kaiku_hub.settings import Settings

        t0 = time.monotonic()
        log: list[dict] = []

        def note(what: str, **kw) -> None:
            log.append({"t": round(time.monotonic() - t0, 2), "what": what, **kw})
            print(f"{log[-1]['t']:6.2f} s  {what}" + ("  " + json.dumps(kw) if kw else ""), flush=True)

        s = Settings.load()
        s.home_id, s.cloud_url = "drum-music-check", None
        s.queue_path, s.state_path, s.store_path = tmp / "q.sqlite", tmp / "state.json", tmp / "sessions.sqlite"
        s.greet_s, s.dial_s, s.breathe_s, s.drum_s, s.drum_idle_end_s, s.nudge_s, s.post_mood_s = 0.3, 8, 3, 60, 3, 0.5, 5
        if speaker:
            os.environ.pop("KAIKU_MUSIC_FILE", None)
        else:
            os.environ["KAIKU_MUSIC_FILE"] = str(wav)
        ok, why = lyria.available(s.lyria_model)
        if not ok:
            print(f"the music adapter cannot start: {why}")
            return 2

        class Timed(lyria.LyriaMusic):
            sent: list[int] = []

            async def start(self, mood=None):
                t = time.monotonic()
                await super().start(mood)
                note("music started" if self._session is not None else "music did NOT start",
                     took_s=round(time.monotonic() - t, 2), mood=mood, prompt=lyria.MOOD_PROMPTS.get(mood or 3))

            async def set_tempo(self, bpm, force):
                before = self._bpm
                await super().set_tempo(bpm, force)
                if self._bpm != before:
                    Timed.sent.append(self._bpm)
                    note("tempo sent to Lyria", bpm=self._bpm, density=round(0.3 + 0.6 * force, 2))

        class Paced(lyria.WavOut):
            """The file takes audio in real time, like a speaker: what is in it is what would have been heard."""

            def write(self, data: bytes) -> None:
                if not getattr(self, "began", False):
                    self.began = True
                    note("first audio")
                super().write(data)
                time.sleep(len(data) / (48000 * 4))

        music = Timed(s.lyria_model, s.bpm_min, s.bpm_max, audio=None if speaker else Paced(str(wav)))
        seen: list = []
        fake = Bus("sensors", home_id=s.home_id, sim=True, heartbeat=False)
        head = Bus("head", home_id=s.home_id, sim=True)

        async def dial(values):
            for v in values:
                await asyncio.sleep(0.15)
                await head.publish("raw.head.ear", {"value": v, "delta": 1})
                await head.publish("raw.head.ear", {"value": v, "delta": 0, "pressed": True})

        async def drum():
            await asyncio.sleep(1.5)
            t_ms = 10_000
            note(f"first tap, {SLOW_BPM} bpm")
            for i, gap in enumerate([60000 // SLOW_BPM] * 20 + [60000 // FAST_BPM] * 30):
                await head.publish("raw.head.tap", {"t_ms": t_ms})
                if i == 20:
                    note(f"she speeds up to {FAST_BPM} bpm")
                t_ms += gap
                await asyncio.sleep(gap / 1000)
            note("last tap")

        async def on_obs(_topic, env):
            seen.append(env)
            if env.type == "obs.ritual" and env.payload.status == "started":
                if env.payload.step == "greet":
                    asyncio.create_task(dial([3]))
                elif env.payload.step == "dial":
                    asyncio.create_task(dial([4, 2, 5]))
                elif env.payload.step == "drum":
                    note("drum step started")
                    asyncio.create_task(drum())
            elif env.type == "obs.drum_session":
                note("obs.drum_session", **{k: v for k, v in env.payload.model_dump().items() if v is not None})
                asyncio.create_task(dial([5]))

        fake.on("obs/#", on_obs)
        hub = Hub(s, voice=OffVoice(), music=music, read_stdin=False)
        stop = asyncio.Event()
        async with fake, head:
            task = asyncio.create_task(hub.run(stop))
            await asyncio.wait_for(hub.bus.connected.wait(), 5)
            await fake.publish("cmd.hub", {"start_ritual": True}, source="cloud")
            for _ in range(1800):
                if any(e.type == "obs.ritual" and e.payload.step == "close" and e.payload.status != "started" for e in seen):
                    break
                await asyncio.sleep(0.05)
            stop.set()
            await asyncio.wait_for(task, 8)
        (out / "run.json").write_text(json.dumps(log, indent=1))

        started = any(e["what"] == "music started" for e in log)
        followed = SLOW_BPM in Timed.sent and FAST_BPM in Timed.sent
        print(f"\nmusic started: {started} · tempos sent: {Timed.sent}")
        if speaker:
            print("played on this computer; nothing was saved to judge the tempo from")
            return 0 if started and followed else 1
        windows = tempo_windows(wav)
        print("tempo in the audio, by 6 s window: " + " ".join(f"{int(a)}s:{b}" for a, b in windows))
        heard = [b for _a, b in windows]
        in_order = SLOW_BPM in heard and FAST_BPM in heard and heard.index(FAST_BPM) > heard.index(SLOW_BPM)
        print(f"audio holds {SLOW_BPM} then {FAST_BPM} bpm: {in_order} · file: {wav}")
        return 0 if started and followed and in_order else 1
    finally:
        broker.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


async def run_tap_back(out: Path, beat: bool, broker_port: int = 0) -> int:
    """Tap it back end to end: hub -> PCM frames on the bus -> the head twin's speaker (a WAV), the twin taps back."""
    import numpy as np
    from kaiku_contracts import config

    config.load_dotenv()
    exe = shutil.which("mosquitto") or next((p for p in ("/opt/homebrew/sbin/mosquitto", "/usr/local/sbin/mosquitto",
                                                         "/usr/sbin/mosquitto") if Path(p).exists()), None)
    if not exe:
        print("mosquitto is not installed (make setup)")
        return 2
    with socket.socket() as so:
        so.bind(("127.0.0.1", broker_port))  # 0 = any free port; a fixed one lets another tool listen in
        port = so.getsockname()[1]
    tmp = Path(tempfile.mkdtemp(prefix="kaiku-tapback-"))
    (tmp / "m.conf").write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n")
    broker = subprocess.Popen([exe, "-c", str(tmp / "m.conf")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wav = out / "head-speaker.wav"
    os.environ.update(MQTT_HOST="127.0.0.1", MQTT_PORT=str(port), KAIKU_HOME_ID="tap-back-check",
                      KAIKU_SIM_HEAD_AUDIO=str(wav))
    for key in ("MQTT_USER", "KAIKU_MUSIC_FILE", "KAIKU_SIM_HEAD_MIC"):
        os.environ.pop(key, None)
    time.sleep(0.6)
    try:
        from kaiku_contracts.bus import Bus
        from kaiku_hub.live import lyria
        from kaiku_hub.live.base import Voice
        from kaiku_hub.main import Hub
        from kaiku_hub.perception.tap_back import level_plan
        from kaiku_hub.settings import Settings

        from sim.nodes.head_sim import HeadSim

        t0 = time.monotonic()
        log: list[dict] = []

        def note(what: str, **kw) -> None:
            log.append({"t": round(time.monotonic() - t0, 2), "what": what, **kw})
            print(f"{log[-1]['t']:6.2f} s  {what}" + ("  " + json.dumps(kw) if kw else ""), flush=True)

        s = Settings.load()
        s.home_id, s.cloud_url, s.face_source = "tap-back-check", None, "off"
        s.queue_path, s.state_path, s.store_path = tmp / "q.sqlite", tmp / "state.json", tmp / "sessions.sqlite"
        s.greet_s, s.dial_s, s.breathe_s, s.nudge_s, s.post_mood_s = 0.3, 8, 3, 0.5, 6
        s.music, s.music_out = ("local" if beat else "lyria"), "head"  # the robot's path: the head's own speaker
        if beat:
            s.tap_back.mode = "tap_back"  # no generated song: the hub's own beat stands in
        else:
            ok, why = lyria.available(s.lyria_model, "head")
            if not ok:
                print(f"the music adapter cannot start: {why}")
                return 2
        levels = level_plan(datetime.now().astimezone().date(), s.tap_back)
        note("today's levels", bpm=[lv.bpm for lv in levels], taps=[lv.taps for lv in levels],
             listen_s=s.tap_back.listen_s, music=s.music, out=s.music_out)

        class Lines(Voice):
            name = "check"

            async def say(self, text: str) -> None:
                note("Kaiku says", line=text)

        hub = Hub(s, voice=Lines(), read_stdin=False)
        music = hub.music
        if not beat and music.name != "lyria":
            print(f"the hub fell back to {music.name!r} music")
            return 2
        real = (music.start, music.song, music.hush)

        async def start(mood=None):
            t = time.monotonic()
            await real[0](mood)
            started = beat or music.can_play_songs
            note("music started" if started else "music did NOT start", took_s=round(time.monotonic() - t, 2), mood=mood)

        async def song(bpm):
            kind = await real[1](bpm)
            note("song asked", bpm=bpm, gives=kind)
            return kind

        async def hush():
            heard = round(music.heard_s(), 2)
            await real[2]()
            note("hush", heard_s=heard)

        music.start, music.song, music.hush = start, song, hush
        seen: list = []
        turn = {"taps": 0, "first": 0.0}
        head = HeadSim(mood=3, seed=11, dial="ear", drum="knock", tap_back_errors=TAP_BACK_ERRORS)
        watch = Bus("sim", home_id=s.home_id, sim=True, heartbeat=False)

        async def on_obs(_topic, env):
            seen.append(env)
            if env.type == "obs.ritual" and env.payload.status == "started":
                if env.payload.step == "greet":  # the person presses the ear: the conversation is theirs to start
                    await watch.publish("raw.head.ear", {"value": 3, "delta": 0, "pressed": True}, source="head")
                elif env.payload.step == "drum":
                    note("drum step started")
            elif env.type == "obs.tap_back":
                p = env.payload
                note("obs.tap_back", quality=env.quality, passed=p.levels_passed, error_pct=p.error_pct,
                     steadiness=p.steadiness, taps=p.taps, duration_s=p.duration_s, song=p.song)
                for lv in p.levels:
                    note(f"  level {lv.level}", **lv.model_dump(exclude={"level"}))
            elif env.type == "obs.drum_session":
                note("obs.drum_session (free drumming: the game did not run)")
            elif env.type == "obs.self_report" and env.payload.context == "post_activity":
                note("mood after", value=env.payload.value)

        async def on_head(_topic, env):
            c = env.payload
            if c.eyes == "listening" and c.bpm:
                note("head listens and shows the beat", bpm=c.bpm, pan_mode=c.pan_mode, chest=c.chest)
            elif c.eyes == "wide":
                turn.update(taps=0)
                note("head: your turn", pan_mode=c.pan_mode)
            elif c.eyes in ("happy", "soft", "neutral") and turn["taps"]:
                note("band face", eyes=c.eyes, taps_sent=turn["taps"], tapping_s=round(time.monotonic() - turn["first"], 2))
                turn.update(taps=0)

        async def on_tap(_topic, _env):
            if not turn["taps"]:
                turn["first"] = time.monotonic()
                note("first tap")
            turn["taps"] += 1

        async def on_chime(_topic, env):
            if env.payload.chime:
                note("buzzer", chime=env.payload.chime)

        watch.on("obs/#", on_obs)
        watch.on("cmd/head", on_head)
        watch.on("raw/head/tap", on_tap)
        watch.on("cmd/sensors", on_chime)
        stop, head_stop = asyncio.Event(), asyncio.Event()
        async with watch:
            task = asyncio.create_task(hub.run(stop))
            head_task = asyncio.create_task(head.run(head_stop))
            await asyncio.wait_for(hub.bus.connected.wait(), 5)
            await head.bus.connected.wait()
            await watch.publish("cmd.hub", {"start_ritual": True}, source="cloud")
            for _ in range(4800):
                if any(e.type == "obs.ritual" and e.payload.step == "close" and e.payload.status != "started" for e in seen):
                    break
                await asyncio.sleep(0.05)
            sent = hub.speaker.stats()
            head_stop.set()
            await asyncio.wait_for(head_task, 8)  # the twin closes its recording
            stop.set()
            await asyncio.wait_for(task, 8)

        # ---- what the HEAD's speaker got
        stats = json.loads(Path(str(wav) + ".json").read_text())
        with wave.open(str(wav)) as w:
            sr = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32768
        spans = stats["sound_spans_s"]
        joined: list[list[float]] = []  # one sound = stretches less than 0.25 s apart (a dry gap, or the cue chime
        for a, b in spans:              # coming straight after the song): the tempo is read over the whole of it
            if joined and a - joined[-1][1] < 0.25:
                joined[-1][1] = b
            else:
                joined.append([a, b])
        songs = [(a, b) for a, b in joined if b - a >= min(4.0, s.tap_back.replay_listen_s * 0.6)]
        game = next((e.payload for e in seen if e.type == "obs.tap_back"), None)
        played = [lv.bpm for lv in levels for _ in range(next((g.tries for g in game.levels if g.level == lv.number), 0))] \
            if game else []
        print(f"\nthe head's speaker ({wav.name}, {len(x) / sr:.1f} s at {sr} Hz mono), from the twin's side:")
        tempo_ok = len(songs) == len(played) and bool(played)
        for i, (a, b) in enumerate(songs):
            want = played[i] if i < len(played) else 0
            near, fit, best = tempo_near(x[int(a * sr):int(b * sr)], sr, want) if want else (0.0, 0.0, 0.0)
            good = bool(want) and abs(near - want) <= max(2.0, 0.03 * want)
            tempo_ok = tempo_ok and good
            print(f"  song {i + 1}: {a:6.2f}-{b:6.2f} s ({b - a:.1f} s)  asked {want} bpm  in the audio {near:.2f} bpm "
                  f"(fit {fit:.2f}; strongest anywhere {best:.1f})  {'ok' if good else 'NOT at its tempo'}")
        # Her turns, from the timeline: "your turn" -> her first tap -> the band. On the recording's clock (it starts
        # when the twin's speaker got its first frame) nothing may sound from her first tap until the band.
        offset = (head.speaker._t0 or t0) - t0
        cues = [e["t"] for e in log if e["what"] == "head: your turn"]
        firsts = [e["t"] for e in log if e["what"] == "first tap"]
        faces = [e["t"] for e in log if e["what"] == "band face"]
        quiet_ok = bool(cues)
        for i, cue in enumerate(cues):
            first = next((t for t in firsts if t >= cue), None)
            face = next((t for t in faces if t >= cue), None)
            if first is None or face is None:
                quiet_ok = False
                print(f"  her turn {i + 1}: no taps or no band in the timeline  NOT ok")
                continue
            q0, q1 = first - offset, face - offset
            peak = float(np.abs(x[int(max(0.0, q0) * sr):int(q1 * sr)]).max()) if q1 > q0 else 0.0
            before = max([end for _start, end in spans if end <= q0 + 0.02] or [0.0])
            ok = peak == 0.0 and q0 - before >= 0.3
            quiet_ok = quiet_ok and ok
            print(f"  her turn {i + 1}: taps from {q0:6.2f} to {q1:6.2f} s ({q1 - q0:.1f} s), loudest sample {peak:.4f}, "
                  f"the speaker's last sound ended {q0 - before:.2f} s before her first tap  {'ok' if ok else 'NOT quiet'}")
        print(f"  frames: {stats['frames_received']} received, {stats['frames_played']} played, "
              f"{stats['drop_messages']} drop messages, {stats['overflows']} overflows, {stats['wrong_size']} wrong size, "
              f"{stats['glitches']} dry gaps under 200 ms inside a sound {stats['glitch_at_s']}; "
              f"buffer at most {stats['max_buffered_ms']} ms; arrival every {stats['interval_mean_ms']} ms "
              f"(sd {stats['interval_sd_ms']}, max {stats['interval_max_ms']})")
        print(f"the hub's clock: {json.dumps(sent)}")
        bands = [(lv.band, lv.tries) for lv in game.levels] if game else []
        want_bands = [("perfect", 1), ("great", 1), ("perfect", 2)]
        started = any(e["what"] == "music started" for e in log)
        closed = any(e.type == "obs.ritual" and e.payload.step == "close" and e.payload.status == "completed" for e in seen)
        clean = stats["overflows"] == 0 and stats["wrong_size"] == 0
        print(f"\nmusic started: {started} · bands: {bands} (wanted {want_bands}) · every song at its tempo: {tempo_ok} · "
              f"quiet while she taps: {quiet_ok} · frames clean: {clean} (dry gaps inside a sound, as this twin heard "
              f"it: {stats['glitches']}) · ritual completed: {closed}")
        (out / "run.json").write_text(json.dumps({"timeline": log, "head": stats, "hub": sent,
                                                  "recording_starts_at_s": round(offset, 3)}, indent=1))
        print(f"files: {wav} · {out / 'run.json'}")
        return 0 if started and bands == want_bands and tempo_ok and quiet_ok and clean and closed else 1
    finally:
        broker.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--speaker", action="store_true", help="play on this computer instead of writing a file")
    ap.add_argument("--tap-back", action="store_true",
                    help="Tap it back (D51): the song through the head twin's speaker, the twin taps each level back")
    ap.add_argument("--beat", action="store_true", help="with --tap-back: the hub's own beat, no model and no cost")
    ap.add_argument("--broker-port", type=int, default=0,
                    help="with --tap-back: the throwaway broker's port (default: any free one), so that another tool "
                         "can listen in, e.g. make head-audio ARGS='check --port N --home tap-back-check'")
    ap.add_argument("--out", default="", help="folder for drum-music.wav and run.json (default logs/drum-music/<time>)")
    a = ap.parse_args()
    out = Path(a.out) if a.out else ROOT / "logs" / "drum-music" / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    logging_quiet()
    if a.tap_back:
        sys.exit(asyncio.run(run_tap_back(out, a.beat, a.broker_port)))
    sys.exit(asyncio.run(run(out, a.speaker)))


def logging_quiet() -> None:
    """The hub's JSON log lines would bury the few lines this check prints."""
    os.environ.setdefault("KAIKU_LOG_LEVEL", "warning")


if __name__ == "__main__":
    main()
