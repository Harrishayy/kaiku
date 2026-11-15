"""Robot bench: the real robot's body, one deterministic step at a time, over the home broker. No model, no
microphone, nobody's words.

    make robot-bench                                  # every step that needs no person, in order
    make robot-bench ARGS="parts ring turn"           # only these steps
    make robot-bench ARGS="arm"                       # needs a person: press the ear when asked
    make robot-bench ARGS="--with-sound turn-waits-for-speaker"
    make robot-bench ARGS="--synthetic-face follow"   # the real hub WILL act on the made-up face
    make robot-bench ARGS="--json parts"

Each step SENDS one contract command as the hub would (`cmd.head`, `cmd.sensors`), WAITS for evidence a machine
can check on the bus, and prints one of
    PASS  the evidence arrived (with the numbers)
    FAIL  it did not
    LOOK  no machine can check this on the present firmware: what a person must see or hear
    SKIP  not run, and why
Exit code 0 only when nothing FAILED. The audio topics and `raw/hub/transcript` (the person's words, D63) are never
read: the bench does not subscribe to them and drops them if a broker sends them anyway.

Steps (default: all but the three that need a person, a sound or a made-up face):
    parts        health/head, health/sensors, health/hub are fresh; versions, camera_ok, hub talk and mic_source
    ring         the ear ring white, green, orange (firmware 0.8.0 has no readback: LOOK)
    turn         a turn left then right; raw/head/pan must say moving, then still
    buzzer       cmd.sensors {chime: ok} (LOOK: hear it)
    camera       camera_enable false = no face, no distance (its light out); true = distance comes back; then off
    face-signs   5 s of counting; one raw/sensors/face_signs with numbers only
    turn-waits-for-speaker   --with-sound: a turn asked for during sound must start only after it
    follow       --synthetic-face: a face at the right edge must make the hub ask for a turn toward it
    arm          asking twice (D58): armed drum + a person's press = step drum; ritual end = idle
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import struct
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kaiku_contracts import make  # noqa: E402
from kaiku_contracts.config import get  # noqa: E402
from kaiku_contracts.registry import to_json  # noqa: E402
from kaiku_contracts.topics import (  # noqa: E402
    AUDIO_FRAME_MS,
    AUDIO_FRAME_SAMPLES,
    AUDIO_RATE_HZ,
    audio_topic,
    is_audio_topic,
    topic_for,
)

from tools.busio import decode, mqtt_kwargs  # noqa: E402

STEPS = ("parts", "ring", "turn", "buzzer", "camera", "face-signs", "turn-waits-for-speaker", "follow", "arm")
DEFAULT = ("parts", "ring", "turn", "buzzer", "camera", "face-signs")  # no person, no sound, no made-up face
FILTERS = ("health/#", "raw/head/#", "raw/sensors/#", "raw/hub/face", "cmd/head")  # never audio, never transcript
HEALTH_MAX_AGE_S = 12.0
RING = (("white", "#ffffff"), ("green", "#28dc5a"), ("orange", "#ff8c28"))


# ------------------------------------------------------------------------------------------------ pure parts
@dataclass
class Result:
    step: str
    status: str  # PASS | FAIL | LOOK | SKIP
    text: str
    numbers: dict[str, Any] = field(default_factory=dict)


@dataclass
class Seen:
    """One message the bench heard: when (monotonic), its name under the home (`raw/head/pan`), its source and
    its payload. Nothing else of the envelope is kept."""

    t: float
    name: str
    source: str
    payload: dict[str, Any]
    ts: datetime | None = None
    retained: bool = False


def select(names: list[str]) -> list[str]:
    """The steps to run, in the bench's own order. None named = the default set. An unknown name is an error."""
    unknown = [n for n in names if n not in STEPS]
    if unknown:
        raise ValueError(f"no such step: {', '.join(unknown)} (steps: {', '.join(STEPS)})")
    wanted = set(names) if names else set(DEFAULT)
    return [s for s in STEPS if s in wanted]


def name_of(topic: str, home: str) -> str | None:
    """`kaiku/v1/<home>/raw/head/pan` -> `raw/head/pan`; None for another home, an audio topic or the person's
    words (`raw/hub/transcript`): those are never looked at."""
    parts = topic.split("/")
    if len(parts) < 5 or parts[:2] != ["kaiku", "v1"] or parts[2] != home or is_audio_topic(topic):
        return None
    name = "/".join(parts[3:])
    return None if name == "raw/hub/transcript" else name


def command(type_: str, payload: dict[str, Any], home: str, source: str = "hub") -> tuple[str, str]:
    """(topic, json) of one contract command, validated against the contract models before anything is sent."""
    env = make(type_, payload, source=source, home_id=home)  # type: ignore[arg-type]
    return topic_for(env), to_json(env)


def after(seen: list[Seen], t0: float, name: str, where: Callable[[dict[str, Any]], bool] | None = None,
          source: str | None = None) -> list[Seen]:
    return [m for m in seen if m.t >= t0 and m.name == name and not m.retained
            and (source is None or m.source == source) and (where is None or where(m.payload))]


def health_check(seen: list[Seen], node: str, now_utc: datetime) -> tuple[bool, dict[str, Any]]:
    """The node's latest heartbeat: alive when it is not `down` and younger than HEALTH_MAX_AGE_S (by its own
    timestamp when it is live, so a retained last will from hours ago never passes)."""
    beats = [m for m in seen if m.name == f"health/{node}"]
    if not beats:
        return False, {"heard": False}
    m = beats[-1]
    age = (now_utc - m.ts).total_seconds() if m.ts is not None else None
    d = m.payload.get("details") or {}
    numbers: dict[str, Any] = {"status": m.payload.get("status"), "version": m.payload.get("version"),
                               "age_s": None if age is None else round(age, 1)}
    for k in ("step", "camera_ok", "talk", "mic_source", "head_mode", "ritual"):
        if k in d:
            numbers[k] = d[k]
    ok = m.payload.get("status") != "down" and age is not None and abs(age) < HEALTH_MAX_AGE_S
    return ok, numbers


def pan_evidence(seen: list[Seen], t0: float, within_s: float = 3.0) -> tuple[bool, dict[str, Any]]:
    """After a turn was asked for at t0: `raw/head/pan` said `moving: true` within `within_s`, and `moving: false`
    after that."""
    pans = after(seen, t0, "raw/head/pan", source="head")
    start = next((m for m in pans if m.payload.get("moving") is True and m.t - t0 <= within_s), None)
    stop = next((m for m in pans if start is not None and m.t > start.t and m.payload.get("moving") is False), None)
    numbers = {"pan_messages": len(pans),
               "moving_after_s": None if start is None else round(start.t - t0, 2),
               "still_after_s": None if stop is None else round(stop.t - t0, 2)}
    return start is not None and stop is not None, numbers


def tone_frames(seconds: float, hz: float = 440.0, level: int = 2500) -> list[bytes]:
    """A quiet tone in the head speaker's wire format: 20 ms frames of signed 16-bit little-endian mono, 16 kHz."""
    n = int(seconds * 1000 / AUDIO_FRAME_MS)
    out = []
    for f in range(n):
        base = f * AUDIO_FRAME_SAMPLES
        out.append(struct.pack(f"<{AUDIO_FRAME_SAMPLES}h", *(
            int(level * math.sin(2 * math.pi * hz * (base + i) / AUDIO_RATE_HZ)) for i in range(AUDIO_FRAME_SAMPLES))))
    return out


def follow_sign_ok(pan: dict[str, Any], x: float, sign: int) -> bool:
    """The hub's answer to a face at `x`: a pan toward it, by `[follow_track] sign`."""
    want = (1 if x > 0 else -1) * sign
    return (pan.get("target_deg") or 0) * want > 0


def render(results: list[Result]) -> str:
    lines = []
    for r in results:
        nums = "  " + json.dumps(r.numbers, sort_keys=True) if r.numbers else ""
        lines.append(f"{r.status:<4} {r.step:<24} {r.text}{nums}")
    fails = sum(r.status == "FAIL" for r in results)
    looks = sum(r.status == "LOOK" for r in results)
    lines.append(f"\n{sum(r.status == 'PASS' for r in results)} passed, {fails} failed, {looks} to look at or hear, "
                 f"{sum(r.status == 'SKIP' for r in results)} skipped")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ the bench
class Bench:
    def __init__(self, client: Any, home: str, *, with_sound: bool = False, synthetic_face: bool = False,
                 say: Callable[[str], None] = lambda s: print(s, file=sys.stderr, flush=True)):
        self.client, self.home, self.with_sound, self.synthetic_face, self.say = client, home, with_sound, synthetic_face, say
        self.seen: list[Seen] = []
        self.results: list[Result] = []

    # ---- bus
    async def listen(self) -> None:
        async for m in self.client.messages:
            name = name_of(str(m.topic), self.home)
            msg = decode(m.payload) if name else None
            if not name or not isinstance(msg, dict) or not isinstance(msg.get("payload"), dict):
                continue
            ts = None
            with contextlib.suppress(Exception):
                ts = datetime.fromisoformat(str(msg.get("ts")).replace("Z", "+00:00"))
            self.seen.append(Seen(time.monotonic(), name, str(msg.get("source")), msg["payload"], ts, bool(m.retain)))

    async def send(self, type_: str, payload: dict[str, Any], source: str = "hub") -> float:
        topic, body = command(type_, payload, self.home, source)
        await self.client.publish(topic, body, qos=1 if type_.startswith("cmd.") else 0)
        return time.monotonic()

    async def wait(self, found: Callable[[], Any], seconds: float) -> Any:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            got = found()
            if got:
                return got
            await asyncio.sleep(0.05)
        return found()

    def add(self, step: str, status: str, text: str, /, **numbers: Any) -> None:
        r = Result(step, status, text, numbers)
        self.results.append(r)
        self.say(render([r]).split("\n")[0])

    # ---- steps
    async def parts(self) -> None:
        await self.wait(lambda: all(after(self.seen, 0, f"health/{n}") for n in ("head", "sensors", "hub")), 12.0)
        now = datetime.now(UTC)
        for node in ("head", "sensors", "hub"):
            ok, numbers = health_check([m for m in self.seen if not m.retained] or self.seen, node, now)
            self.add("parts", "PASS" if ok else "FAIL",
                     f"{node}: alive on the broker" if ok else f"{node}: no fresh heartbeat (powered? on this Wi-Fi?)",
                     **numbers)

    async def ring(self) -> None:
        for name, colour in RING:
            await self.send("cmd.head", {"color": colour})
            self.add("ring", "LOOK", f"the ear ring is {name} now (it breathes while the microphone is open). "
                                     "Firmware 0.8.0 sends nothing back about its ring.", sent=colour)
            await asyncio.sleep(2.0)

    async def turn(self) -> None:
        for way, deg in (("left", -30.0), ("right", 30.0)):
            t0 = await self.send("cmd.head", {"pan": {"target_deg": deg, "speed": 0.6}})
            await self.wait(lambda t0=t0: pan_evidence(self.seen, t0)[0], 6.0)
            ok, numbers = pan_evidence(self.seen, t0)
            self.add("turn", "PASS" if ok else "FAIL",
                     f"the motor ran and stopped (asked: {way})" if ok
                     else f"no movement was reported for a turn {way} (the motor never runs while the speaker has "
                          "sound; is the head on its own charger?)", **numbers)
            self.add("turn", "LOOK", f"the head turned to YOUR {way}, as you face it. If it went the other way, flip "
                                     "`[follow_track] sign` in config/kaiku.toml.")
            await asyncio.sleep(1.5)

    async def turn_waits(self) -> None:
        if not self.with_sound:
            self.add("turn-waits-for-speaker", "SKIP", "run with --with-sound: 2 s of a quiet tone on the head's "
                     "speaker, a turn asked for in the middle of it, and the motor must start only after the sound")
            return
        frames, topic = tone_frames(2.0), audio_topic(self.home, "speaker")
        t_pan, t_end = 0.0, 0.0
        for i, frame in enumerate(frames):
            await self.client.publish(topic, frame, qos=0)
            if i == len(frames) // 4:
                t_pan = await self.send("cmd.head", {"pan": {"target_deg": 30.0, "speed": 0.6}})
            await asyncio.sleep(AUDIO_FRAME_MS / 1000)
        t_end = time.monotonic()
        await self.wait(lambda: after(self.seen, t_pan, "raw/head/pan", lambda p: p.get("moving") is True), 8.0)
        moved = after(self.seen, t_pan, "raw/head/pan", lambda p: p.get("moving") is True)
        if not moved:
            self.add("turn-waits-for-speaker", "FAIL", "the turn never happened after the sound ended")
            return
        early = moved[0].t < t_end
        self.add("turn-waits-for-speaker", "FAIL" if early else "PASS",
                 "the motor started while the sound was still being sent" if early
                 else "the turn waited for the speaker to go quiet",
                 asked_s_before_sound_end=round(t_end - t_pan, 2), moved_s_after_sound_end=round(moved[0].t - t_end, 2))

    async def buzzer(self) -> None:
        await self.send("cmd.sensors", {"chime": "ok"})
        self.add("buzzer", "LOOK", "the sensor board's buzzer played its short `ok` sound (nothing comes back on the bus)")

    def _camera_data(self, t0: float) -> list[Seen]:
        return after(self.seen, t0, "raw/sensors/distance") + after(self.seen, t0, "raw/hub/face", source="sensors")

    async def camera(self) -> None:
        t0 = await self.send("cmd.sensors", {"camera_enable": False})
        await asyncio.sleep(1.5)  # frames already on their way
        t1 = time.monotonic()
        await asyncio.sleep(5.0)
        leaked = self._camera_data(t1)
        self.add("camera", "FAIL" if leaked else "PASS",
                 "camera off: the board still sent face or distance numbers" if leaked
                 else "camera off: no face and no distance for 5 s", messages=len(leaked),
                 off_sent_s_ago=round(time.monotonic() - t0, 1))
        self.add("camera", "LOOK", "the camera's own light is OFF now")
        t2 = await self.send("cmd.sensors", {"camera_enable": True})
        await self.wait(lambda: self._camera_data(t2), 8.0)
        back = self._camera_data(t2)
        self.add("camera", "PASS" if back else "FAIL",
                 "camera on: numbers came back" if back else "camera on: nothing from the camera within 8 s "
                 "(a face must be in view only for `raw/hub/face`; distance comes without one)",
                 first_after_s=round(back[0].t - t2, 2) if back else None)
        self.add("camera", "LOOK", "the camera's own light is ON now")

    async def camera_off(self) -> None:
        await self.send("cmd.sensors", {"camera_enable": False})
        self.add("camera", "LOOK", "left OFF again: on the robot the camera opens only after a yes in a conversation "
                                   "(D61); its light is out")

    async def face_signs(self) -> None:
        await self.send("cmd.sensors", {"camera_enable": True})
        await asyncio.sleep(2.5)  # the device opens
        t0 = await self.send("cmd.sensors", {"face_signs_s": 5})
        await self.wait(lambda: after(self.seen, t0, "raw/sensors/face_signs"), 12.0)
        got = after(self.seen, t0, "raw/sensors/face_signs")
        if not got:
            self.add("face-signs", "FAIL", "no raw/sensors/face_signs within 12 s of asking for a 5 s window")
        else:
            p = got[0].payload
            self.add("face-signs", "PASS", "one window counted (numbers only; no picture leaves the board). "
                     "coverage 0 = nobody was in view, which is a valid result",
                     after_s=round(got[0].t - t0, 1), **{k: p.get(k) for k in
                                                         ("duration_s", "samples", "coverage", "smile_share", "smiles",
                                                          "head_movement") if p.get(k) is not None})

    async def follow(self) -> None:
        sign = -1 if float(get("follow_track", "sign", 1)) < 0 else 1
        if not self.synthetic_face:
            self.add("follow", "SKIP", "by hand: in an open conversation with the camera on, move your face to the edge "
                     "of the camera's picture; within about 2 s the head makes one small turn toward you. Or run "
                     "with --synthetic-face (the real hub will act on a made-up face at the right edge)")
            return
        self.say("WARNING: sending a made-up face at the right edge as the sensor board; the hub will turn the head")
        t0 = time.monotonic()
        for _ in range(15):
            await self.send("raw.hub.face", {"x_norm": 0.8, "y_norm": 0.0, "size": 0.2, "confidence": 0.9}, source="sensors")
            await asyncio.sleep(0.2)
        pans = after(self.seen, t0, "cmd/head", lambda p: isinstance(p.get("pan"), dict), source="hub")
        if not pans:
            self.add("follow", "FAIL", "the hub asked for no turn (it follows only inside a check-in that is not idle, "
                     "never while the speaker has sound, never in the rhythm game; `[follow_track] enabled`?)")
        else:
            ok = follow_sign_ok(pans[0].payload["pan"], 0.8, sign)
            self.add("follow", "PASS" if ok else "FAIL", "the hub asked for a turn toward the face" if ok
                     else "the hub asked for a turn AWAY from the face", target_deg=pans[0].payload["pan"].get("target_deg"),
                     sign=sign, after_s=round(pans[0].t - t0, 2))

    async def arm(self) -> None:
        def step() -> str | None:
            beats = after(self.seen, 0, "health/head")
            return (beats[-1].payload.get("details") or {}).get("step") if beats else None

        if step() in (None, "idle"):
            self.add("arm", "SKIP", "the head is idle: wake it first (press the ear once, it greets), then run this again. "
                     "An armed activity is ignored while idle")
            return
        t0 = await self.send("cmd.head", {"activity": "drum"})
        self.say(">>> PRESS THE EAR NOW (within 20 seconds)")
        await self.wait(lambda: step() == "drum" and after(self.seen, t0, "health/head"), 21.0)
        ok = step() == "drum"
        self.add("arm", "PASS" if ok else "FAIL", "armed + a press: the head went to the drum step" if ok
                 else f"the head did not go to the drum step (it is in {step()}); was the ear pressed in time?", step=step())
        t1 = await self.send("cmd.head", {"ritual": "end"})
        await self.wait(lambda: step() == "idle" and after(self.seen, t1, "health/head"), 8.0)
        ok = step() == "idle"
        self.add("arm", "PASS" if ok else "FAIL", "`ritual: end`: the head went back to rest" if ok
                 else f"the head did not go back to rest (it is in {step()}; needs firmware 0.7.0 or later)", step=step())

    async def run(self, steps: list[str]) -> list[Result]:
        table = {"parts": self.parts, "ring": self.ring, "turn": self.turn, "buzzer": self.buzzer,
                 "camera": self.camera, "face-signs": self.face_signs, "turn-waits-for-speaker": self.turn_waits,
                 "follow": self.follow, "arm": self.arm}
        for s in steps:
            await table[s]()
        if "camera" in steps or "face-signs" in steps:
            await self.camera_off()
        return self.results


async def main_async(args: argparse.Namespace) -> int:
    import aiomqtt

    steps = select(args.steps)
    async with aiomqtt.Client(**mqtt_kwargs()) as client:
        for f in FILTERS:
            await client.subscribe(f"kaiku/v1/{args.home}/{f}")
        bench = Bench(client, args.home, with_sound=args.with_sound, synthetic_face=args.synthetic_face,
                      say=(lambda s: None) if args.json else (lambda s: print(s, flush=True)))
        listener = asyncio.create_task(bench.listen())
        await asyncio.sleep(0.5)
        try:
            results = await bench.run(steps)
        finally:
            listener.cancel()
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=1))
    else:
        print(render(results).split("\n\n")[-1])
    return 1 if any(r.status == "FAIL" for r in results) else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("steps", nargs="*", help=f"steps to run (default: {' '.join(DEFAULT)}); all: {' '.join(STEPS)}")
    ap.add_argument("--home", default="demo-aino", help="the home id the robot's boards publish under")
    ap.add_argument("--with-sound", action="store_true", help="allow the step that plays 2 s of a quiet tone")
    ap.add_argument("--synthetic-face", action="store_true", help="allow the step that sends a made-up face")
    ap.add_argument("--json", action="store_true", help="results as JSON")
    args = ap.parse_args()
    try:
        select(args.steps)
    except ValueError as e:
        ap.error(str(e))
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
