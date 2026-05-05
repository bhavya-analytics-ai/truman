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

## Multimodal System — 2026-05-05

### Phase 1 — Live image pipeline (DONE, commits `990a089`, `8f3deff`)

**What changed:**
- Deleted `_DOC_GROUNDING` template + grounding block from `/api/chat`
- Deleted describe-once maverick call from `/api/upload` — images now return `text: ""`, bytes stay live in DB
- New `truman/multimodal/loader.py` — attach_id → base64 image_url content block (images only for now)
- New `truman/multimodal/prompts.py` — type-specific system hints (iMessage, generic image). Auto-detects type from filename + mime.
- `attach_ids` wired through: `state.py` → `loop.py` → `agent.py` → `nodes.py call_llm`
- `_parse_multimodal_input()` in `orb.py` — extracts image attach_ids from `|attach:ID` markers, strips markers from user text, auto-sets pool to "vision"
- Vision pool upgraded: `llama-3.2-90b-vision → llama-4-scout → maverick`

**What this fixed:**
- "Look again" now works — image bytes re-sent to LLM, not a stale description
- iMessage speaker confusion fixed — proper system hint injected every turn
- No more hallucinated descriptions at upload time

---

### Phase 2 — Sticky attachments + smart send logic (PENDING — build next session)

**Goal:** Image stays in context across turns, not just the upload turn. Drops automatically when no longer needed. Tracks per-attachment.

#### Layer 4 — `truman/multimodal/session_state.py` (new file)

Per-session, per-attachment state. Lives in memory (dict), not SQLite.

```python
_live_attachments: dict[str, list] = {}
# shape: {session_id: [entry, ...]}

# entry shape:
{
    "attach_id":         str,
    "kind":              str,   # "image" | "pdf" | "docx" | "xlsx" | "text"
    "filename":          str,
    "turns_left":        int,   # starts at 10, decrements each turn
    "tokens_est":        int,   # rough token cost for UI display
    "last_used":         bool,  # did last LLM response reference this attachment
    "dependency_turns":  int,   # consecutive turns where last_used was True
}
```

**Functions to build:**
```python
def add_attachment(session_id, attach_id, kind, filename, tokens_est): ...
def get_live_attachments(session_id) -> list: ...   # returns entries where turns_left > 0
def should_send(entry, recent_messages: list) -> bool: ...
def tick_session(session_id, used_attach_ids: list): ...  # decrement + decay, called after each LLM call
def drop_attachment(session_id, attach_id): ...   # user taps X
def clear_session(session_id): ...   # "new topic" / "drop the file"
def reset_turns(session_id, attach_id): ...   # "look again" → turns_left = 10
```

**Send decision logic (per attachment):**
```python
def should_send(entry, recent_messages) -> bool:
    if entry["turns_left"] <= 0:
        return False
    if entry["turns_left"] > 2:      # recency: recent enough, always send
        return True
    if has_image_keywords(recent_messages):  # explicit intent
        return True
    if entry["last_used"]:           # implicit dependency
        return True
    return False

IMAGE_KEYWORDS = [
    "look", "see", "check", "what does", "read", "show",
    "screenshot", "image", "file", "this", "that", "it"
]
```

Note on "this"/"that": will have false positives but false positives only mean image stays in context (costs tokens, not correctness). Acceptable trade-off.

**Decay logic (runs inside tick_session after each turn):**
```python
for entry in attachments:
    entry["turns_left"] -= 1
    if attach_id in used_attach_ids:
        entry["last_used"] = True
        entry["dependency_turns"] += 1
        if entry["dependency_turns"] > 2:   # don't stick forever
            entry["last_used"] = False
            entry["dependency_turns"] = 0
    else:
        entry["last_used"] = False
        entry["dependency_turns"] = 0
```

**"Look again" / re-reference detection (in `_parse_multimodal_input` or `nodes.py`):**
```python
_REREF_RE = re.compile(
    r"\b(look again|check (the|this|that)|re.?read|go back|show me again|what does it say|refer back)\b", re.I
)
# if match + session has live attachments → reset_turns() for all entries
```

**Wiring:**
- `orb.py /api/upload` → call `add_attachment()` after DB save
- `nodes.py call_llm` → replace `state.get("attach_ids")` with `session_state.get_live_attachments(session_id)`, filter by `should_send()`
- After LLM call → `tick_session(session_id, used_attach_ids)` where `used_attach_ids` = attach_ids that were actually sent
- `orb.py` → add `GET /api/live_attachments?session_id=X` and `DELETE /api/live_attachments/<attach_id>` endpoints

#### Also pending in Phase 2

**4 quality improvements (to implement alongside session_state):**

1. **Hard gate on bad eval outputs** — `save_memory` node: explicit check `if eval_score == "bad": return {}` (don't store). Eval node already runs before save_memory in graph but no hard block inside save_memory itself yet.

2. **Multimodal usage log** — one line per turn: `[MULTIMODAL] session=X images=N reused=True/False sent=True/False`. Helps debug cost/latency spikes.

3. **image_ignored eval rule** — in `eval.py` rule check: if image was sent this turn AND response contains zero visual references → flag `IMAGE_IGNORED` issue. Catches vision silently failing when model falls back to training knowledge.

4. **`last_used` signal for eval** — evaluator sets `used_attach_ids` in state after checking response. `tick_session()` reads it to set `entry["last_used"]`. Closes the loop between eval and sticky attachments.

---

## Notes

- All changes fail-soft — every new node wrapped in try/except, never crashes chat
- All new features have ENABLE_* kill switches in config.py
- Deployed to Railway (agent-backend / Truman service) on 2026-05-05
