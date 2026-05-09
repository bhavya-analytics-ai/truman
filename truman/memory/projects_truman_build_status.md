---
name: Truman Build Status & Roadmap
description: Current phase, shipped features, key files, pool config, brain loop. START HERE for Truman work.
type: project
originSessionId: ba0792a2-851f-460c-95aa-aa8256112e95
---
# Truman — Build Status & Roadmap

**Last updated:** 2026-05-05
**Repo:** `/Users/ompandya/Desktop/friday/` | Railway project: `agent-backend`, service: `Truman`
**Deploy:** `railway service truman && railway up` from project root
**Status:** Cleaning phases 1–5 done locally. Deployed to Railway 2026-05-05.

---

## Cleaning Session (2026-05-05) — what actually changed

Previously the codebase had accumulated dead code, random model selection, and no self-evaluation. This session cleaned all of it.

**Cleaning Phase 1 (commit `99c3b54`):** Defined core loop north star, CORE/SUPPORT node map, startup reorder.

**Cleaning Phase 2 (commit `b04d26c`):** Killed dead features.
- Deleted: `concept_lookup` node, `curiosity` node, `concepts.py` (Cognee)
- Deleted: `concept_search` tool, `concept_ingest` tool, `pipeline_mode` tool
- Deleted: `scheduler.py`, `seed_memory.py`
- Cleaned: `risk.py`, `config.py` (ENABLE_COGNEE/ENABLE_CURIOSITY), `agent.py`
- Result: 13→11 nodes, 26→23 tools, ~1-2s faster per message

**Cleaning Phase 3 (commit `a0e4cf1`):** Memory unification.
- New file: `truman/brain/memory.py` — `resolve_memory()` + `build_memory_prompt()`
- Hierarchy enforced: facts → goals → persona_rules (logs NEVER decision authority)
- `call_llm` now uses `resolve_memory()` — single source of truth for context
- Dead `curiosity_ctx` refs removed from nodes.py

**Cleaning Phase 4 (commit `5a61559`):** Stabilized model routing.
- 9 pools → 6 pools, 1 primary + 1 fallback each (no randomness)
- New `detect_pool_with_reason()` — strict priority chain, first match wins, no scoring
- Retry logic: primary 6s → retry primary 3s → fallback 10s
- Structured logs: `[ROUTING] pool= reason= matched=` + `[MODEL] status= fail_reason= latency=`
- Mode hints for GENERAL pool (creative/structured, one line, never overrides persona)
- `ENABLE_EVAL` kill switch added

**Cleaning Phase 5 (commit `3634445`):** Hybrid evaluation layer.
- New file: `truman/brain/eval.py` — rule check → conditional LLM eval
- 5 rule checks: EMPTY_SHORT, HALLUCINATED_BRACKET, TOOL_IGNORED (soft token), GENERIC_RESPONSE, FACT_ANCHOR_MISMATCH (context-bound only)
- LLM eval: llama-3.1-8b, json mode, only fires when rules flag something
- Retry on BAD only, one max, non-cumulative hint injection
- Weak outputs logged as `eval_weak` events (model/pool/issues)
- Graph: `call_llm → evaluate_output → save_memory` (bad drafts never saved)
- `ENABLE_EVAL=1` kill switch

---

## Pool Config (6 pools, NVIDIA NIM only)

```
general:   llama-3.3-70b-instruct      → llama-3.1-8b-instruct
coding:    qwen3-coder-480b-a35b       → kimi-k2-instruct
reasoning: kimi-k2-thinking            → llama-3.3-70b-instruct
agentic:   qwen3-coder-480b-a35b       → kimi-k2-instruct
vision:    llama-3.2-90b-vision        → llama-4-scout-17b-16e
docs:      llama-4-maverick-17b-128e   → llama-3.3-70b-instruct
```

Router priority chain (first match wins, no scoring):
1. has_image → vision
2. tool_detected → agentic
3. is_doc_request (pdf/docx/excel) → docs
4. is_pure_code_request (action verbs + code fence) → coding
5. is_reasoning_or_explain + mentions_code_context → coding
6. is_reasoning_or_explain → reasoning
7. mentions_code_context alone (raw stack trace) → coding
8. default → general

NEVER USE: deepseek-v3.2, glm-4.7, mistral-nemotron, nemotron-nano (dead/unreliable)

---

## Brain Loop (12 nodes, all fail-soft)

```
classify_mood → load_memory → load_goals → detect_pool → detect_tool
→ risk_gate → route_skill → execute_tool → call_llm
→ evaluate_output → save_memory → [emit_event]
```

CORE nodes: classify_mood, detect_pool, detect_tool, risk_gate, route_skill, execute_tool, call_llm, evaluate_output, save_memory
SUPPORT nodes: load_memory, load_goals (enrich reply, fail soft, never block loop)

---

## Key Files

| File | Role |
|---|---|
| `truman/brain/loop.py` | LangGraph StateGraph — 12 nodes |
| `truman/brain/nodes.py` | All 12 brain nodes (fail-soft, trace instrumented) |
| `truman/brain/state.py` | TrumanState TypedDict (incl. eval_score/issues/action/type) |
| `truman/brain/memory.py` | resolve_memory() + build_memory_prompt() — single source of truth |
| `truman/brain/eval.py` | Hybrid evaluator — rule check + conditional LLM + retry |
| `truman/core/config.py` | 6 POOL_* vars, all ENABLE_* defaults, ENABLE_EVAL=1 |
| `truman/core/model_router.py` | detect_pool_with_reason(), run_with_pool() with retry logic |
| `truman/core/persona.py` | SYSTEM prompt |
| `truman/core/risk.py` | Risk tier dict (safe/caution/risky) |
| `truman/text/agent.py` | Keyword detection, tool execution, Mem0, tool cache |
| `truman/voice/orb.py` | Flask app + all API routes |
| `truman/voice/static/dashboard.html` | UI |
| `truman/tools/all_tools.py` | 23 tools |
| `truman/storage/db.py` | SQLite schema + helpers |
| `truman/storage/notifications.py` | push_trace(), push_turn(), SSE |
| `truman/storage/reflect.py` | Nightly reflection |
| `truman/scheduling/proactive.py` | Morning brief, idle nudge, proactive push |
| `truman/delivery/telegram.py` | Telegram bot |
| `truman/delivery/web_push.py` | VAPID, pywebpush |
| `truman/multimodal/` | Full 8-layer multimodal pipeline (loader, call, session_state, prompts) |

---

## Cleaning Session (2026-05-05) — Phase 6 (commit `d46af46`)

**Cleaning Phase 6:** Control Panel — single tab inside existing dashboard.html.
- 6 new API endpoints in `orb.py`: `/api/control/flags` (GET+PATCH), `/api/control/pools`, `/api/control/eval`, `/api/control/storage`, `/api/control/status`
- Dashboard: "control" button (teal) in header → 440px slide-in panel, 4 tabs
- **Flags tab**: toggle any of 18 ENABLE_* at runtime (os.environ + user_prefs, no restart)
- **Pools tab**: 6 pools with primary/fallback + full router priority chain
- **Eval tab**: good/weak/bad distribution, per-pool breakdown, recent bad/weak rows
- **Storage tab**: all SQLite table row counts + DB size
- Auto-refresh every 30s, lazy load per tab, manual refresh button

## Pending / Next

- **Deploy Phase 6:** `railway service truman && railway up`
- **Railway:** Phases 1-5 deployed 2026-05-05. Phase 6 committed locally, pending deploy.
- **RESEND_API_KEY** still needed for morning brief email.
- **Phase 7 (cleaning):** not yet planned

## How to Resume Cold

1. Read this file + `BUILD_LOG.md`
2. Deploy: `railway service truman && railway up`
3. Kill switches all in `truman/core/config.py` — all default to 1 (on)
4. Pools configurable via Railway env vars (POOL_GENERAL etc)
