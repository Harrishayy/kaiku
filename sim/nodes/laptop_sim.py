"""Sim twin of the laptop / "Apps" source (3): web /session + /phq9, and the Mac app (hourly obs.screen_activity
usage rhythm, obs.play_session firefly games and, beside each game, what the Mac camera counted while it ran:
obs.face_signs with method vision_landmarks, D52). HTTPS only.

    uv run python -m sim.nodes.laptop_sim [--every 300] [--once] [--phq9] [--phq9-item9] [--no-camera]

Each default round posts Mac activity plus Firefly and its face signs (`--no-camera`: "Camera during activities"
left off, as the app ships). The retired browser session remains available only
through an explicit legacy fixture invocation; it does not populate ordinary demo rounds.

--phq9-item9 sends a PHQ-9 with item 9 > 0 AND the obs.safety_flag the web app sends alongside it
(the browser shows the crisis panel itself; the flag puts the dashboard into Safety).
"""

from __future__ import annotations

import argparse
import asyncio
import random
from datetime import datetime

import httpx
from kaiku_contracts.config import load_dotenv

from .http_source import HttpSource


class LaptopSim:
    def __init__(self, *, every_s: float = 300.0, seed: int | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, url: str | None = None, camera: bool = True):
        self.every_s = every_s
        self.camera = camera
        self.rng = random.Random(seed)
        self.http = HttpSource("laptop", transport=transport, url=url)

    def session_payload(self) -> dict:
        g = self.rng.gauss
        return {
            "speech_rate": round(max(1.0, g(3.8, 0.3)), 2),
            "pause_ratio": round(min(0.9, max(0.05, g(0.22, 0.04))), 3),
            "pitch_variability": round(max(0.2, g(2.2, 0.3)), 2),
            "expressivity_index": round(min(1.0, max(0.0, g(0.55, 0.08))), 3),
            "reaction_ms_median": round(max(180.0, g(310, 25)), 1),
            "reaction_ms_iqr": round(max(10.0, g(60, 10)), 1),
            "lapses": max(0, int(round(g(1, 1)))),
            "duration_s": round(g(118, 4), 1),
        }

    def screen_payload(self, hour: int) -> dict:
        """One hour of Mac usage rhythm (minutes by category from bundle ids only; no titles/URLs)."""
        g = self.rng.gauss
        active = round(min(60.0, max(0.0, g(38, 10))), 1)
        shares = {"work": 0.5, "communication": 0.2, "social": 0.08, "video": 0.12, "news": 0.05, "games": 0.0,
                  "other": 0.05}
        return {"period_min": 60.0, "active_min": active, "late_night_min": active if hour < 5 else 0.0,
                "category_min": {k: round(active * v, 1) for k, v in shares.items()},
                "switches_per_hour": round(max(0.0, g(16, 4)), 1),
                "longest_stretch_min": round(min(active, max(0.0, g(22, 8))), 1),
                "breaks": max(0, int(round(g(1, 0.7)))), "paused": False}

    def firefly_payload(self) -> dict:
        g = self.rng.gauss
        return {"game": "firefly", "device": "mac", "duration_s": 60.0,
                "reaction_ms_median": round(max(180.0, g(320, 25)), 1),
                "reaction_ms_iqr": round(max(10.0, g(55, 10)), 1),
                "lapses": max(0, int(round(g(1, 1)))), "false_taps": max(0, int(round(g(0.5, 0.7))))}

    def face_signs_payload(self, seconds: float, ref: str | None = None) -> dict:
        """What the Mac camera counted during the game (D52): the landmark method, 15 looks a second.
        It sends no smile, brow or gaze sign (absent, never 0); its blink rate, head movement (face widths a
        second) and range (landmark spread) are on other scales than the phone's face tracking."""
        g = self.rng.gauss
        seconds = float(round(seconds))
        payload = {"task": "firefly", "device": "mac", "method": "vision_landmarks", "duration_s": seconds,
                   "samples": max(1, round(seconds * 15)), "coverage": round(min(0.99, max(0.05, g(0.88, 0.04))), 2),
                   "mouth_open_share": round(min(1.0, max(0.0, g(0.04, 0.01))), 3),
                   "blinks_per_min": round(max(0.0, g(12.5, 1.0)), 1),
                   "head_movement": round(max(0.0, g(0.031, 0.006)), 3),
                   "expression_range": round(min(1.0, max(0.0, g(0.27, 0.02))), 3)}
        return payload | ({"ref": ref} if ref else {})

    async def mac_hour(self, hour: int | None = None) -> bool:
        h = datetime.now().hour if hour is None else hour
        game = self.http.envelope("obs.play_session", self.firefly_payload())
        batch = [self.http.envelope("obs.screen_activity", self.screen_payload(h)), game]
        if self.camera:
            face = self.face_signs_payload(game.payload.duration_s, ref=str(game.id))
            batch.append(self.http.envelope("obs.face_signs", face, face["coverage"]))
        return await self.http.post(batch)

    def phq9_items(self, item9: bool = False) -> list[int]:
        items = [self.rng.choice([0, 0, 1, 1, 2]) for _ in range(8)]
        return [*items, 1 if item9 else 0]

    async def session(self) -> bool:
        return await self.http.post([("obs.laptop_session", self.session_payload())])

    async def phq9(self, item9: bool = False) -> bool:
        items = self.phq9_items(item9)
        batch: list[tuple[str, dict]] = [("obs.phq9", {"total": sum(items), "items": items,
                                                       "item9_positive": items[8] > 0, "mode": "laptop"})]
        if items[8] > 0:
            batch.append(("obs.safety_flag", {"trigger": "phq9_item9", "severity": "high", "handled_locally": True}))
        return await self.http.post(batch)

    async def run(self, stop: asyncio.Event | None = None, once: bool = False, phq9: bool = False,
                  item9: bool = False, legacy_session: bool = False) -> None:
        stop = stop or asyncio.Event()
        first = True
        while not stop.is_set():
            if legacy_session:
                await self.session()
            await self.mac_hour()
            if first and (phq9 or item9):
                await self.phq9(item9=item9)
            first = False
            if once:
                return
            try:
                await asyncio.wait_for(stop.wait(), self.every_s)
            except TimeoutError:
                pass


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--every", type=float, default=300.0, help="seconds between sessions")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--phq9", action="store_true", help="also send a PHQ-9 at start")
    ap.add_argument("--phq9-item9", action="store_true", help="PHQ-9 with item 9 > 0 (+ safety_flag)")
    ap.add_argument("--legacy-session", action="store_true", help="explicit retired browser-task fixture")
    ap.add_argument("--no-camera", action="store_true", help="Camera during activities off: no obs.face_signs")
    a = ap.parse_args()
    asyncio.run(LaptopSim(every_s=a.every, camera=not a.no_camera).run(
        once=a.once, phq9=a.phq9, item9=a.phq9_item9, legacy_session=a.legacy_session))


if __name__ == "__main__":
    main()
