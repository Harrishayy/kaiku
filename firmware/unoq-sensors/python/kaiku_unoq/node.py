"""UNO Q `sensors` node: Bridge (STM32 sketch) <-> MQTT contract messages, plus the camera's derived numbers.

Consumes  cmd/sensors chime -> Modulino Buzzer · camera_enable -> camera on/off · ppg start|stop -> pulse
                      (KY-039 on the sketch; camera pulse as backup per [unoq] ppg_source = auto|ky039|camera)
          raw/head/pan moving -> sketch ignores knocks while the motor runs (vibration)
Emits     raw/head/tap {t_ms, src: knock}  (KY-031; no force)
          raw/sensors/ppg {t0_ms, fs_hz, samples} (KY-039 100 Hz, quality 0.9 | camera ~15 Hz, quality 0.6)
          raw/sensors/hall {at_home} (KY-035: the head faces front; the head firmware brakes on it while homing)
          raw/sensors/light {raw, lux_est} every light_every_s (KY-054; camera backup per [unoq] light_source)
          raw/hub/face (one per face, 5 Hz) · raw/sensors/distance (from face size)
          health/sensors {camera_ok, mcu_ok, mcu_fw, knocks, ppg}
The eyes, knob, LED grids and motor are the Atech head's (cmd/head). The UNO Q LED matrix is a hidden status display.
Hub and broker run on the laptop today; set MQTT_HOST=localhost later to run them on this board (D32).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from kaiku_contracts.bus import Bus
from kaiku_contracts.config import get
from kaiku_contracts.jlog import get_logger

from .bridge import BridgeLike
from .camera import Camera, CameraConfig
from .vision import parse_csv_samples, ppg_signal_ok

KY039_QUALITY = 0.9
CAMERA_PPG_QUALITY = 0.6  # camera pulse is noisier; the hub/cloud quality gates see that

VERSION = "0.1.0"
log = get_logger("sensors")


def camera_config() -> CameraConfig:
    keys = CameraConfig.__dataclass_fields__
    raw = {"index": get("unoq", "camera_index", 0), "detector": get("unoq", "face_detector", "haar"),
           **{k: get("unoq", k) for k in keys if get("unoq", k) is not None}}
    if str(get("unoq", "light_source", "ky054")) != "camera":
        raw["light_every_s"] = float("inf")  # the KY-054 does room light; the camera only as backup
    return CameraConfig(**{k: v for k, v in raw.items() if k in keys})


class SensorsNode:
    def __init__(self, bridge: BridgeLike, *, camera: bool = True, sim: bool = False):
        self.bridge = bridge
        self.bus = Bus("sensors", version=VERSION, sim=sim, details=self._details)
        self.bus.on("cmd/sensors", self._on_sensors_cmd)
        self.bus.on("raw/head/pan", self._on_pan)
        self.light_source = str(get("unoq", "light_source", "ky054"))  # ky054 | camera
        self.light_every_s = float(get("unoq", "light_every_s", 10))
        self.lux_per_count = float(get("unoq", "ky054_lux_per_count", 0.25))
        self.at_home: bool | None = None
        self.mcu_fw: str | None = None
        self.motor_moving = False
        self.knocks = 0
        self.ppg_source = str(get("unoq", "ppg_source", "auto"))  # auto | ky039 | camera
        self.ppg_fallback_s = float(get("unoq", "ppg_fallback_s", 4.0))
        self.ppg_min_range = int(get("unoq", "ppg_min_range", 30))
        self.ppg_max_value = int(get("unoq", "ppg_max_value", 16000))
        self.ppg_active: str | None = None  # None | "ky039" | "camera"
        self._ppg_ok_at = 0.0
        self._ppg_watch: asyncio.Task | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.camera = Camera(camera_config(), self._faces_from_thread, self._light_from_thread,
                             self._error_from_thread, self._camera_ppg_from_thread) if camera else None
        bridge.provide("on_knock", self._knock_from_bridge)
        bridge.provide("on_ppg", self._ppg_from_bridge)
        bridge.provide("on_hall", self._hall_from_bridge)
        bridge.provide("mcu_ready", self._ready_from_bridge)

    def _details(self) -> dict[str, Any]:
        return {"camera_ok": bool(self.camera and self.camera.ok), "mcu_ok": self.mcu_fw is not None,
                "mcu_fw": self.mcu_fw, "knocks": self.knocks, "ppg": self.ppg_active, "at_home": self.at_home}

    # ------------------------------------------------------------ bridge (sketch -> us); router thread
    def _hop(self, coro_fn, *args) -> None:  # noqa: ANN001
        if self.loop is not None:
            self.loop.call_soon_threadsafe(lambda: self.loop.create_task(coro_fn(*args)))  # type: ignore[union-attr]

    def _knock_from_bridge(self, t_ms: int) -> None:
        self._hop(self.knock, int(t_ms))

    def _ppg_from_bridge(self, t0_ms: int, fs_hz: int, csv: str) -> None:
        self._hop(self.ky039_batch, int(t0_ms), float(fs_hz), str(csv))

    def _camera_ppg_from_thread(self, t0_ms: int, fs_hz: float, samples: list[int]) -> None:
        self._hop(self.camera_batch, t0_ms, fs_hz, list(samples))

    def _hall_from_bridge(self, at_home: int, t_ms: int = 0) -> None:
        self._hop(self.hall, bool(at_home))

    def _ready_from_bridge(self) -> None:
        self._hop(self.mcu_ready)

    async def hall(self, at_home: bool) -> None:
        self.at_home = at_home
        await self.bus.publish("raw.sensors.hall", {"at_home": at_home})

    async def read_light(self) -> None:
        """KY-054 under the lid window (the camera is the backup, see camera_config)."""
        v = self._call("light_read")
        if isinstance(v, (int, float)) and v >= 0:
            await self.bus.publish("raw.sensors.light", {"raw": int(v), "lux_est": round(v * self.lux_per_count, 1)})

    async def _light_loop(self) -> None:
        while self.light_source == "ky054":
            await self.read_light()
            await asyncio.sleep(self.light_every_s)

    async def knock(self, t_ms: int) -> None:
        self.knocks += 1
        await self.bus.publish("raw.head.tap", {"t_ms": max(0, t_ms), "src": "knock"})

    # ------------------------------------------------------------ pulse: KY-039 first, camera as backup
    async def ky039_batch(self, t0_ms: int, fs_hz: float, csv: str) -> None:
        samples = parse_csv_samples(csv)
        if self.ppg_active != "ky039" or not samples:
            return
        if ppg_signal_ok(samples, self.ppg_min_range, self.ppg_max_value):
            self._ppg_ok_at = time.monotonic()
        await self.bus.publish("raw.sensors.ppg", {"t0_ms": max(0, t0_ms), "fs_hz": fs_hz, "samples": samples},
                               quality=KY039_QUALITY)

    async def camera_batch(self, t0_ms: int, fs_hz: float, samples: list[int]) -> None:
        if self.ppg_active != "camera" or not samples or not 1 <= fs_hz <= 60:
            return
        await self.bus.publish("raw.sensors.ppg", {"t0_ms": max(0, t0_ms), "fs_hz": fs_hz, "samples": samples},
                               quality=CAMERA_PPG_QUALITY)

    def _use(self, src: str | None) -> None:
        if self.ppg_active == "ky039" and src != "ky039":
            self._call("ppg_stop")
        if self.camera is not None:
            (self.camera.ppg_on.set() if src == "camera" else self.camera.ppg_on.clear())
        if src == "ky039" and self.ppg_active != "ky039":
            self._call("ppg_start")
        if src != self.ppg_active:
            log.info("ppg_source", f"{self.ppg_active} -> {src}")
        self.ppg_active = src

    async def ppg_start(self) -> None:
        want = self.ppg_source
        if want == "camera" or (want == "auto" and self.mcu_fw is None and self.camera is not None):
            self._use("camera")
            return
        self._ppg_ok_at = time.monotonic()
        self._use("ky039")
        if want == "auto" and self.camera is not None:
            self._ppg_watch = asyncio.create_task(self._fallback_watch())

    async def _fallback_watch(self) -> None:
        """auto: no clean KY-039 signal for ppg_fallback_s -> switch to the camera pulse for this session."""
        while self.ppg_active == "ky039":
            await asyncio.sleep(0.5)
            if time.monotonic() - self._ppg_ok_at > self.ppg_fallback_s:
                log.warning("ppg_fallback", "KY-039 flat or silent -> camera pulse")
                self._use("camera")

    async def ppg_stop(self) -> None:
        if self._ppg_watch is not None:
            self._ppg_watch.cancel()
            self._ppg_watch = None
        self._use(None)

    async def mcu_ready(self) -> None:
        """Sketch rebooted: ask its version and restore the status display."""
        self._call("ping")
        self._call("status_set", "ok" if self.bus.connected.is_set() else "net")

    # ------------------------------------------------------------ camera thread -> us
    def _faces_from_thread(self, faces: list[dict], cm: float) -> None:
        self._hop(self.faces, faces, cm)

    def _light_from_thread(self, payload: dict) -> None:
        self._hop(self.bus.publish, "raw.sensors.light", payload)

    def _error_from_thread(self, msg: str) -> None:
        log.warning("camera", msg)

    async def faces(self, faces: list[dict], cm: float) -> None:
        for f in faces:
            await self.bus.publish("raw.hub.face", f)
        await self.bus.publish("raw.sensors.distance", {"cm": cm})

    # ------------------------------------------------------------ MQTT -> sketch
    def _call(self, name: str, *args: Any) -> Any:
        try:
            out = self.bridge.call(name, *args)
            if name == "ping" and out:
                self.mcu_fw = str(out)
            return out
        except Exception as e:  # noqa: BLE001 — a dead sketch must not kill the node (fail soft)
            self.mcu_fw = None if name == "ping" else self.mcu_fw
            log.warning("bridge_call_failed", str(e)[:200], name=name)
            return None

    async def _on_sensors_cmd(self, _t, env) -> None:  # noqa: ANN001
        c = env.payload
        if c.chime is not None:
            self._call("buzz_pattern", c.chime)
        if c.camera_enable is not None and self.camera is not None:
            (self.camera.enabled.set() if c.camera_enable else self.camera.enabled.clear())
        if c.ppg is not None:
            await (self.ppg_start() if c.ppg == "start" else self.ppg_stop())

    async def _on_pan(self, _t, env) -> None:  # noqa: ANN001
        moving = bool(env.payload.moving)
        if moving != self.motor_moving:
            self.motor_moving = moving
            self._call("motor_moving", int(moving))

    # ------------------------------------------------------------ run
    async def run(self, stop: asyncio.Event | None = None) -> None:
        self.loop = asyncio.get_running_loop()
        self._call("ping")
        self._call("status_set", "net")
        if self.camera is not None:
            self.camera.start()
        async with self.bus:
            t0 = time.monotonic()
            await self.bus.connected.wait()
            self._call("status_set", "ok")
            light = asyncio.create_task(self._light_loop())
            try:
                await (stop.wait() if stop else asyncio.Event().wait())
            finally:
                light.cancel()
                if self.camera is not None:
                    self.camera.stop()
                log.info("stopped", f"after {time.monotonic() - t0:.0f} s")
