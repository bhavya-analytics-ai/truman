# TRUMAN VERIFICATION LOG

## Status Legend
- VERIFIED = proven by command output / DB query / runtime test
- PARTIAL = exists but incomplete
- BROKEN = tested and failed
- UNPROVEN = not tested yet
- RISKY = can cause wrong behavior / data loss / security issue

---

## Phase 1 — Storage + Export Audit

### Evidence
- **Date:** 2026-05-16
- **Git commit:** 4f9800e (HEAD on main)
- **DB path (local):** `/Users/ompandya/Desktop/friday/truman/truman.db` (2.5MB, active)
- **DB path (root, dead):** `/Users/ompandya/Desktop/friday/truman.db` — 0 bytes, never used
- **DB path (Railway):** `/data/truman.db` (if `/data` dir exists, else falls back to above)
- **Commands run:** sqlite3 schema + row counts, grep on source files, line-by-line code reads

### Row Counts (as of audit)
| Table | Rows |
|---|---|
| sessions | 92 |
| turns | 1177 |
| events | 153 |
| tool_calls | 49 |
| eval_log | 67 |
| trace_events | 995 |
| attachments | 1 (test row only) |
| reminders | 31 |
| user_facts | 11 |

---

### Findings Table

| Area | Status | Evidence | Notes |
|---|---|---|---|
| User messages saved with timestamp | PARTIAL | `db.py:510`, `orb.py:280`, `save.py:31` | Saved — but TWICE per turn via /api/chat (see Bug 1) |
| Assistant messages saved with timestamp | PARTIAL | `db.py:510`, `orb.py:281`, `save.py:32` | Same double-save issue |
| Session IDs consistent | VERIFIED | `orb.py:230`, `db.py:529` | browser UUID → SQLite int FK is correct |
| Dashboard sidebar count accurate | RISKY | `db.py:584` COUNT(t.id) | Counts double-saved turns → 2x inflated |
| Full session display accurate | PARTIAL | `db.py:602` session_turns() | Returns correct turns but content may have duplicates |
| Tool calls logged | PARTIAL | `db.py:1038`, tool_calls: 49 rows | Only old legacy path — claude-shape path does NOT log tool_calls to DB |
| Events logged | PARTIAL | `db.py:720`, events: 153 rows | Last event May 8 — stale since cloud deploy. trace_events has 995 rows (LangGraph path only) |
| Attachments linked to sessions/turns | BROKEN | `db.py:419` schema | attachments table has NO session_id or turn_id column — zero linkage |
| Export returns full structured JSON | BROKEN | `dashboard.html:1169-1188` | Two bugs: (1) reads sessData.sessions but API returns {groups:[]} → 0 sessions; (2) checks Array.isArray(turns) but /api/history returns {turns:[]} → turns always [] |
| Import can restore structured JSON | BROKEN | `dashboard.html:1195-1212` | Import only writes to in-memory `_msgCache` — never to DB. Lost on refresh. |
| Timestamps are timezone-aware | RISKY | `db.py:485-486` | `datetime.now().isoformat()` = local machine time, no TZ offset. Railway time ≠ local time. |
| No silent save failures | RISKY | `orb.py:283`, `save.py:54` | Both catch Exception and only print — failures invisible. orb.py catches even DB exceptions silently. |

---

### Bugs Found

| Bug | Severity | Evidence | Suggested Fix |
|---|---|---|---|
| **BUG-1: Double save on /api/chat** | HIGH | `orb.py:280-281` saves turns directly; `chat()` also calls `enqueue_save()` → `save.py:31-32` saves again | Remove `log_turn` calls from `orb.py:278-284` — let `save.py` worker be sole writer. OR skip `enqueue_save` on non-streaming path. |
| **BUG-2: Export reads wrong key from /api/sessions** | HIGH | `dashboard.html:1169`: reads `sessData.sessions` but `/api/sessions` returns `{"groups":[{day, sessions:[]}]}` → `sessData.sessions === undefined` → `allSessions = []` → 0 sessions exported | Change JS to flatten groups: `const allSessions = (sessData.groups||[]).flatMap(g=>g.sessions)` |
| **BUG-3: Export reads turns as object not array** | HIGH | `dashboard.html:1183`: `Array.isArray(turns)` where `turns = await histRes.json()` = `{turns:[...]}` → always false → `turns: []` in export | Change to `turns: turns.turns || []` |
| **BUG-4: Import is in-memory only** | HIGH | `dashboard.html:1201`: `Object.assign(_msgCache, imported)` — no API call, no DB write | Import needs a real `/api/import` endpoint that writes to DB |
| **BUG-5: Attachments have no session/turn FK** | MEDIUM | `db.py:419` schema — no `session_id`, no `turn_id` column | Add `session_id TEXT` column to attachments. Wire at upload time (`orb.py:753-754`) |
| **BUG-6: Timestamps are local-naive** | MEDIUM | `db.py:486`: `datetime.now().isoformat()` — no UTC offset | Change `_now()` to `datetime.now(timezone.utc).isoformat(timespec="seconds")` |
| **BUG-7: Tool calls not logged on claude-shape path** | MEDIUM | `tool_calls` table has 49 rows, last entry Apr 30. `chat.py` calls `enqueue_save()` which does NOT call `db.log_tool_call()` | Add `db.log_tool_call()` per tool in `save.py:_persist_turn()` |
| **BUG-8: Silent save failure in orb.py** | MEDIUM | `orb.py:283`: bare `except Exception: pass` swallows all DB errors | Log to `print` at minimum; add to error ring buffer |

---

### Next Required Tests

| Test | Purpose | Safe? |
|---|---|---|
| Probe `/api/sessions` live response shape | Confirm Bug-2 (groups vs sessions key) | YES — read only |
| Probe `/api/history?session_id=<id>` live response | Confirm Bug-3 (turns wrapped vs array) | YES — read only |
| Count turns per session — check for exact 2x duplicates | Confirm Bug-1 (double save) | YES — read only |
| Run probe message through `chat()` directly, then query DB | Prove save.py worker writes to DB | WRITES to local DB only |
| Check events table on Railway vs local | Confirm if events are stale on Railway too | YES — read Railway logs |
| Check what chat_stream path does (does it also double-save?) | `/api/chat/stream` path analysis | YES — read only |

---

## Phase 1 Fix — Export V1

### Evidence
- **Date:** 2026-05-16
- **Git commit:** pending (dashboard.html only, not yet committed)
- **File changed:** `truman/voice/static/dashboard.html`
- **Lines changed:** 72 insertions, 10 deletions (1 file only)
- **Logic simulation:** Python simulation run against exact API response shapes — confirmed correct

### What was fixed
| Bug | Fix | Evidence |
|---|---|---|
| BUG-2: sessData.sessions undefined | `groups.flatMap(g => g.sessions)` — flattens grouped structure | Simulation: old code → 0 sessions; new code → 3 sessions from same payload |
| BUG-3: turns object not array | `histJson.turns` unwrap before map | Simulation: `Array.isArray({turns:[]})` → false; `Array.isArray([])` → true |

### What was added
- `parseAttachmentsFromContent(content)` — regex parses `[Image: NAME|attach:ID]` and `[File: NAME|attach:ID]` tokens, returns structured metadata array, original content unchanged
- Verified against real DB turn: `[Image: Screenshot 2026-05-09 at 12.46.15 PM.png|attach:92ffd5dadcbd4d36]` → correctly extracted id, filename, kind, download_url

### Output shape verified
```json
{
  "schema_version": "truman_chat_export_v1",
  "exported_at": "...",
  "source": "dashboard",
  "session_count": 1,
  "turn_count": 4,
  "sessions": [{ "id": "...", "label": "...", "started_at": "...", "turn_count": 4, "turns": [...] }]
}
```

### Export V1 status: PARTIAL
- Logic is correct (simulation verified)
- BUG-2 and BUG-3 are fixed in code
- Attachment parsing works
- **NOT live-tested against running app** — app not started per rules
- Double-save (BUG-1) means turn counts in export may be 2× actual conversations (not fixed — out of scope for Export v1)
- Import (BUG-4) not fixed — out of scope

### Findings Table update
| Area | Old Status | New Status | Notes |
|---|---|---|---|
| Export returns full structured JSON | BROKEN | PARTIAL | Logic fixed + simulated. Needs live test to VERIFIED. |
| Attachment metadata in export | BROKEN | PARTIAL | parseAttachmentsFromContent() added, tested against real DB token |
