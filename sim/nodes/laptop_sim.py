"""Sim twin of the laptop apps (source 3): /session (2-minute session) and /phq9. HTTPS only.

    uv run python -m sim.nodes.laptop_sim [--every 300] [--once] [--phq9] [--phq9-item9]

--phq9-item9 sends a PHQ-9 with item 9 > 0 AND the obs.safety_flag the web app sends alongside it
(the browser shows the crisis panel itself; the flag puts the dashboard into Safety).
"""

from __future__ import annotations

import argparse
import asyncio
import random

import httpx
from kaiku_contracts.config import load_dotenv

from .http_source import HttpSource


class LaptopSim:
    def __init__(self, *, every_s: float = 300.0, seed: int | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, url: str | None = None):
        self.every_s = every_s
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
                  item9: bool = False) -> None:
        stop = stop or asyncio.Event()
        first = True
        while not stop.is_set():
            await self.session()
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
    a = ap.parse_args()
    asyncio.run(LaptopSim(every_s=a.every).run(once=a.once, phq9=a.phq9, item9=a.phq9_item9))


if __name__ == "__main__":
    main()
