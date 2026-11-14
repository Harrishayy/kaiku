"""Bench: Arduino USB Camera alone, on the UNO Q Linux side (or a laptop webcam). Frames stay in memory.

    python3 camera_check.py [--index 0] [--seconds 20] | <checker>
Prints one JSON line per event: camera (opened), face (2 Hz), light (locked exposure), pulse (camera backup).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
from kaiku_unoq.camera import Camera, CameraConfig  # noqa: E402


def out(**kw) -> None:  # noqa: ANN003
    print(json.dumps(kw), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=20)
    a = ap.parse_args()
    cfg = CameraConfig(index=a.index, face_hz=2, light_every_s=8)
    cam = Camera(cfg,
                 on_faces=lambda faces, cm: out(event="face", n=len(faces), size=max([f["size"] for f in faces],
                                                                                   default=0), cm=cm),
                 on_light=lambda p: out(event="light", **p),
                 on_error=lambda m: out(event="error", msg=m),
                 on_ppg=lambda t0, fs, s: out(event="pulse", fs_hz=fs, n=len(s), range=max(s) - min(s)))
    cam.ppg_on.set()
    cam.start()
    t_end = time.monotonic() + a.seconds
    announced = False
    while time.monotonic() < t_end:
        if cam.ok and not announced:
            out(event="camera", index=a.index, w=cfg.frame_w, h=cfg.frame_h)
            announced = True
        time.sleep(0.2)
    cam.stop()


if __name__ == "__main__":
    main()
