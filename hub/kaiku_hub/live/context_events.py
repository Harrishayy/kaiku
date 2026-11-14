"""Live context layer (plan 06 §4, T5): reflex code tells the open Live session what is happening.

Only a FIXED vocabulary of short bracketed events can be sent (`notice(key)` takes a key, never free text), so an
event can never carry raw numbers or a state word ("stable", "low", ...). The model reacts naturally ("ooh, lively
today!") or stays quiet (proactive audio). Rules (pure + deterministic, tested):

- rate limit: ≥ `min_gap_s` (20 s) between two sent events, ≤ `max_per_session` (8) per session;
- dedupe: the same event is sent at most once per session (a dropped one may be retried later);
- no session open → dropped silently.

Producers live in the hub (`Hub.on_raw`, `Hub.emit`, `Hub.attention_step`, `Hub._open_live`):
drum feel relative to THIS ritual's first taps (`DrumFeel`), breathing post vs pre (`breathing_calmer`),
second face / presence lost, light class (`light_key`), and "it's late" at session start.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from kaiku_contracts.jlog import get_logger

log = get_logger("hub")

VOCAB: dict[str, str] = {
    "drum.lively": "[drumming · lively]",
    "drum.steady": "[drumming · steady]",
    "drum.gentle": "[drumming · gentle]",
    "breathe.calmer": "[breathing · heart calmer]",
    "people.second": "[second person nearby]",
    "people.away": "[person stepped away]",
    "light.dim": "[light · dim]",
    "light.bright": "[light · bright]",
    "time.late": "[it's late]",
}

#: words an event must never contain (consensus/clinical state language) — checked by tests over VOCAB
STATE_WORDS = frozenset({"stable", "insufficient", "worse", "worsening", "better", "improving", "declining",
                         "low", "high", "depressed", "depression", "relapse", "anxious", "sad", "risk", "crisis",
                         "check-in", "call", "diagnosis", "mood", "state", "baseline", "score", "normal"})

DIM_LUX, BRIGHT_LUX = 50.0, 1000.0   # light classes (between = nothing worth saying)
LATE_HOURS = frozenset({23, 0, 1, 2, 3})


@dataclass
class ContextEvents:
    sink: Callable[[str], Awaitable[None]]
    min_gap_s: float = 20.0
    max_per_session: int = 8
    clock: Callable[[], float] = time.monotonic
    active: bool = False
    sent: list[str] = field(default_factory=list)
    _last: float = -1e18

    def open_session(self) -> None:
        self.active, self.sent, self._last = True, [], -1e18

    def close_session(self) -> None:
        self.active = False

    def allowed(self, key: str) -> bool:
        text = VOCAB.get(key)
        return (text is not None and self.active and text not in self.sent
                and len(self.sent) < self.max_per_session and self.clock() - self._last >= self.min_gap_s)

    async def notice(self, key: str) -> bool:
        """Send one vocabulary event if the rules allow it. Never raises."""
        if not self.allowed(key):
            return False
        text = VOCAB[key]
        self.sent.append(text)
        self._last = self.clock()
        log.info("context_event", text, n=len(self.sent))
        try:
            await self.sink(text)
        except Exception as e:  # a voice failure never breaks the ritual
            log.warning("context_event_failed", type(e).__name__)
        return True


@dataclass
class DrumFeel:
    """Drumming energy relative to the first `window` taps of this ritual (not an absolute judgement)."""

    window: int = 6
    refractory_ms: float = 80
    up: float = 1.15
    down: float = 0.85
    times: list[int] = field(default_factory=list)
    forces: list[float | None] = field(default_factory=list)

    def reset(self) -> None:
        self.times, self.forces = [], []

    @staticmethod
    def _tempo(times: list[int]) -> float | None:
        iv = [b - a for a, b in zip(times, times[1:], strict=False) if 0 < b - a <= 2000]
        return 60000.0 / median(iv) if iv else None

    def add(self, t_ms: int, force: float | None) -> str | None:
        """Add a tap; returns a VOCAB key once there are `window` taps, else None.
        `force` is None for the KY-031 knock switch (timing only): then tempo alone decides."""
        if self.times and (t_ms < self.times[-1] or t_ms - self.times[-1] < self.refractory_ms):
            if t_ms < self.times[-1]:
                self.reset()  # device clock reset
            else:
                return None
        self.times.append(int(t_ms))
        self.forces.append(None if force is None else float(force))
        n = self.window
        if len(self.times) < n:
            return None
        ratios: list[float] = []
        t0, t1 = self._tempo(self.times[:n]), self._tempo(self.times[-n:])
        if t0 and t1:
            ratios.append(t1 / t0)
        first, last = self.forces[:n], self.forces[-n:]
        if None not in first and None not in last:
            f0, f1 = sum(first) / n, sum(last) / n  # type: ignore[arg-type]
            if f0 > 0:
                ratios.append(f1 / f0)
        if not ratios:
            return "drum.steady"
        r = sum(ratios) / len(ratios)
        return "drum.lively" if r >= self.up else "drum.gentle" if r <= self.down else "drum.steady"


def breathing_calmer(payload: dict[str, Any]) -> bool:
    """obs.intervention_response{activity: breathe}: heart rate down (or HRV up with heart rate not up)."""
    if payload.get("activity") != "breathe":
        return False
    d = payload.get("delta") or {}
    hr, rmssd = d.get("hr_bpm"), d.get("rmssd_ms")
    if hr is not None and hr > 0:
        return False
    return (hr is not None and hr < 0) or (rmssd is not None and rmssd > 0)


def light_key(lux: float) -> str | None:
    return "light.dim" if lux < DIM_LUX else "light.bright" if lux >= BRIGHT_LUX else None


def late_key(hour: int) -> str | None:
    return "time.late" if hour in LATE_HOURS else None
