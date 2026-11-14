"""Arduino USB Camera (UVC) on the UNO Q Linux side, through the powered USB-C PD hub.

Privacy (root rule 5, docs/privacy.md): frames live only in this function's local variables. Nothing is written
to disk, logged or sent; only face boxes, a distance estimate and a light number come out.
The camera's own microphone (UAC) is never opened.
Camera pulse (backup for the KY-039, plan 07): while `ppg_on`, mean green of the forehead patch per frame ->
`on_ppg(t0_ms, fs_hz, samples)` once a second (green x 100 as ints; fs = measured frame rate, ~15 Hz).
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .vision import Box, biggest, distance_cm, face_payload, forehead, light_payload


@dataclass
class CameraConfig:
    index: int = 0
    frame_w: int = 640
    frame_h: int = 480
    fps: int = 15
    face_hz: float = 5
    detector: str = "haar"
    distance_k_cm: float = 9.0
    far_cm: float = 300
    light_every_s: float = 60
    exposure_absolute: int = 156
    lux_per_unit: float = 2.0


def resolve_index(index: int, by_id: str = "/dev/v4l/by-id") -> int | None:
    """index >= 0: use it. index < 0 ("auto"): the first USB camera's capture node from its stable by-id name.
    On the UNO Q the number moves between boots (/dev/video2 one boot, /dev/video0 the next; 0-3 also hold the
    Qualcomm codec), so the robot uses auto. None = no camera found."""
    if index >= 0:
        return index
    import glob
    import os
    import re
    for link in sorted(glob.glob(f"{by_id}/*-video-index0")):
        m = re.search(r"video(\d+)$", os.path.realpath(link))
        if m:
            return int(m.group(1))
    return None


def _v4l2(index: int, *ctrls: str) -> bool:
    """Set v4l2 controls; fail soft (returns False) if v4l2-ctl is missing or the control name differs."""
    try:
        for c in ctrls:
            subprocess.run(["v4l2-ctl", "-d", f"/dev/video{index}", "-c", c], check=True, capture_output=True,
                           timeout=3)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


class Camera:
    """Background thread. `on_faces(list[dict], distance_cm)` per detection tick, `on_light(dict)` per sample.

    Callbacks run on this thread; the caller hops them onto its asyncio loop.
    """

    def __init__(self, cfg: CameraConfig, on_faces: Callable[[list[dict], float], None],
                 on_light: Callable[[dict], None], on_error: Callable[[str], None] = lambda _e: None,
                 on_ppg: Callable[[int, float, list[int]], None] = lambda *_a: None):
        self.cfg = cfg
        self.on_faces, self.on_light, self.on_error, self.on_ppg = on_faces, on_light, on_error, on_ppg
        self.ppg_on = threading.Event()
        self._box: Box | None = None
        self._ppg: list[int] = []
        self._ppg_t0 = 0.0
        self.enabled = threading.Event()
        self.enabled.set()
        self.ok = False
        self._stop = threading.Event()
        self._light_now = threading.Event()
        self._thread: threading.Thread | None = None
        self._dev: int | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 3.0) -> None:
        """Stop and wait for the thread to release the camera. Exiting while it is still inside OpenCV aborts the
        whole process ("terminate called without an active exception"), seen on the UNO Q 2026-11-14."""
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout_s)

    def sample_light_now(self) -> None:
        self._light_now.set()

    def _detector(self, cv2):  # noqa: ANN001
        # VERIFY yunet: cv2.FaceDetectorYN needs a model file on the board; haar ships with OpenCV.
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        clf = cv2.CascadeClassifier(path)

        def detect(gray) -> list[Box]:  # noqa: ANN001
            found = clf.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(24, 24))
            return [Box(int(x), int(y), int(w), int(h)) for (x, y, w, h) in found]

        return detect

    def _sample_light(self, cap, cv2) -> None:  # noqa: ANN001
        """Mean luminance with auto-exposure off at a fixed exposure (the auto loop would hide a dark room)."""
        c = self.cfg
        locked = _v4l2(self._dev, "auto_exposure=1", f"exposure_time_absolute={c.exposure_absolute}") or _v4l2(
            self._dev, "exposure_auto=1", f"exposure_absolute={c.exposure_absolute}")  # names differ by kernel
        via_cv = False
        if not locked:  # no v4l2-ctl (App Lab's container): the same UVC controls through OpenCV's V4L2 backend
            via_cv = bool(cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1) and cap.set(cv2.CAP_PROP_EXPOSURE, c.exposure_absolute))
            locked = via_cv
        time.sleep(0.4)  # let the sensor settle
        for _ in range(3):
            cap.read()  # drop frames taken before the lock
        ok, frame = cap.read()
        if ok:
            y = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)[:, :, 0]
            self.on_light(light_payload(float(y.mean()), c.lux_per_unit))
        if via_cv:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
        elif locked:
            _v4l2(self._dev, "auto_exposure=3") or _v4l2(self._dev, "exposure_auto=3")
        if not locked:
            self.on_error("light: exposure lock failed; value is auto-exposed")

    def _run(self) -> None:
        try:
            import cv2  # opencv-python-headless
        except ImportError as e:
            self.on_error(f"opencv missing: {e}")
            return
        c = self.cfg
        backoff = 1.0
        while not self._stop.is_set():
            self._dev = resolve_index(c.index)
            cap = cv2.VideoCapture(self._dev if self._dev is not None else -1)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, c.frame_w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, c.frame_h)
            cap.set(cv2.CAP_PROP_FPS, c.fps)
            if self._dev is None or not cap.isOpened():
                self.ok = False
                self.on_error(f"camera {c.index} (/dev/video{self._dev}) not available (PD hub data port? see hardware/wiring.md)")
                time.sleep(backoff)
                backoff = min(10.0, backoff * 2)
                continue
            backoff, self.ok = 1.0, True
            detect = self._detector(cv2)
            next_face = 0.0
            next_light = time.monotonic() + (5 if c.light_every_s != float("inf") else float("inf"))
            try:
                while not self._stop.is_set():
                    if not self.enabled.is_set():
                        time.sleep(0.2)
                        continue
                    now = time.monotonic()
                    if self._light_now.is_set() or now >= next_light:
                        self._light_now.clear()
                        self._sample_light(cap, cv2)
                        next_light = now + c.light_every_s
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError("frame read failed")
                    self._ppg_tick(frame, time.monotonic())
                    if now < next_face:
                        continue
                    next_face = now + 1.0 / c.face_hz
                    h, w = frame.shape[:2]
                    boxes = detect(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                    del frame  # never kept past this tick
                    faces = [face_payload(b, w, h) for b in boxes]
                    big = biggest(boxes)
                    self._box = big or self._box
                    self.on_faces(faces, distance_cm(big.w / w if big else None, c.distance_k_cm, c.far_cm))
            except Exception as e:  # noqa: BLE001 — a camera glitch must not kill the node
                self.ok = False
                self.on_error(f"camera: {e}")
            finally:
                cap.release()

    def _ppg_tick(self, frame, now: float) -> None:  # noqa: ANN001
        if not self.ppg_on.is_set() or self._box is None:
            self._ppg, self._ppg_t0 = [], now
            return
        f = forehead(self._box)
        patch = frame[f.y:f.y + f.h, f.x:f.x + f.w, 1]  # BGR -> G
        if patch.size == 0:
            return
        if not self._ppg:
            self._ppg_t0 = now
        self._ppg.append(int(round(float(patch.mean()) * 100)))
        if now - self._ppg_t0 >= 1.0 and len(self._ppg) >= 5:
            fs = len(self._ppg) / (now - self._ppg_t0)
            self.on_ppg(int(self._ppg_t0 * 1000), round(fs, 2), self._ppg)
            self._ppg = []
