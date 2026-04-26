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

### Known Deploy Issue
- Local repo has NO git remote and Railway CLI is logged out
- Om must run `railway login` then `railway up` to deploy these commits
- All 4 commits (030aa9a → c62c335) are local only

### Verified on Railway (Phase 0-2 baseline)
- Time shows correctly: "Sunday, Apr 26 2026, 12:17 PM ET"
- /health endpoint clean
- LangGraph path active (ENABLE_LANGGRAPH=1)
- Cognee active (ENABLE_COGNEE=1)

---

1. PWA (30 min work, easiest)
Add a manifest file → Chrome shows "Install Truman" button → becomes its own app icon in your dock. Runs in its own window, no browser tab needed. Can launch on Mac startup. Still uses WebRTC AEC underneath. Same code we're about to write.

2. Electron wrapper (few hours)
Wrap the orb in a native Mac app. Looks like a regular Mac app, lives in dock or menu bar. Best UX, feels like a real desktop app. Same WebRTC AEC inside.

3. Menu bar app (advanced)
Tiny icon in your Mac menu bar (top-right). Click it → starts session. Hidden Chromium does the audio. Cleanest UX possible — Truman lives in your menu bar always, no window at all.