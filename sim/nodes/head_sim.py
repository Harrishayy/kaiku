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
import math
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


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manual", action="store_true", help="don't auto-respond to ritual steps")
    ap.add_argument("--tempo", type=float, default=96.0)
    ap.add_argument("--mood", type=int, choices=range(1, 6))
    ap.add_argument("--dial", choices=("button", "ear"), help="default: config [robot] dial_input")
    a = ap.parse_args()
    asyncio.run(HeadSim(auto=not a.manual, tempo_bpm=a.tempo, mood=a.mood, dial=a.dial).run())


if __name__ == "__main__":
    main()
