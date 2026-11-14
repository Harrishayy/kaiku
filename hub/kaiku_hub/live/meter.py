"""Spend meter for streaming model sessions (Gemini Live, Lyria RealTime) on the shared `kaiku_contracts.budget` ledger.

    meter = SessionMeter("gemini", model)
    meter.open()                  # guard(estimate(model, audio_min=5)) -> BudgetExceeded = don't open; charges minute 1
    meter.start(on_exceeded)      # every started minute after that: guard + charge(audio_min=1);
                                  # over the cap -> on_exceeded() (the adapter closes politely, scripted fallback)
    meter.stop()
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from kaiku_contracts import budget
from kaiku_contracts.jlog import get_logger

log = get_logger("hub")

OPEN_ESTIMATE_MIN = 5.0


class SessionMeter:
    def __init__(self, provider: str, model: str, *, component: str = "hub", minute_s: float = 60.0):
        self.provider, self.model, self.component, self.minute_s = provider, model, component, minute_s
        self.minutes = 0
        self._task: asyncio.Task | None = None

    def _charge_minute(self) -> None:
        usd = budget.estimate(self.model, audio_min=1)
        budget.guard(self.provider, self.model, usd)
        budget.charge(self.provider, self.model, usd, task="live_session", component=self.component, units="1 min")
        self.minutes += 1

    def open(self) -> None:
        """Raises BudgetExceeded if a typical session (5 min) could cross the cap; else charges the first minute."""
        budget.guard(self.provider, self.model, budget.estimate(self.model, audio_min=OPEN_ESTIMATE_MIN))
        self.minutes = 0
        self._charge_minute()

    def start(self, on_exceeded: Callable[[], Awaitable[None]]) -> None:
        self.stop()
        self._task = asyncio.get_running_loop().create_task(self._loop(on_exceeded), name=f"meter-{self.provider}")

    async def _loop(self, on_exceeded: Callable[[], Awaitable[None]]) -> None:
        while True:
            await asyncio.sleep(self.minute_s)
            try:
                self._charge_minute()
            except budget.BudgetExceeded as e:
                log.warning("budget_exceeded", str(e), model=self.model, minutes=self.minutes)
                self._task = None  # on_exceeded may call stop(); don't cancel ourselves mid-callback
                await on_exceeded()
                return

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
