"""Head speaker + microphone over MQTT, with no hub and no model (plan 07 §4, ../../AGENTS.md).

The head (standalone firmware, MQTT firmware or this folder's bench program) plays what arrives on

    kaiku/v1/<home>/audio/head/speaker   raw PCM: signed 16-bit little-endian, mono, 16 000 Hz, 20 ms = 640 bytes
                                         a message; a zero-length message = drop what is buffered

and, only while `cmd.head {mic: "open"}` is held (re-sent every few seconds), sends its microphone on

    kaiku/v1/<home>/audio/head/mic       the same format

From the repo root (`make head-audio ARGS='...'` = `uv run python firmware/atech-head/bench/speaker_pcm/audio_test.py ...`):

    bench --host <broker>                 the two-minute test: 10 s test sound, a dropped sound, 5 s of microphone
    play  --host <broker> [--wav f.wav] [--seconds 10] [--bpm 100] [--drop]
    mic   --host <broker> [--seconds 5]   saves recordings/mic-<time>.wav (gitignored) + frames, gaps, level
    check --host <broker> [--seconds 20]  listens to ANOTHER sender (the hub) and checks it against the format
    hold  --host <broker> [--seconds 20] [--bpm 100]   leads the standalone head's drum step the way the hub does in
                                          "tap it back" (drum: hold, sway, your turn, drum: end) and reports its taps
    show  --host <broker> help|none       `cmd.head {show: help | none}`, the hub's crisis-path command: a help screen
                                          on a head with a display; on the robot's standalone head (no display) the
                                          ritual ends quietly and it stays calm
    fake-head --host <broker> [--drum]    a stand-in head for testing this tool: no hardware, no sound

This tool never plays or records sound on the computer it runs on: it publishes frames and writes WAV files.
Recordings are the person's voice: they stay on this computer, are gitignored, and must never be committed or uploaded
(root AGENTS.md rule 5). Needs paho-mqtt (in the repo's uv environment).
"""

from __future__ import annotations

import argparse
import array
import json
import math
import os
import secrets
import sys
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

RATE = 16000
FRAME_SAMPLES = 320
FRAME_BYTES = FRAME_SAMPLES * 2
FRAME_S = FRAME_SAMPLES / RATE  # 0.02
HERE = Path(__file__).resolve().parent


# ---------------------------------------------------------------- sound
def test_signal(seconds: float = 10.0, bpm: float = 100.0) -> array.array:
    """A click and a short note on every beat (C E G C, then again): easy to hear a gap, a stutter or a wrong tempo."""
    n = int(seconds * RATE)
    out = array.array("h", bytes(2 * n))
    beat = 60.0 / bpm
    notes = (523.25, 659.25, 783.99, 1046.5)
    k = 0
    while k * beat < seconds:
        start = int(k * beat * RATE)
        for i in range(int(0.004 * RATE)):  # click: 4 ms of 2 kHz, decaying
            if start + i < n:
                out[start + i] = int(16000 * math.sin(2 * math.pi * 2000 * i / RATE) * (1 - i / (0.004 * RATE)))
        f, n0, length, fade = notes[k % 4], start + int(0.06 * RATE), int(0.18 * RATE), int(0.01 * RATE)
        for i in range(length):  # note: 180 ms, 10 ms fades, about -9 dBFS
            if n0 + i >= n:
                break
            env = min(1.0, i / fade, (length - i) / fade)
            out[n0 + i] = int(11500 * env * math.sin(2 * math.pi * f * i / RATE))
        k += 1
    return out


def tone(seconds: float, hz: float = 660.0, level: int = 9000) -> array.array:
    n = int(seconds * RATE)
    fade = int(0.01 * RATE)
    return array.array("h", (int(level * min(1.0, i / fade, (n - i) / fade) * math.sin(2 * math.pi * hz * i / RATE))
                             for i in range(n)))


def read_wav(path: Path) -> array.array:
    """Any 16-bit PCM WAV -> mono 16 kHz (channels averaged, linear resampling: fine for a test)."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            sys.exit(f"{path}: {8 * w.getsampwidth()}-bit WAV; this tool reads 16-bit PCM only")
        ch, rate = w.getnchannels(), w.getframerate()
        raw = array.array("h", w.readframes(w.getnframes()))
    if sys.byteorder == "big":
        raw.byteswap()
    mono = raw if ch == 1 else array.array("h", (sum(raw[i:i + ch]) // ch for i in range(0, len(raw) - ch + 1, ch)))
    if rate == RATE:
        return mono
    n = int(len(mono) * RATE / rate)
    out = array.array("h", bytes(2 * n))
    for i in range(n):
        x = i * rate / RATE
        j = int(x)
        a, b = mono[j], mono[min(j + 1, len(mono) - 1)]
        out[i] = int(a + (b - a) * (x - j))
    return out


def le_bytes(samples: array.array) -> bytes:
    """Signed 16-bit little-endian, whatever this computer is."""
    if sys.byteorder == "little":
        return samples.tobytes()
    s = array.array("h", samples)
    s.byteswap()
    return s.tobytes()


def to_frames(samples: array.array) -> list[bytes]:
    s = array.array("h", samples)
    s.extend([0] * ((-len(samples)) % FRAME_SAMPLES))
    b = le_bytes(s)
    return [b[i:i + FRAME_BYTES] for i in range(0, len(b), FRAME_BYTES)]


def level(samples: array.array) -> dict:
    if not samples:
        return {"peak_dbfs": None, "rms_dbfs": None, "clipped": 0}
    peak = max(1, max(abs(x) for x in samples))
    rms = max(1.0, math.sqrt(sum(x * x for x in samples) / len(samples)))
    return {"peak_dbfs": round(20 * math.log10(peak / 32768), 1), "rms_dbfs": round(20 * math.log10(rms / 32768), 1),
            "clipped": sum(1 for x in samples if abs(x) >= 32767)}


# ---------------------------------------------------------------- MQTT
def connect(a: argparse.Namespace, name: str):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        sys.exit("paho-mqtt missing: run this through `make head-audio ARGS=...` (the repo's uv environment)")
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"kaiku-{name}-{secrets.token_hex(3)}")
    if a.user:
        c.username_pw_set(a.user, a.password or None)
    try:
        c.connect(a.host, a.port, keepalive=30)
    except OSError as e:
        sys.exit(f"no broker at {a.host}:{a.port} ({e}). Start one (`make broker`) or pass --host / --port.")
    try:  # send every frame at once: Nagle would hold the second of two small messages until the first is ACKed
        import socket

        c.socket().setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, AttributeError):
        pass
    c.loop_start()
    return c


def topics(home: str) -> dict[str, str]:
    base = f"kaiku/v1/{home}"
    return {"spk": f"{base}/audio/head/speaker", "mic": f"{base}/audio/head/mic", "cmd": f"{base}/cmd/head",
            "health": f"{base}/health/head", "tap": f"{base}/raw/head/tap", "pan": f"{base}/raw/head/pan",
            "sensors": f"{base}/cmd/sensors"}


def uuid7() -> str:
    ms = time.time_ns() // 1_000_000
    b = bytearray(ms.to_bytes(6, "big") + secrets.token_bytes(10))
    b[6] = 0x70 | (b[6] & 0x0F)
    b[8] = 0x80 | (b[8] & 0x3F)
    h = b.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def envelope(home: str, type_: str, payload: dict, source: str = "sim") -> str:
    """The contract envelope (contracts/python/kaiku_contracts/envelope.py), marked as a test sender."""
    ts = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return json.dumps({"v": 1, "id": uuid7(), "ts": ts, "home_id": home, "source": source, "type": type_,
                       "payload": payload, "sim": True}, separators=(",", ":"))


def send_stream(c, topic: str, frames: list[bytes], lead_ms: float) -> float:
    """One frame every 20 ms, `lead_ms` ahead of the clock (the hub runs about 80 ms ahead, never above 120)."""
    t0 = time.monotonic()
    behind = 0.0  # worst case of a frame leaving after its own slot on the clock: the lead was used up
    for i, f in enumerate(frames):
        wait = t0 + i * FRAME_S - lead_ms / 1000 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        behind = max(behind, time.monotonic() - (t0 + i * FRAME_S))
        c.publish(topic, f, qos=0, retain=False)
    time.sleep(max(0.0, t0 + len(frames) * FRAME_S - time.monotonic()))  # until the sound has had time to play
    return behind


class HeadHealth:
    """The head's own audio counters from `health/head` details.audio (the firmwares; the bench prints on USB)."""

    def __init__(self, c, topic: str):
        self.last: dict | None = None
        self.n = 0
        c.message_callback_add(topic, self._on)
        c.subscribe(topic, qos=1)

    def _on(self, _c, _u, msg) -> None:
        try:
            p = json.loads(msg.payload)["payload"]
        except (ValueError, KeyError, TypeError):
            return
        self.last, self.n = p, self.n + 1

    def audio(self) -> dict | None:
        return ((self.last or {}).get("details") or {}).get("audio")

    def wait_new(self, seconds: float) -> None:
        n, end = self.n, time.monotonic() + seconds
        while self.n == n and time.monotonic() < end:
            time.sleep(0.05)


# ---------------------------------------------------------------- play
def play(a: argparse.Namespace, c=None) -> int:
    own = c is None
    c = c or connect(a, "play")
    t = topics(a.home)
    health = HeadHealth(c, t["health"])
    samples = read_wav(Path(a.wav)) if a.wav else test_signal(a.seconds, a.bpm)
    if a.wav and a.seconds and len(samples) > int(a.seconds * RATE) and a.cut:
        samples = samples[:int(a.seconds * RATE)]
    frames = to_frames(samples)
    what = a.wav or f"test sound: a click and a note on every beat, {a.bpm:g} a minute"
    print(f"speaker: {len(frames)} frames ({len(frames) * FRAME_S:.1f} s) to {t['spk']}\n         {what}")
    time.sleep(0.6)  # retained health, if a firmware is on the broker
    before = health.audio()
    behind = send_stream(c, t["spk"], frames, a.lead_ms)
    print(f"         sent in real time, {a.lead_ms:g} ms ahead"
          + (f"; THIS computer fell {behind * 1000:.0f} ms behind the clock at one point (a gap then is not the head's fault)" if behind > 0.02 else ""))
    if a.drop:
        time.sleep(1.0)  # a pause the bench program reads as "the first sound is over"
        burst = to_frames(tone(0.4))
        for f in burst:
            c.publish(t["spk"], f, qos=0)
        c.publish(t["spk"], b"", qos=0)
        print(f"         then {len(burst)} frames at once (0.4 s of one note) and a zero-length message: the head must drop\n"
              "         what it had not played yet, so you hear a short blip (0.15 s or so), not a 0.4 s note")
        time.sleep(0.6)
    rc = 0
    if before is not None:
        health.wait_new(6.5)
        after = health.audio() or {}
        d = {k: after.get(k, 0) - before.get(k, 0) for k in ("rx", "drop", "dry")}
        sent = len(frames) + (20 if a.drop else 0)
        sounds = 2 if a.drop else 1
        print(f"head reports (health/head): {d['rx']} of {sent} frames received, {d['drop']} dropped, "
              f"ran dry {d['dry']} times (the end of each sound counts once: {sounds} expected), "
              f"longest loop pass {(health.last or {}).get('details', {}).get('loop_max_ms', '?')} ms")
        if d["rx"] < sent or d["drop"] or d["dry"] > sounds:
            print("  -> frames were lost or the sound had gaps: see the checklist in docs/robot-network-handover.md")
            rc = 1
    else:
        print("no health/head with audio counters on this broker (the bench program prints its counters on USB instead)")
    if own:
        c.loop_stop()
        c.disconnect()
    return rc


# ---------------------------------------------------------------- microphone
def mic(a: argparse.Namespace, c=None, seconds: float | None = None) -> int:
    own = c is None
    c = c or connect(a, "mic")
    t = topics(a.home)
    seconds = a.seconds if seconds is None else seconds
    got: list[tuple[float, bytes]] = []
    c.message_callback_add(t["mic"], lambda _c, _u, m: got.append((time.monotonic(), bytes(m.payload))))
    c.subscribe(t["mic"], qos=0)
    time.sleep(1.0)
    before = len(got)  # the microphone is not held open yet: every frame here is a privacy fault
    print(f"microphone: holding it open for {seconds:g} s ({t['cmd']} {{mic: open}} every 2 s)\n"
          "            >>> speak now, towards the head <<<")
    t_open = time.monotonic()
    while time.monotonic() - t_open < seconds:
        c.publish(t["cmd"], envelope(a.home, "cmd.head", {"mic": "open"}), qos=1)
        time.sleep(min(2.0, max(0.05, seconds - (time.monotonic() - t_open))))
    c.publish(t["cmd"], envelope(a.home, "cmd.head", {"mic": "close"}), qos=1)
    t_close = time.monotonic()
    time.sleep(1.5)
    if own:
        c.loop_stop()
        c.disconnect()

    held = [(ts, p) for ts, p in got[before:] if ts <= t_close + 0.3]
    after = [1 for ts, _ in got[before:] if ts > t_close + 0.3]  # 0.3 s: frames already on their way
    bad = [len(p) for _, p in held if len(p) != FRAME_BYTES]
    pcm = array.array("h", b"".join(p for _, p in held if len(p) == FRAME_BYTES))
    if sys.byteorder == "big":
        pcm.byteswap()  # little-endian on the wire
    times = [ts for ts, _ in held]
    gaps = [b - a_ for a_, b in zip(times, times[1:], strict=False) if b - a_ > 0.1]
    expected = int(seconds / FRAME_S)
    lv = level(pcm)
    first = (times[0] - t_open) if times else None
    print(f"  frames received     {len(held)} (about {expected} expected: 50 a second; the head sends 1-2 every 32 ms)")
    print(f"  first frame after   {first * 1000:.0f} ms" if first is not None else "  first frame after   never")
    print(f"  wrong-sized frames  {len(bad)}" + (f" (sizes {sorted(set(bad))})" if bad else ""))
    print(f"  gaps over 100 ms    {len(gaps)}" + (f" (longest {max(gaps) * 1000:.0f} ms)" if gaps else ""))
    print(f"  before it was open  {before} frames (must be 0)")
    print(f"  after it was closed {len(after)} frames (must be 0)")
    if pcm:
        print(f"  level               peak {lv['peak_dbfs']} dBFS, average {lv['rms_dbfs']} dBFS, {lv['clipped']} clipped samples")
        if lv["peak_dbfs"] < -30:
            print("     -> very quiet: raise MIC_GAIN in firmware/atech-head/kaiku_link/head_audio.h (speech should peak around -20 to -6 dBFS)")
        elif lv["clipped"] > len(pcm) // 1000:
            print("     -> clipping: lower MIC_GAIN in firmware/atech-head/kaiku_link/head_audio.h")
        out = Path(a.out) if a.out else HERE / "recordings" / f"mic-{datetime.now():%Y%m%d-%H%M%S}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(le_bytes(pcm))
        print(f"  saved               {len(pcm) / RATE:.1f} s -> {out}   (the person's voice: never commit or upload it)")
    ok = len(held) >= 0.8 * expected and not bad and not before and not after
    if not held:
        print("  -> no frames: is the head on this broker and this home id? Does its ear ring turn blue (the only\n"
              "     microphone light on the robot's head; an orange dot too on a head with a display)? Nothing is\n"
              "     sent while its speaker plays or for 250 ms after.")
    elif not ok:
        print("  -> FAIL: see the lines above")
    return 0 if ok else 1


# ---------------------------------------------------------------- check another sender
def check(a: argparse.Namespace) -> int:
    c = connect(a, "check")
    t = topics(a.home)
    got: list[tuple[float, int]] = []
    c.message_callback_add(t["spk"], lambda _c, _u, m: got.append((time.monotonic(), len(m.payload))))
    c.subscribe(t["spk"], qos=0)
    print(f"listening on {t['spk']} for {a.seconds:g} s ...")
    time.sleep(a.seconds)
    c.loop_stop()
    c.disconnect()
    frames = [(ts, n) for ts, n in got if n]
    flushes = sum(1 for _, n in got if n == 0)
    bad = sorted({n for _, n in frames if n != FRAME_BYTES})
    # a sound = frames with no pause over 300 ms; within it, lead = audio sent so far minus time gone by
    sounds: list[list[float]] = []
    for (ts, _n), prev in zip(frames, [None] + frames[:-1], strict=False):
        if prev is None or ts - prev[0] > 0.3:
            sounds.append([])
        sounds[-1].append(ts)
    print(f"  messages    {len(frames)} frames in {len(sounds)} sound(s), {flushes} zero-length (drop)")
    print(f"  frame size  {'all 640 bytes' if not bad else f'WRONG sizes {bad}'}")
    ok = bool(frames) and not bad
    for k, s in enumerate(sounds, 1):
        # audio sent so far minus time gone by, counted from the sound's first frame. The head starts a sound with a
        # 120 ms cushion: a sender more than that behind makes a gap; one far ahead fills the 500 ms ring.
        leads = [i * FRAME_S - (ts - s[0]) for i, ts in enumerate(s)]
        ahead, behind = max(leads), max(0.0, -min(leads))
        good = ahead <= 0.14 and behind <= 0.1
        ok = ok and good
        print(f"  sound {k:<2}    {len(s)} frames ({len(s) * FRAME_S:.1f} s): at most {ahead * 1000:.0f} ms ahead of the clock "
              f"(limit 140), {behind * 1000:.0f} ms behind (limit 100)  {'ok' if good else 'NOT ok'}")
    print("  -> PASS" if ok else "  -> FAIL" if frames else "  -> nothing was sent")
    return 0 if ok else 1


# ---------------------------------------------------------------- lead the drum step (no hub)
def hold(a: argparse.Namespace) -> int:
    """What the hub does to a standalone head in "tap it back", by hand: while the head is in ITS drum step, hold
    it (`cmd.head {drum: hold}` every 3 s), sway for the first half, "your turn" for the second, then `drum: end`."""
    c = connect(a, "hold")
    t = topics(a.home)
    st = {"step": None, "held": False, "moving": False, "taps": [], "chimes": []}

    def on(_c, _u, m) -> None:
        try:
            env = json.loads(m.payload)
            p = env["payload"]
        except (ValueError, KeyError, TypeError):
            return
        if m.topic == t["health"]:
            d = p.get("details") or {}
            st["step"], st["held"] = d.get("step"), st["held"] or bool(d.get("drum_held"))
        elif m.topic == t["tap"]:
            st["taps"].append((time.monotonic(), p.get("src", "imu"), p.get("force")))
        elif m.topic == t["pan"]:
            st["moving"] = st["moving"] or bool(p.get("moving"))
        elif m.topic == t["sensors"] and env.get("source") == "head":
            st["chimes"].append(p.get("chime"))

    c.on_message = on
    c.subscribe([(t["health"], 1), (t["tap"], 0), (t["pan"], 0), (t["sensors"], 1)])

    def send(**payload) -> None:
        c.publish(t["cmd"], envelope(a.home, "cmd.head", payload), qos=1)

    print("waiting for the head to be in its drum step (press the ear through mood, energy, sleep and the breathing;\n"
          f"or on USB: drum) ... up to {a.wait:g} s")
    end = time.monotonic() + a.wait
    while st["step"] != "drum" and time.monotonic() < end:
        time.sleep(0.1)
    if st["step"] != "drum":
        print(f"  -> the head never said step drum (last step: {st['step']}). Is the standalone firmware on this broker and home id?")
        return 1
    half = a.seconds / 2
    print(f"1. hold + sway at {a.bpm:g} a minute for {half:g} s: the head stays in its drum step (no countdown of its own, no\n"
          "   tap tones), sways on the beat, and taps are NOT reported while it moves")
    t0 = time.monotonic()
    send(drum="hold", eyes="listening", pan_mode="sway", bpm=a.bpm)
    while time.monotonic() - t0 < half:
        time.sleep(min(3.0, max(0.05, half - (time.monotonic() - t0))))
        send(drum="hold")
    t1 = time.monotonic()
    print(f"2. your turn for {half:g} s: the head stands still. TAP THE HEAD NOW, about once a second")
    send(drum="hold", eyes="wide", pan_mode="still")
    while time.monotonic() - t1 < half:
        time.sleep(min(3.0, max(0.05, half - (time.monotonic() - t1))))
        send(drum="hold")
    t2 = time.monotonic()
    print("3. drum: end: the head ends its drum step (end chime on the UNO Q buzzer, its two-note chirp, step done)")
    send(drum="end", pan_mode="still")
    time.sleep(3.0)
    c.loop_stop()
    c.disconnect()

    def count(lo: float, hi: float, src: str) -> int:
        return sum(1 for ts, s_, _f in st["taps"] if lo <= ts < hi and s_ == src)

    forces = [f for ts, s_, f in st["taps"] if t1 <= ts < t2 and s_ == "imu" and isinstance(f, (int, float))]
    print(f"  held (health/head drum_held)   {'yes' if st['held'] else 'NO: the head did not take the hold'}")
    print(f"  moving reported during sway    {'yes' if st['moving'] else 'no (no sway seen: motor power? SWAY_SPEED_PCT too low?)'}")
    print(f"  taps while swaying             motion sensor {count(t0, t1, 'imu')} (should be 0), knock {count(t0, t1, 'knock')}")
    print(f"  taps in your turn              motion sensor {count(t1, t2, 'imu')}, knock {count(t1, t2, 'knock')}"
          + (f"; force {min(forces):.2f} to {max(forces):.2f} g" if forces else ""))
    print(f"  end_drum chime after the end   {'yes' if 'end_drum' in st['chimes'] else 'NO'}; the head is now in step `{st['step']}`")
    ok = st["held"] and "end_drum" in st["chimes"]
    print("  -> the head followed the hold and the end" if ok else "  -> FAIL: see the lines above")
    return 0 if ok else 1


# ---------------------------------------------------------------- a stand-in head (to test this tool; no hardware)
def fake_head(a: argparse.Namespace) -> int:
    """Follows the head's rules: counts speaker frames, sends microphone frames (a 440 Hz note) only while the
    microphone is held open, not while speaker frames arrive nor 250 ms after, and closes after 10 s without a hold.
    `--leak` breaks the rule on purpose (frames without a hold) to show that `mic` catches it."""
    c = connect(a, "fake-head")
    t = topics(a.home)
    st = {"open_at": None, "spk_at": 0.0, "rx": 0, "flush": 0, "tx": 0, "held_at": None, "sway": False, "tap_at": 0.0,
          "step": "drum", "health_at": 0.0}

    def say(type_: str, topic: str, payload: dict, retain: bool = False) -> None:
        c.publish(topic, envelope(a.home, type_, payload, source="head"), qos=1, retain=retain)

    def health(step: str) -> None:
        say("health", t["health"], {"status": "ok", "version": "fake-head", "uptime_s": 1.0,
                                    "details": {"step": step, "firmware": "standalone", "drum_held": st["held_at"] is not None}})

    def on_spk(_c, _u, m) -> None:
        st["spk_at"] = time.monotonic()
        st["rx" if m.payload else "flush"] += 1

    def on_cmd(_c, _u, m) -> None:
        try:
            p = json.loads(m.payload)["payload"]
            v = p.get("mic")
        except (ValueError, KeyError, TypeError, AttributeError):
            return
        if v == "open":
            st["open_at"] = time.monotonic()
        elif v == "close":
            st["open_at"] = None
        if p.get("show") in ("help", "none"):
            if p["show"] == "help":
                st["open_at"] = None  # the microphone shuts with the help screen
            print(f"  show: {p['show']}", flush=True)
        if a.drum and p.get("drum") == "hold":  # the standalone head in its drum step
            st["held_at"] = time.monotonic()
            if "pan_mode" in p:
                st["sway"] = p["pan_mode"] == "sway"
                say("raw.head.pan", t["pan"], {"deg": 0, "homed": True, "moving": st["sway"]})
            health("drum")
        elif a.drum and p.get("drum") == "end" and st["held_at"] is not None:
            st["held_at"], st["sway"], st["step"] = None, False, "done"
            say("cmd.sensors", t["sensors"], {"chime": "end_drum"})
            health("done")

    c.message_callback_add(t["spk"], on_spk)
    c.message_callback_add(t["cmd"], on_cmd)
    c.subscribe([(t["spk"], 0), (t["cmd"], 1)])
    note = to_frames(array.array("h", (int(3277 * math.sin(2 * math.pi * 440 * i / RATE)) for i in range(RATE))))  # -20 dBFS
    print(f"stand-in head on {a.host}:{a.port}, home {a.home}" + (" (LEAKING on purpose)" if a.leak else "") + "; Ctrl-C to stop")
    end = time.monotonic() + a.seconds if a.seconds else None
    i, nxt, shown = 0, time.monotonic(), (0, 0, 0)
    try:
        while end is None or time.monotonic() < end:
            now = time.monotonic()
            if st["open_at"] is not None and now - st["open_at"] > 10.0:
                st["open_at"] = None  # the hub went quiet: close by itself
            quiet = now - st["spk_at"] > 0.25 + 0.12  # the last frame may still be playing
            if a.leak or (st["open_at"] is not None and quiet):
                c.publish(t["mic"], note[i % len(note)], qos=0)
                st["tx"] += 1
                i += 1
            if a.drum and now - st["health_at"] >= 2.0:  # never retained: a stand-in must not linger on a broker
                st["health_at"] = now
                health(st["step"])
            if st["held_at"] is not None and not st["sway"] and now - st["tap_at"] >= 0.6:  # a tap every 0.6 s, still only
                st["tap_at"] = now
                say("raw.head.tap", t["tap"], {"t_ms": int(now * 1000), "force": 1.2, "src": "imu"})
            nxt += FRAME_S
            time.sleep(max(0.0, nxt - time.monotonic()))
            if int(now) != int(now - FRAME_S) and (st["rx"], st["flush"], st["tx"]) != shown:
                shown = (st["rx"], st["flush"], st["tx"])
                print(f"  speaker frames in {st['rx']}, drops {st['flush']}, microphone frames out {st['tx']}", flush=True)
    except KeyboardInterrupt:
        pass
    c.loop_stop()
    c.disconnect()
    print(f"stand-in head: {st['rx']} speaker frames in, {st['flush']} drops, {st['tx']} microphone frames out")
    return 0


def show(a: argparse.Namespace) -> int:
    """The hub's crisis path sends this; here by hand, to see the help screen. No sound, no hold, no hub needed."""
    c = connect(a, "show")
    t = topics(a.home)
    c.publish(t["cmd"], envelope(a.home, "cmd.head", {"show": a.what}), qos=1).wait_for_publish(5)
    print(f"sent {{show: {a.what}}} to {t['cmd']}: " + (
        "a head WITH a display (the MQTT firmware) now shows the helpline's name, its number and the emergency number;\n"
        "the robot's standalone head has none: its ritual ends quietly, the microphone shuts, the motor stands still and\n"
        "it stays calm (health/head: help_shown false, help_screen none, calm true) until `none`, an ear press or\n"
        "10 minutes. No sound either way" if a.what == "help" else "the help screen is gone / the calm is over"))
    c.loop_stop()
    c.disconnect()
    return 0


def bench(a: argparse.Namespace) -> int:
    c = connect(a, "bench")
    a.drop = True
    rc = play(a, c)
    time.sleep(1.0)  # the head sends no microphone frames while its speaker sounds, nor 250 ms after
    rc |= mic(a, c, seconds=a.mic_seconds)
    c.loop_stop()
    c.disconnect()
    print("\nBy ear: even clicks and notes with no gaps, then one short blip. Then answer the bench checker's question.")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default=os.environ.get("MQTT_HOST", "localhost"), help="broker (default $MQTT_HOST or localhost)")
    common.add_argument("--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    common.add_argument("--user", default=os.environ.get("MQTT_USER", ""))
    common.add_argument("--password", default=os.environ.get("MQTT_PASS", ""), help="default $MQTT_PASS (never printed)")
    common.add_argument("--home", default="demo-aino", help="the home id the boards publish on (KAIKU_HOME_ID in secrets.h)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, helptext in (("play", "send a sound to the head's speaker"), ("bench", "play + drop + microphone: the two-minute test")):
        p = sub.add_parser(name, parents=[common], help=helptext)
        p.add_argument("--wav", help="a 16-bit PCM WAV instead of the built-in test sound")
        p.add_argument("--seconds", type=float, default=10.0, help="length of the test sound (default 10)")
        p.add_argument("--cut", action="store_true", help="with --wav: play only the first --seconds")
        p.add_argument("--bpm", type=float, default=100.0)
        p.add_argument("--lead-ms", type=float, default=80.0, help="how far ahead of the clock to send (default 80)")
        p.add_argument("--mic-seconds", type=float, default=5.0)
        p.add_argument("--out", help="microphone WAV path (default recordings/mic-<time>.wav)")
        if name == "play":
            p.add_argument("--drop", action="store_true", help="afterwards: 0.4 s at once + a zero-length message")
    p = sub.add_parser("mic", parents=[common], help="hold the head's microphone open and save what it sends")
    p.add_argument("--seconds", type=float, default=5.0)
    p.add_argument("--out", help="WAV path (default recordings/mic-<time>.wav)")
    p = sub.add_parser("show", parents=[common], help="the help screen: show help | show none")
    p.add_argument("what", choices=["help", "none"])
    p = sub.add_parser("check", parents=[common], help="check another sender's speaker frames (size, pacing, drop)")
    p.add_argument("--seconds", type=float, default=20.0)
    p = sub.add_parser("fake-head", parents=[common], help="a stand-in head for testing this tool")
    p.add_argument("--seconds", type=float, default=0.0, help="stop after this long (default: until Ctrl-C)")
    p.add_argument("--leak", action="store_true", help="send microphone frames without a hold (a broken head)")
    p.add_argument("--drum", action="store_true", help="also stand in its drum step and follow drum: hold | end")
    p = sub.add_parser("hold", parents=[common], help="lead the standalone head's drum step like the hub (no hub)")
    p.add_argument("--seconds", type=float, default=20.0, help="half swaying, half `your turn` (default 20)")
    p.add_argument("--bpm", type=float, default=100.0)
    p.add_argument("--wait", type=float, default=120.0, help="how long to wait for the head's drum step")
    a = ap.parse_args(argv)
    return {"play": play, "bench": bench, "mic": mic, "show": show, "check": check, "hold": hold,
            "fake-head": fake_head}[a.cmd](a)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
