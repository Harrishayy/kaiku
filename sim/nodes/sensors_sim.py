"""Sim twin of the UNO Q sensor node: distance (presence), PPG on demand, light, hall, top button, and the UNO Q
camera's face boxes (App Lab YOLO): one `raw.hub.face` per person per frame at 5 Hz while someone is within
FACE_CM, growing as they approach (hub/kaiku_hub/devices/unoq_yolo.py has the interface)."""

from __future__ import annotations

import argparse
import asyncio
import math
import random
import time
from datetime import datetime

from kaiku_contracts.bus import Bus
from kaiku_contracts.config import load_dotenv

from .signals import PpgSynth, approach_curve, daylight_lux

FAR_CM = 200.0
NEAR_CM = 50.0
PPG_BATCH = 25
FACE_CM = 180.0  # the camera "sees" someone closer than this


class SensorsSim:
    def __init__(self, *, arrive_after_s: float | None = 3.0, dwell_s: float = 600.0, hr_bpm: float = 68.0,
                 seed: int | None = None, faces: bool = True):
        self.arrive_after_s = arrive_after_s
        self.dwell_s = dwell_s
        self.rng = random.Random(seed)
        self.ppg = PpgSynth(hr_bpm=hr_bpm, seed=seed)
        self._hr_rest = hr_bpm
        self._breathe_t0: float | None = None
        self.ppg_on = False
        self.camera = False
        self.faces = faces
        self.people = 1  # keyboard `2` toggles a second person
        self._arrived_at: float | None = None
        self._left_at: float | None = None
        self._t0 = time.monotonic()
        self.bus = Bus("sensors", sim=True, details=lambda: {"sim": True, "ppg": self.ppg_on, "near": self.is_near})
        self.bus.on("cmd/sensors", self._on_cmd)
        self.bus.on("obs/ritual", self._on_ritual)

    @property
    def is_near(self) -> bool:
        return self._arrived_at is not None and self._left_at is None

    # ------------------------------------------------------------ actions (also used by keyboard)
    def arrive(self) -> None:
        self._arrived_at, self._left_at = time.monotonic(), None

    def leave(self) -> None:
        if self._arrived_at is not None:
            self._left_at = time.monotonic()

    def toggle_second_person(self) -> int:
        self.people = 1 if self.people == 2 else 2
        return self.people

    def face_boxes(self, cm: float, now: float) -> list[dict]:
        """RawFace payloads for what the camera would see at this distance (empty when nobody is close)."""
        if not self.faces or cm >= FACE_CM:
            return []
        closeness = max(0.0, min(1.0, (FACE_CM - cm) / (FACE_CM - NEAR_CM)))
        size = 0.05 + 0.30 * closeness
        x = 0.5 - 0.4 * closeness + 0.05 * math.sin(now * 0.7)  # walks in from the right, settles near centre
        out = [{"x_norm": round(x, 3), "y_norm": round(-0.1 + self.rng.gauss(0, 0.01), 3), "size": round(size, 3),
                "confidence": 0.9}]
        if self.people == 2:
            out.append({"x_norm": round(x - 0.7, 3), "y_norm": -0.05, "size": round(size * 0.9, 3),
                        "confidence": 0.85})
        return out

    async def button(self, hold_s: float = 0.2, id: str = "top") -> None:
        await self.bus.publish("raw.sensors.button", {"id": id, "pressed": True})
        await asyncio.sleep(hold_s)
        await self.bus.publish("raw.sensors.button", {"id": id, "pressed": False})

    # ------------------------------------------------------------ handlers
    async def _on_cmd(self, _t, env) -> None:
        cmd = env.payload
        if cmd.ppg is not None:
            self.ppg_on = cmd.ppg == "start"
        if cmd.camera_enable is not None:
            self.camera = cmd.camera_enable
        self.bus.log.info("cmd_sensors", str(cmd.model_dump(exclude_none=True)))

    async def _on_ritual(self, _t, env) -> None:
        # paced breathing raises RSA, like the real thing
        if env.payload.step == "breathe":
            started = env.payload.status == "started"
            self.ppg.breath_bpm, self.ppg.rsa_ms = (6.0, 70.0) if started else (12.0, 40.0)
            self._breathe_t0 = time.monotonic() if started else None
            if not started:
                self.ppg.hr_bpm = self._hr_rest

    # ------------------------------------------------------------ loops
    def distance_cm(self, now: float) -> float:
        noise = self.rng.gauss(0, 1.5)
        if self._arrived_at is None:
            return FAR_CM + noise
        if self._left_at is not None:
            return approach_curve(now - self._left_at, NEAR_CM, FAR_CM) + noise
        return approach_curve(now - self._arrived_at, FAR_CM, NEAR_CM) + noise

    async def _distance_loop(self) -> None:
        while True:
            now = time.monotonic()
            if self.arrive_after_s is not None and self._arrived_at is None and now - self._t0 >= self.arrive_after_s:
                self.arrive()
            if self.is_near and self._arrived_at and now - self._arrived_at > self.dwell_s:
                self.leave()
            cm = max(0.0, self.distance_cm(now))
            await self.bus.publish("raw.sensors.distance", {"cm": round(cm, 1)})
            for box in self.face_boxes(cm, now):
                await self.bus.publish("raw.hub.face", box)
            await asyncio.sleep(0.2)

    async def _ppg_loop(self) -> None:
        period = PPG_BATCH / self.ppg.fs_hz
        next_t = time.monotonic()
        while True:
            if self.ppg_on:
                if self._breathe_t0 is not None:  # heart settles ~4 bpm over 30 s of slow breathing
                    self.ppg.hr_bpm = self._hr_rest - min(4.0, 4.0 * (time.monotonic() - self._breathe_t0) / 30.0)
                t0 = int((time.monotonic() - self._t0) * 1000)
                samples = self.ppg.samples(PPG_BATCH)
                await self.bus.publish("raw.sensors.ppg", {"t0_ms": t0, "fs_hz": self.ppg.fs_hz, "samples": samples},
                                       quality=0.9)
            next_t += period
            await asyncio.sleep(max(0.0, next_t - time.monotonic()))
            if not self.ppg_on:
                next_t = time.monotonic()

    async def _slow_loop(self) -> None:
        await self.bus.publish("raw.sensors.hall", {"at_home": True})
        while True:
            now = datetime.now()
            lux = daylight_lux(now.hour + now.minute / 60)
            await self.bus.publish("raw.sensors.light", {"raw": int(lux * 2), "lux_est": round(lux, 1)})
            await asyncio.sleep(10)

    async def run(self, stop: asyncio.Event | None = None) -> None:
        async with self.bus:
            tasks = [asyncio.create_task(c()) for c in (self._distance_loop, self._ppg_loop, self._slow_loop)]
            try:
                await (stop.wait() if stop else asyncio.Event().wait())
            finally:
                for t in tasks:
                    t.cancel()


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arrive-after", type=float, default=3.0, help="seconds until someone approaches (-1 = never)")
    ap.add_argument("--dwell", type=float, default=600.0)
    ap.add_argument("--hr", type=float, default=68.0)
    ap.add_argument("--no-faces", action="store_true", help="don't publish camera face boxes")
    ap.add_argument("--two", action="store_true", help="two people walk up together")
    a = ap.parse_args()
    sim = SensorsSim(arrive_after_s=None if a.arrive_after < 0 else a.arrive_after, dwell_s=a.dwell, hr_bpm=a.hr,
                     faces=not a.no_faces)
    sim.people = 2 if a.two else 1
    asyncio.run(sim.run())


if __name__ == "__main__":
    main()
