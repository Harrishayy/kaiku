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
-- usage ledger (plan 06 §2): one row per model call or deterministic answer. NEVER any content.
CREATE TABLE IF NOT EXISTS model_calls (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    home_id TEXT,
    model TEXT NOT NULL,
    task TEXT NOT NULL,
    route TEXT,
    latency_ms REAL,
    ok INTEGER NOT NULL,
    fallback INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS model_calls_ts ON model_calls(ts);
-- graph memory (plan 06 §3): built by code from memories, episodes and bandit outcomes. Person-facing only.
CREATE TABLE IF NOT EXISTS kg_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    home_id TEXT NOT NULL,
    type TEXT NOT NULL,
    label TEXT NOT NULL,
    norm TEXT NOT NULL,
    origin TEXT NOT NULL,            -- memory:<id> | episode | bandit | self
    status TEXT NOT NULL DEFAULT 'active',   -- active | merged | expired (consolidation diffs)
    merged_into INTEGER,
    updated TEXT NOT NULL,
    UNIQUE(home_id, type, norm)
);
CREATE TABLE IF NOT EXISTS kg_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    home_id TEXT NOT NULL,
    src INTEGER NOT NULL,
    dst INTEGER NOT NULL,
    rel TEXT NOT NULL,
    weight REAL NOT NULL,
    evidence TEXT NOT NULL DEFAULT '[]',   -- ids: mem:<id>, episode ids, event ids (bandit)
    updated TEXT NOT NULL,
    UNIQUE(home_id, src, dst, rel)
);
-- Gemini Embedding 2 vectors (float32) per memory / graph node; keyed by text hash so edits re-embed.
CREATE TABLE IF NOT EXISTS embeddings (
    home_id TEXT NOT NULL,
    ref TEXT NOT NULL,               -- mem:<id> | kg:<id>
    model TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY(home_id, ref, model)
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

    def memory_homes(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._db.execute("SELECT DISTINCT home_id FROM memories ORDER BY home_id")]

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

    # ------------------------------------------------------------------ usage ledger (no content)
    def model_call_insert(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO model_calls(ts,home_id,model,task,route,latency_ms,ok,fallback) VALUES (?,?,?,?,?,?,?,?)",
                (row.get("ts") or _now(), row.get("home_id"), row["model"], row["task"], row.get("route"),
                 row.get("latency_ms"), int(bool(row.get("ok"))), int(bool(row.get("fallback")))))

    def model_calls(self, since: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM model_calls WHERE ts>=? ORDER BY seq", (since,))]

    def model_calls_count(self, home_id: str, model: str, since: str) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM model_calls WHERE home_id=? AND model=? AND ts>=?"
                                        " AND task NOT LIKE '%.route'",
                                        (home_id, model, since)).fetchone()[0])

    # ------------------------------------------------------------------ graph memory
    def kg_upsert_node(self, home_id: str, type_: str, label: str, norm: str, origin: str, ts: str) -> int:
        """Insert or refresh (label/origin) a node; its status (merged/expired) is kept."""
        with self._lock:
            self._db.execute(
                "INSERT INTO kg_nodes(home_id,type,label,norm,origin,updated) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(home_id,type,norm) DO UPDATE SET label=excluded.label, origin=excluded.origin,"
                " updated=excluded.updated", (home_id, type_, label, norm, origin, ts))
            return int(self._db.execute("SELECT id FROM kg_nodes WHERE home_id=? AND type=? AND norm=?",
                                        (home_id, type_, norm)).fetchone()[0])

    def kg_upsert_edge(self, home_id: str, src: int, dst: int, rel: str, weight: float, evidence: list[str],
                       ts: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO kg_edges(home_id,src,dst,rel,weight,evidence,updated) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(home_id,src,dst,rel) DO UPDATE SET weight=excluded.weight,"
                " evidence=excluded.evidence, updated=excluded.updated",
                (home_id, src, dst, rel, weight, json.dumps(evidence), ts))

    def kg_prune(self, home_id: str, keep_nodes: set[int], keep_edges: set[tuple[int, int, str]]) -> None:
        """Drop code-derived nodes/edges that no longer have a source (deleted memory, gone outcome)."""
        with self._lock:
            for e in self._db.execute("SELECT id, src, dst, rel FROM kg_edges WHERE home_id=?", (home_id,)).fetchall():
                if (e["src"], e["dst"], e["rel"]) not in keep_edges:
                    self._db.execute("DELETE FROM kg_edges WHERE id=?", (e["id"],))
            for n in self._db.execute("SELECT id FROM kg_nodes WHERE home_id=?", (home_id,)).fetchall():
                if n["id"] not in keep_nodes:
                    self._db.execute("DELETE FROM kg_nodes WHERE id=?", (n["id"],))
                    self._db.execute("DELETE FROM embeddings WHERE home_id=? AND ref=?", (home_id, f"kg:{n['id']}"))

    def kg_nodes(self, home_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM kg_nodes WHERE home_id=? ORDER BY id",
                                                      (home_id,))]

    def kg_edges(self, home_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM kg_edges WHERE home_id=? ORDER BY id", (home_id,)).fetchall()
        return [{**dict(r), "evidence": json.loads(r["evidence"])} for r in rows]

    def kg_set_status(self, home_id: str, node_id: int, status: str, merged_into: int | None = None) -> int:
        with self._lock:
            return self._db.execute("UPDATE kg_nodes SET status=?, merged_into=? WHERE home_id=? AND id=?",
                                    (status, merged_into, home_id, node_id)).rowcount

    # ------------------------------------------------------------------ embeddings
    def embedding_put(self, home_id: str, ref: str, model: str, text_hash: str, vector: bytes) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO embeddings(home_id,ref,model,text_hash,vector) VALUES (?,?,?,?,?)",
                             (home_id, ref, model, text_hash, vector))

    def embeddings(self, home_id: str, model: str) -> dict[str, tuple[str, bytes]]:
        """{ref: (text_hash, vector bytes)}"""
        with self._lock:
            rows = self._db.execute("SELECT ref, text_hash, vector FROM embeddings WHERE home_id=? AND model=?",
                                    (home_id, model)).fetchall()
        return {r["ref"]: (r["text_hash"], r["vector"]) for r in rows}

    def embedding_delete_missing(self, home_id: str, refs: set[str]) -> None:
        with self._lock:
            for r in self._db.execute("SELECT DISTINCT ref FROM embeddings WHERE home_id=?", (home_id,)).fetchall():
                if r["ref"] not in refs:
                    self._db.execute("DELETE FROM embeddings WHERE home_id=? AND ref=?", (home_id, r["ref"]))
