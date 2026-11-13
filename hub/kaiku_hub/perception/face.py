"""Local face position -> raw/hub/face (x_norm, y_norm, size, confidence). Optional dep: opencv.

Privacy: frames are processed in memory and dropped immediately. Nothing is written to disk or sent.
Camera runs only while someone is near (hub enables/disables it from presence).
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable

from kaiku_contracts.jlog import get_logger

log = get_logger("hub")

try:  # optional: uv sync --extra camera  (or uv pip install opencv-python-headless)
    import cv2  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - depends on environment
    cv2 = None


def available() -> bool:
    return cv2 is not None


class FaceTracker:
    """Runs a lightweight Haar detector in a thread at ~`hz`; calls `on_face(payload)` on the event loop."""

    def __init__(self, on_face: Callable[[dict], object], device: int = 0, hz: float = 8.0):
        self.on_face = on_face
        self.device = device
        self.period = 1.0 / hz
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> bool:
        if cv2 is None:
            log.info("face_disabled", "opencv not installed (uv sync --extra camera)")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="face", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:  # pragma: no cover - needs a camera
        cap = cv2.VideoCapture(self.device)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.5)
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                h, w = gray.shape
                faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(40, 40))
                del frame, gray  # never keep frames
                # one payload per face (largest 3): the attention ladder counts people per frame
                for x, y, fw, fh in sorted(faces, key=lambda f: -f[2] * f[3])[:3]:
                    payload = {
                        "x_norm": round(((x + fw / 2) / w) * 2 - 1, 3),
                        "y_norm": round(((y + fh / 2) / h) * 2 - 1, 3),
                        "size": round(min(1.0, fw / w), 3),
                        "confidence": 0.8,
                    }
                    if self._loop:
                        self._loop.call_soon_threadsafe(self.on_face, payload)
                time.sleep(self.period)
        finally:
            cap.release()
