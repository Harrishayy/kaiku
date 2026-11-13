"""Sim twin of the iPhone app (source `phone`). HTTPS only, like KaikuKit: POSTs the morning Apple Health summary
(obs.wearable_daily -> the optional "wearable" consensus source), the weather check (obs.self_report x3 with
channel "phone" -> robot source, it is the daily dial) and a firefly + a pebbles game played on the phone
(obs.play_session).

    uv run python -m sim.nodes.phone_sim [--every 300] [--once] [--no-watch]

--no-watch: a person without a watch (device phone_only: steps only, no sleep/HR/HRV).
"""

from __future__ import annotations

import argparse
import asyncio
import random
from datetime import datetime

import httpx
from kaiku_contracts.config import load_dotenv

from .http_source import HttpSource


class PhoneSim:
    def __init__(self, *, every_s: float = 300.0, seed: int | None = None, watch: bool = True,
                 transport: httpx.AsyncBaseTransport | None = None, url: str | None = None):
        self.every_s = every_s
        self.watch = watch
        self.rng = random.Random(seed)
        self.http = HttpSource("phone", transport=transport, url=url)

    def wearable_payload(self) -> dict:
        g = self.rng.gauss
        today = datetime.now().date().isoformat()
        if not self.watch:
            return {"date": today, "steps": max(0, int(g(5200, 1200))), "device": "phone_only"}
        return {"date": today, "sleep_min": round(max(120.0, g(440, 30))), "sleep_midpoint_min": round(g(195, 20)),
                "sleep_regularity": round(min(1.0, max(0.0, g(0.8, 0.05))), 2),
                "resting_hr_bpm": round(max(40.0, g(62, 2)), 1), "hrv_sdnn_ms": round(max(10.0, g(45, 5)), 1),
                "steps": max(0, int(g(7000, 1500))), "exercise_min": round(max(0.0, g(25, 8))),
                "device": "apple_watch"}

    def weather_check(self) -> list[tuple[str, dict]]:
        return [("obs.self_report", {"item": item, "value": self.rng.choice([3, 4, 4, 5]), "context": "ritual",
                                     "channel": "phone"}) for item in ("mood", "energy", "sleep")]

    def firefly(self) -> tuple[str, dict]:
        g = self.rng.gauss
        return ("obs.play_session", {"game": "firefly", "device": "phone", "duration_s": 60.0,
                                     "reaction_ms_median": round(max(180.0, g(330, 25)), 1),
                                     "reaction_ms_iqr": round(max(10.0, g(58, 10)), 1),
                                     "lapses": max(0, int(round(g(1, 1)))),
                                     "false_taps": max(0, int(round(g(0.5, 0.7))))})

    def pebbles(self) -> tuple[str, dict]:
        g = self.rng.gauss
        return ("obs.play_session", {"game": "pebbles", "device": "phone", "duration_s": round(max(20.0, g(75, 10)), 1),
                                     "span_max": max(2, min(12, int(round(g(6, 1))))),
                                     "accuracy": round(min(1.0, max(0.0, g(0.8, 0.08))), 2)})

    async def morning(self) -> bool:
        """What the app sends when opened in the morning: Health summary + weather check."""
        return await self.http.post([("obs.wearable_daily", self.wearable_payload()), *self.weather_check()])

    async def play(self) -> bool:
        return await self.http.post([self.firefly(), self.pebbles()])

    async def run(self, stop: asyncio.Event | None = None, once: bool = False) -> None:
        stop = stop or asyncio.Event()
        while not stop.is_set():
            await self.morning()
            await self.play()
            if once:
                return
            try:
                await asyncio.wait_for(stop.wait(), self.every_s)
            except TimeoutError:
                pass


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--every", type=float, default=300.0, help="seconds between rounds")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-watch", action="store_true", help="phone only: steps, no sleep/HR/HRV")
    a = ap.parse_args()
    asyncio.run(PhoneSim(every_s=a.every, watch=not a.no_watch).run(once=a.once))


if __name__ == "__main__":
    main()
