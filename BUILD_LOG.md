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
