"""SQLite repository. All SQL lives here; the rest of the cloud calls these methods only.

One writer (the API container). Thread-safe via a lock: FastAPI runs sync routes in a threadpool.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    home_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload TEXT NOT NULL,
    quality REAL,
    sim INTEGER NOT NULL DEFAULT 0,
    received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_home_ts ON events(home_id, ts);
CREATE INDEX IF NOT EXISTS events_received ON events(received_at);
CREATE TABLE IF NOT EXISTS homes (
    home_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'watch',  -- consensus state
    summary TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS explanations (
    home_id TEXT PRIMARY KEY,
    input_hash TEXT NOT NULL,
    explanation TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commands (
    id TEXT PRIMARY KEY,
    home_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    envelope TEXT NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS actions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    home_id TEXT NOT NULL,
    action TEXT NOT NULL,
    note TEXT,
    by_who TEXT,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS node_health (
    home_id TEXT PRIMARY KEY,
    report TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=DELETE")  # network volumes dislike WAL
        self._db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Additive migrations for DBs created by older versions (never destructive)."""
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(actions)")}
        if "by_who" not in cols:
            self._db.execute("ALTER TABLE actions ADD COLUMN by_who TEXT")

    def ping(self) -> bool:
        try:
            with self._lock:
                self._db.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    # ------------------------------------------------------------------ events
    def insert_events(self, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
        """rows: envelope dicts (json mode). Returns (inserted, duplicates)."""
        inserted = dupes = 0
        now = _now()
        with self._lock:
            self._db.execute("BEGIN")
            try:
                for r in rows:
                    cur = self._db.execute(
                        "INSERT OR IGNORE INTO events(id,home_id,ts,type,source,payload,quality,sim,received_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (str(r["id"]), r["home_id"], r["ts"], r["type"], r["source"], json.dumps(r["payload"]),
                         r.get("quality"), int(bool(r.get("sim"))), now),
                    )
                    if cur.rowcount:
                        inserted += 1
                    else:
                        dupes += 1
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return inserted, dupes

    def events_for_home(self, home_id: str, types: Iterable[str] | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM events WHERE home_id=?"
        args: list[Any] = [home_id]
        if types:
            types = list(types)
            q += f" AND type IN ({','.join('?' * len(types))})"
            args += types
        q += " ORDER BY ts"
        with self._lock:
            return [self._row_to_env(r) for r in self._db.execute(q, args).fetchall()]

    def recent_events(self, home_id: str | None, since: str | None, limit: int) -> list[dict[str, Any]]:
        q = "SELECT * FROM events WHERE 1=1"
        args: list[Any] = []
        if home_id:
            q += " AND home_id=?"
            args.append(home_id)
        if since:
            q += " AND ts>?"
            args.append(since)
        q += " ORDER BY ts DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            return [self._row_to_env(r) for r in self._db.execute(q, args).fetchall()]

    def home_ids(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._db.execute("SELECT DISTINCT home_id FROM events ORDER BY home_id")]

    def home_has_sim(self, home_id: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM events WHERE home_id=? AND sim=1 LIMIT 1", (home_id,)).fetchone() is not None

    @staticmethod
    def _row_to_env(r: sqlite3.Row) -> dict[str, Any]:
        env = {"v": 1, "id": r["id"], "ts": r["ts"], "home_id": r["home_id"], "source": r["source"],
               "type": r["type"], "payload": json.loads(r["payload"]), "sim": bool(r["sim"])}
        if r["quality"] is not None:
            env["quality"] = r["quality"]
        return env

    def delete_sim(self) -> int:
        """Demo reset: drop all simulated events and every derived row of homes left without events."""
        with self._lock:
            n = self._db.execute("DELETE FROM events WHERE sim=1").rowcount
            for table in ("homes", "explanations", "commands", "actions", "node_health"):
                self._db.execute(f"DELETE FROM {table} WHERE home_id NOT IN (SELECT DISTINCT home_id FROM events)")
            self._db.execute("DELETE FROM explanations")  # cheap to regenerate
            self._db.execute("DELETE FROM kv WHERE key LIKE 'phq9_due:%'")
        return n

    # ------------------------------------------------------------------ homes (computed status)
    def save_home_summary(self, home_id: str, state: str, summary: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO homes(home_id,status,summary,updated_at) VALUES (?,?,?,?)"
                " ON CONFLICT(home_id) DO UPDATE SET status=excluded.status, summary=excluded.summary,"
                " updated_at=excluded.updated_at",
                (home_id, state, json.dumps(summary, default=str), _now()),
            )

    def home_summaries(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {r["home_id"]: json.loads(r["summary"]) for r in self._db.execute("SELECT * FROM homes")}

    def home_summary(self, home_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._db.execute("SELECT summary FROM homes WHERE home_id=?", (home_id,)).fetchone()
        return json.loads(r[0]) if r else None

    # ------------------------------------------------------------------ explanations (LLM cache)
    def get_explanation(self, home_id: str) -> tuple[str, dict[str, Any]] | None:
        with self._lock:
            r = self._db.execute("SELECT input_hash, explanation FROM explanations WHERE home_id=?",
                                 (home_id,)).fetchone()
        return (r[0], json.loads(r[1])) if r else None

    def save_explanation(self, home_id: str, input_hash: str, explanation: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO explanations(home_id,input_hash,explanation,created_at) VALUES (?,?,?,?)"
                " ON CONFLICT(home_id) DO UPDATE SET input_hash=excluded.input_hash,"
                " explanation=excluded.explanation, created_at=excluded.created_at",
                (home_id, input_hash, json.dumps(explanation, default=str), _now()),
            )

    # ------------------------------------------------------------------ commands
    def queue_command(self, envelope: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO commands(id,home_id,ts,envelope) VALUES (?,?,?,?)",
                             (str(envelope["id"]), envelope["home_id"], envelope["ts"], json.dumps(envelope)))

    def pending_commands(self, home_id: str, since: str | None) -> list[dict[str, Any]]:
        """Undelivered commands (or, with `since`, every command after that ts). Marks them delivered."""
        with self._lock:
            if since:
                rows = self._db.execute("SELECT id, envelope FROM commands WHERE home_id=? AND ts>? ORDER BY ts",
                                        (home_id, since)).fetchall()
            else:
                rows = self._db.execute("SELECT id, envelope FROM commands WHERE home_id=? AND delivered=0 ORDER BY ts",
                                        (home_id,)).fetchall()
            if rows:
                self._db.execute(f"UPDATE commands SET delivered=1 WHERE id IN ({','.join('?' * len(rows))})",
                                 [r[0] for r in rows])
        return [json.loads(r[1]) for r in rows]

    # ------------------------------------------------------------------ actions
    def log_action(self, home_id: str, action: str, note: str | None, by: str | None = None) -> str:
        ts = _now()
        with self._lock:
            self._db.execute("INSERT INTO actions(home_id,action,note,by_who,ts) VALUES (?,?,?,?,?)",
                             (home_id, action, note, by, ts))
        return ts

    def actions(self, home_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT action, note, by_who AS by, ts FROM actions WHERE home_id=? ORDER BY seq", (home_id,))]

    # ------------------------------------------------------------------ node health
    def save_node_health(self, home_id: str, report: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO node_health(home_id,report,updated_at) VALUES (?,?,?)"
                " ON CONFLICT(home_id) DO UPDATE SET report=excluded.report, updated_at=excluded.updated_at",
                (home_id, json.dumps(report, default=str), _now()),
            )

    def node_health(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {r["home_id"]: json.loads(r["report"]) for r in self._db.execute("SELECT * FROM node_health")}

    # ------------------------------------------------------------------ kv (eval results etc.)
    def kv_get(self, key: str) -> Any:
        with self._lock:
            r = self._db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def kv_set(self, key: str, value: Any) -> None:
        with self._lock:
            self._db.execute("INSERT INTO kv(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             (key, json.dumps(value, default=str)))

    def kv_delete(self, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM kv WHERE key=?", (key,))
