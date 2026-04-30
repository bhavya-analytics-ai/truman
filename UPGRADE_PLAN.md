# TRUMAN — Upgrade Plan (Friday-Level AI OS)

> READ THIS FIRST in every new Claude session. Then read BUILD_LOG.md.

---

## VISION

Truman is not a chatbot. It's a Friday-level AI operating system:
- Knows Om's projects, preferences, calendar, goals
- Runs tools autonomously — searches, builds, deploys, files
- Learns continuously — every convo is reflected on and compressed into memory
- Always-on on Railway (cloud brain), Mac bridge for local actions
- Voice: browser WebRTC mic → Whisper → LLM → TTS
- Models: NVIDIA NIM free tier (primary), Groq (fallback). OpenAI = voice only.

---

## ARCHITECTURE (8-Layer Brain)

```
Sensors → Memory Load → Goal Check → Curiosity → Brain Loop → Risk Gate → Effectors → Experiment
```

Brain Loop = LangGraph StateGraph (nodes.py):
1. classify_mood
2. concept_lookup (Cognee graph)
3. load_memory (Mem0 facts)
4. detect_pool
5. detect_tool
6. execute_tool
7. call_llm
8. save_memory + emit_event

Memory Stack (5 tiers):
- Working: chat_history (in-RAM, 32 turns)
- Episodic: SQLite sessions + turns + summaries
- Semantic: Mem0 facts (durable, deduplicated)
- Procedural: Cognee concept graph (entity relationships)
- Conceptual: reflect.py nightly compression → next_day_priorities + decisions

---

## PHASE STATUS

| Phase | Name | Status | Commit |
|-------|------|--------|--------|
| 0 | Foundation — clock, memory schema, events drawer | ✅ Shipped | 6b62d6f |
| 1 | LangGraph brain loop | ✅ Shipped | de5b7a0 |
| 2 | Cognee concept graph | ✅ Shipped | 85e5ace |
| 2.1 | NIM embeddings + timezone fix + reflect.py fix | ✅ Shipped | 972ccf4 |
| 3   | Skills (files/web/github), kill switch, Groq removed | ✅ Shipped | 030aa9a |
| 3.1 | Repo index, list_repos, per-repo Cognee scoping | ✅ Shipped | c24a92b |
| 3.x | Skill priority fix, github async, persona inventory | ✅ Shipped | 45e01c2 |
| 3.2 | Live progress tracking + completion toast + /api/tasks | ✅ Shipped | c62c335 |
| 4 | Goals + curiosity layer | ✅ Shipped | 5b3ec20 |
| 5 | Risk gate node | ✅ Shipped | 2fb9212 |
| 6 | Speed + truth + toasts + barge-in | ✅ Shipped | d26236e |
| 6.1 | Fast 8B primary + Mem0 skip + persona anti-fabricate | ✅ Shipped | 9b7692d |
| 7 | UI noise cut + sticky model lock | 🔜 Next | — |
| 8 | E2B code sandbox | ⬜ Planned | — |
| 7 | Screenpipe screen context | ⬜ Planned | — |
| 8 | Mac bridge (local actions) | ⬜ Planned | — |
| 9 | WhisperKit iOS mic | ⬜ Planned | — |
| 10 | Voice diarization (pyannote) | ⬜ Planned | — |
| 11 | Pipecat voice pipeline | ⬜ Planned | — |
| 12 | Project folder indexer | ⬜ Planned | — |
| 13 | GitHub repo ingestion | ⬜ Planned | — |
| 14 | Multi-session UI + model switcher | ⬜ Planned | — |
| 15 | Proactive push (goals → nudges) | ⬜ Planned | — |
| 16 | Cybersecurity hardening | ⬜ Planned | — |

---

## PHASE DETAILS

### Phase 3 — MCP Skill Library
- Standardize tools as MCP servers (Model Context Protocol)
- Skills: web search, file ops, GitHub, forex, calendar
- Each skill = separate process, hot-swappable
- Kill switch: ENABLE_MCP=1
- Files: truman/skills/ directory

### Phase 4 — Goals + Curiosity Layer
- goals table in SQLite: goal text, priority, deadline, status
- curiosity node: if Truman has idle time, searches for Om's goal-relevant info
- db.py additions: add_goal(), get_active_goals(), complete_goal()
- Inject top 3 active goals into system prompt

### Phase 5 — Risk Gate
- New LangGraph node between call_llm and effectors
- Checks: is this action destructive? does it touch prod? is it financial?
- Low risk → auto-execute. High risk → ask Om first.
- Config: RISK_THRESHOLD env var

### Phase 6 — E2B Code Sandbox
- E2B cloud sandbox for safe code execution
- Truman can write + run Python without touching Om's machine
- Tool: run_code(code: str) → stdout + stderr
- Kill switch: ENABLE_E2B=1

### Phase 7 — Screenpipe Screen Context
- Screenpipe captures what Om is looking at
- Feeds visual context into memory_context before call_llm
- Truman knows what app Om is in, what he's reading
- Kill switch: ENABLE_SCREENPIPE=1

### Phase 8 — Mac Bridge
- mac_bridge.py runs as daemon on Om's Mac
- WebSocket to Railway: receives commands, executes local actions
- Actions: open app, type text, run script, read clipboard, screenshot
- Already has bridge stub — just needs daemon auto-start (launchd plist)

### Phase 9 — WhisperKit iOS Mic
- Om speaks on iPhone → WhisperKit transcribes on-device → sends text to Railway
- No audio over network, privacy-first
- Companion iOS shortcut or app

### Phase 12 — Project Folder Indexer
- Index ~/Desktop/friday + other project dirs into Cognee
- Truman knows Om's entire codebase
- Re-index on file change (FSEvents watcher)

### Phase 13 — GitHub Repo Ingestion
- Give Truman a GitHub URL → it clones + ingests into Cognee
- Truman can answer questions about any repo Om points at
- Tool: ingest_repo(url: str)

### Phase 14 — Multi-Session UI + Model Switcher
- Dashboard: sidebar with session list, new chat button
- Old sessions slide down as new ones come in
- Bottom bar: model selector + active agent indicator
- Current UI: orb + single chat. New: full session management

---

## GUARDRAILS

- Every node fails soft → logs to node_errors, never crashes chat
- All new features behind env var kill switches
- NVIDIA NIM for everything except voice (OpenAI = STT/TTS only)
- No RAG — Mem0 + Cognee is smarter
- Deploy = Railway push only. No manual file edits on prod.
- reflect.py runs nightly at 2am via launchd — feeds Mem0 + summaries

---

## KEY FILES

```
truman/brain/loop.py        — LangGraph StateGraph, run() entry point
truman/brain/nodes.py       — all 8 brain nodes
truman/brain/state.py       — TrumanState TypedDict
truman/brain/concepts.py    — Cognee wrapper
truman/text/agent.py        — LLM pools, tool detection, fallback chain
truman/core/model_router.py — pool → model mapping
truman/core/persona.py      — SYSTEM prompt
truman/storage/db.py        — SQLite schema + all helpers
truman/storage/reflect.py   — nightly reflection loop
truman/tools/all_tools.py   — TOOLS list
truman/voice/orb.py         — Flask app, all API routes
truman/voice/static/dashboard.html — UI
```

---

## ENV VARS (Railway)

```
ENABLE_LANGGRAPH=1      — use LangGraph brain (else legacy)
ENABLE_COGNEE=1         — use concept graph node
ENABLE_MCP=0            — MCP skills (not yet)
ENABLE_E2B=0            — code sandbox (not yet)
NVIDIA_API_KEY          — NIM free tier
OPENAI_API_KEY          — voice only (STT/TTS)
GROQ_API_KEY            — fallback LLM
MEM0_API_KEY            — episodic facts
```

---

## COST POLICY

- NVIDIA NIM: free (all text/vision inference)
- Groq: free tier fallback
- OpenAI: paid, voice only — no text inference
- Mem0: free tier
- Railway: $5/mo hobby plan
- E2B: free tier when added
- Cybersecurity: hold — costs money, add last
