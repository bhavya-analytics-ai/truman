# Truman — Claude Session Instructions

## READ THESE FIRST (in order)

1. `UPGRADE_PLAN.md` — full architecture, all 17 phases, phase details, key files, env vars
2. `BUILD_LOG.md` — what shipped, when, what was fixed, commit hashes
3. `truman_master_pan.md` — original master plan (do NOT modify)

## Rules for this project

- Om = Om. Always call him Om, never "user".
- NIM = primary LLM for everything. OpenAI = voice only (STT/TTS). Never route text through OpenAI.
- Every new feature gets an env var kill switch before wiring into the graph.
- Every node in brain/nodes.py must fail soft (try/except → node_errors, never crash chat).
- Work on main branch directly. No co-author lines in commits.
- After any change: `git add <specific files>` + `git commit`. No deploy unless Om says deploy.
- No scope creep. Ask Om if something is out of phase.
- Do not touch `truman_master_pan.md`. Do not rewrite `README.md` without asking.

## Current state (as of 2026-04-26)

Phases 0-2 shipped. Railway is live. LangGraph active. Cognee active.
Next: Phase 3 — MCP skill library.

## Quick file map

```
truman/brain/loop.py         LangGraph StateGraph entry point
truman/brain/nodes.py        8 brain nodes
truman/brain/concepts.py     Cognee wrapper
truman/text/agent.py         LLM pools, fallback chain, tool detection
truman/storage/db.py         SQLite schema + helpers
truman/storage/reflect.py    Nightly reflection (2am launchd)
truman/voice/orb.py          Flask app + all API routes
truman/voice/static/dashboard.html  UI
truman/tools/all_tools.py    TOOLS list
truman/core/persona.py       SYSTEM prompt
```
