"""
db.py — Truman's local persistence layer (SQLite, WAL mode).

Single file at `truman.db` alongside the code. Holds:
  - sessions          : one row per Cmd+Shift+T session
  - turns             : every user + assistant utterance (+ FTS5 search)
  - session_summaries : filled by nightly reflection (currently unused)
  - reminders         : survives process death; fired by a separate scheduler
  - tool_calls        : history of every tool Truman ran

All helpers are thread-safe — each call opens its own connection. WAL lets
multiple threads read concurrently while one writes.

Call db.init() once at boot (main.py).
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

# db.py lives at truman/storage/db.py; truman.db lives at truman/truman.db.
# Two dirname() hops: truman/storage/db.py → truman/storage/ → truman/.
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "truman.db",
)

_init_lock = threading.Lock()
_initialized = False


# ── Connection ────────────────────────────────────────────────────────────────
@contextmanager
def _conn():
    """Per-call connection. Cheap with SQLite. Auto-commits on clean exit."""
    c = sqlite3.connect(DB_PATH, timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at   TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    role       TEXT    NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT    NOT NULL,
    ts         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_ts      ON turns(ts);

CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    content,
    content='turns',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
    INSERT INTO turns_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON turns BEGIN
    INSERT INTO turns_fts(turns_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS turns_au AFTER UPDATE ON turns BEGIN
    INSERT INTO turns_fts(turns_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO turns_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TABLE IF NOT EXISTS session_summaries (
    session_id INTEGER PRIMARY KEY REFERENCES sessions(id),
    summary    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    note             TEXT    NOT NULL,
    fire_at          TEXT    NOT NULL,
    fired            INTEGER NOT NULL DEFAULT 0,
    fired_at         TEXT,
    created_at       TEXT    NOT NULL,
    apple_reminder_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(fire_at) WHERE fired = 0;

CREATE TABLE IF NOT EXISTS tool_calls (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    name       TEXT    NOT NULL,
    args       TEXT    NOT NULL,
    result     TEXT,
    ts         TEXT    NOT NULL,
    date       TEXT    GENERATED ALWAYS AS (substr(ts, 1, 10)) VIRTUAL
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_ts      ON tool_calls(ts);

-- ── Events log (ring buffer, persisted, last 1000) ────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT    NOT NULL,
    date       TEXT    GENERATED ALWAYS AS (substr(ts, 1, 10)) VIRTUAL,
    kind       TEXT    NOT NULL,  -- 'chat' | 'tool' | 'loop' | 'memory' | 'sensor' | 'error' | 'risk'
    source     TEXT    NOT NULL DEFAULT 'text',  -- 'text' | 'voice' | 'mic' | 'screen' | 'feed' | 'loop'
    session_id TEXT,
    pool       TEXT,
    model      TEXT,
    elapsed_ms INTEGER,
    status     TEXT    NOT NULL DEFAULT 'ok',    -- 'ok' | 'slow' | 'error' | 'warn'
    detail     TEXT,   -- JSON blob or short string
    error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts     ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_date   ON events(date);
CREATE INDEX IF NOT EXISTS idx_events_kind   ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);

-- ── Episodic memory (daily events from mic/screen/feeds) ──────────────────────
CREATE TABLE IF NOT EXISTS memory_episodic (
    id         TEXT    PRIMARY KEY,
    ts         TEXT    NOT NULL,
    date       TEXT    GENERATED ALWAYS AS (substr(ts, 1, 10)) VIRTUAL,
    source     TEXT    NOT NULL,  -- 'mic' | 'screen' | 'feed' | 'session' | 'reflection'
    session_id TEXT,
    summary    TEXT    NOT NULL,
    raw        TEXT,   -- original chunk before summarization
    tags       TEXT    -- JSON array of topic tags
);
CREATE INDEX IF NOT EXISTS idx_episodic_date    ON memory_episodic(date);
CREATE INDEX IF NOT EXISTS idx_episodic_source  ON memory_episodic(source);
CREATE INDEX IF NOT EXISTS idx_episodic_session ON memory_episodic(session_id);

-- ── Concept graph mirror (Cognee snapshots) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_concepts (
    id         TEXT    PRIMARY KEY,
    ts         TEXT    NOT NULL,
    date       TEXT    GENERATED ALWAYS AS (substr(ts, 1, 10)) VIRTUAL,
    source     TEXT    NOT NULL DEFAULT 'cognee',
    name       TEXT    NOT NULL,
    kind       TEXT    NOT NULL DEFAULT 'concept',  -- 'concept' | 'entity' | 'relation'
    domain     TEXT,   -- 'forex' | 'seacap' | 'general' | etc
    body       TEXT,   -- JSON: description, related, edges
    updated_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_concepts_name   ON memory_concepts(name);
CREATE INDEX IF NOT EXISTS idx_concepts_domain ON memory_concepts(domain);

-- ── Skill library ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_skills (
    id          TEXT    PRIMARY KEY,
    ts          TEXT    NOT NULL,
    date        TEXT    GENERATED ALWAYS AS (substr(ts, 1, 10)) VIRTUAL,
    source      TEXT    NOT NULL DEFAULT 'mcp',
    name        TEXT    NOT NULL UNIQUE,
    description TEXT    NOT NULL,
    schema      TEXT,   -- JSON: args + return type
    last_used   TEXT,
    use_count   INTEGER NOT NULL DEFAULT 0,
    success_rate REAL   NOT NULL DEFAULT 1.0
);

-- ── Goals ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_goals (
    id          TEXT    PRIMARY KEY,
    ts          TEXT    NOT NULL,
    date        TEXT    GENERATED ALWAYS AS (substr(ts, 1, 10)) VIRTUAL,
    source      TEXT    NOT NULL DEFAULT 'om',  -- 'om' | 'truman'
    session_id  TEXT,
    title       TEXT    NOT NULL,
    description TEXT,
    status      TEXT    NOT NULL DEFAULT 'active',  -- 'active' | 'done' | 'paused' | 'dropped'
    progress    TEXT,   -- JSON: milestones, last_check, notes
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_goals_status ON memory_goals(status);

-- ── Reflections (nightly) ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_reflections (
    id         TEXT    PRIMARY KEY,
    ts         TEXT    NOT NULL,
    date       TEXT    GENERATED ALWAYS AS (substr(ts, 1, 10)) VIRTUAL,
    source     TEXT    NOT NULL DEFAULT 'nightly',
    scope      TEXT    NOT NULL DEFAULT 'day',   -- 'day' | 'week'
    summary    TEXT    NOT NULL,
    insights   TEXT,   -- JSON array
    promoted   INTEGER NOT NULL DEFAULT 0        -- 1 = facts sent to Mem0
);
CREATE INDEX IF NOT EXISTS idx_reflections_date ON memory_reflections(date);

-- ── Feeds (market/news/calendar ingested items) ───────────────────────────────
CREATE TABLE IF NOT EXISTS memory_feeds (
    id         TEXT    PRIMARY KEY,
    ts         TEXT    NOT NULL,
    date       TEXT    GENERATED ALWAYS AS (substr(ts, 1, 10)) VIRTUAL,
    source     TEXT    NOT NULL,  -- 'oanda' | 'rss' | 'calendar' | 'email'
    title      TEXT,
    body       TEXT    NOT NULL,
    url        TEXT,
    relevance  REAL    NOT NULL DEFAULT 0.5,
    surfaced   INTEGER NOT NULL DEFAULT 0  -- 1 = Truman told Om about this
);
CREATE INDEX IF NOT EXISTS idx_feeds_date   ON memory_feeds(date);
CREATE INDEX IF NOT EXISTS idx_feeds_source ON memory_feeds(source);

-- ── Repo index ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_repos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,   -- repo short name
    url         TEXT    NOT NULL,
    file_count  INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT    NOT NULL,
    last_pulled TEXT,
    status      TEXT    NOT NULL DEFAULT 'done',   -- cloning | ingesting | done | failed
    progress    INTEGER NOT NULL DEFAULT 0,        -- files processed so far
    total       INTEGER NOT NULL DEFAULT 0,        -- expected total files
    stage       TEXT,                              -- short label: 'cloning', 'reading files', 'building graph'
    error       TEXT
);

-- ── Unified timeline view (all memory types in one query) ─────────────────────
CREATE VIEW IF NOT EXISTS memory_all AS
    SELECT id, ts, date, source, 'turn'       AS kind, content  AS body FROM turns
    UNION ALL
    SELECT id, ts, date, source, 'episodic'   AS kind, summary  AS body FROM memory_episodic
    UNION ALL
    SELECT id, ts, date, source, 'concept'    AS kind, body              FROM memory_concepts
    UNION ALL
    SELECT id, ts, date, source, 'reflection' AS kind, summary  AS body FROM memory_reflections
    UNION ALL
    SELECT id, ts, date, source, 'feed'       AS kind, body              FROM memory_feeds
;
"""


def init():
    """Create the DB file + schema if missing. Safe to call multiple times."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        with _conn() as c:
            c.execute("PRAGMA journal_mode = WAL")
            c.execute("PRAGMA synchronous = NORMAL")
            c.executescript(_SCHEMA)
            # ── Migrations (safe to re-run, all catch duplicate-column errors) ──
            for ddl in [
                "ALTER TABLE reminders ADD COLUMN apple_reminder_id TEXT",
                # turns: add source + date for unified timeline
                "ALTER TABLE turns ADD COLUMN source TEXT NOT NULL DEFAULT 'text'",
                # memory_repos: progress tracking columns
                "ALTER TABLE memory_repos ADD COLUMN status   TEXT    NOT NULL DEFAULT 'done'",
                "ALTER TABLE memory_repos ADD COLUMN progress INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE memory_repos ADD COLUMN total    INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE memory_repos ADD COLUMN stage    TEXT",
                "ALTER TABLE memory_repos ADD COLUMN error    TEXT",
            ]:
                try:
                    c.execute(ddl)
                except Exception:
                    pass

            # backfill turns.date virtual col doesn't need migration (GENERATED)
            # trim events table to last 1000 rows on boot
            try:
                c.execute("""
                    DELETE FROM events WHERE id NOT IN (
                        SELECT id FROM events ORDER BY id DESC LIMIT 1000
                    )
                """)
            except Exception:
                pass
            # Self-heal: any session left with ended_at=NULL from a hard kill /
            # SIGKILL gets closed now using its last turn's ts (or started_at).
            # Without this, reflect.py skips them forever (it only processes
            # ended sessions) and summaries never get written.
            fixed = c.execute("""
                UPDATE sessions
                SET ended_at = COALESCE(
                    (SELECT MAX(ts) FROM turns WHERE turns.session_id = sessions.id),
                    started_at
                )
                WHERE ended_at IS NULL
            """).rowcount
            if fixed:
                print(f"[DB] Self-heal: closed {fixed} dangling session(s)")
        _initialized = True
        print(f"[DB] Ready at {DB_PATH}")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Sessions ──────────────────────────────────────────────────────────────────
def start_session() -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO sessions(started_at) VALUES (?)",
            (_now(),),
        )
        return cur.lastrowid


def end_session(session_id: int) -> None:
    if session_id is None:
        return
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
            (_now(), session_id),
        )


# ── Turns ─────────────────────────────────────────────────────────────────────
def log_turn(session_id: Optional[int], role: str, content: str) -> None:
    if not session_id or not content:
        return
    with _conn() as c:
        c.execute(
            "INSERT INTO turns(session_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (session_id, role, content, _now()),
        )


def recent_turns(n: int = 10) -> list[dict]:
    """Last N turns across all sessions, chronological."""
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content, ts FROM turns ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def session_turns(session_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content, ts FROM turns WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def search_turns(query: str, limit: int = 20) -> list[dict]:
    """FTS5 search across all turns. Returns most-recent-first."""
    if not query.strip():
        return []
    with _conn() as c:
        rows = c.execute(
            """
            SELECT t.role, t.content, t.ts, t.session_id
            FROM turns_fts f
            JOIN turns t ON t.id = f.rowid
            WHERE turns_fts MATCH ?
            ORDER BY t.id DESC
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Session summaries (for nightly reflection) ────────────────────────────────
def set_session_summary(session_id: int, summary: str) -> None:
    with _conn() as c:
        c.execute(
            """
            INSERT INTO session_summaries(session_id, summary, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET summary = excluded.summary
            """,
            (session_id, summary, _now()),
        )


def last_session_summary() -> Optional[dict]:
    """Most recent completed session's summary — for context injection on start."""
    with _conn() as c:
        row = c.execute(
            """
            SELECT s.id AS session_id, s.started_at, s.ended_at, ss.summary
            FROM sessions s
            JOIN session_summaries ss ON ss.session_id = s.id
            ORDER BY s.id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


# ── Reminders ─────────────────────────────────────────────────────────────────
def add_reminder(note: str, fire_at: datetime, apple_reminder_id: Optional[str] = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO reminders(note, fire_at, created_at, apple_reminder_id) VALUES (?, ?, ?, ?)",
            (note, fire_at.isoformat(timespec="seconds"), _now(), apple_reminder_id),
        )
        return cur.lastrowid


def get_due_reminders(now: Optional[datetime] = None) -> list[dict]:
    now = (now or datetime.now()).isoformat(timespec="seconds")
    with _conn() as c:
        rows = c.execute(
            "SELECT id, note, fire_at, apple_reminder_id FROM reminders WHERE fired = 0 AND fire_at <= ? ORDER BY fire_at",
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_reminder_fired(reminder_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE reminders SET fired = 1, fired_at = ? WHERE id = ?",
            (_now(), reminder_id),
        )


def claim_reminder(reminder_id: int) -> bool:
    """Atomically mark a reminder fired. Returns True only if we claimed it.

    Use this when multiple processes could fire reminders (e.g. Truman's
    in-process loop AND the standalone scheduler) to avoid double-fires.
    """
    with _conn() as c:
        cur = c.execute(
            "UPDATE reminders SET fired = 1, fired_at = ? WHERE id = ? AND fired = 0",
            (_now(), reminder_id),
        )
        return cur.rowcount > 0


def list_reminders(include_fired: bool = False) -> list[dict]:
    with _conn() as c:
        if include_fired:
            rows = c.execute(
                "SELECT id, note, fire_at, fired, fired_at FROM reminders ORDER BY fire_at DESC"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, note, fire_at FROM reminders WHERE fired = 0 ORDER BY fire_at"
            ).fetchall()
    return [dict(r) for r in rows]


# ── Tool calls ────────────────────────────────────────────────────────────────
def log_event_db(
    kind: str,
    source: str = "text",
    session_id: str = None,
    pool: str = None,
    model: str = None,
    elapsed_ms: int = None,
    status: str = "ok",
    detail: str = None,
    error: str = None,
) -> None:
    """Persist one event to the events table. Non-blocking — fails silently."""
    try:
        with _conn() as c:
            c.execute(
                """INSERT INTO events(ts, kind, source, session_id, pool, model,
                   elapsed_ms, status, detail, error)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (_now(), kind, source, session_id, pool, model,
                 elapsed_ms, status, detail, error),
            )
    except Exception:
        pass


def get_events(limit: int = 100, kind: str = None, date: str = None) -> list[dict]:
    with _conn() as c:
        clauses, params = [], []
        if kind:
            clauses.append("kind = ?"); params.append(kind)
        if date:
            clauses.append("date = ?"); params.append(date)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = c.execute(
            f"SELECT * FROM events {where} ORDER BY id DESC LIMIT ?",
            params + [limit],
        ).fetchall()
    return [dict(r) for r in rows]


def add_episodic(
    source: str,
    summary: str,
    session_id: str = None,
    raw: str = None,
    tags: list = None,
) -> None:
    import uuid, json as _j
    with _conn() as c:
        c.execute(
            """INSERT INTO memory_episodic(id, ts, source, session_id, summary, raw, tags)
               VALUES (?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), _now(), source, session_id,
             summary, raw, _j.dumps(tags or [])),
        )


def get_episodic(date: str = None, source: str = None, limit: int = 50) -> list[dict]:
    with _conn() as c:
        clauses, params = [], []
        if date:
            clauses.append("date = ?"); params.append(date)
        if source:
            clauses.append("source = ?"); params.append(source)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = c.execute(
            f"SELECT * FROM memory_episodic {where} ORDER BY ts DESC LIMIT ?",
            params + [limit],
        ).fetchall()
    return [dict(r) for r in rows]


# ── Repo index ───────────────────────────────────────────────────────────────
def repo_start(name: str, url: str, total: int = 0, stage: str = "cloning") -> None:
    """Create or reset a repo row at the START of an ingest run."""
    now = _now()
    with _conn() as c:
        c.execute("""
            INSERT INTO memory_repos(name, url, file_count, ingested_at, last_pulled,
                                       status, progress, total, stage, error)
            VALUES (?, ?, 0, ?, ?, 'cloning', 0, ?, ?, NULL)
            ON CONFLICT(name) DO UPDATE SET
                url        = excluded.url,
                last_pulled= excluded.ingested_at,
                status     = 'cloning',
                progress   = 0,
                total      = excluded.total,
                stage      = excluded.stage,
                error      = NULL
        """, (name, url, now, now, total, stage))

def repo_progress(name: str, progress: int, total: int = None, stage: str = None) -> None:
    """Update mid-run progress. Cheap, called frequently."""
    sets = ["progress = ?"]
    args = [progress]
    if total is not None:
        sets.append("total = ?"); args.append(total)
    if stage is not None:
        sets.append("stage = ?"); args.append(stage)
    args.append(name)
    with _conn() as c:
        c.execute(f"UPDATE memory_repos SET {', '.join(sets)} WHERE name = ?", args)

def repo_done(name: str, file_count: int) -> None:
    with _conn() as c:
        c.execute("""
            UPDATE memory_repos
               SET status = 'done', progress = ?, total = ?, file_count = ?, stage = NULL, error = NULL
             WHERE name = ?
        """, (file_count, file_count, file_count, name))

def repo_failed(name: str, error: str) -> None:
    with _conn() as c:
        c.execute("UPDATE memory_repos SET status = 'failed', error = ?, stage = NULL WHERE name = ?",
                   (error[:500], name))

# Back-compat: code that calls upsert_repo still works
def upsert_repo(name: str, url: str, file_count: int) -> None:
    repo_done(name, file_count)
    with _conn() as c:
        c.execute("UPDATE memory_repos SET url = ?, last_pulled = ? WHERE name = ?",
                   (url, _now(), name))

def list_repos() -> list[dict]:
    with _conn() as c:
        rows = c.execute("""
            SELECT name, url, file_count, ingested_at, last_pulled,
                   status, progress, total, stage, error
              FROM memory_repos
          ORDER BY ingested_at DESC
        """).fetchall()
    return [dict(r) for r in rows]

def active_repo_tasks() -> list[dict]:
    """Return only repos that are currently cloning/ingesting OR finished in last 30s.
    The recently-finished window lets the dashboard show a 'done' confirmation briefly."""
    with _conn() as c:
        rows = c.execute("""
            SELECT name, url, file_count, status, progress, total, stage, error,
                   last_pulled
              FROM memory_repos
             WHERE status IN ('cloning', 'ingesting', 'failed')
                OR (status = 'done' AND datetime(last_pulled) > datetime('now', 'localtime', '-30 seconds'))
          ORDER BY last_pulled DESC
        """).fetchall()
    return [dict(r) for r in rows]


# ── Kill switch (file-based — Truman cannot disable this) ────────────────────
_KILL_FLAG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", ".killswitch",
)

def killswitch_active() -> bool:
    return os.path.exists(_KILL_FLAG)

def killswitch_set(off: bool) -> None:
    """off=True → create flag (Truman goes dark). off=False → remove flag."""
    if off:
        open(_KILL_FLAG, "w").close()
    elif os.path.exists(_KILL_FLAG):
        os.remove(_KILL_FLAG)


# ── Goals ────────────────────────────────────────────────────────────────────
def add_goal(title: str, description: str = None, priority: int = 3) -> str:
    """Insert a new active goal. Returns the new goal's UUID."""
    import uuid
    gid = str(uuid.uuid4())
    now = _now()
    with _conn() as c:
        c.execute(
            """INSERT INTO memory_goals(id, ts, source, title, description, status, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (gid, now, "om", title, description or "", "active", now),
        )
    return gid


def get_active_goals(limit: int = 3) -> list[dict]:
    """Return top N active goals ordered by ts desc (most recently added first)."""
    with _conn() as c:
        rows = c.execute(
            """SELECT id, ts, title, description, progress, updated_at
               FROM memory_goals WHERE status = 'active'
               ORDER BY ts DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_goals() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, ts, title, description, status, updated_at FROM memory_goals ORDER BY ts DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def complete_goal(query: str) -> bool:
    """Mark goal matching query title as done. Returns True if found."""
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "UPDATE memory_goals SET status='done', updated_at=? WHERE status='active' AND title LIKE ?",
            (now, f"%{query}%"),
        )
        return cur.rowcount > 0


def drop_goal(query: str) -> bool:
    """Mark goal matching query title as dropped. Returns True if found."""
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "UPDATE memory_goals SET status='dropped', updated_at=? WHERE status='active' AND title LIKE ?",
            (now, f"%{query}%"),
        )
        return cur.rowcount > 0


def log_tool_call(
    session_id: Optional[int],
    name: str,
    args: Any,
    result: Any = None,
) -> None:
    try:
        args_json = json.dumps(args, default=str)
    except Exception:
        args_json = str(args)
    result_str = None if result is None else str(result)[:2000]
    with _conn() as c:
        c.execute(
            "INSERT INTO tool_calls(session_id, name, args, result, ts) VALUES (?, ?, ?, ?, ?)",
            (session_id, name, args_json, result_str, _now()),
        )
