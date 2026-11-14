"""Local session store: the actual numbers behind each ritual, kept at home so a session can be audited or re-derived.

One SQLite file (`[hub] store_path`, default logs/hub_sessions.sqlite) with three tables:

    sessions  one row per ritual: id, home_id, episode_id (the id the cloud knows), started/ended (UTC), reason, outcome,
              sim, summary JSON (the engagement summary and the "not measured" reasons)
    samples   every raw.* message the hub received while that ritual ran, exactly as validated: envelope ts,
              source, type, quality, sim, payload JSON (tap times, pulse samples, distances, face box positions,
              light, dial turns, button edges, pan). Numbers only: the bus never carries an image or audio.
    obs       every obs.* the hub emitted in that ritual (envelope id, type, ts, quality, payload JSON): the link from
              the stored raw data to what was uplinked. The same envelope id is the cloud's event id.

Nothing in this file is ever uplinked (root rule 5; the uplink only takes obs.*). Retention: sessions older than
`store_retention_days` are deleted when a ritual starts, then the oldest ones until the file is under
`store_max_mb`. Writes are buffered and flushed about once a second and at the end of the ritual; a write error
disables the store for that ritual and never touches the ritual itself (fail soft).

Export / audit / replay: `tools/session.py`.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from kaiku_contracts import Envelope
from kaiku_contracts.jlog import get_logger

log = get_logger("hub")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, home_id TEXT NOT NULL DEFAULT '', episode_id TEXT,
    started TEXT NOT NULL, ended TEXT,
    reason TEXT NOT NULL DEFAULT '', outcome TEXT, sim INTEGER NOT NULL DEFAULT 0, summary TEXT);
CREATE TABLE IF NOT EXISTS samples (n INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, ts TEXT NOT NULL,
    source TEXT NOT NULL, type TEXT NOT NULL, quality REAL, sim INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS obs (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, ts TEXT NOT NULL, type TEXT NOT NULL,
    quality REAL, sim INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS samples_session ON samples (session_id, n);
CREATE INDEX IF NOT EXISTS obs_session ON obs (session_id, ts);
"""
FLUSH_S = 1.0
FLUSH_ROWS = 500


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class SessionStore:
    def __init__(self, path: Path | str | None, *, retention_days: float = 30, max_mb: float = 200):
        self.path = None if path is None else Path(path)
        self.retention_days = retention_days
        self.max_mb = max_mb
        self.session_id: str | None = None
        self.db: sqlite3.Connection | None = None
        self._rows: list[tuple] = []
        self._obs: list[tuple] = []
        self._last_flush = 0.0
        self.error: str | None = None
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.db = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
                self.db.execute("PRAGMA journal_mode=WAL")
                self.db.executescript(SCHEMA)
            except (OSError, sqlite3.Error) as e:
                self._fail(e)

    @property
    def enabled(self) -> bool:
        return self.db is not None

    def _fail(self, e: Exception) -> None:
        self.error = f"{type(e).__name__}: {e}"[:200]
        log.error("session_store_failed", self.error)
        self.db, self.session_id, self._rows, self._obs = None, None, [], []

    # ------------------------------------------------------------ one ritual
    def begin(self, session_id: str, reason: str, *, home_id: str = "", sim: bool = False,
              now: datetime | None = None) -> None:
        if self.db is None:
            return
        self.flush()
        try:
            self.prune(now)
            self.db.execute("INSERT OR REPLACE INTO sessions (id, home_id, started, reason, sim) VALUES (?,?,?,?,?)",
                            (session_id, home_id, _iso(now or datetime.now(UTC)), reason, int(sim)))
            self.session_id = session_id
        except sqlite3.Error as e:
            self._fail(e)

    def add_raw(self, env: Envelope[Any]) -> None:
        """A raw.* envelope received during the open session. No-op outside a session."""
        if self.db is None or self.session_id is None or not env.type.startswith("raw."):
            return
        self._rows.append((self.session_id, _iso(env.ts), env.source, env.type, env.quality, int(env.sim),
                           env.payload.model_dump_json(exclude_none=True)))
        self._maybe_flush()

    def add_obs(self, env: Envelope[Any], session_id: str | None = None) -> None:
        """An obs.* the hub emitted during the open session (links the raw data to what was uplinked).
        `session_id` links a late observation (the end-of-ritual summary) to an already closed session."""
        session_id = session_id or self.session_id
        if self.db is None or session_id is None:
            return
        self._obs.append((str(env.id), session_id, _iso(env.ts), env.type, env.quality, int(env.sim),
                          env.payload.model_dump_json(exclude_none=True)))
        self._maybe_flush()

    def _maybe_flush(self) -> None:
        if len(self._rows) + len(self._obs) >= FLUSH_ROWS or time.monotonic() - self._last_flush >= FLUSH_S:
            self.flush()

    def flush(self) -> None:
        self._last_flush = time.monotonic()
        if self.db is None or not (self._rows or self._obs):
            return
        rows, obs, self._rows, self._obs = self._rows, self._obs, [], []
        try:
            self.db.execute("BEGIN")
            self.db.executemany("INSERT INTO samples (session_id, ts, source, type, quality, sim, payload) "
                                "VALUES (?,?,?,?,?,?,?)", rows)
            self.db.executemany("INSERT OR IGNORE INTO obs (id, session_id, ts, type, quality, sim, payload) "
                                "VALUES (?,?,?,?,?,?,?)", obs)
            self.db.execute("COMMIT")
        except sqlite3.Error as e:
            self._fail(e)

    def end(self, *, outcome: str, episode_id: str | None = None, sim: bool = False, summary: dict | None = None,
            now: datetime | None = None) -> None:
        if self.db is None or self.session_id is None:
            return
        self.flush()
        sid, self.session_id = self.session_id, None
        if self.db is None:
            return
        try:
            self.db.execute("UPDATE sessions SET ended = ?, outcome = ?, episode_id = ?, sim = MAX(sim, ?), summary = ? "
                            "WHERE id = ?", (_iso(now or datetime.now(UTC)), outcome, episode_id, int(sim),
                                             json.dumps(summary) if summary else None, sid))
        except sqlite3.Error as e:
            self._fail(e)

    # ------------------------------------------------------------ retention
    def _drop(self, ids: list[str]) -> None:
        assert self.db is not None
        for table, col in (("samples", "session_id"), ("obs", "session_id"), ("sessions", "id")):
            self.db.executemany(f"DELETE FROM {table} WHERE {col} = ?", [(i,) for i in ids])  # noqa: S608 — fixed names

    def size_mb(self) -> float:
        if self.db is None:
            return 0.0
        pages = self.db.execute("PRAGMA page_count").fetchone()[0] - self.db.execute("PRAGMA freelist_count").fetchone()[0]
        return pages * self.db.execute("PRAGMA page_size").fetchone()[0] / 1e6

    def prune(self, now: datetime | None = None) -> int:
        """Delete sessions past retention, then the oldest until under max_mb. Returns sessions deleted."""
        if self.db is None:
            return 0
        cutoff = _iso((now or datetime.now(UTC)) - timedelta(days=self.retention_days))
        old = [r[0] for r in self.db.execute("SELECT id FROM sessions WHERE started < ? AND id IS NOT ?",
                                             (cutoff, self.session_id))]
        self._drop(old)
        dropped = len(old)
        while self.size_mb() > self.max_mb:
            row = self.db.execute("SELECT id FROM sessions WHERE id IS NOT ? ORDER BY started LIMIT 1",
                                  (self.session_id,)).fetchone()
            if row is None:
                break
            self._drop([row[0]])
            dropped += 1
        if dropped:
            log.info("session_store_pruned", f"{dropped} sessions", size_mb=round(self.size_mb(), 1))
        return dropped

    def close(self) -> None:
        self.flush()
        if self.db is not None:
            self.db.close()
            self.db = None


# ---------------------------------------------------------------- read side (tools/session.py, tests)
def open_readonly(path: Path | str) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def list_sessions(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM samples WHERE session_id = s.id) AS samples, "
        "(SELECT COUNT(*) FROM obs WHERE session_id = s.id) AS obs FROM sessions s ORDER BY started").fetchall()
    return [{**dict(r), "sim": bool(r["sim"]), "summary": json.loads(r["summary"]) if r["summary"] else None}
            for r in rows]


def resolve_session(db: sqlite3.Connection, ref: str) -> str:
    """Session by id, episode id, unique prefix, or `last`."""
    if ref == "last":
        row = db.execute("SELECT id FROM sessions ORDER BY started DESC LIMIT 1").fetchone()
        if row is None:
            raise LookupError("the store has no sessions yet")
        return row[0]
    rows = db.execute("SELECT id FROM sessions WHERE id = ? OR episode_id = ? OR id LIKE ? OR episode_id LIKE ?",
                      (ref, ref, ref + "%", ref + "%")).fetchall()
    if len(rows) != 1:
        raise LookupError(f"{len(rows)} sessions match {ref!r}")
    return rows[0][0]


def read_session(db: sqlite3.Connection, session_id: str) -> tuple[dict, list[dict], list[dict]]:
    """(session row, raw samples in arrival order, emitted obs in time order); payloads decoded."""
    s = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if s is None:
        raise LookupError(f"no session {session_id!r}")
    session = {**dict(s), "sim": bool(s["sim"]), "summary": json.loads(s["summary"]) if s["summary"] else None}

    def rows(sql: str) -> list[dict]:
        return [{**dict(r), "sim": bool(r["sim"]), "payload": json.loads(r["payload"])}
                for r in db.execute(sql, (session_id,))]

    return (session, rows("SELECT ts, source, type, quality, sim, payload FROM samples WHERE session_id = ? ORDER BY n"),
            rows("SELECT id, ts, type, quality, sim, payload FROM obs WHERE session_id = ? ORDER BY ts, id"))
