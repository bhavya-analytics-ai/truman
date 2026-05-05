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

# On Railway (volume mounted at /data), persist there so DB survives redeploys.
# Locally, fall back to truman/truman.db alongside the code.
if os.path.isdir("/data"):
    DB_PATH = "/data/truman.db"
else:
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

-- ── Eval log (Phase 5 — quality scoring per turn) ────────────────────────────
CREATE TABLE IF NOT EXISTS eval_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    date        TEXT    GENERATED ALWAYS AS (substr(ts, 1, 10)) VIRTUAL,
    turn_id     TEXT,
    session_id  TEXT,
    model       TEXT,
    pool        TEXT,
    score       TEXT    NOT NULL,  -- 'good' | 'weak' | 'bad' | 'skip'
    issues      TEXT,              -- JSON array of issue codes
    reason      TEXT,
    action      TEXT,              -- 'accept' | 'retry'
    retry_fired INTEGER NOT NULL DEFAULT 0,
    score_after TEXT               -- score after retry (if fired)
);
CREATE INDEX IF NOT EXISTS idx_eval_log_date  ON eval_log(date);
CREATE INDEX IF NOT EXISTS idx_eval_log_score ON eval_log(score);
CREATE INDEX IF NOT EXISTS idx_eval_log_model ON eval_log(model);

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

-- ── User preferences (changeable via natural language) ──────────────────────
-- KEY SPLIT (enforced by memory hierarchy):
--   CONFIG keys  → live here: morning_brief_hour, morning_brief_hour_int,
--                             quiet_start, quiet_end, vapid_public_key, vapid_private_key
--   BEHAVIOR keys→ go to persona_rules table, NOT here
-- logs intentionally excluded from decision context (see brain/memory.py)
CREATE TABLE IF NOT EXISTS user_prefs (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- ── Sleep log (tracks reported sleep, 7-day rolling average) ─────────────────
CREATE TABLE IF NOT EXISTS sleep_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT NOT NULL,          -- YYYY-MM-DD (the day sleep started)
    sleep_start  TEXT NOT NULL,          -- HH:MM 24h
    sleep_end    TEXT NOT NULL,          -- HH:MM 24h
    duration_min INTEGER NOT NULL,       -- computed minutes
    raw_input    TEXT,                   -- what Om actually said
    created_at   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sleep_log_date ON sleep_log(date);

-- ── Pending actions (risk gate — 5 min TTL) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS pending_actions (
    id         TEXT    PRIMARY KEY,
    tool_name  TEXT    NOT NULL,
    args       TEXT    NOT NULL,
    user_input TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    expires_at TEXT    NOT NULL
);

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

-- ── Web push subscriptions (Phase 14 — iPhone PWA notifications) ────────────
CREATE TABLE IF NOT EXISTS push_subs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint   TEXT NOT NULL UNIQUE,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    created_at REAL NOT NULL
);

-- ── Persona rules (Phase 13 — self-correcting persona) ──────────────────────
CREATE TABLE IF NOT EXISTS persona_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    rule       TEXT    NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    source     TEXT    NOT NULL DEFAULT 'manual',  -- 'manual' | 'auto'
    created_at REAL    NOT NULL
);

-- ── User facts (cross-chat persistent memory about Om) ──────────────────────
CREATE TABLE IF NOT EXISTS user_facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fact        TEXT    NOT NULL,
    importance  INTEGER NOT NULL DEFAULT 3,   -- 1 (low) to 5 (critical)
    source      TEXT    NOT NULL DEFAULT 'manual',  -- manual | auto
    created_at  REAL    NOT NULL,
    last_used   REAL
);

-- ── Activity trace log ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trace_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,           -- unix timestamp (float)
    session_id  TEXT    NOT NULL,
    turn_id     TEXT    NOT NULL,           -- groups events per chat turn
    node        TEXT    NOT NULL,           -- e.g. detect_tool, call_llm
    status      TEXT    NOT NULL,           -- start | end | error
    duration_ms INTEGER,                   -- only on 'end'
    summary     TEXT,                      -- one-line human-readable summary
    args_json   TEXT,                      -- JSON: input args / params
    result_json TEXT                       -- JSON: output preview
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
                # sessions: add browser_id (UUID from frontend), label, first_message
                "ALTER TABLE sessions ADD COLUMN browser_id    TEXT",
                "ALTER TABLE sessions ADD COLUMN label         TEXT",
                "ALTER TABLE sessions ADD COLUMN first_message TEXT",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_browser ON sessions(browser_id)",
                # Phase 14: push_subs table
                """CREATE TABLE IF NOT EXISTS push_subs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    endpoint TEXT NOT NULL UNIQUE,
                    p256dh TEXT NOT NULL,
                    auth TEXT NOT NULL,
                    created_at REAL NOT NULL
                )""",
                # Phase 13: persona_rules table (add_rule creates it, but ensure it exists on old DBs)
                """CREATE TABLE IF NOT EXISTS persona_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at REAL NOT NULL
                )""",
                # Phase 15: attachments — persistent file/image storage
                """CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                    data BLOB NOT NULL,
                    created_at REAL NOT NULL DEFAULT (unixepoch())
                )""",
                # Phase 15: boss_messages — WhatsApp + Gmail intake with approval flow
                """CREATE TABLE IF NOT EXISTS boss_messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    source      TEXT NOT NULL,
                    sender      TEXT NOT NULL,
                    text        TEXT NOT NULL,
                    draft_reply TEXT,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    extra_json  TEXT DEFAULT '{}',
                    created_at  REAL NOT NULL
                )""",
                # Phase 15B: VIP contacts — track approval counts for auto-reply
                """CREATE TABLE IF NOT EXISTS vip_contacts (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier       TEXT NOT NULL UNIQUE,
                    approval_count   INTEGER NOT NULL DEFAULT 0,
                    auto_reply_on    INTEGER NOT NULL DEFAULT 0,
                    updated_at       REAL NOT NULL DEFAULT (unixepoch())
                )""",
                # Phase 15D: reply_contacts whitelist — who gets Telegram approval flow
                """CREATE TABLE IF NOT EXISTS reply_contacts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL DEFAULT (unixepoch())
                )""",
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


def get_or_create_session(browser_id: str, label: str = None) -> int:
    """Return SQLite integer id for a browser session UUID, creating if needed."""
    with _conn() as c:
        row = c.execute("SELECT id FROM sessions WHERE browser_id = ?", (browser_id,)).fetchone()
        if row:
            return row["id"]
        cur = c.execute(
            "INSERT INTO sessions(started_at, browser_id, label) VALUES (?, ?, ?)",
            (_now(), browser_id, label),
        )
        return cur.lastrowid


def update_session_label(browser_id: str, label: str) -> None:
    with _conn() as c:
        c.execute("UPDATE sessions SET label = ? WHERE browser_id = ?", (label, browser_id))


def delete_session(browser_id: str) -> None:
    with _conn() as c:
        row = c.execute("SELECT id FROM sessions WHERE browser_id = ?", (browser_id,)).fetchone()
        if row:
            c.execute("DELETE FROM turns WHERE session_id = ?", (row["id"],))
            c.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))


def get_sessions_by_day() -> list[dict]:
    """All sessions grouped by day, newest first. Each has id, browser_id, label,
    started_at, first_message, turn_count."""
    with _conn() as c:
        rows = c.execute("""
            SELECT s.browser_id, s.label, s.started_at, s.first_message,
                   COUNT(t.id) AS turn_count,
                   MAX(t.ts)   AS last_active
            FROM sessions s
            LEFT JOIN turns t ON t.session_id = s.id
            WHERE s.browser_id IS NOT NULL
            GROUP BY s.id
            ORDER BY s.started_at DESC
            LIMIT 200
        """).fetchall()
    return [dict(r) for r in rows]


def set_session_first_message(browser_id: str, msg: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET first_message = ? WHERE browser_id = ? AND first_message IS NULL",
            (msg[:120], browser_id),
        )


def session_turns(session_id) -> list[dict]:
    """Accepts integer id or browser UUID string."""
    with _conn() as c:
        if isinstance(session_id, str):
            row = c.execute("SELECT id FROM sessions WHERE browser_id = ?", (session_id,)).fetchone()
            if not row:
                return []
            session_id = row["id"]
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


# ── Pending actions (risk gate) ───────────────────────────────────────────────
def save_pending_action(tool_name: str, args: Any, user_input: str) -> str:
    """Store a risky action pending confirmation. Returns the action ID."""
    import uuid
    from datetime import timedelta
    pid = str(uuid.uuid4())
    now = datetime.now()
    expires = (now + timedelta(minutes=5)).isoformat(timespec="seconds")
    with _conn() as c:
        c.execute(
            "INSERT INTO pending_actions(id, tool_name, args, user_input, created_at, expires_at) VALUES (?,?,?,?,?,?)",
            (pid, tool_name, json.dumps(args, default=str), user_input,
             now.isoformat(timespec="seconds"), expires),
        )
    return pid


def get_pending_action() -> Optional[dict]:
    """Most recent non-expired pending action, or None."""
    now = _now()
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM pending_actions WHERE expires_at > ? ORDER BY created_at DESC LIMIT 1",
            (now,),
        ).fetchone()
    return dict(row) if row else None


def clear_pending_action(pid: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM pending_actions WHERE id = ?", (pid,))


def expire_pending_actions() -> None:
    """Delete all expired pending actions. Call on every turn."""
    now = _now()
    with _conn() as c:
        c.execute("DELETE FROM pending_actions WHERE expires_at <= ?", (now,))


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


# ── Trace event helpers ───────────────────────────────────────────────────────

def log_trace(session_id: str, turn_id: str, node: str, status: str,
              summary: str = "", args: Any = None, result: Any = None,
              duration_ms: int = None) -> None:
    """Save a brain node trace event to SQLite."""
    import time as _time
    try:
        args_json   = json.dumps(args,   default=str) if args   is not None else None
        result_json = json.dumps(result, default=str) if result is not None else None
    except Exception:
        args_json   = str(args)   if args   is not None else None
        result_json = str(result) if result is not None else None
    try:
        with _conn() as c:
            c.execute(
                """INSERT INTO trace_events
                   (ts, session_id, turn_id, node, status, duration_ms, summary, args_json, result_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_time.time(), session_id, turn_id, node, status,
                 duration_ms, summary[:300] if summary else None,
                 args_json, result_json),
            )
            # keep last 5000 trace rows
            c.execute("""DELETE FROM trace_events WHERE id NOT IN
                         (SELECT id FROM trace_events ORDER BY id DESC LIMIT 5000)""")
    except Exception:
        pass


# ── User facts helpers ────────────────────────────────────────────────────────

def save_fact(fact: str, importance: int = 3, source: str = "manual") -> int:
    """Save a user fact. Returns new row id."""
    import time as _t
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO user_facts (fact, importance, source, created_at) VALUES (?, ?, ?, ?)",
            (fact.strip(), max(1, min(5, importance)), source, _t.time()),
        )
        return cur.lastrowid


def search_facts(query: str, limit: int = 5) -> list[dict]:
    """
    Keyword search over user_facts — local Mem0 replacement.
    Splits query into words, scores each fact by how many words it matches,
    returns top `limit` results sorted by score then importance.
    """
    words = [w.lower() for w in query.split() if len(w) > 3]
    if not words:
        return get_top_facts(limit)
    with _conn() as c:
        rows = c.execute(
            "SELECT id, fact, importance, source FROM user_facts ORDER BY importance DESC, created_at DESC LIMIT 200"
        ).fetchall()
    scored = []
    for r in rows:
        text = r["fact"].lower()
        score = sum(1 for w in words if w in text)
        if score > 0:
            scored.append((score, dict(r)))
    scored.sort(key=lambda x: (-x[0], -x[1]["importance"]))
    return [item for _, item in scored[:limit]]


def get_top_facts(limit: int = 10) -> list[dict]:
    """Top facts by importance + recency for system prompt injection."""
    with _conn() as c:
        rows = c.execute(
            """SELECT id, fact, importance, source, created_at
               FROM user_facts
               ORDER BY importance DESC, created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_facts() -> list[dict]:
    """All facts, newest first — for the memory panel."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, fact, importance, source, created_at FROM user_facts ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_fact(fact_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM user_facts WHERE id = ?", (fact_id,))


# ── User prefs ────────────────────────────────────────────────────────────────

def get_pref(key: str, default: str = None) -> Optional[str]:
    with _conn() as c:
        row = c.execute("SELECT value FROM user_prefs WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_pref(key: str, value: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO user_prefs(key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, _now()),
        )


def get_all_prefs() -> dict:
    with _conn() as c:
        rows = c.execute("SELECT key, value FROM user_prefs").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ── Sleep log ────────────────────────────────────────────────────────────────

def log_sleep(date: str, sleep_start: str, sleep_end: str,
              duration_min: int, raw_input: str = None) -> None:
    """Insert or replace sleep entry for a given date."""
    with _conn() as c:
        c.execute(
            """INSERT INTO sleep_log(date, sleep_start, sleep_end, duration_min, raw_input, created_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(date) DO UPDATE SET
                   sleep_start=excluded.sleep_start,
                   sleep_end=excluded.sleep_end,
                   duration_min=excluded.duration_min,
                   raw_input=excluded.raw_input,
                   created_at=excluded.created_at""",
            (date, sleep_start, sleep_end, duration_min, raw_input, _now()),
        )


def get_sleep_stats(days: int = 7) -> list[dict]:
    """Return last N sleep entries ordered by date desc."""
    with _conn() as c:
        rows = c.execute(
            """SELECT date, sleep_start, sleep_end, duration_min, raw_input
               FROM sleep_log ORDER BY date DESC LIMIT ?""",
            (days,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Web push subscriptions (Phase 14) ────────────────────────────────────────

def save_push_sub(endpoint: str, p256dh: str, auth: str) -> None:
    """Upsert a push subscription (endpoint is unique key)."""
    import time as _t
    with _conn() as c:
        c.execute(
            """INSERT INTO push_subs (endpoint, p256dh, auth, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh, auth=excluded.auth""",
            (endpoint, p256dh, auth, _t.time()),
        )


def get_all_push_subs() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT endpoint, p256dh, auth FROM push_subs").fetchall()
    return [dict(r) for r in rows]


def delete_push_sub(endpoint: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))


# ── Persona rules (Phase 13) ──────────────────────────────────────────────────

def add_rule(rule: str, source: str = "manual") -> int:
    """Save a new persona rule. Returns new row id."""
    import time as _t
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO persona_rules (rule, active, source, created_at) VALUES (?, 1, ?, ?)",
            (rule.strip(), source, _t.time()),
        )
        return cur.lastrowid


def get_active_rules() -> list[dict]:
    """Active rules only — injected into every SYSTEM prompt."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, rule, source, created_at FROM persona_rules WHERE active = 1 ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_rules() -> list[dict]:
    """All rules (active + inactive) for the dashboard panel."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, rule, active, source, created_at FROM persona_rules ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def toggle_rule(rule_id: int, active: int) -> None:
    """Toggle a rule on/off (active=1 or 0)."""
    with _conn() as c:
        c.execute("UPDATE persona_rules SET active = ? WHERE id = ?", (active, rule_id))


def delete_rule(rule_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM persona_rules WHERE id = ?", (rule_id,))


def get_trace_history(session_id: str = None, limit: int = 200) -> list[dict]:
    """Fetch recent trace events, optionally filtered by session."""
    try:
        with _conn() as c:
            if session_id:
                rows = c.execute(
                    """SELECT id, ts, session_id, turn_id, node, status,
                              duration_ms, summary, args_json, result_json
                       FROM trace_events WHERE session_id = ?
                       ORDER BY id DESC LIMIT ?""",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    """SELECT id, ts, session_id, turn_id, node, status,
                              duration_ms, summary, args_json, result_json
                       FROM trace_events ORDER BY id DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        cols = ["id","ts","session_id","turn_id","node","status",
                "duration_ms","summary","args_json","result_json"]
        return [dict(zip(cols, r)) for r in reversed(rows)]
    except Exception:
        return []


# ── Attachments (Phase 15 — persistent file/image storage) ───────────────────

def save_attachment(attach_id: str, filename: str, mime_type: str, data: bytes) -> None:
    """Store raw file bytes. Called from /api/upload."""
    import time as _time
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO attachments (id, filename, mime_type, data, created_at) VALUES (?,?,?,?,?)",
            (attach_id, filename, mime_type, data, _time.time())
        )

def get_attachment(attach_id: str) -> dict | None:
    """Return {id, filename, mime_type, data} or None."""
    with _conn() as c:
        row = c.execute(
            "SELECT id, filename, mime_type, data FROM attachments WHERE id = ?",
            (attach_id,)
        ).fetchone()
    if not row:
        return None
    return {"id": row[0], "filename": row[1], "mime_type": row[2], "data": row[3]}


# ── Boss messages (Phase 15 — WhatsApp + Gmail intake) ───────────────────────

def save_boss_message(source: str, sender: str, text: str, extra: dict = None) -> int:
    """Save incoming WhatsApp/Gmail message. Returns row id."""
    import time as _time
    extra_json = json.dumps(extra or {})
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO boss_messages (source, sender, text, extra_json, status, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (source, sender, text, extra_json, _time.time())
        )
        return cur.lastrowid


def set_boss_draft(msg_id: int, draft: str) -> None:
    with _conn() as c:
        c.execute("UPDATE boss_messages SET draft_reply = ? WHERE id = ?", (draft, msg_id))


def get_boss_message(msg_id: int) -> Optional[dict]:
    with _conn() as c:
        row = c.execute(
            "SELECT id, source, sender, text, draft_reply, status, extra_json FROM boss_messages WHERE id = ?",
            (msg_id,)
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0], "source": row[1], "sender": row[2], "text": row[3],
        "draft_reply": row[4], "status": row[5],
        "extra": json.loads(row[6] or "{}"),
    }


def set_boss_status(msg_id: int, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE boss_messages SET status = ? WHERE id = ?", (status, msg_id))


def get_approved_boss_replies(limit: int = 5) -> list:
    """Return draft_reply strings for approved messages — used as tone examples."""
    with _conn() as c:
        rows = c.execute(
            "SELECT draft_reply FROM boss_messages WHERE status = 'approved' AND draft_reply IS NOT NULL ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [r[0] for r in rows]


def get_approved_boss_replies_for_sender(sender: str, limit: int = 50) -> list:
    """Per-contact style learning: return Om's approved replies to a specific sender."""
    with _conn() as c:
        rows = c.execute(
            "SELECT draft_reply FROM boss_messages WHERE status = 'approved' "
            "AND draft_reply IS NOT NULL AND sender = ? ORDER BY id DESC LIMIT ?",
            (sender, limit)
        ).fetchall()
    return [r[0] for r in rows]


def get_queued_boss_messages() -> list:
    """Return messages queued during quiet hours, oldest first."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, source, sender, text, draft_reply, extra_json FROM boss_messages "
            "WHERE status = 'queued' ORDER BY id ASC"
        ).fetchall()
    return [
        {"id": r[0], "source": r[1], "sender": r[2], "text": r[3],
         "draft_reply": r[4], "extra": __import__("json").loads(r[5] or "{}")}
        for r in rows
    ]


# ── VIP contacts (Phase 15B — iMessage auto-reply) ───────────────────────────

def get_vip_approval_count(identifier: str) -> int:
    """Return number of times Om approved a reply to this contact."""
    with _conn() as c:
        row = c.execute(
            "SELECT approval_count FROM vip_contacts WHERE identifier = ?",
            (identifier,)
        ).fetchone()
    return row[0] if row else 0


def increment_vip_approval_count(identifier: str) -> int:
    """Increment approval count for contact. Returns new count."""
    import time as _time
    with _conn() as c:
        c.execute(
            """INSERT INTO vip_contacts (identifier, approval_count, updated_at)
               VALUES (?, 1, ?)
               ON CONFLICT(identifier) DO UPDATE SET
                 approval_count = approval_count + 1,
                 updated_at = excluded.updated_at""",
            (identifier, _time.time())
        )
        row = c.execute(
            "SELECT approval_count FROM vip_contacts WHERE identifier = ?",
            (identifier,)
        ).fetchone()
    return row[0] if row else 1


def list_vip_contacts() -> list:
    """Return all VIP contact rows."""
    with _conn() as c:
        rows = c.execute(
            "SELECT identifier, approval_count, auto_reply_on, updated_at FROM vip_contacts ORDER BY approval_count DESC"
        ).fetchall()
    return [
        {"identifier": r[0], "approval_count": r[1], "auto_reply_on": bool(r[2]), "updated_at": r[3]}
        for r in rows
    ]


# ── Reply contacts whitelist ───────────────────────────────────────────────────

def add_reply_contact(name: str) -> bool:
    """Add a contact to the reply whitelist. Returns True if added, False if already exists."""
    try:
        with _conn() as c:
            c.execute("INSERT INTO reply_contacts (name) VALUES (?)", (name.strip().lower(),))
        return True
    except Exception:
        return False


def remove_reply_contact(name: str) -> bool:
    """Remove a contact from the reply whitelist. Returns True if removed."""
    with _conn() as c:
        cur = c.execute("DELETE FROM reply_contacts WHERE name = ?", (name.strip().lower(),))
    return cur.rowcount > 0


def list_reply_contacts() -> list:
    """Return all whitelisted contact names."""
    with _conn() as c:
        rows = c.execute("SELECT id, name, created_at FROM reply_contacts ORDER BY name").fetchall()
    return [{"id": r[0], "name": r[1], "created_at": r[2]} for r in rows]


def is_reply_contact(sender: str, extra: dict = None) -> bool:
    """
    Returns True if sender matches any whitelist entry (or whitelist is empty = allow all).
    Matches against name, phone number, or email — partial/substring match.
    """
    contacts = list_reply_contacts()
    if not contacts:
        return True   # empty whitelist = everyone gets through
    extra = extra or {}
    name  = (sender or "").lower()
    phone = (extra.get("phone") or "").replace("+", "").lower()
    email = (extra.get("email") or "").lower()
    for c in contacts:
        pattern = c["name"]
        if pattern in name or pattern in phone or pattern in email:
            return True
    return False


# ── Eval log (Phase 5 — quality scoring) ─────────────────────────────────────

def log_eval(
    turn_id:     str,
    session_id:  str,
    model:       str,
    pool:        str,
    score:       str,
    issues:      list,
    reason:      str  = "",
    action:      str  = "accept",
    retry_fired: int  = 0,
    score_after: str  = None,
) -> None:
    """Insert one row per turn into eval_log. Fire-and-forget from a thread."""
    try:
        with _conn() as c:
            c.execute(
                """INSERT INTO eval_log
                   (ts, turn_id, session_id, model, pool, score, issues, reason,
                    action, retry_fired, score_after)
                   VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    turn_id, session_id, model, pool, score,
                    json.dumps(issues), reason, action, retry_fired, score_after,
                ),
            )
    except Exception:
        pass  # eval logging never crashes the system


def get_eval_summary(days: int = 7, limit: int = 10) -> list[dict]:
    """
    Top recurring issues per model/pool in the last N days.
    Used for future dashboard + tuning.
    """
    try:
        with _conn() as c:
            rows = c.execute(
                """SELECT model, pool, score, issues, COUNT(*) as n
                   FROM eval_log
                   WHERE date >= date('now', ?)
                   GROUP BY model, pool, score, issues
                   ORDER BY n DESC
                   LIMIT ?""",
                (f"-{days} days", limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []
