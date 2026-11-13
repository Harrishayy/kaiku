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
-- companion mind (plan 03 §6): what the person chose to tell Kaiku. Never read by clinician routes.
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    home_id TEXT NOT NULL,
    category TEXT NOT NULL,
    text TEXT NOT NULL,
    norm TEXT NOT NULL,              -- dedupe key (casefolded, whitespace/punctuation-trimmed)
    created TEXT NOT NULL,
    last_used TEXT,
    UNIQUE(home_id, norm)
);
CREATE TABLE IF NOT EXISTS episodes (  -- one row per session; no transcript, no audio
    id TEXT PRIMARY KEY,
    home_id TEXT NOT NULL,
    surface TEXT NOT NULL,
    intent TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT,
    tools TEXT NOT NULL DEFAULT '[]',
    outcome TEXT
);
CREATE INDEX IF NOT EXISTS episodes_home ON episodes(home_id, start);
CREATE TABLE IF NOT EXISTS threads (   -- at most one open per home; continues on any surface
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    home_id TEXT NOT NULL,
    skill TEXT NOT NULL,
    topic TEXT NOT NULL,
    created TEXT NOT NULL,
    expires TEXT NOT NULL,
    closed TEXT
);
"""

FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    text, content='memories', content_rowid='id', tokenize='porter unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
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
        try:
            self._db.executescript(FTS)
            self.fts = True
        except sqlite3.OperationalError:  # SQLite built without FTS5: recall falls back to LIKE
            self.fts = False
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
            for table in ("homes", "explanations", "commands", "actions", "node_health", "memories", "episodes",
                          "threads"):
                self._db.execute(f"DELETE FROM {table} WHERE home_id NOT IN (SELECT DISTINCT home_id FROM events)")
            self._db.execute("DELETE FROM explanations")  # cheap to regenerate
            self._db.execute("DELETE FROM kv WHERE key LIKE 'phq9_due:%'")
            self._db.execute("DELETE FROM kv WHERE key LIKE 'remember_off:%' AND substr(key, 14) NOT IN"
                             " (SELECT DISTINCT home_id FROM events)")
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

    # ------------------------------------------------------------------ memories (Kaiku's notebook)
    def memory_insert(self, home_id: str, category: str, text: str, norm: str, created: str) -> tuple[int, bool]:
        """Returns (id, created_new). Same normalised text for the same home -> the existing row (last_used bumped)."""
        with self._lock:
            r = self._db.execute("SELECT id FROM memories WHERE home_id=? AND norm=?", (home_id, norm)).fetchone()
            if r:
                self._db.execute("UPDATE memories SET last_used=? WHERE id=?", (created, r[0]))
                return int(r[0]), False
            cur = self._db.execute("INSERT INTO memories(home_id,category,text,norm,created) VALUES (?,?,?,?,?)",
                                   (home_id, category, text, norm, created))
            return int(cur.lastrowid or 0), True

    def memories(self, home_id: str) -> list[dict[str, Any]]:
        """Newest first."""
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT id, category, text, created, last_used FROM memories WHERE home_id=?"
                " ORDER BY created DESC, id DESC", (home_id,))]

    def memory_search(self, home_id: str, terms: list[str], limit: int) -> list[dict[str, Any]]:
        """Match any term (FTS5 bm25 with porter stemming: walk ~ walking), best first, then most recent."""
        terms = [t for t in terms if t]
        if not terms:
            return []
        with self._lock:
            if self.fts:
                q = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
                rows = self._db.execute(
                    "SELECT m.id, m.category, m.text, m.created, m.last_used FROM memories_fts f"
                    " JOIN memories m ON m.id=f.rowid WHERE memories_fts MATCH ? AND m.home_id=?"
                    " ORDER BY bm25(memories_fts), m.created DESC LIMIT ?", (q, home_id, limit)).fetchall()
            else:
                like = " OR ".join("lower(text) LIKE ?" for _ in terms)
                rows = self._db.execute(
                    f"SELECT id, category, text, created, last_used FROM memories WHERE home_id=? AND ({like})"
                    " ORDER BY created DESC LIMIT ?", (home_id, *[f"%{t.lower()}%" for t in terms], limit)).fetchall()
        return [dict(r) for r in rows]

    def memory_touch(self, ids: list[int], ts: str) -> None:
        if ids:
            with self._lock:
                self._db.execute(f"UPDATE memories SET last_used=? WHERE id IN ({','.join('?' * len(ids))})",
                                 (ts, *ids))

    def memory_delete(self, home_id: str, memory_id: int | None = None) -> int:
        """Delete one memory (by id) or all of a home's memories."""
        with self._lock:
            if memory_id is None:
                return self._db.execute("DELETE FROM memories WHERE home_id=?", (home_id,)).rowcount
            return self._db.execute("DELETE FROM memories WHERE home_id=? AND id=?", (home_id, memory_id)).rowcount

    def memory_delete_last(self, home_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._db.execute("SELECT id, category, text FROM memories WHERE home_id=?"
                                 " ORDER BY created DESC, id DESC LIMIT 1", (home_id,)).fetchone()
            if r:
                self._db.execute("DELETE FROM memories WHERE id=?", (r["id"],))
        return dict(r) if r else None

    def memory_expire(self, home_id: str, category: str, before: str) -> int:
        with self._lock:
            return self._db.execute("DELETE FROM memories WHERE home_id=? AND category=? AND created<?",
                                    (home_id, category, before)).rowcount

    # ------------------------------------------------------------------ episodes (one per session, no transcript)
    def episode_upsert(self, ep: dict[str, Any]) -> None:
        """Insert, or update end/outcome/tools of an existing session (start/surface/intent are kept)."""
        with self._lock:
            self._db.execute(
                "INSERT INTO episodes(id,home_id,surface,intent,start,end,tools,outcome) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET end=COALESCE(excluded.end, episodes.end),"
                " outcome=COALESCE(excluded.outcome, episodes.outcome), tools=excluded.tools",
                (ep["id"], ep["home_id"], ep["surface"], ep["intent"], ep["start"], ep.get("end"),
                 json.dumps(ep.get("tools", [])), ep.get("outcome")))

    def episode(self, episode_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
        return {**dict(r), "tools": json.loads(r["tools"])} if r else None

    def episodes(self, home_id: str, since: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM episodes WHERE home_id=? AND start>=? ORDER BY start",
                                    (home_id, since or "")).fetchall()
        return [{**dict(r), "tools": json.loads(r["tools"])} for r in rows]

    # ------------------------------------------------------------------ open thread
    def thread_open(self, home_id: str, skill: str, topic: str, created: str, expires: str) -> int:
        """Opening a thread closes any other open one (one thread at a time)."""
        with self._lock:
            self._db.execute("UPDATE threads SET closed=? WHERE home_id=? AND closed IS NULL", (created, home_id))
            cur = self._db.execute("INSERT INTO threads(home_id,skill,topic,created,expires) VALUES (?,?,?,?,?)",
                                   (home_id, skill, topic, created, expires))
            return int(cur.lastrowid or 0)

    def thread_current(self, home_id: str, now: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM threads WHERE home_id=? AND closed IS NULL AND expires>?"
                                 " ORDER BY created DESC LIMIT 1", (home_id, now)).fetchone()
        return dict(r) if r else None

    def thread_close(self, home_id: str, ts: str, skill: str | None = None) -> int:
        with self._lock:
            q, args = "UPDATE threads SET closed=? WHERE home_id=? AND closed IS NULL", [ts, home_id]
            if skill:
                q += " AND skill=?"
                args.append(skill)
            return self._db.execute(q, args).rowcount
