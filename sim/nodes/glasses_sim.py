"""Sim twin of the glasses (source 2). HTTPS only: POSTs obs.outing + obs.intervention_response (activity "walk")
to the cloud. The current demo models phone-supported outing duration/steps only; it does not invent
glasses motion, camera daylight, or evidence that the outing occurred outdoors.

    uv run python -m sim.nodes.glasses_sim [--every 300] [--once]
"""

from __future__ import annotations

import argparse
import asyncio
import random

import httpx
from kaiku_contracts.config import load_dotenv

from .http_source import HttpSource


class GlassesSim:
    def __init__(self, *, every_s: float = 300.0, seed: int | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, url: str | None = None):
        self.every_s = every_s
        self.rng = random.Random(seed)
        self.http = HttpSource("glasses", transport=transport, url=url)

    def walk(self) -> list[tuple[str, dict]]:
        minutes = round(self.rng.uniform(12, 35), 1)
        steps = int(minutes * self.rng.uniform(85, 110))
        pre = self.rng.choice([2, 3, 3, 4])
        post = min(5, pre + self.rng.choice([0, 1, 1]))
        return [
            ("obs.outing", {"minutes": minutes, "steps": steps, "method": "steps"}),
            ("obs.intervention_response", {"activity": "walk", "pre": {"mood": pre}, "post": {"mood": post},
                                           "delta": {"mood": float(post - pre)}}),
        ]

    async def walk_done(self) -> bool:
        return await self.http.post(self.walk())

    async def run(self, stop: asyncio.Event | None = None, once: bool = False) -> None:
        stop = stop or asyncio.Event()
        while not stop.is_set():
            await self.walk_done()
            if once:
                return
            try:
                await asyncio.wait_for(stop.wait(), self.every_s)
            except TimeoutError:
                pass


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--every", type=float, default=300.0, help="seconds between walks")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    asyncio.run(GlassesSim(every_s=a.every).run(once=a.once))


if __name__ == "__main__":
    main()
