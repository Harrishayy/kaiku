"""Sim twin of the iPhone app (source `phone`). HTTPS only, like KaikuKit: POSTs the morning Apple Health summary
(obs.wearable_daily -> the optional "wearable" consensus source), the weather check (obs.self_report x3 with
channel "phone" -> robot source, it is the daily dial) and the games played on the phone (obs.play_session:
firefly, pebbles, and the measured lantern / seeds / watering with their trial record and envelope quality).

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

    # research-inspired games (docs/validation.md -> Games). `session` = nth session on this device (1-3 = warm-up).
    def lantern(self, session: int = 6, slowing: float = 0.0, valid: bool = True) -> tuple[str, dict]:
        """PVT-style simple reaction time. `slowing` 0..1 shifts the whole distribution (psychomotor slowing)."""
        g = self.rng.gauss
        codes, rts = [], []
        for _ in range(24):
            r = self.rng.random()
            if r < (0.03 if valid else 0.5):
                codes.append("m")
                rts.append(0)
            elif r < (0.06 if valid else 0.6):
                codes.append("a")
                rts.append(0)
            else:
                rt = int(max(150.0, g(310 + 90 * slowing, 40 + 30 * slowing)))
                codes.append("l" if rt >= 500 else "h")
                rts.append(rt)
        ok = sorted(x for x in rts if x)
        payload: dict = {"game": "lantern", "device": "phone", "duration_s": round(max(60.0, g(92, 4)), 1),
                         "lapses": codes.count("l") + codes.count("m"), "false_starts": codes.count("a"),
                         "trials_n": 24, "valid_n": len(ok), "input": "touch", "session_index": session,
                         "warmup": session <= 3, "valid": len(ok) >= 16, "rt_ms": rts, "trial_codes": "".join(codes)}
        if ok:
            mean = sum(ok) / len(ok)
            sd = (sum((x - mean) ** 2 for x in ok) / max(1, len(ok) - 1)) ** 0.5
            payload |= {"reaction_ms_median": float(ok[len(ok) // 2]),
                        "reaction_ms_iqr": float(ok[(3 * len(ok)) // 4] - ok[len(ok) // 4]),
                        "reaction_ms_cv": round(min(5.0, sd / mean), 3),
                        "response_speed": round(sum(1000 / x for x in ok) / len(ok), 3)}
        if len(ok) < 16:
            payload["flags"] = ["few_trials"]
        return ("obs.play_session", payload)

    def seeds(self, session: int = 6, slowing: float = 0.0) -> tuple[str, dict]:
        """Symbol-digit substitution, 90 s."""
        g = self.rng.gauss
        n = max(15, int(round(g(40 - 10 * slowing, 3))))
        codes = "".join("x" if self.rng.random() < 0.05 else "c" for _ in range(n))
        rts = [int(max(600.0, g(90_000 / n, 350))) for _ in range(n)]
        right = sorted(rt for rt, c in zip(rts, codes, strict=True) if c == "c")
        return ("obs.play_session", {
            "game": "seeds", "device": "phone", "duration_s": round(g(106, 3), 1),
            "throughput_per_min": round(codes.count("c") / 1.5, 2), "accuracy": round(codes.count("c") / n, 3),
            "reaction_ms_median": float(right[len(right) // 2]), "trials_n": n, "valid_n": codes.count("c"),
            "input": "touch", "session_index": session, "warmup": session <= 3, "valid": True,
            "rt_ms": rts, "trial_codes": codes})

    def watering(self, session: int = 6, slowing: float = 0.0) -> tuple[str, dict]:
        """Effort-for-reward choice, 8 rounds."""
        g = self.rng.gauss
        codes = "".join("H" if self.rng.random() < 0.65 - 0.35 * slowing else "E" for _ in range(8))
        return ("obs.play_session", {
            "game": "watering", "device": "phone", "duration_s": round(max(40.0, g(82, 6)), 1),
            "hard_choice_ratio": round(codes.count("H") / 8, 3), "tap_rate_hz": round(max(1.5, g(5.2 - slowing, 0.4)), 2),
            "trials_n": 8, "valid_n": 8, "input": "touch", "session_index": session, "warmup": session <= 3,
            "valid": True, "rt_ms": [int(max(300.0, g(1300, 300))) for _ in range(8)], "trial_codes": codes})

    @staticmethod
    def game_quality(payload: dict) -> float:
        """The envelope quality the app sends with a measured game (doubtful -> 0.2, below every quality_min)."""
        if payload.get("valid") is False:
            return 0.2
        return round(max(0.6, min(1.0, payload["valid_n"] / payload["trials_n"])), 2)

    async def morning(self) -> bool:
        """What the app sends when opened in the morning: Health summary + weather check."""
        return await self.http.post([("obs.wearable_daily", self.wearable_payload()), *self.weather_check()])

    async def play(self) -> bool:
        games = [self.lantern(), self.seeds(), self.watering()]
        return await self.http.post([self.firefly(), self.pebbles(), *((t, p, self.game_quality(p)) for t, p in games)])

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
