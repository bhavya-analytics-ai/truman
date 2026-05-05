# REFACTOR_LOG.md — Truman Internal Cleanup

This file tracks internal refactors, cleanups, and infrastructure improvements.
Not features. Not new capabilities. Just making what exists cleaner, faster, and more reliable.

Separate from BUILD_LOG.md intentionally — BUILD_LOG is for product history, this is for engineering integrity.

---

## Cleaning Session — 2026-05-05

**Why:** Codebase had accumulated dead code (Cognee), random model selection (5 models in POOL_GENERAL = coin flip), no quality gate on outputs, and memory with no enforced priority. System worked but felt unpredictable.

**What shipped:**

### Phase 1 — Core loop definition (`99c3b54`)
- Added north star comment to loop.py defining what Truman actually is
- Mapped all nodes as CORE vs SUPPORT
- Reordered startup so context (memory, goals) loads before decisions (pool, tool)

### Phase 2 — Dead feature removal (`b04d26c`)
- Deleted `concept_lookup` node, `curiosity` node, `concepts.py` (Cognee integration)
- Deleted `concept_search`, `concept_ingest`, `pipeline_mode` tools
- Deleted `scheduler.py` (duplicate), `seed_memory.py` (one-off script)
- Cleaned `ENABLE_COGNEE` / `ENABLE_CURIOSITY` refs from config.py, risk.py, agent.py
- Result: 13 → 11 nodes, 26 → 23 tools, ~1-2s faster per message, zero Cognee calls

### Phase 3 — Memory unification (`a0e4cf1`)
- New file: `truman/brain/memory.py`
- `resolve_memory()` — single source of truth for all context reaching the LLM
- `build_memory_prompt()` — enforces insertion order: facts → mem0 → goals → persona rules
- Hierarchy: facts = ground truth, goals = intent, persona = constraints, logs = never decision authority
- Guardrails: goals filtered to active-only, persona_rules always a list never None
- `call_llm` now calls `resolve_memory()` instead of assembling context ad-hoc

### Phase 4 — Model routing stabilization (`5a61559`)
- 9 pools → 6 pools (removed POOL_CREATIVE, POOL_DESIGN, POOL_FAST)
- 1 primary + 1 fallback per pool — no randomness
- Pool assignments: general (llama-3.3-70b/8b), coding (qwen3-coder/kimi-k2), reasoning (kimi-k2-thinking/llama-3.3-70b), agentic (qwen3-coder/kimi-k2), vision (llama-3.2-90b/llama-4-scout), docs (llama-4-maverick/llama-3.3-70b)
- Replaced keyword scoring with `detect_pool_with_reason()` — strict priority chain, first match wins, no ties possible
- 5 detection functions: `_is_pure_code_request`, `_is_reasoning_or_explain`, `_mentions_code_context`, `_is_doc_request`
- Retry logic: primary (6s) → retry primary (3s) → fallback (10s)
- Structured logs every turn: `[ROUTING] pool= reason= matched=` + `[MODEL] status= fail_reason= latency=`
- Mode hints for GENERAL pool: one-line nudge for creative/doc requests
- Validated: 14/14 routing test cases correct before committing

### Phase 5 — Hybrid evaluation layer (`3634445`, `286797f`)
- New file: `truman/brain/eval.py`
- Rule check (instant): EMPTY_SHORT, HALLUCINATED_BRACKET, TOOL_IGNORED (soft token match), GENERIC_RESPONSE (hard fail only), FACT_ANCHOR_MISMATCH (context-bound, escalates only)
- LLM eval (conditional): llama-3.1-8b, json mode, only fires when rules flag something (~10-20% of messages)
- Score: good / weak / bad. Action: accept / retry
- Retry on BAD only — one max, non-cumulative hint injection, same pool
- eval result keyed by turn_id — async cannot mutate frozen result
- Graph rewired: `call_llm → evaluate_output → save_memory` (bad drafts never reach memory)
- `eval_log` SQLite table: per-turn scores, issues, model, pool, retry_fired, score_after
- `log_eval()` + `get_eval_summary()` helpers in db.py
- ENABLE_EVAL=1 kill switch

### Phase 6 — Control Panel (`d46af46`)
- New tab inside existing `dashboard.html` — no second dashboard, no new pages
- 6 new endpoints in `orb.py`: `/api/control/flags` (GET + PATCH), `/api/control/pools`, `/api/control/eval`, `/api/control/storage`, `/api/control/status`
- **Flags tab**: toggle any of 18 ENABLE_* at runtime (os.environ + user_prefs), no restart needed
- **Pools tab**: 6 pools with primary/fallback model names + full router priority chain (8 rules in order)
- **Eval tab**: good/weak/bad score distribution, per-pool breakdown, recent bad/weak rows
- **Storage tab**: all SQLite table row counts + DB file size in MB
- Auto-refresh every 30s while open, lazy load per tab switch, manual refresh button in footer
- Zero performance impact on chat — all endpoints are read-only queries, flag PATCH only hits env + user_prefs

---

## Notes

- All changes fail-soft — every new node wrapped in try/except, never crashes chat
- All new features have ENABLE_* kill switches in config.py
- Deployed to Railway (agent-backend / Truman service) on 2026-05-05
