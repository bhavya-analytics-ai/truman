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
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    note       TEXT    NOT NULL,
    fire_at    TEXT    NOT NULL,
    fired      INTEGER NOT NULL DEFAULT 0,
    fired_at   TEXT,
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(fire_at) WHERE fired = 0;

CREATE TABLE IF NOT EXISTS tool_calls (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    name       TEXT    NOT NULL,
    args       TEXT    NOT NULL,
    result     TEXT,
    ts         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
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
def add_reminder(note: str, fire_at: datetime) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO reminders(note, fire_at, created_at) VALUES (?, ?, ?)",
            (note, fire_at.isoformat(timespec="seconds"), _now()),
        )
        return cur.lastrowid


def get_due_reminders(now: Optional[datetime] = None) -> list[dict]:
    now = (now or datetime.now()).isoformat(timespec="seconds")
    with _conn() as c:
        rows = c.execute(
            "SELECT id, note, fire_at FROM reminders WHERE fired = 0 AND fire_at <= ? ORDER BY fire_at",
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
