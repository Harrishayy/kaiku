"""Sim twin of the glasses (source 2). HTTPS only: POSTs obs.outing + obs.intervention_response (activity "walk")
to the cloud, like the iPhone app's DAT glasses bridge does: walk minutes from phone location, cadence / gait
regularity / head-up ratio from the glasses IMU (`method: dat_imu`), daylight minutes from sparse camera frames.

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
            ("obs.outing", {"minutes": minutes, "steps": steps, "method": "dat_imu",
                            "cadence_spm": round(self.rng.gauss(106, 4), 1),
                            "gait_regularity": round(min(1.0, max(0.0, self.rng.gauss(0.82, 0.05))), 3),
                            "head_up_ratio": round(min(1.0, max(0.0, self.rng.gauss(0.62, 0.06))), 3),
                            "daylight_min": round(minutes * self.rng.uniform(0.4, 0.8), 1)}),
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
