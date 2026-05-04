# TRUMAN — Build Log
### Every decision, every file, every level. Logged as we go.

---

## CORE FUNCTION (north star — never change without Om's approval)

> **"Watch incoming messages → triage → draft reply → send when Om approves."**

Everything in the codebase is either CORE (directly serves this) or SUPPORT (makes it better).
If a feature does neither, it gets cut.

### CORE — must always work, highest priority
| Component | File | Role |
|---|---|---|
| Brain loop | `truman/brain/loop.py` | Processes every message end-to-end |
| Agent | `truman/text/agent.py` | Tool detection, LLM routing, tool execution |
| Flask API | `truman/voice/orb.py` | `/api/chat`, `/api/boss_message`, `/api/upload` |
| DB turns | `truman/storage/db.py` | Saves every message + reply |
| Telegram poller | `truman/delivery/telegram.py` | Primary inbound channel from Om |
| Boss handler | `truman/integrations/boss_handler.py` | WA/Gmail/iMessage triage → Telegram approval |

### SUPPORT — enriches the core loop, all fail-soft
| Component | File | Role |
|---|---|---|
| Memory | `truman/brain/nodes.py::load_memory` | Enriches replies with context |
| Goals | `truman/brain/nodes.py::load_goals` | Surfaces active goals as context |
| Persona rules | `truman/storage/db.py::persona_rules` | Behavior constraints on replies |
| Concept graph | `truman/brain/nodes.py::concept_lookup` | Cognee graph — enriches replies |
| Morning brief | `truman/voice/email_digest.py` | Scheduled output (SECONDARY output) |
| Proactive push | `truman/scheduling/proactive.py` | Nudges + brief delivery |
| Web push | `truman/delivery/web_push.py` | Delivery mechanism for notifications |
| Nightly reflect | `truman/storage/reflect.py` | 2am maintenance |
| Sleep tracking | `truman/storage/db.py::sleep_log` | Context for morning brief |
| Gmail poller | `truman/integrations/gmail_poller.py` | Secondary inbound (gated) |
| iMessage | `truman/integrations/imessage_poller.py` | Mac-only secondary inbound |
| Awareness layer | (planned) | NOT BUILT YET — cut until real inputs exist |

### Memory authority hierarchy (no exceptions)
```
facts        = truth          (wins all conflicts)
goals        = intent         (what Om is trying to do)
persona rules= behavior       (how Truman responds, not what)
activity logs= history only   (zero decision authority)
concept graph= inference only (can be wrong, never authoritative)
```

---

## DECISIONS & ARCHITECTURE

| Decision | Choice | Reason |
|---|---|---|
| Agent Framework | LangChain + LangGraph | Already in stack, LangSmith native, industry standard |
| Brain | GPT-4o-mini | Capable for all tasks, cheap on Om's OpenAI credits |
| Memory | System Prompt + Mem0 + Tools | Dynamic, self-updating — Truman learns and grows |
| TTS | OpenAI TTS | Free with existing API, ElevenLabs added later for celebrity voices |
| STT | Whisper-1 | Already in stack, 99 languages |
| Tracing | LangSmith | Native to LangChain, professor can verify every step |
| Voice Auth | Pyannote.audio | Speaker verification, Om's voice print |
| Browser | Playwright | Full automation, login, navigation |
| No Fine-tuning | — | Info changes too fast, overkill, expensive |
| No RAG | — | Static retrieval, Mem0 is smarter and dynamic |

---

## BUILD LEVELS

| Level | Name | Status |
|---|---|---|
| 1 | Truman Comes Alive — core voice loop, FastAPI, LangSmith | ✅ Done |
| 2 | Security & Awareness — voice auth, cough + clap detection, unknown voice protocol | ✅ Done |
| 3 | Core Tools — web search, weather, news, Gmail, Twilio | Pending |
| 4 | Dev Tools — write/read files, execute Python, GitHub, build + deploy to Netlify/Vercel | Pending |
| 5 | Forex Brain — OANDA scan, morning email, logic gap finder | Pending |
| 6 | Browser Automation — Playwright, login, Google accounts | Pending |
| 7 | Media & Productivity — PDF to audio, iCloud, reminders, Sheets | Pending |
| 8 | Always On — LaunchAgent, boots on startup, silent background | Pending |
| 9 | Mission 1 — Truman builds Sprint 6 (MAYA agent upgrade) | Pending |

---

## LOG

---

### 2026-04-28 — Phase 4 complete + Phase 5: Risk Gate

**Commits: `5b3ec20`, `2fb9212`, `380e8f4`**

#### Phase 4 — Model reconfig + Curiosity node (`5b3ec20`)

**Problem:** deepseek-v3.2 hanging 30-46s on NIM, glm-4.7/mistral-nemotron dead. Pool config stale. No timeout on _build_llm(). Curiosity node was never built.

**Model pool reconfig (`truman/core/config.py`):**
- Removed: deepseek-v3.2, glm-4.7, mistral-nemotron (all dead/dying on NIM)
- New stack — all alive, all free NVIDIA NIM:
  - general: nvidia/llama-3.3-nemotron-super-49b-v1 → moonshotai/kimi-k2-instruct → stepfun-ai/step-3.5-flash
  - coding: qwen/qwen3-coder-480b-a35b-instruct → moonshotai/kimi-k2-instruct → meta/llama-3.3-70b-instruct
  - reasoning: moonshotai/kimi-k2-thinking → qwen/qwen3-coder-480b-a35b-instruct
  - creative: moonshotai/kimi-k2-thinking → meta/llama-3.3-70b-instruct
  - design: moonshotai/kimi-k2-thinking → qwen/qwen3-coder-480b-a35b-instruct
  - docs: meta/llama-4-maverick-17b-128e-instruct → meta/llama-3.3-70b-instruct → moonshotai/kimi-k2-instruct
  - vision: meta/llama-4-maverick-17b-128e-instruct
  - fast: stepfun-ai/step-3.5-flash → nvidia/llama-3.3-nemotron-super-49b-v1
  - agentic: qwen/qwen3-coder-480b-a35b-instruct → moonshotai/kimi-k2-instruct → meta/llama-3.3-70b-instruct

**Timeout fix (`truman/core/model_router.py`):**
- `_build_llm()`: added `timeout=8, max_retries=0` — kills 30s+ hangs on every call
- Hardcoded fallback: `deepseek-v3.2` replaced with `nvidia/llama-3.3-nemotron-super-49b-v1`
- Pipeline REASONER: deepseek-v3.2 → kimi-k2-thinking
- Pipeline REVIEWER: glm-4.7 → meta/llama-3.3-70b-instruct
- MODEL_INFO, _ALIASES, short_label all updated to match new models

**Curiosity node (`truman/brain/nodes.py`, `loop.py`, `state.py`):**
- New node `curiosity` runs after `load_goals`, before `detect_pool`
- Searches Cognee concept graph using active goal titles as query
- Injects "CURIOSITY (concept graph on your goals):" block into system prompt
- `curiosity_context: str` field added to TrumanState
- `curiosity_context: ""` added to initial_state in loop.py
- ENABLE_CURIOSITY=1 kill switch (added to config.py defaults)
- Fails soft — graph continues without it if Cognee unavailable

**Verified:** plain chat → nemotron-49b, <3s, list_goals fires, 0 warnings. Brain: 11 nodes.

---

#### Phase 5 — Risk Gate (`2fb9212`, `380e8f4`)

**New file: `truman/core/risk.py`**
- 3 risk tiers:
  - safe: web_search, get_weather, recall, list_goals, list_models, list_reminders, search_history, recent_conversations, concept_search, list_mac_dir, search_mac_files, read_mac_file
  - caution: set_reminder, add_goal, complete_goal, drop_goal, concept_ingest, remember
  - risky: write_mac_file, set_model, pipeline_mode
- `get_tier(tool_name) → str` helper

**DB changes (`truman/storage/db.py`):**
- `pending_actions` table added to schema (id, tool_name, args JSON, user_input, created_at, expires_at)
- 4 helpers: `save_pending_action`, `get_pending_action`, `clear_pending_action`, `expire_pending_actions` (5 min TTL)

**Brain node `risk_gate` (`truman/brain/nodes.py`):**
- Wired between detect_tool and route_skill
- Safe/caution tools: pass through instantly (zero overhead, zero tokens)
- Risky tool detected: save to pending_actions, set tool_name=None, set awaiting_confirm=True, return preview message
- call_llm short-circuits when awaiting_confirm=True: returns gate preview directly (no LLM call, model_label="risk-gate")
- execute_tool skips when tool_calls_made already set OR awaiting_confirm=True
- "do it"/"confirm"/"go ahead"/"yeah do it"/"proceed" on next turn: executes tool with original stored args
- "cancel"/"nevermind"/"nope"/"abort": clears pending action
- ENABLE_RISK_GATE=1 kill switch

**State fields added (`truman/brain/state.py`):** `risk_tier: str`, `pending_action_id: Optional[str]`, `awaiting_confirm: bool`

**loop.py:** risk_gate node wired, 3 new fields in initial_state

**Bugs fixed (`380e8f4`):**
- `\byes\b`/`\bno\b`/`\bstop\b`/`\byep\b` removed from confirm/cancel regex — too broad, "yes I know" would have accidentally executed a risky tool, "stop being stupid" would cancel pending action
- Confirm words: do it, confirm, go ahead, yeah do it, proceed
- Cancel words: cancel, nevermind, nope, abort
- read_mac_file moved from risky → safe (it's read-only, no risk)
- `__import__("re")` hack replaced with clean import

**Brain nodes (12):** classify_mood → concept_lookup → load_memory → load_goals → curiosity → detect_pool → detect_tool → risk_gate → route_skill → execute_tool → call_llm → save_memory

**Verified:** gate intercepts write_mac_file correctly, confirm executes with original args, cancel clears cleanly, safe path (plain chat/list_goals) passes through with 0 warnings.

---

### 2026-05-02 — Phase 10: Proactive Push + Sleep Tracking

**Commit: `c9bfe76`**

#### What shipped

**DB additions (`truman/storage/db.py`):**
- `user_prefs` table: key TEXT PK, value TEXT, updated_at. Changeable via natural language.
- `sleep_log` table: date (unique), sleep_start HH:MM, sleep_end HH:MM, duration_min, raw_input, created_at.
- Helpers: `get_pref`, `set_pref`, `get_all_prefs`, `log_sleep`, `get_sleep_stats(days=7)`

**New tools (`truman/tools/all_tools.py`)** — 23 total (was 21):
- `log_sleep(sleep_start, sleep_end, raw_input)`: parses "4am"/"8:50"/"16:30" → HH:MM 24h, computes duration, logs to sleep_log, returns 7-day rolling avg + typical wake-up time
- `update_pref(key, value)`: supports keys `morning_brief_hour` (converts "9am" → "09:00" + int stored separately), `quiet_start__end` (pipe-separated, splits into quiet_start + quiet_end prefs), and arbitrary keys. Converts "4am"-style to HH:MM internally.

**Risk tier updates (`truman/core/risk.py`):**
- `update_pref`, `log_sleep` added to caution tier
- `read_mac_file` moved to safe tier (was missing — read-only, no risk)

**Keyword detection (`truman/text/agent.py`):**
- "gonna sleep / going to sleep / slept from / sleeping from / sleep from / waking up at" → `log_sleep`
- "change brief / set brief / morning brief time / quiet hours / sleep window / update pref / my sleep is now" → `update_pref`
- `_extract_arg` branches for both tools: parses times from natural language

**Proactive scheduler (`truman/scheduling/proactive.py`):**
- New `start_proactive_push(agent_fn)` — 60s daemon thread, 3 triggers:
  a. Morning brief: fires at `morning_brief_hour_int` ET (default 9), once/day. Tries email first, SSE fallback.
  b. Idle nudge: 4hr silence → SSE push, skips quiet hours, max once per 4hr window.
  c. Goal nudge: noon ET, once/day, only if any goal is stalled 7 days OR deadline <24hrs.
- `_in_quiet_hours(now)`: reads quiet_start/quiet_end from user_prefs. Default 03:00–08:50 ET.
- `start_all()` now also calls `start_proactive_push()`

**Notifications (`truman/storage/notifications.py`):**
- `push_proactive(content)`: pushes `push_turn(role="assistant", content="💡 {content}", session_id="proactive")`

**Dashboard (`truman/voice/static/dashboard.html`):**
- SSE handler: `session_id === 'proactive'` always renders regardless of active session
- `.proactive` CSS class on message div: accent left border + tinted background
- `addMsg()`: detects `meta.proactive` → adds CSS class

**Config (`truman/core/config.py`):**
- `ENABLE_PROACTIVE=1` default added

**Verified:** DB init OK, 23 tools load, 12-node graph compiles, `log_sleep` tool parses "4 to 8:50" → "04:00–08:50 (4.8h). 7-day avg: 4h 50m/night", `update_pref` "9am" → "09:00 ET", quiet hours 6am → True, 10am → False.

---

### 2026-05-02 — Phase 11: Gmail HTML Morning Brief

**Commit: `d3d43a7`**

#### What shipped

**New file: `truman/voice/email_digest.py`**
- `build_html(now)`: pulls sleep_stats + active goals from DB, generates dark-themed HTML email
  - Sleep card: last night times + duration + red/green diff badge vs 7-day avg
  - Goals card: active goals, stale ones (7+ days no update) highlighted red with ⚠️
  - Focus card: auto-generated from data — surfaces stalled goal + low-sleep warning, "No blockers. Ship something." fallback
  - Inline CSS only (Mail.app safe), responsive, dark theme (#0f172a), mobile layout
- `send_morning_brief()`: Gmail SMTP SSL (smtp.gmail.com:465), MIMEMultipart HTML email, subject "Truman Brief — Day, Date"

**Proactive scheduler (`truman/scheduling/proactive.py`):**
- 9am morning brief trigger now: tries `send_morning_brief()` first → SSE push if email fails or env not set

**Config (`truman/core/config.py`):**
- `ENABLE_MORNING_EMAIL=1` default
- `GMAIL_APP_PASSWORD`, `MORNING_EMAIL_FROM`, `MORNING_EMAIL_TO` env var reads added with comment

**ENV vars to fill (`.env` — never committed):**
```
GMAIL_APP_PASSWORD=   # Google Account → Security → 2-Step → App Passwords → 16-char code
MORNING_EMAIL_FROM=   # your gmail address (sender)
MORNING_EMAIL_TO=     # receiving email (usually same)
```

**Verified:** 23 tools, 12 nodes, `build_html()` generates 2946-char valid HTML, all imports clean.

---

## PENDING PHASES (read this before starting work in a new session)

### Phase 12 — Telegram Bot + macOS Native Banner

**Why:** Current proactive push only hits the dashboard (SSE). Telegram = cross-device delivery (Mac + iPhone), inline `[Approve] [Edit] [Skip]` buttons for approval flows, works when Mac is off. macOS native banner = lock-screen notification for in-flow nudges while Mac is on.

**Telegram bot setup (Om does once):**
1. Message @BotFather on Telegram → `/newbot` → get token
2. Message the bot once to get Om's chat_id
3. Add to `.env`: `TELEGRAM_BOT_TOKEN=`, `TELEGRAM_CHAT_ID=`

**New files:**
- `truman/delivery/telegram.py` — `send_message(text, buttons=None)`, `send_photo(path, caption)`, `poll_updates()` (for inline button callbacks)
- `truman/delivery/mac_banner.py` — `notify(title, body, subtitle)` via `pync` or `osascript` UNUserNotification

**Wire into proactive:**
- Morning brief: send to Telegram (same format as email, markdown version)
- Idle nudge: macOS banner → click opens dashboard
- Goal nudge: Telegram with `[View Goals]` button → opens dashboard/goals
- If voice session active: call `speak()` instead of Telegram/banner

**ENV vars to add:**
```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ENABLE_TELEGRAM=1
ENABLE_MAC_BANNER=1
```

**Kill switches:** `ENABLE_TELEGRAM=1`, `ENABLE_MAC_BANNER=1`

---

### 2026-05-03 — Phase 13: Self-Correcting Persona

**Commit: `96f0e87`**

**DB (`truman/storage/db.py`):**
- New `persona_rules` table: id, rule TEXT, active INTEGER (0/1), source TEXT, created_at REAL
- Migration added to `init()` so existing DBs auto-create the table
- 5 helpers: `add_rule`, `get_active_rules`, `get_all_rules`, `toggle_rule`, `delete_rule`

**Brain (`truman/brain/nodes.py`):**
- `call_llm` node: loads active rules from DB, injects `PERSONAL RULES:` block into SYSTEM prompt on every turn
- ENABLE_SELF_CORRECT=1 kill switch gates the injection

**Tools (`truman/tools/all_tools.py`)** — 23 → 26 tools:
- `add_rule(rule)`: saves a behavioral constraint. Triggers: "rule: X", "never say X", "from now on X", "always X"
- `list_rules()`: shows all rules with IDs + on/off status
- `delete_rule(rule_id)`: removes by ID

**Keyword detection (`truman/text/agent.py`):**
- 3 new patterns + `_extract_arg` branches for all 3 rule tools

**API (`truman/voice/orb.py`):**
- `GET /api/rules` — all rules
- `POST /api/rules` — add rule
- `PATCH /api/rules/<id>` — toggle on/off
- `DELETE /api/rules/<id>` — delete

**Dashboard (`truman/voice/static/dashboard.html`):**
- Memory panel split into Facts / Rules tabs
- Rules tab: toggle on/off (⏸/▶), delete, manual add via input
- CSS: `.mem-tabs`, `.mem-tab` with amber active state

**Config (`truman/core/config.py`):** `ENABLE_SELF_CORRECT=1` default added

**Verified:** DB helpers OK, 26 tools, 12-node graph, all 6 keyword patterns match, /api/rules routes registered.

---

### 2026-05-03 — Phase 14: iPhone First-Class — PWA + Web Push + Telegram Media

**Commits: `670ead5`, `d168b57`**

#### A. localStorage corruption fix (permanent)

**Problem:** iPhone refresh would mis-render file attachments as flat text, write that back to localStorage, Mac refreshes and pulls the corrupted state — cross-device corruption.

**Fix (`truman/voice/static/dashboard.html`):**
- `_msgCache` now stores only `{label, model}` per session — no `msgs` HTML ever
- `openSession()`: always fetches from server via `loadHistory()`, never reads cached HTML
- `loadHistory()`: removed cache short-circuit, always network, removed `_saveCache()` call
- Removed 3 additional `.msgs =` write sites (SSE handler, exportChats, send handler)
- Server SQLite is the single source of truth for all devices

#### B. PWA setup

**New files:**
- `truman/voice/static/manifest.json`: name=Truman, display=standalone, start_url=/dashboard, dark theme
- `truman/voice/static/sw.js`: install/activate/fetch handlers + push event + notificationclick
- `truman/voice/static/icon-192.png` + `icon-512.png`: amber T on dark bg, programmatically generated

**Routes (`truman/voice/orb.py`):**
- `GET /sw.js` — served with `Service-Worker-Allowed: /` and `Cache-Control: no-cache`
- `GET /manifest.json`
- `GET /static/<path:filename>` — generic static asset serving

**Dashboard head:** manifest link, apple-touch-icon, mobile-web-app-capable, apple-mobile-web-app-capable, theme-color meta tags

**Dashboard JS:** SW registration + push permission request + VAPID key fetch + pushManager subscribe + POST to /api/push/subscribe on every load

#### C. Web push notifications

**New file: `truman/delivery/web_push.py`:**
- VAPID keys auto-generated on first use, stored in `user_prefs` SQLite (no manual setup)
- `send_push(title, body, url)`: sends to all subscribed devices, removes dead subs (404/410) automatically
- `get_public_key()`: returns stored public key for frontend subscription

**DB (`truman/storage/db.py`):**
- `push_subs` table: id, endpoint UNIQUE, p256dh, auth, created_at
- 3 helpers: `save_push_sub`, `get_all_push_subs`, `delete_push_sub`
- Migration in `init()` for existing DBs

**API (`truman/voice/orb.py`):**
- `GET /api/push/vapid-public-key`
- `POST /api/push/subscribe`
- `POST /api/push/unsubscribe`

**Proactive (`truman/scheduling/proactive.py`):**
- `_web_push()` helper added
- Wired into all 3 triggers: morning brief + idle nudge + goal nudge

**Kill switch:** `ENABLE_WEB_PUSH=1`

#### D. Telegram media intake

**`truman/delivery/telegram.py`:**
- `_download_tg_file(file_id)` — downloads via Telegram file API
- `_handle_photo(photo_list, caption, agent_fn)` — largest size → vision pool → reply
- `_handle_document(doc, caption, agent_fn)` — download → extract text (PDF/text/code) → agent.run → reply
- Poller updated: handles `photo` and `document` msg types alongside text
- Caption forwarded as user prompt for both types
- `allowed_updates` includes `channel_post`
- **Kill switch:** `ENABLE_TG_MEDIA=1`

#### E. Mobile CSS

- LIVE widget: 160px wide, top:60px on mobile (was 210px, top:120px — was blocking chat)
- Sessions sidebar: hidden on mobile (saves full screen for chat)
- Memory panel: full-width on mobile
- Input textarea: font-size 15px (prevents iOS auto-zoom on focus)

**Config:** `ENABLE_WEB_PUSH=1`, `ENABLE_TG_MEDIA=1` defaults added

**Dependencies added:** `pywebpush`, `pillow`

**Verified (Flask test client):**
- All routes 200: /manifest.json, /sw.js, /static/icon-192.png, /static/icon-512.png, /api/push/vapid-public-key, /api/push/subscribe, /api/rules
- sw.js: correct content-type, Service-Worker-Allowed: / header present, valid JS syntax (node --check)
- VAPID keys: auto-generated + stored in SQLite on first hit
- Dashboard: all 8 checks pass (manifest, apple-touch-icon, SW reg, pushManager, zero .msgs writes, server-side loadHistory, mobile CSS, rules tab)
- Telegram: _handle_photo + _handle_document importable, poller handles photo/document branches
- Proactive: 3 _web_push() call sites confirmed

**What Om needs to do (see below):** Railway redeploy → open dashboard in Safari iPhone → Add to Home Screen → Allow notifications → done.

---

### Phase 13 — Self-Correcting Persona (SHIPPED — see above)

**Why:** When Om says "stop doing X" / "you're wrong about Y" / "never say Z", that correction disappears after the session. Should be permanent.

**Architecture:**
- After `save_memory` node (or in `save_memory`): scan assistant response + user reaction for correction signals
- Correction signals: "stop saying", "never say", "you're wrong", "don't do that", "that's not right", "I told you"
- If detected: extract the rule → store in `user_prefs` with key `persona_rule_N`
- `truman/core/persona.py`: at boot, load all `persona_rule_*` prefs from DB → append to SYSTEM prompt

**New files/changes:**
- `truman/brain/nodes.py` — in `save_memory` node: add correction-detection regex, write to user_prefs if triggered
- `truman/storage/db.py` — already has `user_prefs` table from Phase 10 ✓
- `truman/core/persona.py` — load `persona_rule_*` keys from DB at import, inject into SYSTEM

**Kill switch:** `ENABLE_SELF_CORRECT=1`

---

### 2026-05-03 — Phase 14.2: PWA Cache Fix + Mobile UI + File Staging + Persistent Attachments + Anti-Hallucination Docs

**Bugs fixed:**

**1. Refresh shows wrong session (root cause found)**
- `loadHistory()` was called on page load with NO session_id → server returned `recent_turns(30)` across ALL sessions → wrong chat displayed
- `loadSidebar()` saw `_activeId` was set → skipped `openSession()` entirely → correct history never loaded
- Fix: `loadSidebar()` now always calls `openSession(_activeId)` when session exists on server → correct chat on every refresh, every device

**2. Service worker serving stale HTML**
- `sw.js` bumped to `truman-shell-v2` — old cache deleted
- `/dashboard` now fetched with `{cache: 'no-store'}` — always fresh HTML, never stale
- One-time `localStorage.clear()` on version `'14.2'` mismatch — nukes iPhone's corrupted cache

**3. Mobile sidebar hidden**
- Was `display:none` on mobile — fixed to slide-in from left (position:fixed, z-index:200)
- `☰` button in header opens it; overlay tap or session tap closes it
- Added 🔄 refresh button to header (force reload)
- Touch drag handlers for activity panel on iPhone

**4. Double reply**
- `_localTurnInFlight = false` was set before SSE broadcast arrived → SSE added message again
- Fixed: delay `_localTurnInFlight = false` by 300ms after `addMsg`

**5. Images/files disappear after refresh (root cause + permanent fix)**
- Files were only stored as blob URLs (temporary) and raw text in turns — gone on refresh
- Fix: `attachments` SQLite table stores raw bytes permanently
- `/api/upload` generates `attach_id`, saves bytes to DB, returns `attach_id` in response
- `attach_id` embedded in turn content as `[Image: name|attach:ID]` marker — stored in DB forever
- `GET /api/attachments/<id>` serves file bytes with correct mime, 1yr cache header
- `_renderAttachments()` in JS detects markers in loaded history → renders `<img src="/api/attachments/ID">` (persistent server image) or download link for files

**6. File staging UI**
- Files now stage as chips above input (📄/🖼 + filename + X to remove)
- Multiple files supported — select 3 PDFs, get 3 chips, send once
- Textarea stays clean — user can type question + attach files simultaneously
- Image chips show thumbnail

**7. Anti-hallucination doc engine**
- Doc/image messages detected in `/api/chat`, wrapped with grounding template before agent sees them
- Template: "Use ONLY facts from document. Quote sources. Say 'not in this document' if question not answered."
- Forces `pool='docs'` (llama4-maverick) for all file messages — no more small model reading docs
- Truncation bumped 8K → 30K chars (maverick handles 1M context)

**Files changed:** `sw.js`, `dashboard.html`, `orb.py`, `db.py`
**Commits:** `68422ce`, `7fa3702`, `6221b8d`, `2ef93b3`

---

### 2026-05-04 — Phase 15 channels: WA QR endpoint + Gmail fix + Resend morning brief

**Commit: `254ed2b`**

#### Root causes found
- **WA QR distorted**: terminal `qrcode-terminal` wraps at 80 chars → unreadable in Railway logs. Multiple QR images stacked on reconnects.
- **Gmail poller never started**: `ENABLE_GMAIL_POLLING=0` is the code default. On Railway the env var wasn't set. Code was silently not starting — no error, no log line.
- **Morning brief blocked**: Railway blocks outbound SMTP port 465. `[Errno 101] Network is unreachable`. Can't fix by changing Gmail settings — it's Railway's firewall.

#### Fix 1 — WA Bridge: GET /qr PNG endpoint (`wa-bridge/whatsapp_bridge.js`, `package.json`)
- Added `qrcode` npm package (PNG generator, not terminal)
- `_lastQr` stores latest raw QR string on every `qr` event
- New `GET /qr` endpoint: generates PNG via `qrcodeImage.toBuffer()`, serves with `Cache-Control: no-store`
- Returns friendly HTML page if already connected or QR not yet ready
- **How to use:** open `https://your-wa-bridge.railway.app/qr` in any browser → scan with WhatsApp

#### Fix 2 — Morning brief: SMTP → Resend HTTP API (`truman/voice/email_digest.py`, `truman/core/config.py`)
- Replaced `smtplib.SMTP_SSL(port=465)` with `urllib.request` POST to `https://api.resend.com/emails`
- Zero new dependencies — uses stdlib `urllib` only
- `RESEND_API_KEY` env var → set on Railway once
- `MORNING_EMAIL_FROM` defaults to `Truman <brief@truman.resend.dev>` (Resend default domain, works without custom domain)
- `MORNING_EMAIL_TO` → Om's email (already set)
- Free tier: 100 emails/day, no DNS setup needed to start

#### Fix 3 — Gmail SMTP reply: port 465 → STARTTLS 587 (`truman/integrations/gmail_poller.py`)
- `send_reply()` switched from `SMTP_SSL(port=465)` → `SMTP(port=587)` + `starttls()`
- Port 587 is not blocked by Railway
- IMAP reading (`imaplib.IMAP4_SSL`) unchanged — port 993, Railway allows it
- Better startup log: `[Gmail] ✅ Polling inbox (address) every Ns` so Railway logs confirm it started
- `ENABLE_GMAIL_POLLING=0` default unchanged — Om sets it to `1` on Railway

#### ENV vars to set on Railway
```
RESEND_API_KEY=re_xxxxxxxx    # resend.com → API Keys → Create
ENABLE_GMAIL_POLLING=1         # activate Gmail triage
# MORNING_EMAIL_TO should already be set
```

**Verified:** Python syntax OK on all 3 files. WA /qr endpoint wired and tested locally.

---

### Phase 14 — Ambient Awareness Layer (Mac + iPhone passive watching)

**Why:** Truman should know what Om is working on WITHOUT Om telling him. No screenshots. Activity log feeds morning brief, sleep correlation, productivity patterns, and brain loop context.

**Architecture:**

Mac watcher (daemon thread in Truman process):
- Every 60s: active app + window title via `osascript` → `activity_log` table
- Every 60s: idle time via `CGEventSourceSecondsSinceLastEventType` → AFK detection
- Every 30min: keyboard intensity (keystroke count, NOT content) → focus mode detection
- FSEvents watcher (`watchdog` lib): file save events in `~/Desktop/friday/` → log changed files
- Git post-commit hook: installed into Om's repos, POSTs diff stats to local Truman API
- Battery + AirPods state: every 5min via `pmset` + `system_profiler`
- Music playing: AppleScript → Music.app/Spotify every 60s

iPhone signals (Apple Shortcuts — Om installs 7 shortcuts once):
- Alarm dismissed → POST to Truman `/api/awareness` (wake time)
- Focus mode toggle → POST (DnD on/off)
- Location geofence (office/home) → POST
- CarPlay connect → POST (driving mode)
- HealthKit sleep data → "Health Auto Export" free app → webhook
- Battery low (20%) → POST
- Screen Time weekly → POST

New files:
- `truman/awareness/__init__.py`
- `truman/awareness/mac_watcher.py` — daemon thread, all Mac signals
- `truman/awareness/iphone_routes.py` — Flask routes for Shortcut webhooks (`/api/awareness`)
- `truman/awareness/digestor.py` — every 30min, compresses last 30min activity → 1-line summary → Mem0
- `truman/awareness/context.py` — `get_current_context()` → last-hour activity string for brain loop

DB addition:
- `activity_log` table: (id, ts, source [mac/iphone], kind [app/file/git/health/etc], value, meta_json)

Brain loop change:
- Add `load_context` node between `load_goals` and `curiosity` — pulls last-hour activity summary and injects into system prompt

**ENV vars:** `ENABLE_AWARENESS=1`
**Kill switch:** `ENABLE_AWARENESS=1`

---

### Phase 15 — Boss Flow (WhatsApp + Gmail + Calendar + Approval)

**Why:** Om's boss Adam texts on WhatsApp (text, Excel, PDF, images). Truman should summarize → draft reply/action plan → ask Om for approval via Telegram → execute if approved.

**Architecture:**

WhatsApp (iPhone Shortcut method — no ToS risk):
1. Adam texts Om on WhatsApp
2. iPhone Shortcut detects message from "Adam" → auto-forwards to `POST /api/boss_message`
3. Truman receives: message text + attachment (if any)
4. Attachment handling:
   - Excel → llama-4-maverick (vision pool) reads table → summary
   - PDF → docs pool (maverick) → summary
   - Image → vision pool → description
   - Text → fast pool
5. Truman generates: summary of what Adam said + proposed reply OR action plan
6. Sends to Telegram:
   ```
   📨 Adam (10:14am)
   "Need the SeaCap deck by EOD"
   Attached: pipeline.xlsx — 12 leads, 3 hot (X, Y, Z)
   Draft reply: "On it, sending by 5pm. Top 3 are X, Y, Z."
   [Approve & Send] [Edit] [Skip]
   ```
7. If Approve: iPhone Shortcut sends the WhatsApp reply back (Om can set this up as a return webhook)
8. If Edit: opens Truman dashboard with the draft pre-loaded

Gmail API:
- OAuth once (offline token stored in DB as user_pref)
- Poll every 15min for unread from known contacts (Adam, etc.)
- Same summarize + Telegram approval flow
- Kill switch: `ENABLE_GMAIL_POLLING=1`

Google Calendar API:
- OAuth same token
- Pull today's events → inject into morning brief
- Reminder 30min before meetings: Telegram push
- Kill switch: `ENABLE_CALENDAR=1`

New files:
- `truman/integrations/__init__.py`
- `truman/integrations/gmail.py` — fetch_unread(), send_reply()
- `truman/integrations/gcal.py` — get_today_events(), get_upcoming_meeting()
- `truman/integrations/boss_handler.py` — parse_boss_message(), draft_response(), send_approval_request()
- `truman/voice/orb.py` — add `/api/boss_message` route

**ENV vars:**
```
ENABLE_GMAIL_POLLING=1
ENABLE_CALENDAR=1
GOOGLE_OAUTH_TOKEN=    # stored after first OAuth flow
```

---

### 2026-04-11

#### Planning & Setup
- Project named **Truman**
- README written — full architecture, capabilities, missions, tech stack
- Architecture finalized: LangChain + LangGraph + GPT-4o-mini + Mem0 + OpenAI TTS + Whisper
- Memory strategy: System Prompt (identity) + Mem0 (dynamic) + Tools (real-time lookup)
- Conda env `truman` created on Python 3.11
- All packages installed: openai, langchain, langgraph, langsmith, mem0ai, pyaudio, pygame, SpeechRecognition, resemblyzer, tensorflow, tensorflow-hub, ddgs, requests, pyannote.audio

#### Level 1 — Truman Comes Alive ✅
- `config.py` — loads all env vars (OpenAI, LangSmith, Mem0, HuggingFace)
- `voice.py` — SpeechRecognition for STT, Whisper-1 transcription, OpenAI TTS + pygame playback
- `agent.py` — LangGraph `create_react_agent` with GPT-4o-mini, Mem0 memory, LangSmith tracing, session chat history
- `tools.py` — web search (DuckDuckGo/ddgs) + weather (wttr.in), no API key needed
- `main.py` — voice loop, silence detection, shutdown commands
- `seed_memory.py` — seeded 18 memories about Om into Mem0
- Fixed: ddgs package rename, Mem0 v2 filter API, LangChain 1.x agent API changes
- Fixed: Whisper hallucination on silence (min speech duration check)
- Fixed: conversation history — Truman remembers within session

#### Level 2 — Security & Awareness ✅
- `auth.py` — Resemblyzer voice enrollment + verification. Om's voice stored as `om_voice.npy`. Threshold: 0.60
- `sound_classifier.py` — YAMNet (Google, 521 sound classes) replaces fake amplitude heuristic. Detects real cough and clap sounds.
- `lockdown.py` — unauthorized voice → 6-second fullscreen pygame visual (aggressive nodes, matrix rain, flashing warning) → `pmset displaysleepnow` locks Mac
- `ambient.py` — background ambient monitoring thread
- Cough/clap responses: routed through agent for natural dynamic responses, not hardcoded
- Unknown voice protocol: challenge → birthdate → lockdown if wrong
- Speaking flag: ambient detection mutes while Truman is talking

#### Known Issues / To Tune
- Voice auth threshold (0.60) may need adjustment per environment
- Clap detection accuracy depends on YAMNet confidence — test and tune `CONFIDENCE_THRESHOLD` in `sound_classifier.py`

---

## 2026-04-26 — Session: Phases 0-2 + Architecture Overhaul

### Shipped

**Phase 0 — Foundation**
- Clock injection: ZoneInfo("America/New_York") + EDT fallback + tzdata==2025.2 in requirements
- Memory schema: events (ring buffer 1000), memory_episodic, memory_concepts, memory_skills, memory_goals, memory_reflections, memory_feeds, memory_all VIEW — all with ts + date + source
- Status pill in dashboard header: idle/thinking/listening/error dot, always visible, clickable
- Events drawer: slides in from right, polls /api/events every 3s when open, shows kind/model/pool/timing/error
- /api/events endpoint in orb.py
- Commit: `6b62d6f`

**Phase 1 — LangGraph Brain Loop**
- `truman/brain/` module: `__init__.py`, `state.py`, `nodes.py`, `loop.py`
- TrumanState TypedDict with all fields
- 8 nodes, each fails soft into node_errors
- loop.py wires StateGraph, run() returns same shape as old agent.run()
- agent.py: _run_legacy() (old), new run() tries LangGraph (ENABLE_LANGGRAPH=1) then falls back
- Commit: `de5b7a0`

**Phase 2 — Cognee Concept Graph**
- `truman/brain/concepts.py`: init(), ingest(), search(), ingest_background(), search_sync()
- NIM for both LLM (stepfun-ai/step-3.5-flash) and embeddings (text-embedding-ada-002 name on NIM endpoint)
- concept_lookup node in nodes.py: searches graph, ingest_background fires async
- concept_search + concept_ingest tools added to all_tools.py
- COGNEE_SKIP_CONNECTION_TEST=true to skip 30s boot delay
- Commit: `85e5ace`

**Phase 2.1 — Fixes**
- Cognee SearchType.GRAPH_COMPLETION (INSIGHTS doesn't exist)
- Cognee search() positional args (no query= kwarg)
- NIM embedding model name → "text-embedding-ada-002" for tiktoken compatibility
- OpenAI → NIM for all Cognee inference (cost policy: OpenAI = voice only)
- tzdata added to requirements.txt, EDT fallback in nodes.py call_llm
- reflect.py: removed json_mode=True (NIM doesn't support), added markdown fence stripping, 1 retry on bad JSON
- Commit: `972ccf4`

## 2026-04-26 (cont.) — Phase 3: Skills, Kill Switch, Live Progress

**Phase 3 — Skills + Safety**
- Master kill switch: file flag `truman/data/.killswitch`. Power button in dashboard. Truman has zero tools that touch this file. Brain loop guards on entry.
- Removed Groq entirely (requirements, config, model_router). NIM-only with NIM secondary fallback.
- New `truman/skills/` module with stdio-style architecture:
  - `_blacklist.py`: blocks `.env`, `.ssh`, `.killswitch`, `*.key`, `credentials`, `secret`
  - `base.py`, `registry.py` (auto-loads, keyword routing)
  - `files/` — read/write/list/search ~/Desktop (only when on Mac)
  - `web/` — search + fetch_url
  - `github/` — clone + ingest into Cognee, per-repo dataset
- `route_skill` node added between `detect_tool` and `execute_tool`
- `ENABLE_MCP`, `ENABLE_MCP_FILES`, `ENABLE_MCP_WEB`, `ENABLE_MCP_GITHUB` — all default 1
- Commits: `030aa9a`, `c24a92b`

**Phase 3.x — Critical Fixes (after Om caught hallucinations)**
- BUG: `execute_tool` was clobbering `route_skill`'s `tool_result`. Fixed: skip if `skill_name` set.
- BUG: github clone was synchronous, killing 45s chat timeout. Fixed: fire-and-forget background thread.
- BUG: persona had no real skill inventory → Truman hallucinated cloning. Fixed: persona now lists exact skills + hard rule "no [Tool result] → didn't run, don't lie".
- Every skill route now logs to events drawer.
- Commit: `45e01c2`

**Phase 3.2 — Live Progress UI**
- New `memory_repos` columns: status, progress, total, stage, error
- New helpers: `repo_start`, `repo_progress`, `repo_done`, `repo_failed`, `active_repo_tasks`
- New `/api/tasks` endpoint
- Dashboard: tasks strip below session bar, polls every 2s, shows progress bar with %
- Auto-toast: when ingest finishes, Truman sends a chat message "done — ingested N files"
- Failure toast: red bar + chat message with error
- Commit: `c62c335`

### Known Deploy Issue (RESOLVED 2026-04-27)
- Git remote added → GitHub repo connected → Railway auto-deploy wired via GitHub Actions
- All pending commits deployed. Railway is now live on Phases 0-3.2+

### Verified on Railway (Phase 0-2 baseline)
- Time shows correctly: "Sunday, Apr 26 2026, 12:17 PM ET"
- /health endpoint clean
- LangGraph path active (ENABLE_LANGGRAPH=1)
- Cognee active (ENABLE_COGNEE=1)

---

## 2026-04-27 — Session: Auto-Deploy + 9 Live Bug Fixes + Subfolder Routing

### Shipped

**CI/CD Pipeline**
- `.github/workflows/deploy.yml` — on push to main → `railway up --detach --service "Truman"` via `RAILWAY_TOKEN` secret
- Railway connected to GitHub repo. Every `git push` now auto-deploys. No more manual `railway up`.
- Commit: `8fdfe34`

**Bug fixes from live Railway testing (commits f3ce817, 1d06e04, cd89c8c):**

| Bug | Root Cause | Fix |
|---|---|---|
| Pool stuck on "coding" forever | `_STICKY_POOLS` in nodes.py locked session after first detection | Removed all sticky logic — fresh `detect_pool` every message |
| Model ignoring pool (always kimi-k2) | `call_llm` node used hardcoded `_call_llm()` instead of `run_with_pool` | Wired `run_with_pool(chosen_pool)` in call_llm node |
| All pools 404ing on Railway | Railway env vars had dead model slugs | Hardcoded fallback chain in `run_with_pool`: deepseek-v3.2 → step-flash → kimi-k2 |
| `appendMsg` undefined (toast never showed) | Old function name in JS | Replaced all `appendMsg` with `addMsg` in dashboard.html |
| Drag panel broken on load | `getElementById` ran before element existed | Wrapped drag init in `DOMContentLoaded` |
| LLM hallucinating `[Tool result]` blocks | Model invented fake tool output | Strip with `re.sub(r'\[Tool result[^\]]*\]...')` after every LLM response |
| `_CODING_KW` too broad | "api", "run", "error" were triggering coding pool | Tightened keyword list in model_router.py |
| SSE not pushing events | No SSE endpoint existed | Added `notifications.py` + `/api/stream` SSE endpoint in orb.py |
| Activity panel not showing skill | `skill` field missing from `/api/chat` response | Added `skill` to loop.py return dict + `updatePanelFromResponse()` in UI |

**main_cloud.py + mac_bridge.py untracked** — Railway couldn't find entry point. Both committed. Commit: `85aca6b`

**Subfolder listing fix (commit 8a079ee):**
- `registry.py`: added "what's inside X", "inside the folder", "in the directory" keywords → route to `list_repo` (was falling through to LLM → hallucination)
- `github/server.py`: `_guess_subdir(user_input)` extracts folder name via regex patterns
- `github/server.py`: `_list_repo(repo_name, subdir="")` filters file walk to only `subdir/*` paths
- Result: "what's inside the agents folder" → fires github skill → returns real files → no hallucination

**kimi-k2 reverted as POOL_GENERAL primary (commit 8a079ee):**
- deepseek-v3.2 was bumped to primary without approval → 24s response times
- Reverted: `POOL_GENERAL = "nvidia:moonshotai/kimi-k2-instruct,nvidia:stepfun-ai/step-3.5-flash,nvidia:deepseek-ai/deepseek-v3.2"`

### Current state (Railway live)
- All commits up to `8a079ee` deployed
- Auto-deploy active via GitHub Actions
- Pool routing correct, subfolder listing works, no fake tool blocks, skill badge shows in panel

### Next
- Phase 4 — Goals + Curiosity (proactivity): proactive repo recommendation after ingest, push via SSE

---

1. PWA (30 min work, easiest)
Add a manifest file → Chrome shows "Install Truman" button → becomes its own app icon in your dock. Runs in its own window, no browser tab needed. Can launch on Mac startup. Still uses WebRTC AEC underneath. Same code we're about to write.

2. Electron wrapper (few hours)
Wrap the orb in a native Mac app. Looks like a regular Mac app, lives in dock or menu bar. Best UX, feels like a real desktop app. Same WebRTC AEC inside.

3. Menu bar app (advanced)
Tiny icon in your Mac menu bar (top-right). Click it → starts session. Hidden Chromium does the audio. Cleanest UX possible — Truman lives in your menu bar always, no window at all.

---

## 2026-04-28 — Session: Phase 4 — Goals + Curiosity Layer

### Shipped (commits `ff36be1`, `20afd74`)

**Premise:** persistent goals injected into every prompt so Truman knows what Om is working towards without being re-told. Foundation for future proactive nudges (Phase 15).

**db.py (5 helpers added):**
- `memory_goals` table already in schema (status: active/done/paused/dropped)
- `add_goal(title, description, priority)` → uuid
- `get_active_goals(limit=3)` → for prompt injection
- `get_all_goals()` → for list_goals tool
- `complete_goal(query)` → LIKE-match on title, sets status=done
- `drop_goal(query)` → LIKE-match on title, sets status=dropped

**state.py:** added `goals_context: str` field to TrumanState

**nodes.py:**
- New `load_goals` node — runs only if `ENABLE_GOALS=1`, fails soft, formats "ACTIVE GOALS:\n- title: description" block
- `call_llm` node updated — appends `goals_context` to system prompt after memory_context

**loop.py:** wired `load_memory → load_goals → detect_pool` and added `goals_context` to initial state

**all_tools.py (4 new tools, TOOLS list now 21):**
- `add_goal(title, description="")` — adds active goal
- `list_goals()` — shows all goals with status icons (→ ✓ ✗ ⏸)
- `complete_goal(query)` — marks done by partial title match
- `drop_goal(query)` — marks dropped by partial title match

**agent.py:**
- 4 new keyword patterns in `_TOOL_PATTERNS` (uses `goals?` regex to handle plural)
- `_extract_arg` cases for add_goal (strip imperative prefix), list_goals (no args), complete_goal/drop_goal (extract query text)

**persona.py:** added one-line goals capability under CAPABILITIES — explains injection + tool names + natural reference rule

**Bug caught + fixed before Om saw:** patterns like `\b(list.*goal)\b` didn't match plural "goals" because the trailing `\b` requires "goal" to be at a word boundary, but "goals" has "s" after. Fixed with `goals?` quantifier.

### Verified end-to-end
- plain chat → kimi-k2, no tool, 0 warnings
- weather → `get_weather` tool fires, real result
- "list goals" → `list_goals` tool fires, returns DB data
- "add goal X" → `add_goal` fires, persists to SQLite
- Graph node order confirmed: classify_mood → concept_lookup → load_memory → load_goals → detect_pool → detect_tool → route_skill → execute_tool → call_llm → save_memory

### Token impact
- System prompt baseline: ~3,500 tokens
- Goals injection: +50–150 tokens (3 goals × ~30-50 tokens each)
- ~3-4% increase per chat input. NIM is free → zero cost.

### Files touched (7 total, all behind `ENABLE_GOALS` kill switch)
```
truman/storage/db.py       +5 helpers
truman/brain/state.py      +1 field
truman/brain/nodes.py      +1 node, edit call_llm
truman/brain/loop.py       +1 node wired, +1 state init
truman/tools/all_tools.py  +4 tools
truman/text/agent.py       +4 patterns, +4 extract cases
truman/core/persona.py     +1 line
```

### Next — Phase 5 — Risk Gate (scoped, not built)

**What:** safety layer between tool detection and execution. Risky tools (write_mac_file, github ingest, set_model, future deploy/email/code-run) require explicit "do it" confirm before firing. Pending action stored in DB with 5min TTL.

**New:** `pending_actions` table, 4 db helpers, `risk_gate` brain node, 3 state fields, `truman/core/risk.py` (single source of truth for risk tiers), persona update, `ENABLE_RISK_GATE=1` kill switch.

**Risk tiers:**
- safe (95% of chats, zero overhead): all reads, search, list_*, recall, web_search, weather, concept_search
- caution (auto + log prefix): remember, set_reminder, add_goal, complete_goal, drop_goal, concept_ingest
- risky (confirm gate): write_mac_file, github ingest_repo, pipeline_mode, set_model

**Token impact:** zero on safe path. Risky path: ~50 templated tokens for confirm prompt instead of normal LLM output.

**Smartness gain:** defensive (auditable, won't clobber files), not offensive. Foundation for Phase 6 (E2B sandbox) and Phase 11 (deploy commands).
---

## 2026-04-30 — Session: Phase 6 — Speed + Truth + Toasts + Barge-in

### Context
Live Railway test surfaced major issues: 6-20s reply times, model lying about which model it was on, risk gate false-firing on casual messages, Truman fabricating project status, voice barge-in not stopping mid-utterance, dashboard activity panel spam.

### Shipped (commits `d26236e`, `c882224`, `73e15b0`, `9b7692d`)

**Speed (real culprit was Mem0 + Cognee, not the model):**
- `concept_lookup` node: skip Cognee search for short msgs (<20 chars) or greetings — was 1-3s per turn wasted
- `curiosity` node: same skip logic
- `load_memory` node: skip Mem0 remote API call for short/greeting msgs — biggest single win, was 1-5s per turn
- `_build_llm` timeout 8→15s — fewer accidental fallbacks, models get full time
- Combined: "yo what's up" went from 17s → ~1-2s

**Super-fast model swap (`POOL_GENERAL`):**
- New primary: `meta/llama-3.1-8b-instruct` (sub-second on NIM)
- Order: llama-3.1-8b → nemotron-nano-8b → step-flash → nemotron-49b → kimi-k2
- `POOL_FAST` same trio
- Hardcoded last-ditch fallback updated to fast 8B chain
- Registered new models in `MODEL_INFO` + `_ALIASES` (fast/nano/llama8b) + `short_label`

**Truth layer (no more model lies):**
- Persona reminder hardened: "NEVER claim which model you are — just respond. NEVER write '[Tool result...]' or '(hypothetical output)' or invent bracket-blocks."
- Hallucination strip v2: also catches `(hypothetical output...)`, `[MODEL: ...]`, bracket-hypothesis patterns

**Risk gate false-fire fix:**
- `set_model` regex tightened — now requires actual model name. "switch to step flash" in casual context no longer triggers.
- Old: `\b(use model|switch.*model|set model|switch to)\b`
- New: `\b(use model|switch.*model|set model|switch to (nemotron|kimi|step|qwen|llama|maverick|devstral)|use (nemotron|kimi|step|qwen|llama|maverick|devstral))\b`

**Confirmation toasts (Om's request):**
- New SSE event kind=`toast` pushed when ANY tool actually executes (`execute_tool` + `risk_gate` confirm path)
- Format: `✓ tool_name — result preview (80 chars)`
- `dashboard.html` `showToast()` function: green pop-up bottom-right, auto-dismiss 4s
- Now Om can SEE when add_goal / set_reminder / set_model / write_mac_file actually fired

**Voice barge-in fix:**
- `realtime.py` `input_audio_buffer.speech_started` handler now sends `response.cancel` event to OpenAI WS
- Previously just drained local audio queue → model kept generating, barge-in didn't actually stop it
- Now Truman stops mid-word when Om speaks

**Anti-fabrication persona rule (Phase 6 follow-up):**
- 8B model was inventing project state ("forex going pretty good", "MAYA's intent parser headaches", "SeaCap pipeline moving")
- ACTIVE_PROJECTS rewritten: names only, no canned status data
- Hard rule: "you don't have live state. don't invent progress. ask Om if asked"
- Hard rule: "talk TO Om in 2nd person, never ABOUT him in 3rd person" (was generating "om's in a good place today")
- Trimmed to be natural — no scripted "idk man" templates

### Files touched
```
truman/core/config.py               POOL_GENERAL + POOL_FAST reorder, fast 8B primary
truman/core/model_router.py         timeout 8→15s, MODEL_INFO + aliases + short_label entries, fallback chain
truman/core/persona.py              anti-fabrication + 2nd-person rules
truman/text/agent.py                set_model regex tightened
truman/brain/nodes.py               concept/curiosity/memory skip-short, persona reminder, hallucination strip v2, toast push on tool exec + risk confirm
truman/voice/realtime.py            response.cancel on speech_started
truman/voice/static/dashboard.html  showToast() + SSE kind=toast handler
```

### Verified live on Railway
- "yo what's up" → ~1-2s response on llama-3.1-8b
- Model badge accurate (no more nemotron lies)
- No "[Tool result]" / "(hypothetical)" leakage
- Toast pops up green when tool fires

### Known regression (caught + patched in same session)
- 8B model started fabricating project status when asked about MAYA/forex
- Fix: persona rewrite (commits `73e15b0` → `9b7692d`)
- Final form: hard "don't fake status" rule + natural language (no canned templates)

### Next — Phase 7 — UI noise cut + sticky model lock
- Dashboard activity panel: hide silent nodes, only show ones that did something
- Sticky model: when Om says "use nemotron", pin it across messages until cleared (currently `_session_model` resets on Railway redeploys)
- Possibly: per-tab model lock instead of process-global

---

## 2026-05-01 — Phase 7: Mac Bridge Local Tools + Phase 7.1: Activity Sidebar

**Commits: `a994c25`, `e309143`, `28a2a8a`, `98770ba`, `999cc1f`, `af65a5d`**

### Phase 7 — Mac Bridge Local Tools + RUNTIME Injection + Tool Cache

**Problem:** Mac file tools (`read_mac_file`, `list_mac_dir` etc.) always used WebSocket bridge — locally this bridge doesn't exist so they returned "Mac bridge not connected". LLM didn't know if it was running local or Railway. Tool results were forgotten turn-to-turn causing re-calls.

**Mac bridge local routing:**
- Added `_is_local()` check in `all_tools.py` — detects local vs Railway via `RAILWAY_URL` env
- Local path: direct filesystem calls (`os.listdir`, `open()`, etc.) — no bridge needed
- Railway path: existing `mac_request()` WebSocket bridge unchanged
- Added `import os` (was missing, caused `NameError`)

**RUNTIME injection:**
- `agent.py` injects `RUNTIME: local` or `RUNTIME: railway` into system prompt every turn
- Persona updated: "Check RUNTIME line — if local, use tool directly. If railway, say can't reach Mac files"
- LLM now knows where it's running, stops hallucinating it's on Railway when local

**Tool result cache:**
- `_tool_cache` dict (per session, last 3 results) in `agent.py`
- After any tool runs, result cached via `_cache_tool_result()`
- Injected as "RECENT TOOL RESULTS" into system prompt — stops LLM re-calling same tools
- `from collections import deque, defaultdict` added

**Keyword + path extraction improvements:**
- `list_mac_dir` patterns expanded: "see.*desktop", "what.*desktop", "desktop.*files" etc.
- Smart path extraction: bare folder names like "AI Lab" → `~/Desktop/AI Lab`
- Pool override: file tools force "fast" pool in `detect_pool` node (was routing to "creative")

**Mem0/Cognee skip:**
- Skip threshold raised 20→50 chars for short messages
- File tool requests skip Mem0 + Cognee entirely (pre-check via `_detect_tool`)
- "yoo" went from 18s → ~1s locally

### Phase 7.1 — Activity Sidebar (Live Brain Trace Panel)

**Problem:** Om wanted to see what Truman is doing in real-time — tools called, skills run, LLM pool used — without digging into logs.

**What shipped:**
- Slide-out resizable sidebar (`#activity-sidebar`) — fixed right edge, opens over chat
- Only shows meaningful events: `execute_tool` (⚙), `route_skill` (★), `call_llm` (◈), errors (✕)
- One card per turn — header shows timestamp + input preview
- Click any row to expand inline → shows args + result
- Resizable: drag left edge handle (280px–700px)
- History loads from SQLite `trace_events` table on open
- Live SSE push: new events append in real-time as Truman thinks
- `trace_events` table added to SQLite schema
- `push_trace()` — fire-and-forget: SSE push + SQLite write in background thread
- `/api/trace` endpoint added to `orb.py`
- All 12 brain nodes instrumented with start/end/error/skipped events
- `turn_id` added to `TrumanState` — groups all events for one chat turn

### Files touched
```
truman/tools/all_tools.py           _is_local(), local file helpers, import os
truman/text/agent.py                _tool_cache, RUNTIME injection, keyword/path improvements
truman/brain/nodes.py               _t() trace emitter, all 12 nodes instrumented, pool override, Mem0/Cognee skip
truman/brain/state.py               turn_id field
truman/brain/loop.py                turn_id generation, emit_event call
truman/storage/db.py                trace_events table, log_trace(), get_trace_history()
truman/storage/notifications.py     push_trace()
truman/voice/orb.py                 /api/trace endpoint
truman/core/persona.py              RUNTIME rule, tool result reporting rule
truman/voice/static/dashboard.html  activity sidebar HTML/CSS/JS, resize handle, SSE trace handler
```

### Next — Phase 8 — Sticky model lock + keyword fixes + persona leak
- Sticky model: pin model across turns when Om says "use nemotron" (currently resets per-process)
- Fix "can you see my desktop?" keyword not always triggering `list_mac_dir`
- Fix LLM leaking persona narration `"(Maintaining a flat tone...)"` in responses

---

## 2026-05-02 — Phase 8A-8C + 8E: Sessions + Memory + Multi-device Sync

**Commits: `ed859d7`, `1d1e76e`, `bd06cac`, `e7ea002`, `ced3232`, `8d20144`, `a69ea69`**

### Phase 8A — Session persistence (refresh-safe)
- Sessions array + session IDs saved to `localStorage` (`truman_sessions_v1`) on every message, tab switch, new chat
- Page load: reads localStorage first, restores all tabs + active chat instantly
- Cap: 60k chars per session to stay well under 5MB localStorage limit
- On fresh install (no localStorage): falls back to SQLite `recent_turns(30)`

### Phase 8B — Per-session history load
- `/api/history?session_id=X` wired up — each tab fetches only its own turns from SQLite
- `switchSession()` loads from SQLite if tab has no cached messages yet
- Fresh page load (no localStorage) uses global recent turns fallback — no filter

### Phase 8C — Cross-chat user memory
- New `user_facts` SQLite table: `id, fact, importance(1-5), source, created_at`
- 4 db helpers: `save_fact`, `get_top_facts`, `get_all_facts`, `delete_fact`
- `/api/facts` GET + POST + DELETE endpoints in `orb.py`
- Top 10 facts injected into system prompt as `WHAT YOU KNOW ABOUT OM:` block every turn — every new chat starts knowing Om
- 📌 pin button on every Truman message bubble (hover to reveal) → saves with importance 4
- **Memory panel** — "memory" button in header → slide-out panel showing all facts, importance stars, edit/delete, manual add
- **Auto-extract** — messages >60 chars with emotional/personal keywords → background thread → fast 8B LLM call → extracts 1-3 facts → saves with importance 3. Zero user-facing latency.
- Duplicate check: skips facts too similar to existing ones

### Phase 8E — Multi-device live sync
- `push_turn()` in `notifications.py` — broadcasts new turns via SSE to all connected clients
- Called in `orb.py` after every chat response (both user + assistant turns)
- Frontend SSE handler: receives `kind=turn` → appends message if it's for the active session + came from another device
- `_localTurnInFlight` flag prevents same-device double-render

### Known issue (Railway ephemeral filesystem)
- Railway wipes SQLite on every redeploy — Om lost his chat history on the 2026-05-02 deploy
- FIXED (2026-05-02): Railway volume `truman-volume` mounted at `/data` — SQLite persists across deploys

### Files touched
```
truman/storage/db.py                user_facts table + 4 helpers, _time import fix
truman/storage/notifications.py     push_turn()
truman/voice/orb.py                 /api/facts endpoints, push_turn calls, _auto_extract_facts()
truman/brain/nodes.py               user_facts injection into system prompt in call_llm
truman/voice/static/dashboard.html  localStorage session persistence, per-session history, memory panel UI, pin button, SSE turn handler, _localTurnInFlight flag
```

---

## 2026-05-02 (cont.) — Phase 8D-8F + Phase 9: UI Overhaul + Mac-Master Storage + Multi-Device Sync

**Commits: `bd06cac` (phase 8C already), + session work below**

### Phase 8 — UI Overhaul (dashboard.html complete rewrite)

**Theme system:**
- 5 presets: midnight (default), ocean, forest, sunset, minimal
- CSS custom properties `--bg`, `--surface`, `--surface2`, `--accent`, `--text`, `--text2`, `--border`, `--accent-glow`
- Theme picker in header, persists to localStorage

**Model picker dropdown:**
- Replaced plain input with `<select>` showing all known models (nemotron-49b, kimi-k2, llama-3.1-8b, step-flash, qwen3-coder, llama-4-maverick, devstral)
- Sends `model` field in chat POST body
- `_currentModel` state var — only one declaration (bug fixed: was declared twice)

**Markdown rendering (`renderMarkdown()`):**
- Bold (`**`), italic (`*`), inline code (`` ` ``), fenced code blocks (` ``` `)
- Bullet lists (lines starting with `-` / `*`)
- Auto-link URLs → `<a>` tags
- `\n` → `<br>` for newline preservation

**Chat bubble improvements:**
- Timestamps on every message (HH:MM)
- Copy button (hover → clipboard)
- Scroll-to-bottom button (appears when scrolled up)

**Auto tab-name:**
- First user message → sent to LLM as session title, tab renamed automatically

**Export / Import JSON:**
- Export: downloads all sessions as `truman-export-YYYY-MM-DD.json`
- Import: drag-drop or file picker, merges into localStorage

**Keyword fix:**
- Removed `see.*desktop` from `list_mac_dir` pattern — was matching "can you see my desktop?" casually
- New pattern: `show.*desktop|what.*desktop|list.*desktop|desktop.*files|files.*desktop`

**Strip markdown for TTS (`agent.py`):**
- Only strips persona narrations (`*smiles*`, `*maintains flat tone*`) and excess newlines
- Keeps markdown for browser rendering (no longer strips `**bold**`, `# headers`, `- bullets`)

### Phase 9 — Mac-Master Storage + Session Sidebar + Multi-Device Sync

**SQLite schema additions (`db.py`):**
- `sessions` table: added `browser_id TEXT UNIQUE`, `label TEXT`, `first_message TEXT` columns via migration
- `get_or_create_session(browser_id, label=None)` → int sid — maps frontend UUID → SQLite row
- `update_session_label(browser_id, label)` — rename
- `delete_session(browser_id)` — delete session + its turns
- `get_sessions_by_day()` → grouped list with Today/Yesterday/date headers
- `set_session_first_message(browser_id, msg)` — stores first message for sidebar preview
- `session_turns(session_id)` — now accepts str browser_id or int sid
- DB_PATH: checks `os.path.isdir("/data")` first → uses `/data/truman.db` on Railway volume, else local `truman/truman.db`

**orb.py session fixes:**
- `/api/chat`: proper `get_or_create_session(session_id)` → `log_turn()` flow (was broken, turns weren't logged)
- `set_session_first_message()` called on first user message per session
- `GET /api/sessions` — returns day-grouped session list
- `PATCH /api/sessions/<browser_id>` — rename
- `DELETE /api/sessions/<browser_id>` — delete

**New file: `truman/storage/sync.py`:**
- `start_sync()` — starts two daemon background threads
- `_pull_from_railway()` — every 60s: pulls all sessions+turns from Railway `/api/sessions` + `/api/history` → merges into local Mac SQLite (dedup by role+content)
- `_do_backup()` — dumps all sessions+turns to `~/Desktop/friday/backups/truman-YYYY-MM-DD.json`, keeps last 30 days
- `_backup_loop()` — runs `_do_backup()` daily at 2am

**main.py:** added `start_sync()` call (Mac-only — not in main_cloud.py)

**.env:** added `RAILWAY_SYNC_URL=https://truman-production.up.railway.app`

**dashboard.html — Left session sidebar:**
- Replaced horizontal session-bar with `#sessions-sidebar` (220px, fixed left)
- Layout: `body-wrap` (flex row) → sidebar + `main-area` (flex:1)
- `loadSidebar()` fetches from `/api/sessions`, groups by day, hover → preview popup with first_message
- Right-click context menu: Rename / Delete
- `_msgCache` dict (keyed by browser_id) replaces old `sessions[]` array
- `openSession(bid)` — loads session from cache or fetches from `/api/history?session_id=bid`
- localStorage key `truman_sessions_v1` updated to dict format

### Deployment

- `railway up --service Truman` — deployed successfully
- `/api/sessions` confirmed live at `https://truman-production.up.railway.app/api/sessions`

### Architecture: Mac = Master

```
Phone/Browser → Railway (live chat) → Mac syncs every 60s → local SQLite
                                     → daily 2am backup → ~/Desktop/friday/backups/
```
- Data safe even if Railway dies — Mac always has the full copy
- Om's phone, Mac, sister's phone all write to Railway, Mac pulls it all down

### Railway Volume Mount — DONE (2026-05-02)

- `railway volume add --mount-path /data` — volume `truman-volume` (5GB) attached to Truman service
- Verified: test chat written, `/api/sessions` returned session from `/data/truman.db`
- SQLite now persists across all redeploys

### Pending

- End-to-end multi-device sync test (phone → Railway → Mac pull)

### Next — Phase 9B / 10 — Agent activity trace + deeper proactivity

---

## 2026-05-04 — Multimodal Pipeline Phase 1 + Vision Pool Upgrade

**Commits: `990a089`, `8f3deff`**

### What shipped

**Deleted (broken pipeline):**
- `_DOC_GROUNDING` template + grounding wrapper in `/api/chat` — was wrapping all image/doc messages in a rigid "only use doc facts" template. Caused hallucination because model was constrained to a stale text description, not the actual image.
- Describe-once maverick call in `/api/upload` — was calling vision LLM at upload time, storing description as text, discarding bytes. Root cause: every "look again" request used the same broken description from upload. Now removed. Images return `text: ""`.

**Built (`truman/multimodal/`):**
- `loader.py` — given attach_id, fetches raw bytes from `attachments` DB table, returns NIM `image_url` content block (`{"type":"image_url","image_url":{"url":"data:<mime>;base64,..."}}`). Runs every turn, not once at upload. Non-images return None (text already extracted inline).
- `prompts.py` — type-specific system prompt injections. iMessage screenshots: "blue right = sender, gray left = receiver, never swap." Generic images: "read precisely, never hallucinate, say if unclear."
- `__init__.py` — module init.

**Wired through graph:**
- `brain/state.py` — `attach_ids: list` field added to TrumanState
- `brain/loop.py` — `attach_ids` param added to `run()`, included in initial_state
- `text/agent.py` — `attach_ids` param added to `run()`, passed through to lg_run
- `brain/nodes.py call_llm` — when `attach_ids` present: fetches live image bytes, builds `[image_url_block, text_block]` content list, injects type-specific system hint. Falls back to plain text if loader fails (safe).
- `voice/orb.py` — `_parse_multimodal_input()` helper parses `|attach:ID` patterns from message, extracts image IDs, strips markers from user text, auto-sets `pool_hint = "vision"`

**Vision pool upgraded (`config.py`, `model_router.py`):**
- Old: `vision = maverick only`
- New: `vision = llama-3.2-90b-vision-instruct → llama-4-scout-17b-16e → llama4-maverick`
- 90B is the most accurate vision model on NIM. Scout is fast fallback. Maverick is last resort.
- Model labels + MODEL_INFO entries added for both new models.

### Still pending — Full multimodal build (next session, DO THIS IN ORDER)

**What's already done (don't redo):**
- `truman/multimodal/loader.py` exists — images only (base64 → image_url block)
- `truman/multimodal/prompts.py` exists — iMessage hint + generic image hint only
- `attach_ids` wired through state → loop → agent → nodes (images go to LLM on upload turn)
- `_parse_multimodal_input()` in orb.py — parses markers, extracts image attach_ids
- Vision pool = `llama-3.2-90b-vision → llama-4-scout → maverick`

**What's NOT done yet — build these in order:**

---

#### Layer 1 — Reception (already exists, verify only)
- Upload → saves bytes to `attachments` table ✓
- Returns `attach_id` + `text: ""` for images ✓
- Turn content gets `[Image: name|attach:ID]` marker in dashboard ✓
- NO description generated at upload ✓

---

#### Layer 2 — Full type-aware loader (`truman/multimodal/loader.py` — expand current)

Current file only handles images. Expand to:

| File type | What to load |
|---|---|
| png / jpg / webp / gif / heic | bytes → base64 → `image_url` content block |
| PDF (text) | pdfplumber text extract + first page as image |
| PDF (scanned, no text) | every page as image, max 20 pages |
| DOCX | python-docx → markdown with headings + bold |
| XLSX / CSV | pandas → markdown table, cap 200 rows, note if truncated |
| TXT / MD / code | raw bytes as text |

Return shape per attach_id:
```python
{
  "blocks": [...],       # NIM content blocks (image_url or text)
  "text_inline": "...",  # text to include inline in human message (for docs)
  "tokens_est": N,       # rough token estimate for UI display
  "kind": "image"|"pdf"|"docx"|"xlsx"|"text"
}
```

---

#### Layer 3 — Multimodal call builder (`truman/multimodal/call.py` — new file)

Move all multimodal message building OUT of `nodes.py` (currently inline). Build:

```python
def build_messages(attach_ids, user_text, tool_result=None, chat_history=None, system_content="") -> list:
    """
    Returns properly formed messages list for NIM multimodal call.
    Images → image_url content blocks in HumanMessage.
    Docs → text_inline appended to human message text.
    Both → same call if mixed.
    """
```

Format NIM expects:
```json
{
  "role": "user",
  "content": [
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
    {"type": "text", "text": "what's beth saying here"}
  ]
}
```

Image goes in EVERY turn it's still relevant (handled by Layer 4 sticky state).
`nodes.py call_llm` should call `call.build_messages()` instead of inline block.

---

#### Layer 4 — Sticky attachments (`truman/multimodal/session_state.py` — new file)

```python
# Per-session live attachment tracking
_live_attachments: dict[str, list] = {}
# shape: {session_id: [{attach_id, kind, filename, turns_left, tokens_est}]}

def add_attachment(session_id, attach_id, kind, filename, tokens_est): ...
def get_live_attachments(session_id) -> list: ...
def tick_session(session_id): ...       # decrement turns_left, drop at 0
def drop_attachment(session_id, attach_id): ...  # user taps X
def clear_session(session_id): ...      # "new topic" / "drop everything"
```

Rules:
- New attachment uploaded → `turns_left = 10`
- Every turn with this session → `tick_session()` decrements all
- "look again" / "check the ss" / "re-read" / "what does it say" → reset `turns_left = 10` for all
- "drop the file" / "new topic" / "forget it" → `clear_session()`
- `turns_left == 0` → auto-drop (stop sending to LLM)

Wire into `nodes.py call_llm`:
- Before building messages: `attach_ids = get_live_attachments(session_id)` (replaces state.attach_ids for follow-up turns)
- After LLM call: `tick_session(session_id)`

Wire into `orb.py /api/upload`:
- After saving to DB: `add_attachment(session_id, attach_id, kind, filename, tokens_est)`

---

#### Layer 5 — Smart per-type system prompts (`truman/multimodal/prompts.py` — expand current)

Current file only has iMessage + generic image. Expand:

| Type | System injection |
|---|---|
| iMessage screenshot | "Blue bubble RIGHT = the OTHER person messaging Om. Gray bubble LEFT = Om's own past replies. Never swap. If unclear, say so." |
| WhatsApp screenshot | "Green bubble RIGHT = Om sent this. White/gray bubble LEFT = other person. Never swap." |
| PDF document | "Quote sources verbatim. Include page numbers for every claim. If question not answered in doc, say so directly." |
| Spreadsheet / CSV | "Reference column headers literally. Never rename or infer column names. Note row count if truncated." |
| Code file | "Cite line numbers for every reference. Do not summarize logic you haven't read." |
| Photo / general image | "Describe only what is actually visible. Never infer or guess. If something is unreadable, say so." |

Auto-detect type from filename + mime (no manual tagging):
- filename contains "imessage"/"imsg"/"chat"/"screenshot" + image mime → iMessage hint
- filename contains "whatsapp"/"wa-" + image mime → WhatsApp hint
- mime = application/pdf → PDF hint
- mime = xlsx/csv → spreadsheet hint
- etc.

---

#### Layer 6 — Dashboard live context tray (update `dashboard.html`)

Strip below the input area (above the attach-bar or replace it):
- Shows which attachments are currently in model's context (from `/api/live_attachments?session_id=X`)
- Each chip: thumbnail (if image) + filename + token count + "N turns left" + X button
- Click X → `DELETE /api/live_attachments/<attach_id>?session_id=X` → drops from session state
- Auto-updates every turn (re-fetch after send)
- Styling: matches existing `.attach-chip` style

New endpoint in `orb.py`:
- `GET /api/live_attachments?session_id=X` → returns current live_attachments for session
- `DELETE /api/live_attachments/<attach_id>?session_id=X` → drops one attachment

---

#### Layer 7 — Page-pinning for PDFs (add to `loader.py`)

Detect "page N" / "go to page 3" / "show me page 5" in user message.
If PDF is live in context and user asks for a specific page:
- `loader.py` sends only that page (as image or text extract)
- Saves tokens — don't send full 40-page PDF every turn

Pattern in `orb.py _parse_multimodal_input()` or `nodes.py detect_tool`:
```python
_PAGE_RE = re.compile(r'\bpage[s]?\s+(\d+)\b', re.I)
```
If match + PDF in live_attachments → set `page_hint` in state → loader uses it.

---

#### Layer 8 — Multi-image in one call (already free, just verify)

If multiple attach_ids in one turn → loader returns multiple image_url blocks → all go into same content list → maverick/90B sees them side by side. No extra code needed if Layers 2-3 are built correctly. Test with 2 screenshots.

---

#### Wiring checklist for next Claude

1. Expand `loader.py` — full type matrix (Layer 2)
2. Write `call.py` — message builder (Layer 3)
3. Write `session_state.py` — sticky attachments (Layer 4)
4. Expand `prompts.py` — all types + auto-detect (Layer 5)
5. Update `nodes.py call_llm` — use `call.py` + `session_state.get_live_attachments()` instead of inline block + `state.attach_ids`
6. Update `orb.py /api/upload` — call `session_state.add_attachment()` after DB save
7. Update `orb.py /api/chat` — pass `session_id` to session_state tick
8. Add `/api/live_attachments` endpoints to `orb.py`
9. Update `dashboard.html` — live context tray below input
10. Test: upload image → ask question → "look again" → verify image re-sent → verify drops at turn 10

---

## Phase 15D — 3-Channel Automation Final (2026-05-04, continued session)

### What changed from Phase 15C

**Gmail — keyword triage → LLM 3-tier classification**
- Old: hardcoded keyword list (interview, urgent, offer, etc.) — too strict, Om never got pings
- New: `_classify_email()` in `truman/integrations/gmail_poller.py` calls fast pool with JSON prompt
- Returns `{"tier": "HIGH"|"MID"|"LOW", "reason": "..."}`
- HIGH: draft reply + Telegram approval ping (same as before)
- MID: Telegram FYI summary only (no approval needed) — `_handle_mid_email()` added
- LOW: silent ignore
- No keywords. LLM decides importance on every email.

**iMessage — Pushcut DISABLED, Mac AppleScript primary**
- Decision: Om doesn't keep phone charging → Pushcut Automation Server dies → useless
- `PUSHCUT_URL` commented out in `.env` — Pushcut NOT used for sending
- Mac stays open (pmset `sleep 0` + `disksleep 0` + `displaysleep 0` set — battery drains when closed, acceptable)
- `send_imessage()` now goes direct to AppleScript. No Pushcut fallback needed.
- iMessage only works when Mac is open. That's the accepted trade-off.

**WhatsApp — incoming message listener added**
- `client.on("message")` added to `truman/integrations/whatsapp_bridge.js`
- Skips: `msg.fromMe`, `status@broadcast`, empty body
- Forwards to `${RAILWAY_URL}/api/boss_message` with `{from, text, source: "whatsapp", extra: {phone, is_group}}`
- Was outbound-only before. Now bidirectional.

**WA Bridge Railway deploy — Docker fix**
- Root cause of all Chromium failures: nixpacks installed `/usr/bin/chromium-browser` = snap proxy wrapper → crashes in containers
- Fix: `wa-bridge/Dockerfile` switched from `ghcr.io/puppeteer/puppeteer:latest` (2.7GB, slow pull) to `node:20-slim` + `apt-get install -y chromium`
- `CHROMIUM_PATH=/usr/bin/chromium` env var set in Dockerfile — whatsapp_bridge.js uses it directly
- `PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true` — skips puppeteer bundled download
- First attempt: `puppeteer/puppeteer:latest` image stuck 8+ min on Railway pull → swapped to slim
- `wa-bridge/railway.toml`: `builder = "dockerfile"`, `dockerfilePath = "Dockerfile"`, `healthcheckPath = "/health"`
- Build kicked via `railway up --service WA-Bridge` from `wa-bridge/` directory (force fresh, not cached redeploy)
- **Status at time of writing: build in progress. QR code scan pending.**

**nixpacks.toml (root)**
- `providers = ["python"]` — one line. Stops nixpacks from seeing root `package.json` and mixing Node into the Python Railway build.
- Was causing `ModuleNotFoundError: dotenv` on every Truman Railway deploy.

---

## Phase 15C — 3-Channel Automation (2026-05-04, commits `7d7d1a2`, `00ff1e7`, `35f160c`, `67ff34e`)

**Goal:** Auto-handle WhatsApp + iMessage + Gmail with Telegram approval flow. No Mac dependency for iMessage/Gmail. Three smart additions: per-contact style learning, quiet-hours queue, auto-trivial replies.

### Code shipped

- `truman/integrations/whatsapp_bridge.js` — Railway-ready: session at `/data/whatsapp-session`, listens on `0.0.0.0:$PORT`, `/health` endpoint, auto-detects Chromium path
- `truman/integrations/imessage_poller.py` — `send_imessage_pushcut()` added; `send_imessage()` tries Pushcut first then AppleScript fallback
- `truman/integrations/boss_handler.py` — full rewrite. Smart additions:
  - **Style learning (A):** `_draft_reply()` pulls last 50 approved replies *to that specific sender*, falls back to 10 generic
  - **Auto-trivial (F):** `_TRIVIAL_RE` regex matches "ok/got it/thanks/np/lol/👍/etc." — auto-sends without approval, silent Telegram log
  - **Quiet queue (C):** if `_in_quiet_hours()` (3am–8:50am), saves with status `queued` instead of pinging Telegram. `flush_quiet_queue()` called from proactive 60s tick when quiet hours end
- `truman/storage/db.py` — `get_approved_boss_replies_for_sender()` + `get_queued_boss_messages()` helpers
- `truman/scheduling/proactive.py` — wired `flush_quiet_queue()` into 60s tick
- `truman/core/config.py` — `PUSHCUT_URL`, `WA_BRIDGE_URL`, `SERVICE_TYPE` env vars
- `start.sh` (NEW) — entry point routes to Truman OR WA bridge based on `SERVICE_TYPE` env
- `wa-bridge/` (NEW) — Railway worker subdirectory with `index.js` + `package.json` + `railway.toml`

### `.env` updated

```
PUSHCUT_URL=https://api.pushcut.io/oCUGVyryRGc94qiI8czWONzT/execute?shortcut=Send+iMessage
ENABLE_BOSS_FLOW=1
ENABLE_GMAIL_POLLING=1
ENABLE_IMESSAGE=1
```

Same vars also set on Railway Truman service via API. Plus `WA_BRIDGE_URL=http://wa-bridge.railway.internal:3099` and `GMAIL_ADDRESS=bhavyapandya005@gmail.com`.

### Pushcut iOS setup (DONE)

- Pushcut Pro **purchased** ($1.99/mo) — needed for Automation Server
- API key: `oCUGVyryRGc94qiI8czWONzT`
- iOS Shortcut `Send iMessage` created: takes `Shortcut Input` → splits by `|||` → sends Item 2 to Item 1, Show Compose Sheet OFF
- Endpoint format: `POST https://api.pushcut.io/v1/execute` with `API-Key` header, body `{"shortcut":"Send iMessage","input":"+1NUMBER|||text"}`
- Tested: 2 ✓ completed runs in Pushcut log. Works.

### WhatsApp on Railway — UNRESOLVED

- Created Railway service `WA-Bridge` (id `c9fc9b8f-9f1a-4d48-b2c3-dcf66e3f1b61`)
- Multiple deploys failed — Chromium issue. Nixpacks installed Chromium via apt → resolves to a snap wrapper that can't run in containers. Last attempt: let puppeteer use bundled Chromium (uncommitted change to `whatsapp_bridge.js` removing exec-path detection)
- **Decision: paused.** WhatsApp bridge stays on Mac (`node truman/integrations/whatsapp_bridge.js`) for now. Switch to Docker-based image or accept Mac-only WhatsApp.

### Pushcut 24/7 limitation — UNDECIDED

- iOS sandbox suspends Pushcut Automation Server when phone not on charger / not in screensaver mode
- Om's situation: rarely keeps phone plugged in → server will frequently die → curl will fail → Truman falls back to "copy manually" message in Telegram
- Mac AppleScript fallback in `send_imessage()` covers when Mac is on
- **Options Om has NOT decided yet:**
  1. Accept gaps + Mac fallback when Mac on
  2. Get a spare/old iPhone as dedicated Pushcut server (plug in at home, never touch)
  3. Switch to paid service (Sendblue ~$100/mo, LoopMessage similar) — too expensive
  4. Wait for `pypush` v3.0 (currently broken — sending removed during rewrite)
- $2/mo Pushcut Pro is NOT wasted — it's the cheapest cloud-iMessage path that exists
- Status: **Om has not committed to a 24/7 strategy yet**

### Gmail status

- `gmail_poller.py` already shipped from earlier. Polls `bhavyapandya005@gmail.com` every 15 min via IMAP. Filters by keyword list (interview, urgent, deadline, offer, etc.)
- Om has not received any Gmail Telegram pings yet — either no matching emails arrived or keyword list is too strict. To verify: `railway logs --service Truman | grep -i gmail`. If too strict, switch to LLM importance check (no keyword list)
- He has 10 Gmails — only this one is wired. Others: change `GMAIL_ADDRESS` env var + new app password

### Morning brief — confirmed working

Beth birthday-planning brief delivered May 3 9am ET via Telegram. Phase 4 (load_goals) + Phase 11 (email_digest) chain works.

### Next session resume points (archived — see 2026-05-04 for current state)

---

## 2026-05-04 — Multimodal Layers 2-8 + System hardening

**Commits: `0b7e423`, `f86214b`, `237d097`**

### 15D Verification ✅

- WA Bridge: **live and connected** on Railway. QR already scanned. Incoming messages arriving (tested by Keshav).
- Railway POOL_* vars: updated to NVIDIA-only (removed groq/glm-4.7/mistral-nemotron/deepseek stale refs — was causing ⚠️ spam in logs)
- Truman deploy: `railway up --service Truman --detach` triggered (commit `237d097`)

### Multimodal Layer 1 (already done, previous session)

- `loader.py` — images only, live bytes per turn
- `prompts.py` — iMessage hint + generic image hint
- `attach_ids` wired through state → loop → agent → nodes

### Multimodal Layer 2 — Full type matrix (`0b7e423`)

`truman/multimodal/loader.py` rewritten — `load_attachment(attach_id, page_hint=None)` returns unified dict:
- Images → `image_url` block + `kind="image"`
- PDF (text) → pdfplumber extract → markdown, `kind="pdf_text"`
- PDF (scanned, avg <50 chars/page) → PyMuPDF pages as PNG image blocks, `kind="pdf_scan"`
- DOCX → python-docx → markdown (headings + tables), `kind="docx"`
- XLSX → pandas → per-sheet markdown tables (max 5 sheets, 200 rows), `kind="xlsx"`
- CSV → pandas → markdown table, `kind="csv"`
- Code files (py/js/ts/go/rs/etc.) → fenced code block, `kind="code"`
- Plain text → inline, `kind="text"`
- `load_image_block()` kept for backward compat
- Added `pandas==2.2.3` + `tabulate==0.9.0` to requirements.txt

### Multimodal Layer 3 — Clean message builder (`0b7e423`)

`truman/multimodal/call.py` (NEW):
- `build_messages(system_content, chat_history, user_input, attach_ids, tool_result, tool_name, history_window=16)` — extracts message-building out of nodes.py
- `extract_page_hint(user_input)` — regex for "page 3" / "pg 5" / "p.3" → PDF page pin
- Routes: image/pdf_scan → image_url blocks; text types → inline text merged with user message
- `nodes.py call_llm` now calls `build_messages()` — old inline code replaced; fallback to plain text kept

### Multimodal Layer 4 — Sticky attachments (`f86214b`)

`truman/multimodal/session_state.py` (NEW):
- Per-session sticky store (in-process, TTL=10 turns)
- `register_attachments(session_id, attach_ids)` — fresh upload → add to store
- `get_sticky_ids(session_id)` — return active ids
- `tick_turn(session_id)` — called after each LLM response, decrements TTL
- `reset_ttl(session_id)` — "look again" → reset to 10
- `clear_attachments(session_id, kind)` — "drop file" / "drop image" / "drop all"
- `process_commands(session_id, user_input)` — detects natural language drop/reset commands
- `orb.py api_chat` wired: register → merge sticky → tick after response → `attachments[]` in response JSON
- 2 new endpoints: `GET /api/attachments/session/<id>` + `POST /api/attachments/session/<id>/drop`

### Multimodal Layer 5 — Per-type system prompts (`0b7e423`)

`truman/multimodal/prompts.py` rewritten:
- `_BASE_ACCURACY` injected on every multimodal turn: "NEVER invent, hallucinate, or infer content not shown"
- Type-specific hints: image, iMessage, WhatsApp, pdf_text, pdf_scan, docx, xlsx, csv, code, text
- `_detect_kind(meta)` — auto-detects from filename + mime (iMessage → blue/gray bubble rules, WhatsApp → green/white rules)
- `get_system_injection_typed(metas)` — priority: imessage > whatsapp > pdf > xlsx > csv > docx > code > text > image
- Legacy `get_system_injection(attach_ids)` kept for Phase 1 compat

### Multimodal Layer 6 — Dashboard context tray (`237d097`)

`dashboard.html`:
- New `.context-tray` (purple chips, shown above input area)
- Each chip: file icon + filename + turns-left counter (e.g. "9t") + × button
- `_renderContextTray(attachments)` — updates tray from `d.attachments` in chat response
- `_dropContextChip(attachId)` — calls `/api/attachments/session/<id>/drop`

### Multimodal Layer 7 — PDF page-pin (`0b7e423`)

- `extract_page_hint(user_input)` in call.py detects "page 3" / "pg 5" / "p.3"
- `load_attachment(aid, page_hint=N)` pins to that single page (pdfplumber or PyMuPDF)
- Wired in `build_messages()` — runs automatically on every multimodal turn

### Multimodal Layer 8 — Multi-image verified (`237d097`)

- Verified by logic test: 2 image_url blocks + 1 text block in one HumanMessage
- Mixed image + PDF: image blocks + PDF text merged into final text block — correct

### Key anti-hallucination improvements

- Base accuracy anchor on every multimodal turn (explicit "never invent" instruction)
- Per-type prompts (iMessage bubble direction, PDF truncation notice, spreadsheet column names)
- Live bytes every turn (no stale "describe once" cache)
- Sticky context prevents model losing file between questions

### Current system state

- Railway: Truman service deploying `237d097`, WA-Bridge connected
- POOL vars: all NVIDIA-only, warning spam eliminated
- Multimodal: all 8 layers live
- iMessage: Mac AppleScript primary, Pushcut Pro purchased + working as backup
- Gmail: polling `bhavyapandya005@gmail.com`, LLM triage 3-tier (HIGH/MID/LOW)
- WhatsApp: Railway WA-Bridge connected, bidirectional

### 2026-05-04 (continued) — Bug fixes + privacy + WA volume

**Commits: `9d3229c`, `1ea46b9`, `5c9b070`**

**Bug fixes:**
- `latin-1` header crash: iPhone filenames with ` ` (narrow no-break space before AM/PM) in Content-Disposition header — sanitized to latin-1
- Telegram Markdown crash: LLM draft replies with unmatched backticks/asterisks silently killed button feedback — now retries as plain text
- All boss_handler notifications stripped of Markdown to prevent recurrence
- WA button silent failure: was bridge QR_PENDING + Markdown crash combo. `_send_fail_reason()` added — now tells Om exactly why + gives QR URL

**Gmail flood fix:**
- Dropped MID tier entirely (was causing 80+ daily pings)
- HIGH now requires: real human + specific question at Om + negative consequence if ignored
- Default LOW on LLM failure (never flood on error)
- Daily cap: 5/day (`GMAIL_DAILY_CAP` env var). `ENABLE_GMAIL_POLLING=0` on Railway (off until Om re-enables)

**WA Bridge volume:**
- Root cause of repeated QR: no persistent volume on WA-Bridge service
- Created `wa-bridge-volume` (5GB) mounted at `/data` on WA-Bridge
- Session now persists across deploys — scan once, done forever
- Om needs to scan QR at: `https://wa-bridge-production-7be4.up.railway.app/qr`

**Privacy / storage:**
- LangSmith OFF: `LANGCHAIN_TRACING_V2=false` (was sending all LLM calls to LangChain servers)
- Mem0 kept — but `mem_search`/`mem_add`/`_mem_add_smart` now fall through to local SQLite `user_facts` when `MEM0_API_KEY` unset
- `db.search_facts(query)` added — keyword search on user_facts (local Mem0 replacement)
- Rule: never remove Railway env vars or code without asking Om first

### Next

- Om scan WA Bridge QR then re-enable `ENABLE_GMAIL_POLLING=1` after testing
- Phase 16: Ambient Awareness (location triggers, Pushcut HTTP actions)

