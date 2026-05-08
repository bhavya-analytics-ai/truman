# TRUMAN Smart Routing — Design Spec

**Date:** 2026-05-08
**Owner:** Om (Bhavya Pandya)
**Status:** Approved through brainstorming. Pending review before /plan.
**Repo:** `/Users/ompandya/Desktop/friday/truman`
**Production:** `https://truman-production.up.railway.app`
**Last shipped commit:** `018a4fe` (Phase 1 v2 — broken: 30s latency)

---

## Goal

One refactor that fixes everything broken in TRUMAN's brain so we don't touch this layer again. Three problems solved together:

1. **Wrong tool selection** at 40+ tools → semantic tool retrieval (top-K bind)
2. **All 12 nodes for every message** → 3-tier adaptive graph (trivial / normal / complex)
3. **Inconsistent latency** (silent legacy fallback) → tight exception handling + telemetry + canary deletion

Plus one big addition Om asked for:
4. **Self-awareness layer** — TRUMAN knows what he is, where he runs, what he can do every turn (like Claude does)

---

## Success Criteria (locked)

| Metric | Target |
|---|---|
| Trivial latency (`yo`, `2+2`) | <2s |
| Normal latency (most chat) | <8s |
| Complex latency (multi-tool, vision) | <15s |
| Tool selection accuracy | ≥93% on 30-msg test set |
| Fallback rate | <1% over 48h canary |
| Runtime self-awareness | "are you on Railway?" answered correctly always |
| Persona tone | Lowercase, direct, Om-matching, preserved |
| No data loss | `db.recent_turns(10)` unchanged |

---

## Architecture

### Current (broken)

12 nodes, all sequential, all run for every message:
```
mood → memory → goals → skills → pool → detect_tool → risk_gate
     → route_skill → execute_tool → call_llm → eval → save_memory
```

`detect_tool` (regex) pre-executes a tool. `call_llm` then `bind_tools(ALL_36_TOOLS)`. Result: double tool calls, 30s latency, wrong tool picks. LangGraph→legacy fallback fires silently on any exception → inconsistent latency.

### New — 3-tier adaptive graph

```
START
  │
  ▼
tier_router (NEW)  ← regex first; tiny LLM if regex unsure
  │   returns RoutingDecision: {tier, pool, runtime, hints, skip_llm_eval}
  │
  ├─ tier=TRIVIAL ─► classify_mood → self_awareness → call_llm → save_memory
  │                  (5 nodes, target <2s)
  │
  ├─ tier=NORMAL ──► classify_mood → load_memory → self_awareness
  │                → tool_retrieval → call_llm(bind_tools) → [risk_gate
  │                → execute_tool] → eval(rule) → save_memory
  │                  (9 nodes, target <8s)
  │
  └─ tier=COMPLEX ─► all of normal + load_goals + recall_skills
                   → eval(rule + LLM) + tool chain support
                     (12 nodes, target <15s)
```

### Key topology changes

- `detect_tool` (regex tool exec) → DELETED
- `route_skill` (MCP dispatch) → DELETED (MCP tools become normal tools via retrieval)
- `detect_pool` → folded into `tier_router`
- `risk_gate` → moved to AFTER `call_llm` (inspects LLM's choice, not regex)
- `tier_router` → NEW first node
- `self_awareness` → NEW node before `call_llm`
- `tool_retrieval` → NEW node before `call_llm`
- `_extract_arg()` heuristics → DELETED (LLM extracts args via bind_tools)

Net: 4 nodes/functions removed, 3 added. Graph is smaller and adaptive.

---

## Module Structure

### New files (4)

| File | Lines | Purpose |
|---|---|---|
| `truman/core/runtime.py` | ~50 | `is_railway()`, `is_local()`, `db_location()`, `mac_bridge_status()`, `runtime_summary()` |
| `truman/brain/tool_retrieval.py` | ~150 | `init_tool_embeddings()`, `retrieve(msg, tier, pool, k)` |
| `truman/brain/self_awareness.py` | ~200 | `build_self_state()`, `derive_capabilities()`, `render_system_prompt()` |
| `truman/brain/tier_router.py` | ~120 | `classify_tier(msg) → RoutingDecision`. Regex first, LLM fallback. |

### Modified files

| File | Change |
|---|---|
| `truman/brain/loop.py` | Add 3 new nodes, conditional tier-edges, drop deleted nodes |
| `truman/brain/nodes.py` | Refactor `call_llm` (retrieval + dynamic prompt), refactor `risk_gate` (post-LLM), drop `detect_tool`/`route_skill` |
| `truman/brain/state.py` | Add fields: `routing: dict`, `self_state: dict`, `retrieved_tools: list`, `llm_tool_calls: list` |
| `truman/text/agent.py` | Tighten fallback exception (allow-list of transient errors), add `log_fallback_event()` |
| `truman/core/persona.py` | Move `IDENTITY_TEXT` + `PERSONA_ANCHOR` constants to `self_awareness.py`. persona.py keeps dynamic persona_rules from db only. |
| `truman/storage/db.py` | New table `tool_embeddings` (additive migration) |
| `truman/voice/orb.py` | Add `/api/control/fallback-stats`, `/api/control/node-errors` endpoints |
| `truman/voice/static/dashboard.html` | New Control Panel tabs: Fallbacks, Node Errors |

### Deleted (after canary)

- `_run_legacy()`, `_call_llm()`, `_call_llm_with_tools()` in `agent.py` (~170 lines)
- `_detect_tool()`, `_extract_arg()` in `agent.py` (~110 lines)
- `route_skill` node in `nodes.py`
- Static SYSTEM string in `persona.py` (becomes constants in `self_awareness.py`)

---

## Component Details

### 1. Tier Router (`tier_router.py`)

```python
def classify_tier(message: str, image_count: int = 0) -> RoutingDecision:
    # 1. Image present → vision pool, complex tier
    # 2. Regex check trivial patterns (greetings, simple math, "thanks")
    # 3. Regex check complex patterns (multi-step keywords, code keywords + question, "and then")
    # 4. Default → normal
    # 5. If ambiguous (no clear match) → tiny LLM call (llama-3.1-8b, temp=0, 1-token)

@dataclass
class RoutingDecision:
    tier:    Literal["trivial", "normal", "complex"]
    pool:    Literal["general", "coding", "reasoning", "agentic", "vision", "docs"]
    runtime: Literal["railway", "local"]
    hints:   list[str]      # reasons for tier classification
    skip_llm_eval: bool     # always True for trivial
```

Pool detection logic from current `detect_pool_with_reason()` is preserved.

### 2. Tool Retrieval (`tool_retrieval.py`)

```python
_TOOL_VECTORS: dict[str, list[float]] = {}   # tool_name → embedding

def init_tool_embeddings(all_tools, mcp_tools):
    """Boot-time: embed all tool descriptions via NVIDIA NIM nv-embed-v1.
    Persist to SQLite tool_embeddings table for cold-start cache.
    Hash-check description on boot — only re-embed if changed."""

def retrieve(message: str, tier: str, pool: str, k: int = None) -> list[Tool]:
    """Per-turn: cosine similarity, top-K, threshold filter (0.3),
    pool boost (+0.2 to relevant tools)."""
```

K per tier: trivial=0, normal=5, complex=12. Pool boosts: coding→gitnexus__*, mac files; docs→read_mac_file, gitnexus__context; agentic→all MCP.

### 3. Self-Awareness (`self_awareness.py`)

```python
def build_self_state(state: TrumanState) -> dict:
    return {
        "identity":        IDENTITY_TEXT,        # constant
        "runtime":         runtime_summary(),    # from runtime.py
        "environment":     {"date": ..., "time": ..., "tz": ...},
        "tool_inventory":  state["retrieved_tools"],
        "capabilities":    derive_capabilities(runtime, tools),
        "current_state":   {"facts_count": ..., "active_goals": [...], "last_topic": ...},
        "operating_mode":  state["routing"]["tier"],
        "persona_anchor":  PERSONA_ANCHOR,       # constant
    }

def render_system_prompt(self_state: dict, memory_block: str) -> str:
    """Compose: WHO I AM / WHERE / RIGHT NOW / WHAT I CAN ACCESS /
    WHAT I KNOW ABOUT OM / OPERATING MODE / HOW TO RESPOND"""

def derive_capabilities(runtime, tools) -> dict:
    """Returns {"can": [...], "cant": [...]}.
    Runtime-aware: local→Mac access; railway→bridge-mediated or none."""
```

Replaces static `persona.py` SYSTEM string with dynamic per-turn prompt.

### 4. Risk Gate Refactor (in `nodes.py`)

Moves to AFTER `call_llm`:

```python
def risk_gate_node(state):
    tool_calls = state.get("llm_tool_calls", [])
    for tc in tool_calls:
        tier = risk.tier_for(tc["name"])
        if tier == "risky":
            db.save_pending_action(tc["name"], tc["args"], state["user_input"])
            state["response"] = f"want me to {action_summary(tc)}? confirm with 'yes'."
            state["awaiting_confirm"] = True
            return state
        # safe/caution → fall through to execute_tool
    return state
```

Reuses existing `db.save_pending_action`, `db.get_pending_action`, `db.clear_pending_action`. No new schema.

### 5. Fallback Hardening (in `agent.py`)

```python
TRANSIENT_ERRORS = (
    httpx.TimeoutException, httpx.ConnectError,
    openai.APIConnectionError, openai.RateLimitError,
    GraphRecursionError,
)

try:
    result = lg_run(...)
except TRANSIENT_ERRORS as e:
    log_fallback_event(reason="transient", exception_type=type(e).__name__)
    result = _run_legacy(...)
except Exception as e:
    log_fallback_event(reason="bug", ...)
    raise   # surface real bugs, no silent fallback
```

Telemetry to existing `events` table with `kind="langgraph_fallback"`. Surfaced in Control Panel.

---

## State Schema Changes

`truman/brain/state.py` adds fields:
```python
routing:          dict      # RoutingDecision from tier_router
self_state:       dict      # built by self_awareness node
retrieved_tools:  list      # top-K from tool_retrieval
llm_tool_calls:   list      # what the LLM picked, inspected by risk_gate
```

All optional (default empty/None). No breaking changes to existing fields.

---

## SQLite Schema Changes

```sql
CREATE TABLE IF NOT EXISTS tool_embeddings (
    tool_name    TEXT PRIMARY KEY,
    description  TEXT NOT NULL,
    desc_hash    TEXT NOT NULL,            -- to skip re-embed if unchanged
    vector       BLOB NOT NULL,            -- pickled list[float]
    embedded_at  TEXT NOT NULL
);
```

Additive only. No existing tables touched.

---

## Failure Modes & Safety Nets

| Failure | Behavior | Safety net |
|---|---|---|
| NVIDIA embed API down | retrieve returns ALL tools | LLM gets full set (current behavior) |
| Embedding cache corrupt | re-embed all on boot | +2s boot, no runtime impact |
| Top-K all below threshold | fall back to core set (web_search, recall, list_models) | LLM gets 3 default tools |
| `tier_router` crashes | default to NORMAL tier | Safest middle ground |
| `self_awareness` crashes | fall back to static persona.py | Persona always preserved |
| `risk_gate` post-LLM crashes | block tool execution + log to node_errors | Safer than executing unchecked |
| `pending_action` save fails | block execution, reply "system error, try again" | No risky tool runs without confirm |
| Network timeout to NIM | fallback fires once, telemetry logged | Transient errors handled gracefully |
| Bug in load_memory (KeyError) | error surfaces to user, NO silent fallback | Real bugs visible |
| Pending action expires (>5min) | auto-cleared; "yes" treated as new msg | Predictable timeout |

**Worst case for any new component:** falls back to current behavior. Cannot make things worse than today.

---

## Build Sequence (5 phases)

### Phase A — Foundation modules
A1. `runtime.py` + tests
A2. `tool_retrieval.py` + tests
A3. `self_awareness.py` + tests
A4. `tier_router.py` + tests
A5. `tool_embeddings` SQLite migration

**Gate:** all unit tests green, local boot unchanged.

### Phase B — Graph surgery
B1. Add `tier_router` to loop.py
B2. Add `self_awareness` after `load_memory`
B3. Refactor `call_llm` (retrieval + dynamic prompt)
B4. Move `risk_gate` to AFTER `call_llm`
B5. Add tier-conditional edges (3 lanes)
B6. DELETE `_detect_tool` regex execution
B7. DELETE `route_skill` node
B8. Tighten fallback exception in `agent.py`

**Gate:** local boot clean, 5/9/12 tier paths work, no node_errors on normal turns.

### Phase C — Verification suite
- 30-msg tool selection accuracy (≥93%)
- Latency benchmarks (3 trivial, 2 normal, 2 complex, all 3x medians under target)
- Self-awareness tests (8 cases, both runtimes)
- Risk gate tests (8 cases)
- No regressions (last 10 turns + memory hierarchy + persona + multimodal)

**Gate:** all 5 test sets green. Verify output saved + Om approves before push.

### Phase D — Ship + 48h canary
- Show diff to Om
- Push, watch deploy (60-120s)
- Smoke test on Railway
- Monitor 48h: fallback rate <1%, node errors <5/hr, latency targets met
- Auto-rollback if breached (`git revert + push`)

### Phase E — Cleanup (after canary)
- Banner appears in Control Panel
- Om approves manually
- Delete `_run_legacy()`, `_call_llm()`, `_call_llm_with_tools()`, `_detect_tool()`, `_extract_arg()` (~280 lines)
- Final cleanup commit

---

## Timeline

| Phase | Time |
|---|---|
| A — Foundation modules | 1.5 days |
| B — Graph surgery | 2 days |
| C — Verification suite | 1 day |
| D — Ship + canary | 2 days (mostly waiting) |
| E — Cleanup | 30 min |
| **Total** | **~1 week** |

---

## What Stays Untouched

- `truman.db` (1000+ turns of history)
- `.gitnexus/` index folder
- Mem0 cloud
- Railway DB
- Memory hierarchy in `resolve_memory()` (just nested into new dynamic prompt)
- All 23 native tools and 13 MCP tools (descriptions, execution logic — same)
- Phase 5 evaluator (rule layer + conditional LLM eval) — just gated by tier now
- SSE dashboard, multimodal pipeline, voice path, Telegram/WA/Gmail integrations

---

## Out of Scope

- Ruflo orchestrator (future Phase 5+)
- web_intel module (separate spec)
- Adding new tools (use existing)
- New MCP servers (use existing)
- Voice path refactor (separate concern)
- Memory hierarchy redesign (already enforced correctly)

---

## Open Questions / Deferred

- Risk re-route through gate for LLM-picked risky tools: handled by post-LLM risk_gate (Section 4). Resolved.
- Railway gitnexus install: separate Phase 1.5 ticket. Not in this spec.
- Tool count consolidation (23 → 15 by grouping): deferred. Tool retrieval makes count irrelevant.

---

## References

- Audit: `/Users/ompandya/Desktop/AgentResearch/AgentResearch/System Design/TRUMAN_AUDIT_FULL.md`
- Handoff: `/Users/ompandya/Desktop/friday/TRUMAN_CLEANUP_HANDOFF.md`
- Superpowers handoff: `/Users/ompandya/Desktop/AgentResearch/AgentResearch/System Design/SUPERPOWERS_HANDOFF.md`
- Last broken commit: `018a4fe`
- Last known-good baseline: `5237e82` (before Phase 1 attempts)
