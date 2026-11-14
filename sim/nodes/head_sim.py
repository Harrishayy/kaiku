"""Sim twin of the Atech head. Publishes the same raw/head/* topics as the real firmware.

Inputs follow config [robot] (or the dial= / drum= arguments):
  - dial_input "ear" (current build, plan 07: the Atech Knob): turn to 1-5 (raw.head.ear), then press;
    "button": answers are 1-5 short presses of the head button (raw.head.button).
  - drum_input "knock" (current build: KY-031 on the UNO Q, src knock, no force) | "imu" (force in g).

Auto mode (default) behaves like a user, following the hub's dial protocol (hub/kaiku_hub/rituals/steps.py):
  - obs.ritual dial started  -> three answers (mood, energy, sleep): press n times / turn the ear, then press
  - obs.ritual drum started  -> tap at --tempo until the drumming ends
  - obs.drum_session         -> stop tapping; answer the post-activity mood dial (turn + press)
  - obs.ritual phq9 started  -> nine ear presses (spoken PHQ-9: dial 1 -> score 0, 2 -> score 1)
Keyboard mode is driven by sim/run.py (t tap, [ ] ear, e press ear, b press head button).

Like the firmware (D39, firmware/atech-head): the pan is open loop with a soft limit of +-80 deg, `raw.head.pan`
goes out at 5 Hz while the motor moves and 0.5 Hz when idle, `moving` is true only while it really moves
(`pan_mode: sway|track` are ignored: tracking arrives as `pan` targets), and knocks are dropped while it moves or
closer together than the knock debounce (the UNO Q sketch mutes the KY-031 during motor vibration).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import math
import os
import random
import time
from typing import Any

from kaiku_contracts.bus import Bus
from kaiku_contracts.config import get, load_dotenv

PRESS_GAP_S = 0.35  # between presses of one answer (well inside [robot] press_window_s)
PAN_LIMIT_DEG = 80.0  # firmware soft limit (D39: power-on home, no hall sensor)
PAN_DEG_PER_S = 120.0  # at speed 1.0
PAN_TICK_S = 0.2
PAN_IDLE_EVERY = 10  # ticks: 0.5 Hz when idle
KNOCK_DEBOUNCE_MS = 40  # firmware/unoq-sensors/sketch/config.h


def standalone_requested() -> bool:
    return os.environ.get("KAIKU_SIM_HEAD", "").lower() == "standalone"


class HeadSim:
    def __init__(self, *, auto: bool = True, tempo_bpm: float = 96.0, mood: int | None = None,
                 force_g: float = 2.0, seed: int | None = None, dial: str | None = None, drum: str | None = None):
        self.auto = auto
        self.dial = dial or str(get("robot", "dial_input", "ear"))  # ear | button
        self.drum = drum or str(get("robot", "drum_input", "imu"))  # knock | imu
        self.press_window_s = float(get("robot", "press_window_s", 4.0))
        self.tempo_bpm = tempo_bpm
        self.mood = mood
        self.force_g = force_g
        self.rng = random.Random(seed)
        self.ear = 3
        self.deg = 0.0
        self.target_deg = 0.0
        self.pan_speed = 0.5
        self.homed = True
        self.muted_knocks = 0
        self._last_knock_ms = -10_000
        self.state: dict[str, Any] = {"eyes": "neutral", "pan_mode": "still", "chest": "off"}
        self.bus = Bus("head", sim=True, details=lambda: {"sim": True, **self.state})
        self.bus.on("cmd/head", self._on_cmd)
        self.bus.on("obs/ritual", self._on_ritual)
        self.bus.on("obs/drum_session", self._on_drum_session)
        self._t0 = time.monotonic()
        self._drum_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()

    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    def t_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    # ------------------------------------------------------------ actions (also used by keyboard)
    async def tap(self, force_g: float | None = None) -> None:
        if self.drum == "knock":  # knock switch: timing only, no force
            t = self.t_ms()
            if self.moving or t - self._last_knock_ms < KNOCK_DEBOUNCE_MS:
                self.muted_knocks += 1
                return
            self._last_knock_ms = t
            await self.bus.publish("raw.head.tap", {"t_ms": t, "src": "knock"})
            return
        f = force_g if force_g is not None else max(0.2, self.rng.gauss(self.force_g, 0.3))
        await self.bus.publish("raw.head.tap", {"t_ms": self.t_ms(), "force": round(f, 2), "src": "imu"})

    async def turn_ear(self, delta: int) -> None:
        new = min(5, max(1, self.ear + delta))
        d, self.ear = new - self.ear, new
        await self.bus.publish("raw.head.ear", {"value": self.ear, "delta": d, "pressed": False})

    async def press_ear(self) -> None:
        await self.bus.publish("raw.head.ear", {"value": self.ear, "delta": 0, "pressed": True})

    async def press_button(self, hold_s: float = 0.12) -> None:
        await self.bus.publish("raw.head.button", {"id": "head", "pressed": True})
        await asyncio.sleep(hold_s)
        await self.bus.publish("raw.head.button", {"id": "head", "pressed": False})

    # ------------------------------------------------------------ handlers
    async def _on_cmd(self, _t, env) -> None:
        cmd = env.payload.model_dump(exclude_none=True)
        self.state.update({k: v for k, v in cmd.items() if k in ("eyes", "pan_mode", "chest", "bpm")})
        if cmd.get("home") or cmd.get("gesture"):  # a gesture is a timed pulse, then back to the power-on home
            self.target_deg, self.homed = 0.0, True
        if "pan" in cmd:
            self.target_deg = max(-PAN_LIMIT_DEG, min(PAN_LIMIT_DEG, float(cmd["pan"]["target_deg"])))
            self.pan_speed = float(cmd["pan"].get("speed", 0.5)) or 0.5
        self.bus.log.info("cmd_head", str(cmd))

    async def _on_ritual(self, _t, env) -> None:
        if not self.auto:
            return
        step, status = env.payload.step, env.payload.status
        if step == "dial" and status == "started":
            self._spawn(self._auto_dial())
        elif step == "phq9" and status == "started":
            self._spawn(self._auto_phq9())
        elif step == "drum" and status == "started":
            if self._drum_task:
                self._drum_task.cancel()
            self._drum_task = self._spawn(self._auto_drum(float(get("ritual", "drum_s", 45))))
        elif step == "drum" and self._drum_task:
            self._drum_task.cancel()

    async def _on_drum_session(self, _t, env) -> None:
        if not self.auto:
            return
        if self._drum_task:
            self._drum_task.cancel()
        self._spawn(self._answer(min(5, (self.mood or 3) + 1), first_delay=0.8))  # drumming lifted the mood a bit

    async def _answer(self, target: int, first_delay: float = 0.6) -> None:
        """One dial answer: press the button `target` times (button build), or turn the ear to it and press."""
        await asyncio.sleep(first_delay)
        if self.dial == "button":
            for _ in range(target):
                await self.press_button()
                await asyncio.sleep(PRESS_GAP_S)
            await asyncio.sleep(self.press_window_s + 0.3)  # let the hub close the answer
            return
        while self.ear != target:
            await self.turn_ear(1 if target > self.ear else -1)
            await asyncio.sleep(0.25)
        await asyncio.sleep(0.3)
        await self.press_ear()

    async def _auto_dial(self) -> None:
        mood = self.mood or self.rng.choice([2, 3, 3, 4, 4])
        for i, target in enumerate((mood, self.rng.choice([2, 3, 4]), self.rng.choice([2, 3, 4, 5]))):
            await self._answer(target, first_delay=1.0 if i == 0 else 0.6)

    async def _auto_phq9(self) -> None:
        for i in range(9):
            await self._answer(1 if i == 8 or self.rng.random() < 0.6 else 2, first_delay=0.8)

    async def _auto_drum(self, duration_s: float) -> None:
        await asyncio.sleep(0.5)
        start = time.monotonic()
        span = max(1.0, duration_s - 1.0)
        interval = 60.0 / self.tempo_bpm
        while (progress := (time.monotonic() - start) / span) < 1.0:
            lift = 1.0 + 0.4 * progress  # warms up as it goes (the hub says "[drumming · lively]" to Live)
            await self.tap(max(0.2, self.rng.gauss(self.force_g * lift, 0.3)))
            await asyncio.sleep(max(0.12, self.rng.gauss(interval / lift, interval * 0.06)))

    @property
    def moving(self) -> bool:
        return abs(self.target_deg - self.deg) > 0.05

    async def _pan_loop(self) -> None:
        idle = 0
        while True:
            was_moving = self.moving
            if was_moving:
                step = PAN_DEG_PER_S * self.pan_speed * PAN_TICK_S
                self.deg += math.copysign(min(step, abs(self.target_deg - self.deg)), self.target_deg - self.deg)
            idle = 0 if was_moving else idle + 1
            if was_moving or idle == 1 or idle % PAN_IDLE_EVERY == 0:  # 5 Hz moving, one "stopped", then 0.5 Hz
                await self.bus.publish("raw.head.pan", {"deg": round(self.deg, 1), "homed": self.homed,
                                                        "moving": self.moving})
            await asyncio.sleep(PAN_TICK_S)

    async def run(self, stop: asyncio.Event | None = None) -> None:
        async with self.bus:
            pan = asyncio.create_task(self._pan_loop())
            try:
                await (stop.wait() if stop else asyncio.Event().wait())
            finally:
                pan.cancel()
                for t in list(self._tasks):
                    t.cancel()


class StandaloneHeadSim:
    """Twin of the STANDALONE head firmware (D44: firmware/atech-head/standalone/src/main.cpp + kaiku_net.cpp).

    The ritual runs here, on the "head", exactly as in main.cpp: idle -> greet -> mood -> energy -> sleep -> breathe
    -> drum -> done -> idle. Same messages, same order as the firmware:
      health/head       every `health_s` (firmware: 5 s), retained: details {rssi, reconnects, step, firmware: standalone}
      raw.head.ear      a turn, only in a dial step: {value 1-10, delta, pressed false}; every press, in any step:
                        {value = last dial value, 0, pressed true}, published BEFORE the step changes
      cmd.sensors       {chime: wake} on greeting, {start_drum} entering drum, {end_drum} when drumming ends
      raw.head.pan      {deg 0, homed true, moving}: on change + every 2 s (moving during a pan burst or a purr)
    It hears raw.head.tap from other nodes (UNO Q knock: a drum tap, or wakes it from idle), raw.hub.face (wakes it)
    and cmd.head eyes / pan (600 ms burst) / gesture / purr. Nothing else: no ritual results are published.
    Timers are the firmware's (breathing 6 x 10 s, drum 20 s from the first tap or 60 s without one, greeting 60 s,
    goodbye 8 s, 3 s quiet after returning to idle); `time_scale` divides them for fast tests.

    Auto mode is a person: presses to start, turns each dial to its 1-10 answer and presses, breathes (or presses
    to skip with `skip_breathe`), then knocks. The knocks go out as `raw.head.tap {src: knock}` with source
    `sensors`, like the UNO Q's KY-031, and come back to this head through the broker like on the robot.
    """

    FW_VERSION = "atech-head-standalone-0.1.0"
    STEPS = ("idle", "greet", "mood", "energy", "sleep", "breathe", "drum", "done")
    DIALS = ("mood", "energy", "sleep")
    IN_MS, OUT_MS = 4000, 6000
    GREET_TIMEOUT_MS, DONE_MS, DRUM_WAIT_MS, QUIET_MS, GREET_PURR_MS, PAN_BURST_MS, PAN_EVERY_MS = (
        60000, 8000, 60000, 3000, 1500, 600, 2000)

    def __init__(self, *, auto: bool = True, mood: int | None = None, energy: int | None = None,
                 sleep: int | None = None, tempo_bpm: float = 96.0, seed: int | None = None, breath_cycles: int = 6,
                 drum_ms: int = 20000, health_s: float = 5.0, time_scale: float = 1.0, skip_breathe: bool = False,
                 knocks: bool = True):
        self.auto, self.skip_breathe, self.knocks = auto, skip_breathe, knocks
        self.rng = random.Random(seed)
        self.answers = {"mood": mood, "energy": energy, "sleep": sleep}  # 1-10; None = a random plausible answer
        self.tempo_bpm = tempo_bpm
        self.breath_cycles, self.drum_ms = breath_cycles, drum_ms
        self.health_s, self.scale = health_s, max(time_scale, 1e-3)
        self.mode = "idle"
        self.dial_value = 5
        self.taps = 0
        self.eyes = "calm"
        self.muted_knocks = 0
        self.results: dict[str, Any] = {}  # what the firmware prints on USB serial only (never published)
        self._mode_start = self._first_tap = self._quiet_until = 0.0
        self._pan_until = self._purr_until = 0.0
        self._pan_speed = 0
        self._moving = False
        self._tap_latch = self._face = False
        self._last_knock_ms = -10_000
        self._t0 = time.monotonic()
        self._reconnects = 1
        self._user: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.bus = Bus("head", sim=True, version=self.FW_VERSION, heartbeat=False)
        self.bus.on("cmd/head", self._on_cmd)
        self.bus.on("raw/head/tap", self._on_tap)
        self.bus.on("raw/hub/face", self._on_face)

    # ------------------------------------------------------------ time (firmware ms, scaled)
    def _ms(self) -> float:
        return (time.monotonic() - self._t0) * 1000 * self.scale

    async def _sleep_ms(self, ms: float) -> None:
        await asyncio.sleep(ms / 1000 / self.scale)

    # ------------------------------------------------------------ kaiku_net
    async def _health(self, status: str = "ok") -> None:
        await self.bus.publish("health", {"status": status, "version": self.FW_VERSION,
                                          "uptime_s": round(time.monotonic() - self._t0, 1),
                                          "details": {"rssi": -52, "reconnects": self._reconnects, "step": self.mode,
                                                      "firmware": "standalone", "sim": True}})

    async def _ear(self, delta: int, pressed: bool) -> None:
        await self.bus.publish("raw.head.ear", {"value": self.dial_value, "delta": delta, "pressed": pressed})

    async def _chime(self, name: str) -> None:
        await self.bus.publish("cmd.sensors", {"chime": name})

    async def _pan(self) -> None:
        await self.bus.publish("raw.head.pan", {"deg": 0, "homed": True, "moving": self._moving})

    # ------------------------------------------------------------ main.cpp
    async def _set_mode(self, mode: str) -> None:
        self.mode, self._mode_start = mode, self._ms()
        if mode in self.DIALS:
            self.dial_value, self.eyes = 5, "calm"
        elif mode == "drum":
            await self._chime("start_drum")
            self.taps, self._first_tap = 0, 0.0
        elif mode == "idle":
            self._quiet_until = self._ms() + self.QUIET_MS
        if self._user and self._user is not asyncio.current_task():
            self._user.cancel()
        if self.auto:
            self._user = asyncio.create_task(self._person(mode))

    async def _start_greeting(self) -> None:
        await self._set_mode("greet")
        self._purr_until = self._ms() + self.GREET_PURR_MS
        await self._chime("wake")

    async def _finish(self) -> None:  # finishDrum + finishRitual
        self.results["drum"] = {"taps": self.taps}
        await self._chime("end_drum")
        await self._set_mode("done")

    async def _advance(self) -> None:
        m = self.mode
        if m == "idle":
            await self._start_greeting()
        elif m == "greet":
            self.results = {}
            await self._set_mode("mood")
        elif m in self.DIALS:
            await self._set_mode(("energy", "sleep", "breathe")[self.DIALS.index(m)])
        elif m == "breathe":
            self.results["breathe_completed"] = False
            await self._set_mode("drum")
        elif m == "drum":
            await self._finish()
        else:
            await self._set_mode("idle")

    # ------------------------------------------------------------ the person's hands (also the keyboard)
    async def turn_ear(self, delta: int) -> None:
        async with self._lock:
            if self.mode in self.DIALS:  # the firmware reports turns only while dialling
                self.dial_value = min(10, max(1, self.dial_value + delta))
                await self._ear(delta, False)

    async def press_ear(self) -> None:
        async with self._lock:
            await self._ear(0, True)  # sent first, with the dial value as it stands
            if self.mode in self.DIALS:
                self.results[self.mode] = self.dial_value
            await self._advance()

    async def press_button(self, hold_s: float = 0.12) -> None:
        self.bus.log.info("no_button", "the standalone head has no button; press the ear")

    async def tap(self, force_g: float | None = None) -> None:
        """A knock on the UNO Q's sensor (source sensors), dropped while the head's motor runs or inside the debounce."""
        t = int((time.monotonic() - self._t0) * 1000)
        if self._moving or t - self._last_knock_ms < KNOCK_DEBOUNCE_MS:
            self.muted_knocks += 1
            return
        self._last_knock_ms = t
        await self.bus.publish("raw.head.tap", {"t_ms": t, "src": "knock"}, source="sensors")

    # ------------------------------------------------------------ handlers
    async def _on_tap(self, _t, env) -> None:
        if env.source != "head":
            self._tap_latch = True

    async def _on_face(self, _t, env) -> None:
        if env.source != "head":
            self._face = True

    async def _on_cmd(self, _t, env) -> None:
        c = env.payload
        if c.eyes:
            self.eyes = c.eyes if c.eyes in ("happy", "wide", "sleepy") else "calm"
        speed = None
        if c.pan is not None:
            speed = int((1 if c.pan.target_deg >= 0 else -1) * min(1.0, max(0.0, c.pan.speed)) * 100)
        elif c.gesture in ("look_left", "look_right"):
            speed = -60 if c.gesture == "look_left" else 60
        if speed is not None:
            self._pan_speed, self._pan_until = speed, self._ms() + self.PAN_BURST_MS
        if c.gesture == "shake":
            self._purr_until = self._ms() + 600
        if c.purr is not None:
            self._purr_until = self._ms() + min(10000, max(100, c.purr.ms))

    # ------------------------------------------------------------ loop()
    async def _tick(self) -> None:
        now = self._ms()
        moving = (now < self._pan_until and self._pan_speed != 0) or now < self._purr_until
        if moving != self._moving:
            self._moving = moving
            await self._pan()
        if self._face:
            self._face = False
            if self.mode == "idle" and now > self._quiet_until:
                await self._start_greeting()
        if self._tap_latch:
            self._tap_latch = False
            if self.mode == "drum":
                if not self.taps:
                    self._first_tap = now
                self.taps += 1
            elif self.mode == "idle" and now > self._quiet_until:
                await self._start_greeting()  # a pat on the head wakes Kaiku
        since = now - self._mode_start
        if self.mode == "breathe" and since >= self.breath_cycles * (self.IN_MS + self.OUT_MS):
            self.results["breathe_completed"] = True
            await self._set_mode("drum")
        elif self.mode == "drum" and (now - self._first_tap >= self.drum_ms if self.taps else since >= self.DRUM_WAIT_MS):
            await self._finish()
        elif self.mode == "greet" and since > self.GREET_TIMEOUT_MS:
            await self._set_mode("idle")
        elif self.mode == "done" and since > self.DONE_MS:
            await self._set_mode("idle")

    async def _person(self, mode: str) -> None:
        """Auto mode: what someone does when the head shows this step."""
        if mode == "greet":
            await asyncio.sleep(1.2)
            await self.press_ear()
        elif mode in self.DIALS:
            target = self.answers[mode] or self.rng.choice([4, 5, 6, 7, 8])
            await asyncio.sleep(0.6)
            while self.dial_value != target and self.mode == mode:
                await self.turn_ear(1 if target > self.dial_value else -1)
                await asyncio.sleep(0.2)
            await asyncio.sleep(0.4)
            await self.press_ear()
        elif mode == "breathe" and self.skip_breathe:
            await asyncio.sleep(1.5)
            await self.press_ear()
        elif mode == "drum" and self.knocks:
            await asyncio.sleep(0.5)
            interval = 60.0 / self.tempo_bpm
            while self.mode == "drum":
                await self.tap()
                await asyncio.sleep(max(0.12, self.rng.gauss(interval, interval * 0.06)))

    async def run(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        async with self.bus:
            await self._health()
            next_health = next_pan = time.monotonic()
            try:
                while not stop.is_set():
                    async with self._lock:
                        await self._tick()
                    now = time.monotonic()
                    if now >= next_health:
                        next_health = now + self.health_s
                        await self._health()
                    if now >= next_pan:
                        next_pan = now + self.PAN_EVERY_MS / 1000
                        await self._pan()
                    await asyncio.sleep(0.02)
            finally:
                if self._user:
                    self._user.cancel()
                with contextlib.suppress(Exception):
                    await self._health("down")  # the firmware's last will


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manual", action="store_true", help="don't auto-respond to ritual steps")
    ap.add_argument("--tempo", type=float, default=96.0)
    ap.add_argument("--mood", type=int, choices=range(1, 11), help="1-5 (standalone head: 1-10)")
    ap.add_argument("--dial", choices=("button", "ear"), help="default: config [robot] dial_input")
    ap.add_argument("--standalone", action="store_true",
                    help="behave like the standalone head firmware (D44): the ritual runs on the head. "
                         "Also with KAIKU_SIM_HEAD=standalone")
    ap.add_argument("--fast", type=float, default=1.0, help="standalone: divide the firmware's timers by this")
    ap.add_argument("--skip-breathe", action="store_true", help="standalone: press to skip the breathing")
    a = ap.parse_args()
    if a.standalone or standalone_requested():
        asyncio.run(StandaloneHeadSim(auto=not a.manual, tempo_bpm=a.tempo, mood=a.mood, time_scale=a.fast,
                                      skip_breathe=a.skip_breathe).run())
        return
    asyncio.run(HeadSim(auto=not a.manual, tempo_bpm=a.tempo, mood=a.mood and min(5, a.mood), dial=a.dial).run())


if __name__ == "__main__":
    main()
