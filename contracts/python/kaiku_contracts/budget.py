"""Hard spend cap for every paid model call (Gemini API / Vertex, Modal GPU) — shared by cloud, hub, evals, tools.

One small SQLite ledger (default `logs/spend.sqlite`; `KAIKU_SPEND_DB` overrides, e.g. `/data/spend.sqlite` on Modal).
Before a call: `charge(...)` atomically admits and reserves its estimated cost, or raises BudgetExceeded.
`guard(...)` is an advisory preflight only; it does not reserve funds. Prices in `config/kaiku.toml [budget.prices]` are deliberately
*conservative* (rounded up), so the ledger over-counts rather than under-counts. Team rule: total under $10.
Callers treat BudgetExceeded exactly like "model unavailable" → their deterministic fallback.

Live audio is the one reservation that is settled afterwards: a `live_reservation` row holds a whole token's
minutes, and `settle_session` / `settle` append `live_settlement` rows that bring it down to the started minutes the
conversation really used (see "Live reservations" below). The ledger stays append-only: a reservation row is never
changed or removed, and every total the caps read is the plain sum of all rows.
"""

from __future__ import annotations

import math
import os
import re
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
    """Advisory preflight; callers must reserve with charge before starting paid work."""
    _validate_cost(est_usd)
    lim = limits()
    total, today = spent(), spent(_day_start())
    if total + est_usd > lim["total"]:
        raise BudgetExceeded(f"total budget ${lim['total']:.2f} reached (spent ${total:.2f}) — {provider}:{model}")
    if today + est_usd > lim["daily"]:
        raise BudgetExceeded(f"daily budget ${lim['daily']:.2f} reached (today ${today:.2f}) — {provider}:{model}")


def now() -> float:
    """The ledger's clock (every row's `ts`). Settlements measure talk time on this clock."""
    return time.time()


def charge(provider: str, model: str, usd: float, *, task: str = "", component: str = "", units: str = "") -> float:
    """Atomically reserve an estimate before provider work, across processes sharing this ledger.

    Reservations survive failures and process exits: a dispatched request may still bill. Separate
    ledgers enforce separate caps; this is not a distributed account-wide billing limit.
    Returns the row's `ts`, which is how a Live reservation is named when it is settled.
    """
    _validate_cost(usd)
    with _LOCK, _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        lim = limits()
        total, today = c.execute(
            "SELECT COALESCE(SUM(usd),0), COALESCE(SUM(CASE WHEN ts>=? THEN usd ELSE 0 END),0) FROM spend",
            (_day_start(),)).fetchone()
        if total + usd > lim["total"]:
            raise BudgetExceeded(f"total budget ${lim['total']:.2f} reached (spent ${total:.2f}) — {provider}:{model}")
        if today + usd > lim["daily"]:
            raise BudgetExceeded(f"daily budget ${lim['daily']:.2f} reached (today ${today:.2f}) — {provider}:{model}")
        ts = now()
        c.execute("INSERT INTO spend VALUES (?,?,?,?,?,?,?)", (ts, provider, model, task, component, float(usd), units))
        return ts


def _validate_cost(usd: float) -> None:
    if not math.isfinite(usd) or usd < 0:
        raise ValueError("estimated cost must be finite and non-negative")


# ---------------------------------------------------------------- Live reservations
# A Live token is paid for before the conversation: `live_reservation`, units `reserved_audio_minutes=<m>
# session=<id>`. What the conversation really used is known only afterwards, so the reservation is settled by
# appending `live_settlement` rows that name it (`res_ts=<its ts>`): the first one releases what was not used (usd
# <= 0), a later one with evidence of a longer conversation takes some back (usd > 0). The longest evidence wins,
# a reservation is never settled below one started minute or above what it reserved, and one that is never
# settled keeps its full amount. A settlement row carries the reservation's own `ts`, so the daily cap moves on
# the day the reservation was made; `at=` in its units is when it was written.
LIVE_RESERVATION, LIVE_SETTLEMENT = "live_reservation", "live_settlement"
SESSION_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}")
_FIELD = re.compile(r"(\w+)=(\S+)")


def reservation_units(minutes: float, session: str | None = None) -> str:
    tag = f" session={session}" if session and SESSION_ID.fullmatch(session) else ""
    return f"reserved_audio_minutes={minutes:g}{tag}"


def _fields(units: str | None) -> dict[str, str]:
    return dict(_FIELD.findall(units or ""))


def _num(text: str | None) -> float | None:
    try:
        v = float(text)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _tokens(c: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every Live reservation, oldest first, with what its settlement rows say so far."""
    rows = c.execute("SELECT ts, model, usd, units, task FROM spend WHERE task IN (?, ?) ORDER BY ts, rowid",
                     (LIVE_RESERVATION, LIVE_SETTLEMENT)).fetchall()
    settled: dict[str, dict[str, float]] = {}
    for _ts, _model, usd, units, task in rows:
        f = _fields(units)
        if task == LIVE_SETTLEMENT and "res_ts" in f:
            s = settled.setdefault(f["res_ts"], {"usd": 0.0, "billed": 0.0})
            s["usd"] += float(usd)
            s["billed"] = max(s["billed"], _num(f.get("billed_min")) or 0.0)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ts, model, usd, units, task in rows:
        if task != LIVE_RESERVATION:
            continue
        f, key = _fields(units), repr(float(ts))
        s = settled.get(key)
        out.append({"ts": float(ts), "key": key, "model": model, "usd": float(usd), "session": f.get("session"),
                    "minutes": _num(f.get("reserved_audio_minutes")) or 0.0, "settled": s is not None,
                    "billed_min": s["billed"] if s else None,
                    "cost": round(float(usd) + s["usd"], 6) if s else float(usd), "twin": key in seen})
        seen.add(key)
    twins = {t["key"] for t in out if t["twin"]}
    return [t for t in out if t["key"] not in twins]  # two rows with one name cannot be told apart: left alone


def live_reservations(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Every Live reservation with its settled state. The ledger (`path`, default this process's) is opened
    read-only and never created: no ledger, or one without the table, has no reservations."""
    file = Path(path) if path is not None else _db_path()
    if not file.is_file():
        return []
    c = sqlite3.connect(f"file:{file}?mode=ro", uri=True, timeout=10)
    try:
        return _tokens(c)
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()


def rows(since: float, until: float, path: Path | str | None = None) -> list[dict[str, Any]]:
    """Ledger rows with `since <= ts < until`, oldest first (a developer view matches model calls to their
    estimate with it). Read-only like `live_reservations`: the ledger is never created or written."""
    file = Path(path) if path is not None else _db_path()
    if not file.is_file():
        return []
    c = sqlite3.connect(f"file:{file}?mode=ro", uri=True, timeout=10)
    try:
        found = c.execute("SELECT ts, provider, model, task, component, usd, units FROM spend WHERE ts >= ? AND ts < ?"
                          " ORDER BY ts, rowid", (since, until)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()
    return [dict(zip(("ts", "provider", "model", "task", "component", "usd", "units"), r, strict=True)) for r in found]


def bill(token: dict[str, Any], used_s: float, min_minutes: float = 1.0) -> dict[str, float]:
    """What a reservation costs for `used_s` seconds of conversation: whole started minutes, at least
    `min_minutes`, never more than it reserved. Pure."""
    minutes = float(token["minutes"])
    if minutes <= 0 or not math.isfinite(used_s):
        return {"billed_min": minutes, "usd": float(token["usd"])}
    billed = min(minutes, max(float(min_minutes), float(math.ceil(max(0.0, used_s) / 60))))
    return {"billed_min": billed, "usd": round(float(token["usd"]) * billed / minutes, 6)}


def plan_session(tokens: list[dict[str, Any]], end_ts: float, *, floor_ts: float | None = None,
                 min_minutes: float = 1.0) -> list[dict[str, Any]]:
    """Pure. `tokens`: every reservation of ONE conversation, oldest first. Each token was in use from its own
    `ts` until the conversation ended (`end_ts`, never earlier than `floor_ts`, the last moment the conversation
    is known to have been alive), the next token took over, or its minutes ran out, whichever came first.
    Returns the settlement rows to append: [{token, used_s, billed_min, usd (the reservation's new cost), delta}]."""
    end = max(end_ts, floor_ts) if floor_ts is not None else end_ts
    out = []
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1]["ts"] if i + 1 < len(tokens) else math.inf
        used = max(0.0, min(end, nxt, tok["ts"] + tok["minutes"] * 60) - tok["ts"])
        b = bill(tok, used, min_minutes)
        if tok["settled"] and b["billed_min"] <= (tok["billed_min"] or 0.0):
            continue  # settled already, and this is not evidence of a longer conversation
        out.append({"token": tok, "used_s": used, **b, "delta": round(b["usd"] - tok["cost"], 6)})
    return out


def _append(c: sqlite3.Connection, plans: list[dict[str, Any]], via: str) -> None:
    for p in plans:
        tok = p["token"]
        units = (f"session={tok['session'] or '-'} res_ts={tok['key']} used_s={p['used_s']:.0f} "
                 f"billed_min={p['billed_min']:g} reserved_min={tok['minutes']:g} via={via} at={now():.0f}")
        c.execute("INSERT INTO spend VALUES (?,?,?,?,?,?,?)",
                  (tok["ts"], "gemini", tok["model"], LIVE_SETTLEMENT, "cloud", p["delta"], units))


def settle_session(session: str, *, end_ts: float | None = None, elapsed_s: float | None = None,
                   floor_ts: float | None = None, via: str, min_minutes: float = 1.0) -> list[dict[str, Any]]:
    """Settle every Live reservation of one conversation to what it used. The end is `end_ts` on the ledger's
    clock, or `elapsed_s` after the conversation's first reservation (a length reported by the device), default
    now. Atomic; returns the rows it appended (none when there is nothing to change)."""
    if not SESSION_ID.fullmatch(session or ""):
        return []

    def plan(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mine = [t for t in tokens if t["session"] == session]
        if not mine:
            return []
        end = mine[0]["ts"] + max(0.0, elapsed_s) if elapsed_s is not None else end_ts if end_ts is not None else now()
        return plan_session(mine, end, floor_ts=floor_ts, min_minutes=min_minutes)

    if not plan(live_reservations()):  # read-only look first: most conversations have nothing (left) to settle
        return []
    with _LOCK, _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        plans = plan(_tokens(c))  # decided again inside the write transaction
        _append(c, plans, via)
        return plans


def settle(res_ts: float, used_s: float, *, via: str, min_minutes: float = 1.0) -> dict[str, Any] | None:
    """Settle ONE reservation named by its `ts` (a mint that failed: `min_minutes=0`; an old row without a
    session). None when there is no such reservation or nothing to change."""
    def plan(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tok = next((t for t in tokens if t["key"] == repr(float(res_ts))), None)
        return plan_session([tok], tok["ts"] + max(0.0, used_s), min_minutes=min_minutes) if tok else []

    if not plan(live_reservations()):
        return None
    with _LOCK, _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        plans = plan(_tokens(c))
        _append(c, plans, via)
        return plans[0] if plans else None


def session_minutes(session: str) -> float:
    """Minutes now counted for one conversation (settled tokens at what they settled to, open ones in full)."""
    return sum(t["billed_min"] if t["settled"] else t["minutes"] for t in live_reservations() if t["session"] == session)


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
    """Atomically reserve, then call. Failed calls retain their estimate: they may still bill."""
    charge(provider, model, est_usd, task=task, component=component)
    return fn(*args, **kwargs)


def text_estimate(model: str, prompt_chars: int, max_out_tokens: int = 800) -> float:
    """~3 chars per token, rounded up; output assumed at the max."""
    return estimate(model, in_tokens=prompt_chars // 3 + 50, out_tokens=max_out_tokens)
