# TRUMAN — Build Log
### Every decision, every file, every level. Logged as we go.

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