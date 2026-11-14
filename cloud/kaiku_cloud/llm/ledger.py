"""Usage ledger (plan 06 §2): one `model_calls` row per model call (or deterministic answer). NEVER any content —
only ts, home, model, task, route, latency, ok, fallback. The API binds its Store at startup; without a bound store
(unit tests of a single adapter, CLI tools) rows are dropped silently.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

_store: Any = None


def bind(store: Any) -> None:
    global _store
    _store = store


def bound() -> Any:
    return _store


def record(model: str, task: str, *, ok: bool, latency_ms: float | None = None, route: str | None = None,
           fallback: bool = False, home_id: str | None = None) -> None:
    if _store is None:
        return
    try:
        _store.model_call_insert({"ts": datetime.now(UTC).isoformat(), "home_id": home_id, "model": model or "?",
                                  "task": task, "route": route, "latency_ms": latency_ms, "ok": ok,
                                  "fallback": fallback})
    except Exception:  # the ledger never breaks a request
        pass


@contextmanager
def timed(model: str, task: str, *, route: str | None = None, home_id: str | None = None) -> Iterator[None]:
    """Record one call: ok when the block returns, not ok when it raises (the exception propagates)."""
    t0 = time.perf_counter()
    try:
        yield
    except BaseException:
        record(model, task, ok=False, latency_ms=round((time.perf_counter() - t0) * 1000, 1), route=route,
               home_id=home_id)
        raise
    record(model, task, ok=True, latency_ms=round((time.perf_counter() - t0) * 1000, 1), route=route,
           home_id=home_id)


OUTCOME = ".route"  # task suffix of a per-request outcome row (ask_mind.route): which route finally answered


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))], 1)


def summary(store: Any, days: int, tz: Any, now: datetime | None = None) -> dict[str, Any]:
    """Per (local day, model, task): calls, ok, fallbacks, p50/p95 latency. `routes` = ask_mind outcomes.
    Outcome rows that name a real model duplicate that model's call row, so they only feed `routes`."""
    now = now or datetime.now(UTC)
    since_local = (now.astimezone(tz) - timedelta(days=days - 1)).date()
    since = datetime.combine(since_local, datetime.min.time(), tz).astimezone(UTC).isoformat()
    rows = store.model_calls(since)
    routes = Counter(r["route"] for r in rows if r["task"].endswith(OUTCOME) and r["route"])
    calls = [r for r in rows if not r["task"].endswith(OUTCOME) or r["model"] in ("deterministic", "scripted")]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in calls:
        day = datetime.fromisoformat(r["ts"]).astimezone(tz).date().isoformat()
        groups[(day, r["model"], r["task"])].append(r)
    out_rows = []
    for (day, model, task), rs in sorted(groups.items()):
        lat = [r["latency_ms"] for r in rs if r["latency_ms"] is not None]
        out_rows.append({"day": day, "model": model, "task": task, "calls": len(rs), "ok": sum(r["ok"] for r in rs),
                         "fallbacks": sum(r["fallback"] for r in rs), "p50_ms": _pct(lat, 0.5),
                         "p95_ms": _pct(lat, 0.95)})
    real = [r["latency_ms"] for r in calls if r["latency_ms"] is not None and r["model"] not in
            ("deterministic", "scripted", "template", "rule")]
    return {"since": since_local.isoformat(), "days": days, "rows": out_rows,
            "per_model": dict(Counter(r["model"] for r in calls)), "routes": dict(routes), "calls": len(calls),
            "fallback_rate": round(sum(r["fallback"] for r in calls) / len(calls), 3) if calls else 0.0,
            "p50_ms": _pct(real, 0.5), "p95_ms": _pct(real, 0.95)}


def day_start_utc(now: datetime, tz: Any) -> str:
    """ISO UTC timestamp of the local midnight of `now` (budget windows are local days)."""
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()
