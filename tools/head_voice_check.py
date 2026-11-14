"""Kaiku's Live voice through the robot head's own microphone and speaker, with no sound device: one real exchange.

    uv run python tools/head_voice_check.py                     # the question is written to a WAV by macOS `say`
    uv run python tools/head_voice_check.py --question q.wav    # your own recording (16 kHz mono 16-bit)
    uv run python tools/head_voice_check.py --follow            # a head that runs its own ritual (standalone firmware)
    uv run python tools/head_voice_check.py --follow --robot    # the robot's own configuration, without the robot

What runs: the real hub over its own throwaway broker, a throwaway cloud on a free port with a temp database for the
session bootstrap (ports 1883 and 8000 are never touched), and the sim's head twin (`sim/nodes/head_sim.py`) as the
robot's head. `sounddevice` is made unimportable and this computer's audio player is switched off for the run, so
nothing can be heard or recorded here. A ritual is started, the person presses the ear (their consent to the
conversation), the hub opens the real Gemini Live session (`[models].gemini_live`, GEMINI_API_KEY from `.env`) with
the head as its only audio device, and then:

    question.wav -> the twin's microphone -> audio/head/mic -> hub -> Gemini Live
    Gemini Live -> hub -> audio/head/speaker -> the twin's speaker -> head-speaker.wav

One paid Live session of under two minutes on the spend ledger (`KAIKU_SPEND_DB`, default the project's). Prints when
each thing happened and the transcript of both sides. Exit code 0 when the session ran on the head's audio, the
question went in through the microphone topic, Kaiku's spoken answer came out on the speaker topic after it, the
microphone was closed at the end, and no sound device was loaded.

`--follow`: the head is the twin of the STANDALONE firmware and runs the ritual itself; the hub follows it. She wakes
the head and presses its ear at the greeting (her own start: the consent the conversation needs), the hub opens the
real Live session and the head's microphone, Kaiku says each step's line through the head, her spoken question is
answered, she turns and presses through the dials and skips the breathing, and in the head's drum step the hub
plays Tap it back with its own beat (no music model) while the microphone is closed; the ritual ends, Kaiku says
goodbye, the microphone and the session close. Exit code 0 when all of that happened, in that order, in ONE ritual.
One paid Live session of two to four started minutes.

`--follow --robot`: the configuration the real robot runs with, on twins. The person's record is `aino` and the
boards publish on `demo-aino` (`KAIKU_HOME_ID` / `KAIKU_HUB_ROBOT_HOME_ID`); Live voice AND the REAL Lyria songs go
through the head (`[voice] audio = head`, `[music] out = head`, `[tap_back] mode = auto`); her taps come only from
the head's own orientation sensor (`raw.head.tap {src: imu}`, no knock switch); she presses through the dials
without waiting for each line, to keep the paid sessions short (Live is capped at 118 s here). At the end it reads
the throwaway cloud's database and prints what was uplinked: every observation must have landed under `aino` and
none under `demo-aino`. `--beat` swaps Lyria for the hub's own beat (no music model). Two paid sessions: Live (two
started minutes) and Lyria (two started minutes).
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
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
QUESTION = "Hi Kaiku. I slept badly last night, and I feel a bit low today."


def free_port() -> int:
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def question_wav(path: Path, text: str) -> bool:
    """A spoken question as a file (16 kHz mono 16-bit), written by macOS `say -o`: nothing is played."""
    say = shutil.which("say")
    if not say:
        return False
    subprocess.run([say, "-o", str(path), "--data-format=LEI16@16000", text], check=True, timeout=60)
    return path.exists()


RECORD_HOME, ROBOT_HOME = "aino", "demo-aino"  # the person's record / the home id the robot's boards publish on


async def run(out: Path, question: Path | None, text: str, wait_s: float, follow: bool = False,
              robot: bool = False, beat: bool = False) -> int:
    from kaiku_contracts import config

    config.load_dotenv()
    exe = shutil.which("mosquitto") or next((p for p in ("/opt/homebrew/sbin/mosquitto", "/usr/local/sbin/mosquitto",
                                                         "/usr/sbin/mosquitto") if Path(p).exists()), None)
    if not exe:
        print("mosquitto is not installed (make setup)")
        return 2
    if question is None:
        question = out / "question.wav"
        if not question_wav(question, text):
            print("no --question WAV given and no macOS `say` to write one (16 kHz mono 16-bit)")
            return 2
    with wave.open(str(question)) as w:
        question_s = w.getnframes() / w.getframerate()
    tmp = Path(tempfile.mkdtemp(prefix="kaiku-headvoice-"))
    port, cloud_port = free_port(), free_port()
    (tmp / "m.conf").write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n"
                                "set_tcp_nodelay true\n")
    broker = subprocess.Popen([exe, "-c", str(tmp / "m.conf")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # The bootstrap cloud: its own database, template explanations (no Gemma), no key of its own (the robot's hub
    # holds the Live key; scripted lines then have no cached audio and stay text until the conversation is open).
    cloud_env = {k: v for k, v in os.environ.items()
                 if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CLOUD_PROJECT", "KAIKU_HOME_TOKEN",
                              "KAIKU_ADMIN_TOKEN")}
    cloud_env.update(KAIKU_DB_PATH=str(tmp / "cloud.sqlite"), KAIKU_DEMO_MODE="1", KAIKU_LLM="template",
                     KAIKU_NO_DOTENV="1", KAIKU_GENAI_BACKEND="api_key")
    cloud = subprocess.Popen([sys.executable, "-m", "uvicorn", "kaiku_cloud.api.main:app", "--port", str(cloud_port),
                              "--log-level", "warning"], cwd=ROOT, env=cloud_env,
                             stdout=open(tmp / "cloud.log", "w"), stderr=subprocess.STDOUT)
    wav = out / "head-speaker.wav"
    # follow mode: she lets Kaiku's first line begin before she talks (the twin's person starts only in a quiet moment)
    os.environ.update(MQTT_HOST="127.0.0.1", MQTT_PORT=str(port), KAIKU_HOME_ID="head-voice-check",
                      KAIKU_SIM_HEAD_AUDIO=str(wav), KAIKU_SIM_HEAD_MIC=str(question),
                      KAIKU_SIM_HEAD_MIC_DELAY_S="3.0" if follow else "1.0")
    for key in ("MQTT_USER", "KAIKU_MUSIC_FILE", "KAIKU_HOME_TOKEN"):
        os.environ.pop(key, None)
    try:
        for _ in range(120):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cloud_port}/healthz", timeout=1) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(0.25)
        else:
            print("the throwaway cloud did not start:\n" + (tmp / "cloud.log").read_text()[-2000:])
            return 2

        sys.modules["sounddevice"] = None  # type: ignore[assignment]  # `import sounddevice` now fails, as on the robot
        from kaiku_contracts.bus import Bus
        from kaiku_hub.live import gemini_live, lines
        from kaiku_hub.main import Hub
        from kaiku_hub.settings import Settings

        from sim.nodes.head_sim import HeadSim

        refused: list[int] = []

        async def no_player(data: bytes) -> None:  # this computer's afplay/aplay: never in this check
            refused.append(len(data))

        lines._play_wav = no_player
        t0 = time.monotonic()
        log: list[dict] = []

        def note(what: str, **kw) -> None:
            log.append({"t": round(time.monotonic() - t0, 2), "what": what, **kw})
            print(f"{log[-1]['t']:6.2f} s  {what}" + ("  " + json.dumps(kw) if kw else ""), flush=True)

        s = Settings.load()
        s.home_id, s.cloud_url, s.home_token, s.face_source = "head-voice-check", f"http://127.0.0.1:{cloud_port}", None, "off"
        if robot:
            s.home_id, s.robot_home_id = RECORD_HOME, ROBOT_HOME
        s.queue_path, s.state_path, s.store_path = tmp / "q.sqlite", tmp / "state.json", tmp / "sessions.sqlite"
        s.voice, s.voice_audio, s.music, s.music_out = "gemini", "head", "off", "head"
        s.greet_s, s.dial_s = 20, wait_s + 60  # the ritual waits at its first question while she talks
        if follow and robot and not beat:  # as on the robot: generated songs through the head, the game when they play
            s.music, s.tap_back.mode = "lyria", "auto"
        elif follow:  # the game in the head's drum step, with the hub's own beat: no music model
            s.music, s.tap_back.mode = "local", "tap_back"
        ok, why = gemini_live.available(s.gemini_live_model, object())
        if not ok:
            print(f"the Live adapter cannot start: {why}")
            return 2
        hub = Hub(s, read_stdin=False)
        voice = hub.voice
        if voice.name != "gemini" or voice.audio_name != "head":
            print(f"the hub's voice is {voice.name!r} on {getattr(voice, 'audio_name', '?')!r}, not Gemini Live on the head")
            return 2
        voice.keep_transcript = True  # in memory, for this printout only (a synthetic voice asks the question)
        note("hub built", voice=voice.name, audio=voice.audio_name, model=s.gemini_live_model,
             sounddevice=gemini_live.sd is not None, question_s=round(question_s, 2))

        real_open = voice.open_session

        async def open_session(*a, **kw):
            t = time.monotonic()
            opened = await real_open(*a, **kw)
            note("Live session open" if opened else "Live session did NOT open", took_s=round(time.monotonic() - t, 2))
            return opened

        voice.open_session = open_session
        if follow:
            if robot:
                voice.max_seconds = 118.0  # two started minutes of Live at most, whatever happens
                if not beat and hub.music.name != "lyria":
                    print(f"the hub's music is {hub.music.name!r}, not Lyria RealTime (key, model id, google-genai)")
                    return 2
            return await follow_run(out, hub, s, note, log, t0, wav, question, wait_s, refused, gemini_live,
                                    robot=robot, cloud_db=tmp / "cloud.sqlite")
        head = HeadSim(auto=False, dial="ear", drum="knock")
        watch = Bus("sim", home_id=s.home_id, sim=True, heartbeat=False)
        seen: list = []
        mic = {"n": 0, "first": None, "last": None, "bytes_ok": True}
        spk = {"n": 0, "drops": 0, "times": []}
        cmds: list[tuple[float, str]] = []

        def on_mic(data: bytes) -> None:
            now = round(time.monotonic() - t0, 2)
            mic.update(n=mic["n"] + 1, last=now, first=mic["first"] if mic["first"] is not None else now,
                       bytes_ok=mic["bytes_ok"] and len(data) == 640)

        def on_spk(data: bytes) -> None:
            if data:
                spk["n"] += 1
                spk["times"].append(time.monotonic() - t0)
            else:
                spk["drops"] += 1

        async def on_obs(_topic, env):
            seen.append(env)
            if env.type == "obs.ritual" and env.payload.status == "started":
                note("ritual step", step=env.payload.step)
                if env.payload.step == "greet":  # the person presses the ear: the conversation is theirs to start
                    await asyncio.sleep(0.3)
                    await watch.publish("raw.head.ear", {"value": 3, "delta": 0, "pressed": True}, source="head")
                    note("she presses the ear (consent to the conversation)")

        async def on_head(_topic, env):
            if env.payload.mic:
                if not cmds or cmds[-1][1] != env.payload.mic:
                    note(f"cmd.head mic: {env.payload.mic}")
                cmds.append((time.monotonic() - t0, env.payload.mic))

        watch.on("obs/#", on_obs)
        watch.on("cmd/head", on_head)
        watch.on_audio("mic", on_mic)
        watch.on_audio("speaker", on_spk)
        stop, head_stop = asyncio.Event(), asyncio.Event()
        answered_at = None
        async with watch:
            task = asyncio.create_task(hub.run(stop))
            head_task = asyncio.create_task(head.run(head_stop))
            await asyncio.wait_for(hub.bus.connected.wait(), 5)
            await head.bus.connected.wait()
            await asyncio.sleep(1.2)  # the head's first heartbeat: a head is alive
            await watch.publish("cmd.hub", {"start_ritual": True}, source="cloud")
            said = None
            deadline = time.monotonic() + wait_s
            while time.monotonic() < deadline:
                await asyncio.sleep(0.1)
                if said is None and head.mic.said_at is not None:
                    said = head.mic.said_at[0] - t0
                    note("she starts talking (the twin's microphone plays the question)")
                if said is not None and head.mic.said_at[1] - t0 + 0.1 < time.monotonic() - t0 and \
                        time.monotonic() - head.mic.said_at[1] > 0.3 and not any(e["what"] == "she stops talking" for e in log):
                    note("she stops talking")
                asked_end = head.mic.said_at[1] - t0 if head.mic.said_at else None
                after = [t for t in spk["times"] if asked_end is not None and t > asked_end + 0.2]
                if after and answered_at is None and time.monotonic() - head.mic.said_at[1] > 0.3:
                    answered_at = after[0]
                    note("Kaiku's answer starts on the head's speaker", after_her_last_word_s=round(after[0] - asked_end, 2))
                if answered_at is not None and spk["times"] and time.monotonic() - t0 - spk["times"][-1] > 2.5:
                    note("Kaiku has finished")
                    break
            transcript = [dict(t) for t in voice.transcript]
            heard_by_hub = hub.head_audio.mic_frames
            sent = hub.speaker.stats()
            note("the conversation ends")
            await hub.end_ritual()
            await asyncio.sleep(1.0)
            head_stop.set()
            await asyncio.wait_for(head_task, 8)
            stop.set()
            await asyncio.wait_for(task, 10)

        stats = json.loads(Path(str(wav) + ".json").read_text()) if Path(str(wav) + ".json").exists() else {}
        asked = head.mic.said_at
        print("\ntranscript (as Gemini Live heard and said it):")
        for line in transcript:
            print(f"  {line['role']:6}  {line['text'].strip()}")
        person = " ".join(t["text"] for t in transcript if t["role"] == "person").strip()
        kaiku_after = [t for i, t in enumerate(transcript) if t["role"] == "kaiku"
                       and any(p["role"] == "person" for p in transcript[:i])]
        print(f"\nmicrophone (audio/head/mic): {mic['n']} frames on the bus, first at {mic['first']} s, last at {mic['last']} s; "
              f"all 640 bytes: {mic['bytes_ok']}; the hub took {heard_by_hub}; the twin sent {head.mic.sent}, "
              f"held back {head.mic.muted} capture blocks while its speaker played, lost {head.mic.lost} frames of her words")
        print(f"speaker (audio/head/speaker): {spk['n']} frames, {spk['drops']} drop messages; the twin: "
              f"{json.dumps({k: v for k, v in stats.items() if k not in ('sound_spans_s', 'glitch_at_s')})}")
        print(f"sound on the head's speaker (s, the recording's clock): {stats.get('sound_spans_s')}")
        print(f"the hub's clock: {json.dumps(sent)}")
        opened = any(e["what"] == "Live session open" for e in log)
        closed = bool(cmds) and cmds[-1][1] == "close"
        no_device = gemini_live.sd is None and not refused
        went_in = asked is not None and mic["n"] > 0 and bool(person)
        came_out = answered_at is not None and bool(kaiku_after)
        print(f"\nLive on the head's audio: {opened} · her question went in through the microphone topic: {went_in} · "
              f"Kaiku's answer came out on the speaker topic: {came_out} · microphone closed at the end: {closed} · "
              f"no sound device, nothing played here: {no_device}")
        (out / "run.json").write_text(json.dumps({"timeline": log, "transcript": transcript, "mic": mic,
                                                  "speaker": {k: v for k, v in spk.items() if k != "times"},
                                                  "head": stats, "hub": sent}, indent=1))
        print(f"files: {question} · {wav} · {out / 'run.json'}")
        return 0 if opened and went_in and came_out and closed and no_device else 1
    finally:
        cloud.terminate()
        broker.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


async def follow_run(out: Path, hub, s, note, log: list[dict], t0: float, wav: Path, question: Path, wait_s: float,
                     refused: list[int], gemini_live, robot: bool = False, cloud_db: Path | None = None) -> int:
    """The same exchange on a head that runs its own ritual, and the game after it in the same ritual."""
    import sqlite3

    from kaiku_contracts.bus import Bus

    from sim.nodes.head_sim import StandaloneHeadSim

    voice = hub.voice
    os.environ["KAIKU_HOME_ID"] = hub.bus_home  # the twin is a board: it publishes on the robot's home id
    # this robot: no knock switch, her taps are felt by the head's own orientation sensor only (D55)
    head = StandaloneHeadSim(auto=False, seed=4, health_s=2.0, tap_back_errors=[0.02, 0.05, 0.03], drum="imu")
    os.environ["KAIKU_HOME_ID"] = s.home_id
    watch = Bus("sim", home_id=hub.bus_home, sim=True, heartbeat=False)
    tap_srcs: dict[str, int] = {}
    seen: list = []
    mic = {"n": 0, "first": None, "last": None, "bytes_ok": True, "while_closed": 0}
    spk = {"n": 0, "drops": 0, "times": []}
    cmds: list[tuple[float, str]] = []      # every cmd.head mic open/close, with its time
    marks: dict[str, float] = {}            # the first time each thing happened
    traces: list[dict] = []

    def now() -> float:
        return time.monotonic() - t0

    def mark(name: str) -> None:
        marks.setdefault(name, now())

    def on_mic(data: bytes) -> None:
        mic.update(n=mic["n"] + 1, last=round(now(), 2), first=mic["first"] if mic["first"] is not None else round(now(), 2),
                   bytes_ok=mic["bytes_ok"] and len(data) == 640)
        if cmds and cmds[-1][1] == "close" and now() - cmds[-1][0] > 0.5:
            mic["while_closed"] += 1        # a frame the head sent although it was told to close its microphone

    def on_spk(data: bytes) -> None:
        if data:
            spk["n"] += 1
            spk["times"].append(now())
        else:
            spk["drops"] += 1

    async def on_obs(_topic, env):
        seen.append(env)
        if env.type == "obs.ritual":
            note("the hub records", step=env.payload.step, status=env.payload.status)
        elif env.type == "obs.tap_back":
            mark("game_recorded")
            p = env.payload
            note("obs.tap_back", played=p.levels_played, passed=p.levels_passed, song=p.song,
                 bands=[lv.band for lv in p.levels])

    async def on_head(_topic, env):
        c = env.payload
        if c.mic:
            if not cmds or cmds[-1][1] != c.mic:
                note(f"cmd.head mic: {c.mic}")
            cmds.append((now(), c.mic))
        if c.drum == "hold" and "hold" not in marks:
            mark("hold")
            note("the hub holds the head's drum step (Tap it back)")
        if c.drum == "end":
            mark("drum_end")
            note("the hub gives the drum step back")
        if c.eyes == "wide" and c.drum == "hold":
            marks["last_turn"] = now()
            note("your turn (the head's wide eyes)")

    async def on_trace(_topic, env):
        p = env.payload.model_dump(exclude_none=True)
        traces.append(p)
        if p["kind"] in ("said", "tool", "session"):
            note("trace", **p)

    async def on_tap(_topic, env):
        key = f"{env.source}/{env.payload.src}"
        tap_srcs[key] = tap_srcs.get(key, 0) + 1

    watch.on("obs/#", on_obs)
    watch.on("cmd/head", on_head)
    watch.on("raw/hub/trace", on_trace)
    watch.on("raw/head/tap", on_tap)
    watch.on_audio("mic", on_mic)
    watch.on_audio("speaker", on_spk)

    async def until(pred, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if pred():
                return True
            await asyncio.sleep(0.05)
        return bool(pred())

    async def quiet(after: float, settle_s: float = 1.2, at_most: float = 9.0) -> None:
        """Wait until the head's speaker has played something after `after` and gone quiet again."""
        await until(lambda: any(t > after for t in spk["times"]), at_most)
        await until(lambda: not spk["times"] or now() - spk["times"][-1] > settle_s, at_most)

    stop, head_stop = asyncio.Event(), asyncio.Event()
    answered_at = asked_end = None
    transcript: list[dict] = []
    async with watch:
        task = asyncio.create_task(hub.run(stop))
        head_task = asyncio.create_task(head.run(head_stop))
        await asyncio.wait_for(hub.bus.connected.wait(), 5)
        await head.bus.connected.wait()
        if not await until(lambda: hub.following, 8):
            print("the hub did not start following the head (health/head details.firmware = standalone)")
            return 2
        note("the hub follows the head (standalone firmware twin)")
        await asyncio.sleep(0.5)
        t = now()
        await head.press_ear()                      # idle -> its greeting
        note("she wakes the head: its greeting", step=head.mode)
        # Kaiku's invitation in the cached voice, when the cloud has it: she hears it out, then presses
        if await until(lambda: any(x > t for x in spk["times"]), 3.0):
            await until(lambda: now() - spk["times"][-1] > 1.2, 30.0)
            note("the invitation was heard to its end (the cached voice, through the head)")
        else:
            await asyncio.sleep(1.0)
        opened_before_press = [c for c in cmds if c[1] == "open"]
        session_before_press = voice.in_session
        await head.press_ear()                      # greet -> mood: she starts the ritual herself
        mark("press")
        note("she presses the ear at the greeting: her own start", step=head.mode)
        await until(lambda: voice.in_session and any(c[1] == "open" for c in cmds), 15)
        if voice.in_session:
            mark("live")
        # ---- her question, in the mood step, and Kaiku's answer through the head
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            if head.mic.said_at is not None and "asking" not in marks:
                mark("asking")
                note("she starts talking (the twin's microphone plays the question)")
            if head.mic.said_at is not None and time.monotonic() - head.mic.said_at[1] > 0.3:
                asked_end = head.mic.said_at[1] - t0
                if "asked" not in marks:
                    mark("asked")
                    note("she stops talking")
                after = [t for t in spk["times"] if t > asked_end + 0.2]
                if after and answered_at is None:
                    answered_at = after[0]
                    note("Kaiku's answer starts on the head's speaker", after_her_last_word_s=round(after[0] - asked_end, 2))
            if answered_at is not None and now() - spk["times"][-1] > 2.5:
                note("Kaiku has finished")
                break
        transcript = [dict(t) for t in voice.transcript]
        # ---- she answers the three dials on the ear; Kaiku says each step's line
        for turn in (2, -1, 1):
            t = now()
            await head.turn_ear(turn)
            await head.press_ear()
            note("she turns the ear and presses it", head_step=head.mode)
            if robot:
                await asyncio.sleep(1.0)            # she does not wait for each line (the paid sessions stay short)
            else:
                await quiet(t)
        t = now()
        await head.press_ear()                      # breathe -> drum: she skips the breathing
        note("she presses to skip the breathing", head_step=head.mode)
        head.auto = True                            # from here the twin is the person playing the game
        await until(lambda: "hold" in marks, 15)
        await until(lambda: "drum_end" in marks or head.mode != "drum", 240)
        note("the game is over", head_step=head.mode)
        # ---- the head's ritual ends: goodbye, then the microphone and the session close
        await until(lambda: head.mode in ("done", "idle"), 30)
        await until(lambda: not voice.in_session and bool(cmds) and cmds[-1][1] == "close", 25)
        note("the head's ritual is over", head_step=head.mode, live_open=voice.in_session)
        heard_by_hub = hub.head_audio.mic_frames
        sent = hub.speaker.stats()
        await until(lambda: hub.uplink.size() == 0, 20)   # everything recorded has reached the (throwaway) cloud
        note("uplink queue", left=hub.uplink.size())
        await asyncio.sleep(1.5)
        head_stop.set()
        await asyncio.wait_for(head_task, 8)
        stop.set()
        await asyncio.wait_for(task, 10)

    stats = json.loads(Path(str(wav) + ".json").read_text()) if Path(str(wav) + ".json").exists() else {}
    print("\ntranscript of her question and the answer (as Gemini Live heard and said it):")
    for line in transcript:
        print(f"  {line['role']:6}  {line['text'].strip()}")
    said = [p["text"] for p in traces if p["kind"] == "said" and p.get("by") == "live"]
    print("\nwhat Kaiku said through the head, from the hub's own trace (raw.hub.trace, her words are never in it):")
    for line in said:
        print(f"  {line}")
    print(f"\nmicrophone (audio/head/mic): {mic['n']} frames on the bus, first at {mic['first']} s, last at {mic['last']} s; "
          f"all 640 bytes: {mic['bytes_ok']}; the hub took {heard_by_hub}; the twin sent {head.mic.sent}, held back "
          f"{head.mic.muted} capture blocks while its speaker played, lost {head.mic.lost} frames of her words")
    print(f"speaker (audio/head/speaker): {spk['n']} frames, {spk['drops']} drop messages; the twin: "
          f"{json.dumps({k: v for k, v in stats.items() if k not in ('sound_spans_s', 'glitch_at_s')})}")
    print(f"the hub's clock: {json.dumps(sent)}")
    opens = [t for t, m in cmds if m == "open"]
    closes = [t for t, m in cmds if m == "close"]
    game = next((e.payload for e in seen if e.type == "obs.tap_back"), None)
    rituals = [(e.payload.step, e.payload.status) for e in seen if e.type == "obs.ritual"]
    person = " ".join(t["text"] for t in transcript if t["role"] == "person").strip()
    checks = {
        "nothing was listened to before her press": not opened_before_press and not session_before_press,
        "Live opened on her press, on the head's audio": "live" in marks and "press" in marks and marks["live"] >= marks["press"],
        "the microphone opened with it": bool(opens) and "press" in marks and opens[0] >= marks["press"],
        "her question went in through the microphone topic": asked_end is not None and mic["n"] > 0 and bool(person),
        "Kaiku answered through the head's speaker": answered_at is not None,
        "the game was played afterwards, in the same ritual": game is not None and game.levels_played >= 1
        and answered_at is not None and marks.get("game_recorded", 0) > answered_at
        and rituals.count(("greet", "started")) == 1 and ("close", "completed") in rituals,
        # closed as the game began, not opened again before her last turn, and the head sent nothing while closed
        "the microphone was closed for the game": "hold" in marks and "last_turn" in marks
        and any(marks["hold"] - 0.5 <= t <= marks["hold"] + 2 for t in closes)
        and not [t for t in opens if marks["hold"] + 0.5 < t < marks["last_turn"] + 2] and mic["while_closed"] == 0,
        "the microphone and the session were closed at the end": bool(cmds) and cmds[-1][1] == "close" and not voice.in_session,
        "no sound device, nothing played here": gemini_live.sd is None and not refused,
    }
    landed: dict[str, dict[str, int]] = {}
    if cloud_db is not None and cloud_db.exists():
        db = sqlite3.connect(f"file:{cloud_db}?mode=ro", uri=True)
        for home, type_, n in db.execute("select home_id, type, count(*) from events group by 1, 2 order by 1, 2"):
            landed.setdefault(home, {})[type_] = n
        db.close()
    print(f"taps on the bus, by who reported them: {json.dumps(tap_srcs)}")
    print("what landed in the throwaway cloud (home: type = count):")
    for home, types in landed.items():
        print(f"  {home}: " + ", ".join(f"{t} = {n}" for t, n in types.items()))
    if robot:
        record = landed.get(s.home_id, {})
        checks["her taps came only from the head's own sensor (no knock switch)"] = (
            bool(tap_srcs) and set(tap_srcs) == {"head/imu"})
        checks[f"the record was uplinked under {s.home_id!r}, nothing under {hub.bus_home!r}"] = (
            record.get("obs.tap_back", 0) == 1 and record.get("obs.self_report", 0) == 3
            and record.get("obs.ritual", 0) >= 8 and hub.bus_home not in landed and hub.uplink.size() == 0)
        if s.music == "lyria":
            checks["the songs were generated music (Lyria), heard through the head"] = (
                game is not None and game.song == "music")
    print()
    for name, ok in checks.items():
        print(f"  {'ok ' if ok else 'NOT'}  {name}")
    (out / "run.json").write_text(json.dumps({
        "timeline": log, "transcript": transcript, "said_by_live": said, "mic_cmds": cmds, "marks": marks,
        "mic": mic, "speaker": {k: v for k, v in spk.items() if k != "times"}, "head": stats, "hub": sent,
        "game": game.model_dump(mode="json") if game is not None else None, "ritual": rituals,
        "taps_by_source": tap_srcs, "landed_in_cloud": landed,
        "traces": [p for p in traces if p["kind"] != "said"], "checks": checks}, indent=1))
    print(f"files: {question} · {wav} · {out / 'run.json'}")
    return 0 if all(checks.values()) else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--question", default="", help="a WAV of the person's question, 16 kHz mono 16-bit "
                                                   "(default: macOS `say` writes one; nothing is played)")
    ap.add_argument("--text", default=QUESTION, help="what `say` says when no --question is given")
    ap.add_argument("--wait", type=float, default=75.0, help="give up waiting for the answer after this many seconds")
    ap.add_argument("--robot", action="store_true",
                    help="with --follow: the real robot's configuration on twins (record aino, boards on demo-aino, "
                         "Live and REAL Lyria through the head, taps from the head's own sensor only), and what "
                         "landed in the throwaway cloud")
    ap.add_argument("--beat", action="store_true", help="with --robot: the hub's own beat instead of Lyria (no music model)")
    ap.add_argument("--follow", action="store_true",
                    help="the head runs its own ritual (standalone firmware twin): her press opens the conversation, "
                         "the question is answered, then Tap it back in the same ritual with the microphone closed")
    ap.add_argument("--out", default="", help="folder for the WAVs and run.json (default logs/head-voice/<time>)")
    a = ap.parse_args()
    out = Path(a.out) if a.out else ROOT / "logs" / "head-voice" / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("KAIKU_LOG_LEVEL", "warning")
    sys.exit(asyncio.run(run(out, Path(a.question) if a.question else None, a.text, a.wait, a.follow or a.robot,
                             a.robot, a.beat)))


if __name__ == "__main__":
    main()
