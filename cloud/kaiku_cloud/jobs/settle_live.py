"""One-off: settle Live budget reservations that were never settled, from what cloud databases recorded.

    uv run python -m kaiku_cloud.jobs.settle_live --ledger logs/spend.sqlite --db logs/kaiku.sqlite            # dry run
    uv run python -m kaiku_cloud.jobs.settle_live --ledger logs/spend.sqlite --db logs/kaiku.sqlite --apply

The dry run is the default: the ledger and every database are opened read-only and nothing is written. It prints
each unsettled reservation, what it would settle to and why, and the totals before and after. `--apply` appends
`live_settlement` rows through kaiku_contracts.budget (append-only; running it twice changes nothing more).

A reservation is settled only when a database given with `--db` (repeat it for several cloud instances) shows how
long that conversation ran:
- a reservation that names its conversation (`session=`): the episode's recorded end, and for a conversation that
  used several tokens, the next token's mint for every token but the last;
- an older reservation without a name: the mint that a database logged right after it (`model_calls`), the one
  episode (not the robot's) that this home started in the seconds before it, and that episode's recorded end. A
  database is used for this only when every mint it logged has its own reservation in this ledger: one that
  belongs to another ledger is ignored, so a coincidence of timing cannot settle the wrong row;
- with `--last-tool-call`, a named conversation that never reported an end is settled at the last tool call the
  cloud saw, once its token's lifetime is over. That is a lower bound on its length, so it is off by default.
Anything else is left alone and keeps its full reservation.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from kaiku_contracts import budget

# One request does, in this order: episode row (start, cut to the whole second) -> reservation -> the provider
# call (timeout 8 s) -> the mint's log row. So the episode starts at most a few seconds before the reservation and
# never after it, and the log row follows it by at most the timeout.
START_BEFORE_S = 4.0
LOG_AFTER_S = 10.0


def _ro(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _ts(iso: str | None) -> float | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else None
    except ValueError:
        return None


def load_db(path: Path) -> dict[str, Any]:
    """What one cloud database knows about conversations: episodes, logged mints, last tool calls."""
    c = _ro(path)
    try:
        episodes = [dict(r) | {"t0": _ts(r["start"]), "t1": _ts(r["end"])} for r in c.execute(
            "SELECT id, home_id, surface, intent, start, end FROM episodes")]
        mints = [(t, r["home_id"]) for r in c.execute(
            "SELECT ts, home_id FROM model_calls WHERE task='live_reservation' AND ok=1") if (t := _ts(r["ts"]))]
        seen = {}
        for r in c.execute("SELECT key, value FROM kv WHERE key LIKE 'live:%'"):
            try:
                seen[r["key"][5:]] = float(json.loads(r["value"])["last"])
            except (ValueError, KeyError, TypeError):
                continue
    except sqlite3.OperationalError as e:
        raise SystemExit(f"{path}: not a Kaiku cloud database ({e})") from None
    finally:
        c.close()
    return {"name": path.name, "episodes": [e for e in episodes if e["t0"] is not None], "mints": mints, "seen": seen}


def _label(ep: dict[str, Any], db: dict[str, Any]) -> str:
    return f"episode {ep['id'][:8]} {ep['surface']}/{ep['intent']} in {db['name']}"


def assign(tokens: list[dict[str, Any]], db: dict[str, Any], since: float) -> dict[str, str] | None:
    """Which reservation each mint this database logged belongs to: {reservation key: home}. Each mint takes the
    latest reservation in the seconds before its log row that no other mint has taken. None when a mint finds
    none: then this database was not (only) charging this ledger, and nothing in it is trusted for old rows."""
    free = sorted(tokens, key=lambda t: t["ts"])
    out: dict[str, str] = {}
    for t, home in sorted(m for m in db["mints"] if m[0] >= since):
        mine = [tok for tok in free if t - LOG_AFTER_S <= tok["ts"] <= t and tok["key"] not in out]
        if not mine:
            return None
        out[mine[-1]["key"]] = home
    return out


def find_unnamed(tok: dict[str, Any], dbs: list[dict[str, Any]]) -> tuple[float | None, str]:
    """(seconds used | None, why) for a reservation that does not name its conversation."""
    hits = []
    for db in dbs:
        home = (db.get("assigned") or {}).get(tok["key"])
        if home is None:
            continue
        started = [ep for ep in db["episodes"] if ep["home_id"] == home and ep["surface"] != "robot"
                   and tok["ts"] - START_BEFORE_S <= ep["t0"] <= tok["ts"]]
        hits.append((started, db))
    if not hits:
        return None, "no record of this conversation in the databases given"
    if len(hits) > 1:
        return None, f"{len(hits)} databases logged a mint at that moment: cannot tell which"
    started, db = hits[0]
    if not started:
        return None, f"{db['name']} logged this mint but no conversation started with it (a resumed one keeps its full amount)"
    if len(started) > 1:
        return None, f"{len(started)} conversations started at that moment in {db['name']}: cannot tell which"
    ep = started[0]
    if ep["t1"] is None or ep["t1"] < ep["t0"]:
        return None, f"{_label(ep, db)}: no recorded end"
    return ep["t1"] - ep["t0"], f"{_label(ep, db)}, recorded end"


def plan(tokens: list[dict[str, Any]], dbs: list[dict[str, Any]], *, since: float, now: float,
         last_tool_call: bool = False, min_minutes: float = 1.0) -> list[dict[str, Any]]:
    """Pure. One entry per unsettled reservation at or after `since`: {token, why} and, when it can be settled,
    {used_s, billed_min, usd, delta, via}."""
    out: list[dict[str, Any]] = []
    sessions: dict[str, list[dict[str, Any]]] = {}
    for t in tokens:
        if t["session"]:
            sessions.setdefault(t["session"], []).append(t)
    for db in dbs:
        db["assigned"] = assign(tokens, db, since)

    def add(tok: dict[str, Any], used: float | None, why: str, via: str = "") -> None:
        entry: dict[str, Any] = {"token": tok, "why": why}
        if used is not None:
            p = budget.plan_session([tok], tok["ts"] + used, min_minutes=min_minutes)
            if p:
                entry |= {k: p[0][k] for k in ("used_s", "billed_min", "usd", "delta")} | {"via": via}
        out.append(entry)

    for tok in tokens:
        if tok["settled"] or tok["ts"] < since or tok["minutes"] <= 0:
            continue
        if not tok["session"]:
            used, why = find_unnamed(tok, dbs)
            add(tok, used, why, "backfill_episode")
            continue
        group = sessions[tok["session"]]
        nxt = next((t["ts"] for t in group if t["ts"] > tok["ts"]), None)
        found = [(ep, db) for db in dbs for ep in db["episodes"] if ep["id"] == tok["session"]]
        ended = [(ep, db) for ep, db in found if ep["t1"] is not None and ep["t1"] >= ep["t0"]]
        seen = max((db["seen"][tok["session"]] for db in dbs if tok["session"] in db["seen"]), default=None)
        if ended:
            ep, db = ended[0]
            end = group[0]["ts"] + (ep["t1"] - ep["t0"])
            used = max(0.0, min(max(end, seen or end), nxt or float("inf")) - tok["ts"])
            add(tok, used, f"{_label(ep, db)}, recorded end", "backfill_episode")
        elif nxt is not None:
            add(tok, nxt - tok["ts"], "the conversation's next token was minted then", "backfill_next_mint")
        elif last_tool_call and seen is not None and now > tok["ts"] + tok["minutes"] * 60:
            add(tok, max(0.0, seen - tok["ts"]), "last tool call the cloud saw (a lower bound)", "backfill_last_tool")
        elif found:
            add(tok, None, f"{_label(*found[0])}: no recorded end")
        else:
            add(tok, None, "no record of this conversation in the databases given")
    return out


def totals(path: Path) -> dict[str, float]:
    c = _ro(path)
    try:
        total, today, held, n = c.execute(
            "SELECT COALESCE(SUM(usd),0), COALESCE(SUM(CASE WHEN ts>=? THEN usd ELSE 0 END),0),"
            " COALESCE(SUM(CASE WHEN task IN (?,?) THEN usd ELSE 0 END),0), COUNT(*) FROM spend",
            (budget._day_start(), budget.LIVE_RESERVATION, budget.LIVE_SETTLEMENT)).fetchone()
    finally:
        c.close()
    return {"total": float(total), "today": float(today), "live": float(held), "rows": int(n)}


def _when(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", type=Path, required=True, help="the spend ledger to settle (e.g. logs/spend.sqlite)")
    ap.add_argument("--db", type=Path, action="append", default=[], help="a cloud database to look conversations up in; repeatable")
    ap.add_argument("--since", type=date.fromisoformat, default=date.today(), help="settle reservations made on or after this local day (default: today)")
    ap.add_argument("--last-tool-call", action="store_true", help="also settle a named conversation that never reported an end at its last tool call (a lower bound)")
    ap.add_argument("--apply", action="store_true", help="write the settlement rows (default: dry run, nothing is written)")
    a = ap.parse_args(argv)
    for f in [a.ledger, *a.db]:
        if not f.is_file():
            print(f"no such file: {f}", file=sys.stderr)
            return 2
    dbs = [load_db(p) for p in a.db]
    since = datetime.combine(a.since, datetime.min.time()).timestamp()
    tokens = budget.live_reservations(a.ledger)
    plans = plan(tokens, dbs, since=since, now=datetime.now(UTC).timestamp(), last_tool_call=a.last_tool_call)
    before, limit = totals(a.ledger), budget.limits()
    print(f"ledger {a.ledger} · {len(dbs)} database(s) · reservations since {a.since} · "
          f"{'APPLY' if a.apply else 'dry run'}")
    print(f"before: total ${before['total']:.2f} of ${limit['total']:.2f}, today ${before['today']:.2f} of "
          f"${limit['daily']:.2f}, held by Live ${before['live']:.2f} ({before['rows']} rows)")
    for db in dbs:
        n = sum(t >= since for t, _home in db["mints"])
        print(f"  {db['name']}: " + (f"{n} logged mint(s), each with its reservation in this ledger" if db["assigned"] is not None
                                     else f"IGNORED for unnamed rows: not all of its {n} logged mint(s) have a reservation in this ledger"))
    release, left = 0.0, 0
    for p in plans:
        tok = p["token"]
        head = f"  {_when(tok['ts'])}  ${tok['usd']:.2f} for {tok['minutes']:g} min"
        if "delta" in p:
            release -= p["delta"]
            print(f"{head}  ->  {p['used_s']:.0f} s used, {p['billed_min']:g} min counted, ${p['usd']:.2f} "
                  f"(releases ${-p['delta']:.2f})  [{p['why']}]")
        else:
            left += 1
            print(f"{head}  left alone: {p['why']}")
    doing = [p for p in plans if "delta" in p]
    if a.apply and doing:
        os.environ["KAIKU_SPEND_DB"] = str(a.ledger)  # budget writes to the ledger named on the command line
        for p in doing:
            budget.settle(p["token"]["ts"], p["used_s"], via=p["via"])
    after = totals(a.ledger) if a.apply else {**before, "total": before["total"] - release,
                                              "today": before["today"] - release, "live": before["live"] - release,
                                              "rows": before["rows"] + len(doing)}
    print(f"after:  total ${after['total']:.2f} of ${limit['total']:.2f}, today ${after['today']:.2f} of "
          f"${limit['daily']:.2f}, held by Live ${after['live']:.2f} ({after['rows']} rows)")
    print(f"{'released' if a.apply else 'would release'} ${release:.2f} from {len(doing)} reservation(s); "
          f"{left} left alone; room under the total cap ${limit['total'] - before['total']:.2f} -> "
          f"${limit['total'] - after['total']:.2f}")
    if not a.apply:
        print("dry run: nothing was written. Add --apply to append the settlement rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
