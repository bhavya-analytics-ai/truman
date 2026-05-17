# TRUMAN OPERATOR COOKBOOK

This cookbook only includes capabilities that have been verified or investigated by tests.
Unverified capabilities are listed as UNPROVEN until tested.

## Capability Status Legend
- VERIFIED = proven by test output
- PARTIAL = works but has known gaps or bugs
- FAILED = tested and broken
- UNPROVEN = not yet tested

---

## Storage / Export Capabilities (Phase 1 Audit)

| Capability | Status | How to Use | Expected Proof |
|---|---|---|---|
| Chat turns saved to SQLite | PARTIAL | POST /api/chat or GET /api/chat/stream | `SELECT COUNT(*) FROM turns` increases. WARNING: /api/chat double-saves (Bug-1) |
| Sessions created per browser tab | VERIFIED | Any chat via dashboard | `SELECT * FROM sessions ORDER BY id DESC LIMIT 5` shows new row with browser_id |
| Session turns retrievable | VERIFIED | GET /api/history?session_id=<browser_id> | Returns `{turns:[{role,content,ts}]}` |
| Session list for sidebar | VERIFIED | GET /api/sessions | Returns `{groups:[{day, sessions:[{browser_id, label, turn_count, started_at}]}]}` |
| Tool calls logged | PARTIAL | Tools fired via legacy/LangGraph path only | `SELECT * FROM tool_calls ORDER BY id DESC LIMIT 5` — claude-shape path does NOT write here |
| Eval scores logged | PARTIAL | Runs async in save.py background after claude-shape turns | `SELECT score, COUNT(*) FROM eval_log GROUP BY score` |
| Brain trace events logged | PARTIAL | Only on LangGraph path (ENABLE_CLAUDE_SHAPE=0) | `SELECT node, status FROM trace_events ORDER BY id DESC LIMIT 20` |
| Reminders saved | VERIFIED | "remind me to X at Y" via any chat path | `SELECT * FROM reminders ORDER BY id DESC LIMIT 5` |
| Attachments stored | PARTIAL | POST /api/upload — data stored as BLOB | No session/turn linkage (Bug-5). `SELECT id, filename, mime_type FROM attachments` |
| Export chat JSON v1 | PARTIAL | Click "export" button in dashboard header | Downloads `truman-export-YYYY-MM-DD.json` with schema_version, session_count, turn_count, turns, attachment metadata. Bug-2 + Bug-3 fixed. Needs live test to reach VERIFIED. |
| Import chats from JSON | FAILED | Click file input next to export button | In-memory only, lost on refresh (Bug-4) — not fixed in v1 |
| Full export (turns + tools + events) | UNPROVEN | No endpoint exists yet | Deferred to Export v2 — needs /api/export backend endpoint |

---

## Database

### Location
| Environment | Path |
|---|---|
| Local | `/Users/ompandya/Desktop/friday/truman/truman.db` |
| Railway | `/data/truman.db` |
| Dead (ignore) | `/Users/ompandya/Desktop/friday/truman.db` (0 bytes) |

### Key tables
| Table | Purpose | PK | Session link |
|---|---|---|---|
| sessions | One row per browser tab | id (int autoincrement) | browser_id (UUID string from frontend) |
| turns | Every user + assistant message | id (int) | session_id → sessions.id (FK) |
| tool_calls | Tool invocations (legacy/LangGraph only) | id (int) | session_id → sessions.id |
| events | Chat + eval_weak events | id (int) | session_id (string, not FK) |
| eval_log | Quality scores per turn | id (int) | session_id (string, not FK) |
| trace_events | Per-node brain events (LangGraph only) | id (int) | session_id (string) |
| attachments | Uploaded files/images as BLOB | id (string UUID) | NONE — no session/turn link |
| reminders | Scheduled reminders | id (int) | none |
| user_facts | Persistent identity facts | id (int) | none |

### Timestamp format
All timestamps via `_now()` (`db.py:485`) = `datetime.now().isoformat(timespec="seconds")` = **local machine time, no UTC offset**. Not timezone-aware. Railway time will differ from local time.

---

## Known Bugs (as of Phase 1)

| ID | Bug | File | Line | Severity |
|---|---|---|---|---|
| BUG-1 | Double save on /api/chat | `orb.py` + `save.py` | 280, 31 | HIGH |
| BUG-2 | Export reads wrong key from /api/sessions | `dashboard.html` | 1169 | HIGH |
| BUG-3 | Export reads turns as object not array | `dashboard.html` | 1183 | HIGH |
| BUG-4 | Import is in-memory only, lost on refresh | `dashboard.html` | 1201 | HIGH |
| BUG-5 | Attachments have no session/turn FK | `db.py` schema | 419 | MEDIUM |
| BUG-6 | Timestamps are local-naive, no UTC offset | `db.py` | 486 | MEDIUM |
| BUG-7 | Tool calls not logged on claude-shape path | `save.py` | 34 | MEDIUM |
| BUG-8 | Silent save failure in orb.py | `orb.py` | 283 | MEDIUM |
