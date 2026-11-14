"""Sim twin of the UNO Q sensor node: distance (presence), PPG on demand, top button, and the UNO Q
camera's face boxes (App Lab YOLO): one `raw.hub.face` per person per frame at 5 Hz while someone is within
FACE_CM, growing as they approach (hub/kaiku_hub/devices/unoq_yolo.py has the interface).
Unfitted hall and disabled light are explicit legacy bench fixtures, never default demo data.

Like the firmware (D39, firmware/unoq-sensors): there is no distance sensor. `raw.sensors.distance` is the pinhole
estimate from the biggest face box (`[unoq] distance_k_cm / size`), and `far_cm` when the camera sees no face
(nobody there, or a face it can't detect: `face_hidden`). `faces=False` is the legacy distance-sensor fixture.
Pulse fixtures (`ppg_fixture`, all explicit bench modes, never default demo data):
  clean   KY-039-like 100 Hz x 25, quality 0.9          flat     unwired / no finger: a constant
  noisy   no pulse, just noise                            flicker  the D39 artefact: a metronomic ~117 bpm ripple
  camera  the backup: ~15 Hz at a wobbling measured rate, one batch a second, quality 0.6
  auto    flat KY-039 for `[unoq] ppg_fallback_s`, then the camera (the firmware's auto fallback)
Health details mirror the firmware: camera_ok, mcu_ok, mcu_fw, ppg (active source), at_home."""

from __future__ import annotations

import argparse
import asyncio
import math
import random
import time
from datetime import datetime

from kaiku_contracts.bus import Bus
from kaiku_contracts.config import get, load_dotenv

from .signals import PpgSynth, approach_curve, daylight_lux

FAR_CM = 200.0
NEAR_CM = 36.0  # sitting at the desk: face ~25 % of the frame width with the default distance_k_cm
PPG_BATCH = 25
PPG_MODES = ("clean", "flat", "noisy", "flicker", "camera", "auto")
KY039_QUALITY, CAMERA_PPG_QUALITY = 0.9, 0.6  # same as firmware/unoq-sensors/python/kaiku_unoq/node.py
CAMERA_FS = 15.0
FACE_CM = 180.0  # the camera "sees" someone closer than this


class SensorsSim:
    def __init__(self, *, arrive_after_s: float | None = 3.0, dwell_s: float = 600.0, hr_bpm: float = 68.0,
                 seed: int | None = None, faces: bool = True, light: bool = False, hall: bool = False,
                 ppg_fixture: bool | str = False):
        self.arrive_after_s = arrive_after_s
        self.dwell_s = dwell_s
        self.rng = random.Random(seed)
        self.ppg = PpgSynth(hr_bpm=hr_bpm, seed=seed)
        self._hr_rest = hr_bpm
        self._breathe_t0: float | None = None
        self.ppg_on = False
        self.camera = False
        self.faces = faces
        self.light, self.hall = light, hall
        self.ppg_mode: str | None = ("clean" if ppg_fixture is True else ppg_fixture) or None
        if self.ppg_mode is not None and self.ppg_mode not in PPG_MODES:
            raise ValueError(f"ppg_fixture must be one of {PPG_MODES}")
        self.ppg_fixture = bool(self.ppg_mode)
        self.ppg_active: str | None = None  # ky039 | camera, like health/sensors details.ppg on the board
        self._ppg_started = 0.0
        self._ky_t0 = 0
        self._cam_phase = 0.0
        self.k_cm = float(get("unoq", "distance_k_cm", 9.0))
        self.far_cm = float(get("unoq", "far_cm", 300))
        self.lux_per_unit = float(get("unoq", "lux_per_unit", 2.0))
        self.fallback_s = float(get("unoq", "ppg_fallback_s", 4.0))
        self.face_hidden = False  # the person is there but the camera can't find a face (turned away, too dark)
        self.camera_ok = True     # False = camera unplugged: no faces AND no distance messages at all
        self.people = 1  # keyboard `2` toggles a second person
        self._arrived_at: float | None = None
        self._left_at: float | None = None
        self._t0 = time.monotonic()
        self.bus = Bus("sensors", sim=True, details=lambda: {
            "sim": True, "near": self.is_near, "camera_ok": self.camera_ok and self.faces, "mcu_ok": True,
            "mcu_fw": "sim", "ppg": self.ppg_active if self.ppg_on else None, "at_home": None})
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
        if not self.faces or self.face_hidden or not self.camera_ok or cm >= FACE_CM:
            return []
        closeness = max(0.0, min(1.0, (FACE_CM - cm) / (FACE_CM - NEAR_CM)))
        size = min(0.6, self.k_cm / max(cm, 1.0))  # pinhole: the firmware inverts this for raw.sensors.distance
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
            self.ppg_on = self.ppg_fixture and cmd.ppg == "start"
            self._ppg_started = time.monotonic()
            self.ppg_active = ("camera" if self.ppg_mode == "camera" else "ky039") if self.ppg_on else None
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
            boxes = self.face_boxes(cm, now)
            for box in boxes:
                await self.bus.publish("raw.hub.face", box)
            if not self.faces:  # legacy distance-sensor fixture
                await self.bus.publish("raw.sensors.distance", {"cm": round(cm, 1)})
            elif self.camera_ok:  # the build: distance from the biggest face box, far_cm when no face is seen
                size = max((b["size"] for b in boxes), default=0.0)
                est = min(self.far_cm, self.k_cm / size) if size > 0 else self.far_cm
                await self.bus.publish("raw.sensors.distance", {"cm": round(est, 1)})
            await asyncio.sleep(0.2)

    def _ky039_samples(self, mode: str, t: float) -> list[int]:
        if mode == "flat":
            return [16000] * PPG_BATCH
        if mode == "noisy":
            return [int(16000 + self.rng.gauss(0, 900)) for _ in range(PPG_BATCH)]
        if mode == "flicker":  # mains-light beat seen on the bench in open room light: perfectly regular
            return [int(16000 + 600 * math.sin(2 * math.pi * 1.95 * (t + i / 100.0))) for i in range(PPG_BATCH)]
        return self.ppg.samples(PPG_BATCH)

    async def _camera_batch(self) -> float:
        """One camera-pulse batch: ~1 s of forehead green x 100 at this second's measured frame rate."""
        fs = round(CAMERA_FS + self.rng.uniform(-1.2, 1.2), 2)
        n = int(round(fs))
        samples = []
        for _ in range(n):  # remote pulse: a small smooth ripple in the green channel (x 100), no dicrotic detail
            self._cam_phase += 2 * math.pi * (self.ppg.hr_bpm / 60.0) / fs
            samples.append(int(12000 + 40 * math.sin(self._cam_phase) + self.rng.gauss(0, 3)))
        t0 = int((time.monotonic() - self._t0) * 1000)
        await self.bus.publish("raw.sensors.ppg", {"t0_ms": t0, "fs_hz": fs, "samples": samples},
                               quality=CAMERA_PPG_QUALITY)
        return n / fs

    async def _ppg_loop(self) -> None:
        period = PPG_BATCH / self.ppg.fs_hz
        next_t = time.monotonic()
        sent = 0
        while True:
            if not self.ppg_on:
                await asyncio.sleep(0.05)
                next_t, sent = time.monotonic(), 0
                continue
            if self._breathe_t0 is not None:  # heart settles ~4 bpm over 30 s of slow breathing
                self.ppg.hr_bpm = self._hr_rest - min(4.0, 4.0 * (time.monotonic() - self._breathe_t0) / 30.0)
            mode = self.ppg_mode or "clean"
            if mode == "auto":
                mode = "flat" if time.monotonic() - self._ppg_started < self.fallback_s else "camera"
            active = "camera" if mode == "camera" else "ky039"
            if active != self.ppg_active:
                self.ppg_active, next_t, sent = active, time.monotonic(), 0
            if mode == "camera" and not self.face_boxes(self.distance_cm(time.monotonic()), time.monotonic()):
                await asyncio.sleep(0.2)  # no face box -> no forehead patch -> no camera pulse
                next_t = time.monotonic()
                continue
            if mode == "camera":
                next_t += await self._camera_batch()
            else:
                t0 = int((time.monotonic() - self._ppg_started) * 1000) if sent == 0 else self._ky_t0
                self._ky_t0 = t0 + int(PPG_BATCH / self.ppg.fs_hz * 1000)  # fixed sample grid, like the sketch
                await self.bus.publish("raw.sensors.ppg", {"t0_ms": t0, "fs_hz": self.ppg.fs_hz,
                                                           "samples": self._ky039_samples(mode, t0 / 1000)},
                                       quality=KY039_QUALITY)
                next_t += period
            sent += 1
            await asyncio.sleep(max(0.0, next_t - time.monotonic()))

    async def _slow_loop(self) -> None:
        if self.hall:
            await self.bus.publish("raw.sensors.hall", {"at_home": True})
        while True:
            if self.light:
                now = datetime.now()
                lux = daylight_lux(now.hour + now.minute / 60)
                raw = max(0, min(255, int(round(lux / self.lux_per_unit))))  # camera: mean luminance 0-255
                await self.bus.publish("raw.sensors.light", {"raw": raw, "lux_est": round(raw * self.lux_per_unit, 1)})
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
    ap.add_argument("--legacy-light", action="store_true", help="explicit legacy light bench fixture")
    ap.add_argument("--hall", action="store_true", help="explicit optional hall bench fixture")
    ap.add_argument("--ppg-fixture", nargs="?", const="clean", choices=PPG_MODES,
                    help="explicit synthetic pulse fixture, not validated hardware (default mode: clean)")
    a = ap.parse_args()
    sim = SensorsSim(arrive_after_s=None if a.arrive_after < 0 else a.arrive_after, dwell_s=a.dwell, hr_bpm=a.hr,
                     faces=not a.no_faces, light=a.legacy_light, hall=a.hall, ppg_fixture=a.ppg_fixture or False)
    sim.people = 2 if a.two else 1
    asyncio.run(sim.run())


if __name__ == "__main__":
    main()
