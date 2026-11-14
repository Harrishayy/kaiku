"""Record 3 s from the Atech head microphone and save it as a .wav on this laptop.

Flash ./project.yaml first (`atech build . && atech upload .`), close any `atech monitor`, then:

    python record_wav.py --port COM8            # Windows
    python record_wav.py --port /dev/tty.usbmodem101

Needs pyserial (already in the atech venv). Files go to ./recordings/ (gitignored). Bench use only:
never commit recordings or send them anywhere (root AGENTS.md rule 5).
"""

from __future__ import annotations

import argparse
import array
import base64
import json
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import serial  # pyserial

HERE = Path(__file__).resolve().parent


def record(port: str, timeout_s: float = 20.0) -> tuple[bytes, int]:
    with serial.Serial(port, 115200, timeout=0.5) as s:
        time.sleep(0.3)
        s.reset_input_buffer()
        s.write(b'{"action":"record"}\n')
        print("Recording 3 s - speak now...")
        pcm, rate, expected, started = bytearray(), 16000, None, False
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            line = s.readline().decode("ascii", errors="replace").strip()
            if not line:
                continue
            if line.startswith("B64:") and started:
                pcm += base64.b64decode(line[4:])
                continue
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = msg.get("event")
            if ev == "rec_start" and not msg.get("ok"):
                sys.exit("board could not start recording (out of memory?)")
            if ev == "wav_begin":
                print("Receiving audio...")
                started, rate, expected = True, int(msg["rate"]), int(msg["bytes"])
            elif ev == "wav_end" and started:
                if expected is not None and len(pcm) != expected:
                    print(f"warning: got {len(pcm)} bytes, board sent {expected} (some audio lost)")
                return bytes(pcm), rate
        sys.exit("timed out waiting for the board - is bench/mic_record flashed and the port free?")


def normalize(pcm: bytes, target: float = 0.9) -> bytes:
    samples = array.array("h", pcm)
    if not samples:
        return pcm
    mean = sum(samples) // len(samples)  # remove DC offset
    centred = [x - mean for x in samples]
    peak = max(1, max(abs(x) for x in centred))
    gain = min(50.0, target * 32767 / peak)
    return array.array("h", (max(-32768, min(32767, int(x * gain))) for x in centred)).tobytes()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="serial port, e.g. COM8")
    ap.add_argument("--out", type=Path, help="output .wav (default: recordings/mic-<time>.wav)")
    ap.add_argument("--raw", action="store_true", help="save as captured (no DC removal / volume boost)")
    a = ap.parse_args()

    pcm, rate = record(a.port)
    if not a.raw:
        pcm = normalize(pcm)
    out = a.out or HERE / "recordings" / f"mic-{datetime.now():%Y%m%d-%H%M%S}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    print(f"saved {len(pcm) / 2 / rate:.1f} s -> {out}")


if __name__ == "__main__":
    main()
