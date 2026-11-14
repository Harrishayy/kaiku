"""Hard spend cap for every paid model call (Gemini API / Vertex, Modal GPU) — shared by cloud, hub, evals, tools.

One small SQLite ledger (default `logs/spend.sqlite`; `KAIKU_SPEND_DB` overrides, e.g. `/data/spend.sqlite` on Modal).
Before a call: `guard(provider, model, est_usd)` raises BudgetExceeded if it would cross the cap. After the call:
`charge(...)` records the estimated cost. Prices in `config/kaiku.toml [budget.prices]` are deliberately
*conservative* (rounded up), so the ledger over-counts rather than under-counts. Team rule: total under $10.
Callers treat BudgetExceeded exactly like "model unavailable" → their deterministic fallback.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import find_repo_file, get

_LOCK = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


def _db_path() -> Path:
    p = os.environ.get("KAIKU_SPEND_DB")
    if p:
        return Path(p)
    root = find_repo_file("pyproject.toml")
    return (root.parent if root else Path.cwd()) / "logs" / "spend.sqlite"


def _conn() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS spend (ts REAL, provider TEXT, model TEXT, task TEXT, component TEXT,"
              " usd REAL, units TEXT)")
    return c


def limits() -> dict[str, float]:
    return {"total": float(os.environ.get("KAIKU_BUDGET_TOTAL_USD") or get("budget", "total_usd", 10.0)),
            "daily": float(os.environ.get("KAIKU_BUDGET_DAILY_USD") or get("budget", "daily_usd", 4.0))}


def price(model: str) -> dict[str, float]:
    """Per-model price entry from config (USD): in_per_m, out_per_m (tokens), per_min (audio), per_image, per_hour."""
    table: dict[str, Any] = get("budget", "prices", {}) or {}
    hits = [k for k in table if k != "default" and model.startswith(k)]
    if hits:  # longest prefix wins, so "gemini-3.8-flash-tts" never prices as "gemini-3.8-flash"
        return dict(table[max(hits, key=len)])
    return dict(table.get("default", {"in_per_m": 5.0, "out_per_m": 20.0}))


def estimate(model: str, *, in_tokens: int = 0, out_tokens: int = 0, audio_min: float = 0.0, images: int = 0,
             gpu_s: float = 0.0) -> float:
    p = price(model)
    return round(in_tokens / 1e6 * p.get("in_per_m", 0) + out_tokens / 1e6 * p.get("out_per_m", 0)
                 + audio_min * p.get("per_min", 0) + images * p.get("per_image", 0)
                 + gpu_s / 3600 * p.get("per_hour", 0), 6)


def spent(since_s: float | None = None) -> float:
    with _LOCK, _conn() as c:
        q, args = "SELECT COALESCE(SUM(usd), 0) FROM spend", ()
        if since_s is not None:
            q, args = q + " WHERE ts >= ?", (since_s,)
        return float(c.execute(q, args).fetchone()[0])


def _day_start() -> float:
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def guard(provider: str, model: str, est_usd: float) -> None:
    """Raise BudgetExceeded if this call could cross the total or daily cap."""
    lim = limits()
    total, today = spent(), spent(_day_start())
    if total + est_usd > lim["total"]:
        raise BudgetExceeded(f"total budget ${lim['total']:.2f} reached (spent ${total:.2f}) — {provider}:{model}")
    if today + est_usd > lim["daily"]:
        raise BudgetExceeded(f"daily budget ${lim['daily']:.2f} reached (today ${today:.2f}) — {provider}:{model}")


def charge(provider: str, model: str, usd: float, *, task: str = "", component: str = "", units: str = "") -> None:
    with _LOCK, _conn() as c:
        c.execute("INSERT INTO spend VALUES (?,?,?,?,?,?,?)", (time.time(), provider, model, task, component,
                                                               float(usd), units))


def report() -> dict[str, Any]:
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT provider, model, COUNT(*), ROUND(SUM(usd), 4) FROM spend GROUP BY provider, model"
                         " ORDER BY 4 DESC").fetchall()
    lim = limits()
    total = spent()
    return {"limit_total_usd": lim["total"], "limit_daily_usd": lim["daily"], "spent_usd": round(total, 4),
            "spent_today_usd": round(spent(_day_start()), 4), "remaining_usd": round(lim["total"] - total, 4),
            "by_model": [{"provider": r[0], "model": r[1], "calls": r[2], "usd": r[3]} for r in rows]}


if __name__ == "__main__":  # `make spend`
    import json

    print(json.dumps(report(), indent=1))


def metered(provider: str, model: str, est_usd: float, fn, *args: Any, task: str = "", component: str = "",
            **kwargs: Any) -> Any:
    """guard → call → charge the (conservative) estimate. Failed calls are charged too: they may still bill."""
    guard(provider, model, est_usd)
    try:
        return fn(*args, **kwargs)
    finally:
        charge(provider, model, est_usd, task=task, component=component)


def text_estimate(model: str, prompt_chars: int, max_out_tokens: int = 800) -> float:
    """~3 chars per token, rounded up; output assumed at the max."""
    return estimate(model, in_tokens=prompt_chars // 3 + 50, out_tokens=max_out_tokens)
