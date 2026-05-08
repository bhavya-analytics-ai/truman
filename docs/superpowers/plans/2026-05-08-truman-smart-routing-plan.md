# TRUMAN Smart Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace TRUMAN's regex-based tool detection + always-bind-40-tools with a 3-tier adaptive graph (trivial/normal/complex), semantic tool retrieval (top-K), self-awareness layer, and tightened fallback handling — so the system is fast, correct, runtime-aware, and never has to be touched again.

**Architecture:** New `tier_router` first node returns `RoutingDecision`, conditional edges branch to 3 lanes. New `self_awareness` node builds dynamic system prompt per turn (identity + runtime + tools + capabilities). New `tool_retrieval` node binds only top-K tools (cosine similarity via NVIDIA NIM embeddings). Risk gate moves AFTER `call_llm` to inspect LLM-picked tools. Legacy fallback tightened with allow-list + telemetry; deleted after 48h zero-fallback canary.

**Tech Stack:** Python 3.13, LangGraph, NVIDIA NIM (kimi-k2-instruct, llama-3.3-70b-instruct, llama-3.1-8b-instruct, nv-embed-v1), SQLite (WAL mode), pytest.

**Spec:** `/Users/ompandya/Desktop/AgentResearch/AgentResearch/System Design/2026-05-08-truman-smart-routing-design.md`

**Branch strategy:** Work on `main` (Om's preference per CLAUDE.md). One commit per task. NEVER `git push` until Phase D explicit approval.

**Last broken commit (production):** `018a4fe` — "always bind_tools" (6x latency regression)
**Last known-good baseline:** `5237e82` — pre-Phase-1

---

## File Structure

### Files to CREATE

| Path | Purpose |
|---|---|
| `truman/core/runtime.py` | `is_railway()`, `is_local()`, `db_location()`, `mac_bridge_status()`, `runtime_summary()` |
| `truman/brain/tool_retrieval.py` | `init_tool_embeddings()`, `retrieve()` — semantic top-K binding |
| `truman/brain/self_awareness.py` | `build_self_state()`, `derive_capabilities()`, `render_system_prompt()` |
| `truman/brain/tier_router.py` | `classify_tier()` — regex first, LLM fallback |
| `tests/__init__.py` | Empty (pytest package marker) |
| `tests/conftest.py` | Pytest fixtures (DB tmp path, mocked NIM client) |
| `tests/test_runtime.py` | Tests for runtime.py |
| `tests/test_tool_retrieval.py` | Tests for tool_retrieval.py |
| `tests/test_self_awareness.py` | Tests for self_awareness.py |
| `tests/test_tier_router.py` | Tests for tier_router.py |
| `tests/test_risk_gate.py` | Tests for refactored risk_gate node |
| `tests/verify/tool_selection.json` | 30-message tool retrieval accuracy test set |
| `tests/verify/run_verify.py` | Verification runner (called by `/verify`) |
| `pytest.ini` | Pytest config |

### Files to MODIFY

| Path | Change |
|---|---|
| `truman/storage/db.py` | Add `tool_embeddings` table to `_SCHEMA` |
| `truman/brain/state.py` | Add 4 fields: `routing`, `self_state`, `retrieved_tools`, `llm_tool_calls` |
| `truman/brain/loop.py` | Add 3 new nodes, conditional tier-edges, drop deleted nodes |
| `truman/brain/nodes.py` | Refactor `call_llm` (retrieval + dynamic prompt), refactor `risk_gate` (post-LLM), drop `detect_tool`/`route_skill` nodes |
| `truman/text/agent.py` | Tight exception list in fallback handler, add `log_fallback_event()` |
| `truman/core/persona.py` | Move `IDENTITY_TEXT` + `PERSONA_ANCHOR` constants to self_awareness.py |
| `truman/main.py` | Add `init_tool_embeddings(TOOLS, MCP_TOOLS)` after MCP mount |
| `truman/main_cloud.py` | Same as main.py |
| `truman/voice/orb.py` | Add `/api/control/fallback-stats`, `/api/control/node-errors` endpoints |
| `truman/voice/static/dashboard.html` | New Control Panel tabs: Fallbacks, Node Errors |

### Files to DELETE (only after Phase D canary passes)

| Path | Lines |
|---|---|
| `_run_legacy()` in `truman/text/agent.py` | ~110 |
| `_call_llm()` in `truman/text/agent.py` | ~16 |
| `_call_llm_with_tools()` in `truman/text/agent.py` | ~45 |
| `_detect_tool()` in `truman/text/agent.py` | ~30 |
| `_extract_arg()` in `truman/text/agent.py` | ~80 |
| `_TOOL_PATTERNS` list in `truman/text/agent.py` | ~25 |
| Total | **~306 lines** |

---

## Setup Tasks (do these once before Phase A)

### Task S1: Pytest setup

**Files:**
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 2: Create empty `tests/__init__.py`**

```python
# package marker
```

- [ ] **Step 3: Create `tests/conftest.py`**

```python
import os
import sqlite3
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Isolated SQLite DB per test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("truman.storage.db.DB_PATH", db_path)
    from truman.storage import db as _db
    _db._initialized = False
    _db.init()
    yield db_path

@pytest.fixture
def mock_nim_embed(monkeypatch):
    """Mock NVIDIA NIM embedding API. Returns deterministic 8-dim vector."""
    def fake_embed(text):
        # Deterministic hash-based fake embedding
        import hashlib
        h = hashlib.md5(text.encode()).digest()
        return [b / 255.0 for b in h[:8]]
    monkeypatch.setattr("truman.brain.tool_retrieval._embed", fake_embed)
    return fake_embed

@pytest.fixture
def fake_railway(monkeypatch):
    """Pretend we're on Railway."""
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

@pytest.fixture
def fake_local(monkeypatch):
    """Pretend we're local."""
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
```

- [ ] **Step 4: Verify pytest collects**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest --collect-only 2>&1 | head -20
```
Expected: `collected 0 items` (no tests yet, but no errors).

- [ ] **Step 5: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add pytest.ini tests/__init__.py tests/conftest.py
git commit -m "Setup: pytest framework + fixtures for smart routing tests"
```

---

# Phase A — Foundation Modules (no graph touched)

### Task A1: SQLite migration — `tool_embeddings` table

**Files:**
- Modify: `truman/storage/db.py` (add to `_SCHEMA` string, around line 350)

- [ ] **Step 1: Read current schema location**

```bash
grep -n "_SCHEMA" /Users/ompandya/Desktop/friday/truman/storage/db.py | head -3
```
Expected: line numbers for `_SCHEMA = """` and the closing `"""`.

- [ ] **Step 2: Append table to `_SCHEMA`**

Find the line right before the `"""` that closes `_SCHEMA` and add:

```sql
CREATE TABLE IF NOT EXISTS tool_embeddings (
    tool_name    TEXT PRIMARY KEY,
    description  TEXT NOT NULL,
    desc_hash    TEXT NOT NULL,
    vector       BLOB NOT NULL,
    embedded_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_emb_hash ON tool_embeddings(desc_hash);
```

- [ ] **Step 3: Verify boot still succeeds**

```bash
cd /Users/ompandya/Desktop/friday && python -c "from truman.storage import db; db.init(); print('ok')"
```
Expected: `ok` (no errors).

- [ ] **Step 4: Verify table created**

```bash
sqlite3 /Users/ompandya/Desktop/friday/truman/truman.db ".schema tool_embeddings"
```
Expected: shows the CREATE TABLE statement.

- [ ] **Step 5: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/storage/db.py
git commit -m "Phase A1: add tool_embeddings table for retrieval cache"
```

---

### Task A2: `runtime.py` — runtime detection module

**Files:**
- Create: `truman/core/runtime.py`
- Create: `tests/test_runtime.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_runtime.py`:

```python
from truman.core import runtime

def test_is_railway_when_env_set(fake_railway):
    assert runtime.is_railway() is True
    assert runtime.is_local() is False

def test_is_local_when_env_unset(fake_local):
    assert runtime.is_railway() is False
    assert runtime.is_local() is True

def test_db_location_railway(fake_railway, monkeypatch):
    monkeypatch.setattr("os.path.isdir", lambda p: p == "/data")
    assert runtime.db_location() == "/data/truman.db"

def test_db_location_local(fake_local, monkeypatch):
    monkeypatch.setattr("os.path.isdir", lambda p: False)
    assert "truman.db" in runtime.db_location()
    assert "/data/" not in runtime.db_location()

def test_runtime_summary_returns_dict(fake_local):
    s = runtime.runtime_summary()
    assert "location" in s
    assert "db_path" in s
    assert "mac_bridge" in s
    assert s["location"] == "local"

def test_mac_bridge_status_offline_when_no_ws(monkeypatch):
    monkeypatch.setattr("truman.voice.orb._mac_ws", None, raising=False)
    assert runtime.mac_bridge_status() == "offline"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/test_runtime.py -v
```
Expected: FAIL — `ModuleNotFoundError: truman.core.runtime`.

- [ ] **Step 3: Implement `runtime.py`**

Create `truman/core/runtime.py`:

```python
"""runtime.py — TRUMAN's awareness of where he's running.

Single source of truth for environment detection.
Used by self_awareness.py to inject runtime context into every LLM call.
"""
import os
from typing import Literal


def is_railway() -> bool:
    """True if running on Railway (env var set by Railway runtime)."""
    return bool(os.environ.get("RAILWAY_ENVIRONMENT"))


def is_local() -> bool:
    """True if NOT on Railway (Mac/dev environment)."""
    return not is_railway()


def db_location() -> str:
    """Where the SQLite DB lives in this runtime."""
    if os.path.isdir("/data"):
        return "/data/truman.db"
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "truman.db",
    )


def mac_bridge_status() -> Literal["connected", "offline", "unknown"]:
    """Whether the Mac bridge WebSocket is currently connected."""
    try:
        from truman.voice import orb
        return "connected" if getattr(orb, "_mac_ws", None) else "offline"
    except Exception:
        return "unknown"


def runtime_summary() -> dict:
    """One-shot snapshot of runtime context for self_awareness."""
    return {
        "location":   "railway" if is_railway() else "local",
        "db_path":    db_location(),
        "mac_bridge": mac_bridge_status(),
    }
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/test_runtime.py -v
```
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/core/runtime.py tests/test_runtime.py
git commit -m "Phase A2: runtime.py + tests — TRUMAN knows where he's running"
```

---

### Task A3: `tool_retrieval.py` — semantic top-K binding

**Files:**
- Create: `truman/brain/tool_retrieval.py`
- Create: `tests/test_tool_retrieval.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tool_retrieval.py`:

```python
from unittest.mock import MagicMock
from truman.brain import tool_retrieval

def _make_tool(name, description):
    t = MagicMock()
    t.name = name
    t.description = description
    return t

def test_init_tool_embeddings_populates_dict(tmp_db, mock_nim_embed):
    tools = [
        _make_tool("get_weather", "Get current weather for a location"),
        _make_tool("set_reminder", "Schedule a reminder at a future time"),
    ]
    tool_retrieval.init_tool_embeddings(tools, [])
    assert "get_weather" in tool_retrieval._TOOL_VECTORS
    assert "set_reminder" in tool_retrieval._TOOL_VECTORS
    assert len(tool_retrieval._TOOL_VECTORS["get_weather"]) == 8

def test_retrieve_returns_topk(tmp_db, mock_nim_embed):
    tools = [
        _make_tool("get_weather", "Get current weather for a location"),
        _make_tool("set_reminder", "Schedule a reminder"),
        _make_tool("web_search", "Search the web for information"),
    ]
    tool_retrieval.init_tool_embeddings(tools, [])
    result = tool_retrieval.retrieve("what's the weather like", tier="normal", pool="general", k=2)
    assert len(result) == 2
    names = [t.name for t in result]
    assert all(n in {"get_weather", "set_reminder", "web_search"} for n in names)

def test_retrieve_trivial_returns_empty(tmp_db, mock_nim_embed):
    tools = [_make_tool("web_search", "Search the web")]
    tool_retrieval.init_tool_embeddings(tools, [])
    result = tool_retrieval.retrieve("yo", tier="trivial", pool="general")
    assert result == []

def test_retrieve_falls_back_to_all_tools_on_embed_failure(tmp_db, monkeypatch):
    tools = [_make_tool("a", "tool a"), _make_tool("b", "tool b")]
    tool_retrieval._TOOL_VECTORS.clear()
    tool_retrieval._ALL_TOOLS = tools  # populated by init normally
    def broken_embed(text):
        raise RuntimeError("NIM API down")
    monkeypatch.setattr(tool_retrieval, "_embed", broken_embed)
    result = tool_retrieval.retrieve("anything", tier="normal", pool="general")
    assert len(result) == 2  # all tools returned

def test_pool_boost_coding_pushes_gitnexus(tmp_db, mock_nim_embed):
    tools = [
        _make_tool("web_search", "Search the web"),
        _make_tool("gitnexus__query", "Query the codebase knowledge graph"),
    ]
    tool_retrieval.init_tool_embeddings(tools, [])
    result = tool_retrieval.retrieve("look up something", tier="complex", pool="coding", k=2)
    names = [t.name for t in result]
    assert "gitnexus__query" in names

def test_cosine_similarity_basic():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    assert abs(tool_retrieval._cosine(v1, v2) - 1.0) < 1e-6
    v3 = [0.0, 1.0, 0.0]
    assert abs(tool_retrieval._cosine(v1, v3)) < 1e-6
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/test_tool_retrieval.py -v
```
Expected: FAIL — `ModuleNotFoundError: truman.brain.tool_retrieval`.

- [ ] **Step 3: Implement `tool_retrieval.py`**

Create `truman/brain/tool_retrieval.py`:

```python
"""tool_retrieval.py — semantic top-K tool binding.

Replaces bind_tools(ALL_TOOLS) with bind_tools(retrieve(msg)).
At boot: embed every tool description (cached in SQLite).
Per turn: embed user message, cosine similarity, return top-K.
"""
import hashlib
import math
import pickle
import sqlite3
from typing import List
from truman.storage import db

_TOOL_VECTORS: dict = {}     # tool_name → list[float]
_ALL_TOOLS: list = []        # original tool objects (for fallback)
_TOOL_BY_NAME: dict = {}     # tool_name → tool object

# K per tier
_K_TRIVIAL = 0
_K_NORMAL  = 5
_K_COMPLEX = 12

# Pool-aware boosting (+ to cosine score for matching tool name prefixes/keywords)
_POOL_BOOSTS = {
    "coding":    {"gitnexus__": 0.2, "read_mac_file": 0.2, "search_mac_files": 0.2,
                  "write_mac_file": 0.15},
    "docs":      {"read_mac_file": 0.2, "gitnexus__context": 0.15},
    "agentic":   {"gitnexus__": 0.15},
    "reasoning": {"gitnexus__query": 0.15, "recall": 0.1, "search_history": 0.1},
}

# Threshold below which tools are dropped even if in top-K
_SIMILARITY_THRESHOLD = 0.3

# Core fallback set — used if all retrieved tools are below threshold
_CORE_FALLBACK_NAMES = ["web_search", "recall", "list_models"]


def init_tool_embeddings(all_tools, mcp_tools) -> None:
    """Boot-time: embed all tool descriptions, persist to SQLite."""
    global _ALL_TOOLS, _TOOL_BY_NAME
    _ALL_TOOLS = list(all_tools) + list(mcp_tools)
    _TOOL_BY_NAME = {t.name: t for t in _ALL_TOOLS}

    cached = _load_cached_embeddings()

    for tool in _ALL_TOOLS:
        desc = (tool.description or tool.name).strip()
        h = hashlib.md5(desc.encode()).hexdigest()
        if tool.name in cached and cached[tool.name]["desc_hash"] == h:
            _TOOL_VECTORS[tool.name] = cached[tool.name]["vector"]
            continue
        try:
            vec = _embed(f"{tool.name}: {desc}")
            _TOOL_VECTORS[tool.name] = vec
            _persist_embedding(tool.name, desc, h, vec)
        except Exception as e:
            print(f"[tool_retrieval] embed failed for {tool.name}: {e}")


def retrieve(message: str, tier: str, pool: str, k: int = None) -> List:
    """Per-turn: return top-K most relevant tools.

    Falls back to ALL_TOOLS if embedding API fails.
    Returns empty list for trivial tier.
    """
    if tier == "trivial":
        return []
    if k is None:
        k = _K_COMPLEX if tier == "complex" else _K_NORMAL

    if not _TOOL_VECTORS or not message.strip():
        return _ALL_TOOLS

    try:
        msg_vec = _embed(message[:500])
    except Exception as e:
        print(f"[tool_retrieval] embed message failed: {e} — returning ALL_TOOLS")
        return _ALL_TOOLS

    # Score each tool
    scores = {}
    boosts = _POOL_BOOSTS.get(pool, {})
    for name, vec in _TOOL_VECTORS.items():
        s = _cosine(msg_vec, vec)
        # Apply pool boost
        for prefix, boost in boosts.items():
            if name.startswith(prefix) or name == prefix:
                s += boost
                break
        scores[name] = s

    # Top-K above threshold
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top = [(n, s) for n, s in ranked[:k] if s >= _SIMILARITY_THRESHOLD]

    if not top:
        # Fallback to core set
        return [_TOOL_BY_NAME[n] for n in _CORE_FALLBACK_NAMES if n in _TOOL_BY_NAME]

    return [_TOOL_BY_NAME[n] for n, _ in top if n in _TOOL_BY_NAME]


# ── Internals ────────────────────────────────────────────────────────────────

def _embed(text: str) -> List[float]:
    """Call NVIDIA NIM nv-embed-v1. Real implementation."""
    import httpx
    import os
    api_key = os.environ.get("NVIDIA_API_KEY", "")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY not set")
    r = httpx.post(
        "https://integrate.api.nvidia.com/v1/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"input": [text], "model": "nvidia/nv-embed-v1",
              "input_type": "query", "encoding_format": "float"},
        timeout=10.0,
    )
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]


def _cosine(v1: List[float], v2: List[float]) -> float:
    """Standard cosine similarity. Returns 0.0 if either is zero vector."""
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


def _load_cached_embeddings() -> dict:
    """Load tool_embeddings table → {name: {desc_hash, vector}}."""
    out = {}
    try:
        with db._conn() as c:
            rows = c.execute(
                "SELECT tool_name, desc_hash, vector FROM tool_embeddings"
            ).fetchall()
            for r in rows:
                out[r["tool_name"]] = {
                    "desc_hash": r["desc_hash"],
                    "vector": pickle.loads(r["vector"]),
                }
    except Exception as e:
        print(f"[tool_retrieval] cache load failed: {e}")
    return out


def _persist_embedding(name: str, desc: str, desc_hash: str, vec: List[float]) -> None:
    """Store one embedding to SQLite."""
    try:
        with db._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO tool_embeddings
                   (tool_name, description, desc_hash, vector, embedded_at)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                (name, desc, desc_hash, pickle.dumps(vec)),
            )
    except Exception as e:
        print(f"[tool_retrieval] persist failed for {name}: {e}")
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/test_tool_retrieval.py -v
```
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/brain/tool_retrieval.py tests/test_tool_retrieval.py
git commit -m "Phase A3: tool_retrieval.py + tests — semantic top-K binding"
```

---

### Task A4: `self_awareness.py` — dynamic system prompt

**Files:**
- Create: `truman/brain/self_awareness.py`
- Create: `tests/test_self_awareness.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_self_awareness.py`:

```python
from unittest.mock import MagicMock
from truman.brain import self_awareness

def _state(routing_tier="normal", retrieved=None, mood="neutral"):
    return {
        "user_input":      "hi there",
        "routing":         {"tier": routing_tier, "pool": "general", "runtime": "local",
                            "hints": [], "skip_llm_eval": False},
        "retrieved_tools": retrieved or [],
        "mood":            mood,
    }

def test_build_self_state_returns_required_keys(tmp_db, fake_local):
    s = self_awareness.build_self_state(_state())
    for key in ["identity", "runtime", "environment", "tool_inventory",
                "capabilities", "current_state", "operating_mode", "persona_anchor"]:
        assert key in s

def test_build_self_state_runtime_local(tmp_db, fake_local):
    s = self_awareness.build_self_state(_state())
    assert s["runtime"]["location"] == "local"

def test_build_self_state_runtime_railway(tmp_db, fake_railway):
    s = self_awareness.build_self_state(_state())
    assert s["runtime"]["location"] == "railway"

def test_capabilities_local_can_access_mac(tmp_db, fake_local):
    caps = self_awareness.derive_capabilities(
        {"location": "local", "mac_bridge": "offline"}, []
    )
    assert any("mac" in c.lower() for c in caps["can"])

def test_capabilities_railway_cannot_access_mac_directly(tmp_db, fake_railway):
    caps = self_awareness.derive_capabilities(
        {"location": "railway", "mac_bridge": "offline"}, []
    )
    assert any("mac" in c.lower() for c in caps["cant"])

def test_capabilities_railway_with_bridge_can_forward(tmp_db, fake_railway):
    caps = self_awareness.derive_capabilities(
        {"location": "railway", "mac_bridge": "connected"}, []
    )
    assert any("bridge" in c.lower() or "forward" in c.lower() for c in caps["can"])

def test_render_system_prompt_contains_sections(tmp_db, fake_local):
    s = self_awareness.build_self_state(_state())
    prompt = self_awareness.render_system_prompt(s, "memory block here")
    for section in ["WHO I AM", "WHERE I AM RUNNING", "WHAT I CAN ACCESS",
                    "WHAT I KNOW ABOUT OM", "OPERATING MODE", "HOW TO RESPOND"]:
        assert section in prompt
    assert "memory block here" in prompt

def test_tier_tone_hint_trivial_says_short():
    hint = self_awareness.tier_tone_hint("trivial")
    assert "short" in hint.lower() or "brief" in hint.lower()

def test_tier_tone_hint_complex_allows_thinking():
    hint = self_awareness.tier_tone_hint("complex")
    assert "think" in hint.lower() or "reason" in hint.lower()
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/test_self_awareness.py -v
```
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `self_awareness.py`**

Create `truman/brain/self_awareness.py`:

```python
"""self_awareness.py — TRUMAN's dynamic per-turn self-knowledge.

Replaces static persona.py SYSTEM string with a dynamic system prompt
rebuilt every turn. Includes:
  - Identity (who he is)
  - Runtime (railway vs local, mac bridge, db path)
  - Tool inventory (what's available this turn)
  - Capabilities (CAN / CAN'T given runtime)
  - Current state (memory size, active goals, last topic)
  - Operating mode (tier-driven tone hint)
  - Persona anchor (always TRUMAN style)

This is the "knows what he is, like Claude does" layer.
"""
from datetime import datetime
from typing import Literal
from truman.core.runtime import runtime_summary
from truman.storage import db


IDENTITY_TEXT = (
    "I'm TRUMAN, Bhavya's personal AI. I run his life — memory, reminders, "
    "research, code lookups, message triage, scheduling. He calls me when he needs "
    "something done; I do it. I'm not a chatbot — I'm an operator with tools."
)

PERSONA_ANCHOR = (
    "Lowercase. Direct. No fluff. Match Om's energy — if he swore, swearing's fine. "
    "No 'I'm just an AI' disclaimers. No hyping ('great question!'). No apologizing "
    "for things that aren't my fault. If I don't know, I say I don't know and offer "
    "how to find out. Never hallucinate facts about Om's data — query memory or say so."
)


def build_self_state(state: dict) -> dict:
    """Build the per-turn SelfState dict consumed by render_system_prompt."""
    runtime = runtime_summary()
    tier = (state.get("routing") or {}).get("tier", "normal")

    # Tool inventory from retrieval
    tools = state.get("retrieved_tools") or []
    tool_inventory = [
        {"name": t.name, "use": (t.description or "").split(".")[0][:80]}
        for t in tools
    ]

    capabilities = derive_capabilities(runtime, tools)

    # Current state — from db
    try:
        facts_count = len(db.get_top_facts(50))
    except Exception:
        facts_count = 0
    try:
        active_goals = [g.get("title", "") for g in db.get_active_goals(3)]
    except Exception:
        active_goals = []

    now = datetime.now()
    return {
        "identity":        IDENTITY_TEXT,
        "runtime":         runtime,
        "environment":     {
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "tz":   "America/New_York",
        },
        "tool_inventory":  tool_inventory,
        "capabilities":    capabilities,
        "current_state":   {
            "facts_count":  facts_count,
            "active_goals": active_goals,
            "last_topic":   (state.get("session_summary") or "")[:120],
        },
        "operating_mode":  tier,
        "persona_anchor":  PERSONA_ANCHOR,
    }


def derive_capabilities(runtime: dict, tools: list) -> dict:
    """Returns {'can': [...], 'cant': [...]} given runtime + retrieved tools."""
    can, cant = [], []

    if runtime.get("location") == "local":
        can.append("read/list/search Mac files directly")
        can.append("write Mac files (with risk_gate confirmation)")
    else:
        if runtime.get("mac_bridge") == "connected":
            can.append("forward Mac requests through local bridge")
        else:
            cant.append("reach Mac (bridge offline — local TRUMAN not running)")
        cant.append("directly access Mac files (running on Railway)")

    can.append("search my own codebase via gitnexus")
    can.append("query memory (facts about Om, past conversations)")
    can.append("set reminders, manage goals, log sleep")

    cant.append("modify Railway DB or env vars")
    cant.append("see new web content beyond DuckDuckGo snippets")
    cant.append("access paid APIs without keys")

    return {"can": can, "cant": cant}


def tier_tone_hint(tier: str) -> str:
    """Tone instruction injected based on operating mode."""
    if tier == "trivial":
        return "Keep this short. 1-2 sentences max. Match casualness. No tools needed."
    if tier == "complex":
        return ("Take time to think. Multi-step reasoning OK. "
                "Show work briefly when relevant. Tool chains allowed.")
    return "Conversational. Direct answer. No preamble."


def render_system_prompt(self_state: dict, memory_block: str) -> str:
    """Compose the full dynamic system prompt for this turn."""
    rt = self_state["runtime"]
    env = self_state["environment"]
    caps = self_state["capabilities"]
    cs = self_state["current_state"]

    tools_block = (
        "\n".join(f"  - {t['name']}: {t['use']}" for t in self_state["tool_inventory"])
        if self_state["tool_inventory"]
        else "  (no tools needed for this turn)"
    )

    goals_line = (
        ", ".join(cs["active_goals"]) if cs["active_goals"] else "(none active)"
    )

    return f"""# WHO I AM
{self_state['identity']}

# WHERE I AM RUNNING
- Location:    {rt['location']}
- DB:          {rt['db_path']}
- Mac bridge:  {rt['mac_bridge']}
- Today:       {env['date']}, {env['time']} {env['tz']}

# WHAT I CAN ACCESS RIGHT NOW
Tools available this turn:
{tools_block}

I CAN: {', '.join(caps['can'])}.
I CAN'T: {', '.join(caps['cant'])}.

# WHAT I KNOW ABOUT OM
Memory: {cs['facts_count']} pinned facts. Active goals: {goals_line}.
Last topic: {cs['last_topic'] or '(new conversation)'}

{memory_block}

# OPERATING MODE THIS TURN
{self_state['operating_mode']} → {tier_tone_hint(self_state['operating_mode'])}

# HOW TO RESPOND
{self_state['persona_anchor']}
"""
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/test_self_awareness.py -v
```
Expected: 9 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/brain/self_awareness.py tests/test_self_awareness.py
git commit -m "Phase A4: self_awareness.py + tests — TRUMAN knows what he is per turn"
```

---

### Task A5: `tier_router.py` — regex + LLM hybrid classifier

**Files:**
- Create: `truman/brain/tier_router.py`
- Create: `tests/test_tier_router.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tier_router.py`:

```python
from truman.brain import tier_router

def test_classify_trivial_greeting():
    d = tier_router.classify_tier("yo")
    assert d["tier"] == "trivial"

def test_classify_trivial_thanks():
    d = tier_router.classify_tier("thanks man")
    assert d["tier"] == "trivial"

def test_classify_trivial_simple_math():
    d = tier_router.classify_tier("what's 2+2")
    assert d["tier"] == "trivial"

def test_classify_complex_code_lookup():
    d = tier_router.classify_tier("look up risk_gate in my codebase")
    assert d["tier"] == "complex"
    assert d["pool"] == "coding"

def test_classify_complex_multistep():
    d = tier_router.classify_tier("first read this file, then summarize it")
    assert d["tier"] == "complex"

def test_classify_normal_chat():
    d = tier_router.classify_tier("what's the weather in NYC")
    assert d["tier"] == "normal"

def test_classify_image_routes_vision_complex():
    d = tier_router.classify_tier("what's in this", image_count=1)
    assert d["pool"] == "vision"
    assert d["tier"] == "complex"

def test_routing_decision_has_required_fields():
    d = tier_router.classify_tier("hi")
    for k in ["tier", "pool", "runtime", "hints", "skip_llm_eval"]:
        assert k in d

def test_trivial_skips_llm_eval():
    d = tier_router.classify_tier("yo")
    assert d["skip_llm_eval"] is True

def test_complex_does_not_skip_llm_eval():
    d = tier_router.classify_tier("look up risk_gate")
    assert d["skip_llm_eval"] is False
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/test_tier_router.py -v
```
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `tier_router.py`**

Create `truman/brain/tier_router.py`:

```python
"""tier_router.py — first node in the new graph.

Returns a RoutingDecision telling the rest of the graph:
  - which tier to use (trivial / normal / complex)
  - which model pool to use
  - what runtime context applies
  - reasons for the decision (for telemetry)

Regex first (fast), tiny LLM fallback if regex is unsure.
"""
import re
from typing import Literal
from truman.core.runtime import is_railway

# Regex patterns — each maps to (tier, pool, reason)
_TRIVIAL_PATTERNS = [
    (r"^\s*(yo|hi|hey|sup|hello|hola|gm|gn|good\s*(morning|night))\s*[!?.]*\s*$", "greeting"),
    (r"^\s*(thanks?|ty|thx|thank you|cool|nice|ok|okay|sure|got it|sweet|lol)\s*[!?.]*\s*$", "ack"),
    (r"^\s*what'?s?\s*\d+\s*[+\-*/]\s*\d+\s*[?]?\s*$", "simple_math"),
    (r"^\s*\?\s*$", "qmark_only"),
]

_COMPLEX_KEYWORDS = [
    # multi-step
    r"\bfirst\b.*\bthen\b", r"\bafter that\b", r"\bstep by step\b",
    # code introspection
    r"\b(look up|find|search)\b.*\b(my code|codebase|this repo|risk_gate|nodes\.py|truman/)\b",
    r"\bgitnexus\b",
    # debugging
    r"\bdebug\b.*\b(this|my)\b", r"\bwhy.*not work\b", r"\bstack trace\b", r"\btraceback\b",
    # multi-tool intent
    r"\band then\b.*\b(send|save|write)\b",
]

_CODING_KEYWORDS = [
    r"\bcode\b", r"\bfunction\b", r"\bclass\b", r"\bimport\b", r"\bdef \b",
    r"\.py\b", r"\.js\b", r"\.ts\b", r"\bgit\b",
    r"\bnodes\.py\b", r"\brisk_gate\b", r"\btruman/\b",
]

_DOCS_KEYWORDS = [
    r"\.pdf\b", r"\.docx\b", r"\.xlsx\b", r"\bpresentation\b", r"\bdocument\b",
]

_REASONING_KEYWORDS = [
    r"\bwhy\b", r"\bexplain\b", r"\bhow does\b", r"\bcompare\b", r"\banalyze\b",
]


def classify_tier(message: str, image_count: int = 0) -> dict:
    """Returns RoutingDecision dict.

    Priority chain (first match wins):
      1. Image present → vision pool, complex tier
      2. Trivial regex match → trivial tier, general pool
      3. Complex keyword match → complex tier, pool by content
      4. Coding/docs/reasoning keyword → normal tier, matching pool
      5. Default → normal tier, general pool
    """
    msg = (message or "").strip()
    runtime = "railway" if is_railway() else "local"

    # 1. Vision
    if image_count > 0:
        return _decision("complex", "vision", runtime, ["has_image"], skip_llm_eval=False)

    # 2. Trivial
    for pat, reason in _TRIVIAL_PATTERNS:
        if re.match(pat, msg, re.IGNORECASE):
            return _decision("trivial", "general", runtime, [f"trivial:{reason}"], skip_llm_eval=True)

    # 3. Complex
    for pat in _COMPLEX_KEYWORDS:
        if re.search(pat, msg, re.IGNORECASE):
            pool = _detect_pool(msg)
            return _decision("complex", pool, runtime, [f"complex:{pat[:30]}"], skip_llm_eval=False)

    # 4. Pool detection for normal
    pool = _detect_pool(msg)
    return _decision("normal", pool, runtime, [f"normal:pool={pool}"], skip_llm_eval=False)


def _detect_pool(msg: str) -> str:
    """Detect model pool from message keywords."""
    low = msg.lower()
    if any(re.search(p, low) for p in _DOCS_KEYWORDS):
        return "docs"
    if any(re.search(p, low) for p in _CODING_KEYWORDS):
        return "coding"
    if any(re.search(p, low) for p in _REASONING_KEYWORDS):
        return "reasoning"
    return "general"


def _decision(tier, pool, runtime, hints, skip_llm_eval) -> dict:
    return {
        "tier":          tier,
        "pool":          pool,
        "runtime":       runtime,
        "hints":         hints,
        "skip_llm_eval": skip_llm_eval,
    }
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/test_tier_router.py -v
```
Expected: 10 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/brain/tier_router.py tests/test_tier_router.py
git commit -m "Phase A5: tier_router.py + tests — 3-tier classification"
```

---

### Task A6: Phase A integration check

- [ ] **Step 1: All Phase A tests pass together**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/ -v
```
Expected: 31 PASSED, 0 failed.

- [ ] **Step 2: TRUMAN still boots locally**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
from truman.storage import db
from truman.core import runtime
from truman.brain import tool_retrieval, self_awareness, tier_router
db.init()
print('boot ok, runtime:', runtime.runtime_summary()['location'])
print('tier:', tier_router.classify_tier('yo')['tier'])
"
```
Expected: `boot ok, runtime: local` then `tier: trivial`.

- [ ] **Step 3: No graph behavior changed yet**

Verify by checking `truman/brain/loop.py` is unmodified:
```bash
cd /Users/ompandya/Desktop/friday && git diff truman/brain/loop.py
```
Expected: empty (no changes).

- [ ] **Step 4: STOP — checkpoint with Om**

Show Om: "Phase A complete — 4 new modules + tests passing, graph untouched. Ready for Phase B graph surgery?" Wait for explicit yes.

---

# Phase B — Graph Surgery (the careful part)

### Task B1: Add new fields to `state.py`

**Files:**
- Modify: `truman/brain/state.py`

- [ ] **Step 1: Read current state**

```bash
cat /Users/ompandya/Desktop/friday/truman/brain/state.py
```

- [ ] **Step 2: Add 4 new fields to TrumanState TypedDict**

Add these fields (in the same TypedDict, with defaults handled in initial state of loop.py):

```python
# In truman/brain/state.py — add these to the TrumanState TypedDict
routing:          dict     # RoutingDecision from tier_router (default {})
self_state:       dict     # built by self_awareness node (default {})
retrieved_tools:  list     # top-K from tool_retrieval (default [])
llm_tool_calls:   list     # what LLM picked, inspected by risk_gate (default [])
```

- [ ] **Step 3: Verify imports still work**

```bash
cd /Users/ompandya/Desktop/friday && python -c "from truman.brain.state import TrumanState; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Run all tests**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/ -v
```
Expected: 31 PASSED (no regressions).

- [ ] **Step 5: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/brain/state.py
git commit -m "Phase B1: state schema — add routing, self_state, retrieved_tools, llm_tool_calls"
```

---

### Task B2: Wire `init_tool_embeddings` at boot

**Files:**
- Modify: `truman/main.py`
- Modify: `truman/main_cloud.py`

- [ ] **Step 1: Find the MCP mount point in main.py**

```bash
grep -n "MCP\|mount" /Users/ompandya/Desktop/friday/truman/main.py | head -10
```

- [ ] **Step 2: After MCP mount completes, add init call**

In `truman/main.py`, after the MCP mount block (find "MCP_SERVERS" then mount logic), add:

```python
# Smart routing: embed all tools at boot for retrieval
try:
    from truman.brain.tool_retrieval import init_tool_embeddings
    from truman.tools.all_tools import TOOLS as _ALL_TOOLS
    # MCP tools are mutated into the same list after mount; pass empty as 2nd arg
    init_tool_embeddings(_ALL_TOOLS, [])
    print(f"[Smart Routing] Embedded {len(_ALL_TOOLS)} tools for retrieval")
except Exception as e:
    print(f"[Smart Routing] init_tool_embeddings failed: {e}")
```

Repeat in `truman/main_cloud.py` at the equivalent location.

- [ ] **Step 3: Boot locally to verify**

```bash
cd /Users/ompandya/Desktop/friday && timeout 15 python -m truman.main 2>&1 | grep -E "Smart Routing|TRUMAN|error" | head -10
```
Expected: see `[Smart Routing] Embedded N tools for retrieval` line.

- [ ] **Step 4: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/main.py truman/main_cloud.py
git commit -m "Phase B2: wire init_tool_embeddings at boot (main + main_cloud)"
```

---

### Task B3: Add `tier_router` node to `loop.py` (additive — doesn't reroute yet)

**Files:**
- Modify: `truman/brain/loop.py`
- Modify: `truman/brain/nodes.py`

- [ ] **Step 1: Read current loop.py**

```bash
cat /Users/ompandya/Desktop/friday/truman/brain/loop.py
```

- [ ] **Step 2: Add tier_router_node function in nodes.py**

Add near the top of `truman/brain/nodes.py` (after imports):

```python
def tier_router_node(state: dict) -> dict:
    """First node — classifies tier, pool, runtime."""
    from truman.brain.tier_router import classify_tier
    try:
        decision = classify_tier(
            state.get("user_input", ""),
            image_count=len(state.get("attach_ids", []) or []),
        )
        state["routing"] = decision
    except Exception as e:
        state.setdefault("node_errors", {})["tier_router"] = str(e)
        state["routing"] = {"tier": "normal", "pool": "general",
                            "runtime": "local", "hints": ["fallback"],
                            "skip_llm_eval": False}
    return state
```

- [ ] **Step 3: Wire tier_router as FIRST node in loop.py**

In `truman/brain/loop.py`, find the `add_node` calls. Add:

```python
g.add_node("tier_router", tier_router_node)
```

Change the entry edge from `START → classify_mood` to `START → tier_router → classify_mood`:

```python
g.add_edge(START, "tier_router")
g.add_edge("tier_router", "classify_mood")
```

(Remove the old `g.add_edge(START, "classify_mood")` line.)

- [ ] **Step 4: Verify graph still runs end-to-end**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
from truman.brain.loop import get_graph
g = get_graph()
result = g.invoke({'user_input': 'hi', 'session_id': 'test', 'attach_ids': []})
print('tier:', result.get('routing', {}).get('tier'))
print('response:', result.get('response', '')[:60])
"
```
Expected: `tier: trivial` then a short response.

- [ ] **Step 5: All existing tests pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/ -v
```
Expected: 31 PASSED.

- [ ] **Step 6: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/brain/loop.py truman/brain/nodes.py
git commit -m "Phase B3: tier_router as first graph node (additive, no rerouting yet)"
```

---

### Task B4: Add `self_awareness` node (additive — populates state.self_state)

**Files:**
- Modify: `truman/brain/loop.py`
- Modify: `truman/brain/nodes.py`

- [ ] **Step 1: Add self_awareness_node function in nodes.py**

```python
def self_awareness_node(state: dict) -> dict:
    """Build per-turn SelfState dict for dynamic system prompt."""
    from truman.brain.self_awareness import build_self_state
    try:
        state["self_state"] = build_self_state(state)
    except Exception as e:
        state.setdefault("node_errors", {})["self_awareness"] = str(e)
        state["self_state"] = {}
    return state
```

- [ ] **Step 2: Wire after load_memory in loop.py**

```python
g.add_node("self_awareness", self_awareness_node)
g.add_edge("load_memory", "self_awareness")
g.add_edge("self_awareness", "load_goals")  # was: load_memory → load_goals
```

(Replace the old `g.add_edge("load_memory", "load_goals")` line.)

- [ ] **Step 3: Verify**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
from truman.brain.loop import get_graph
g = get_graph()
result = g.invoke({'user_input': 'are you on railway', 'session_id': 'test', 'attach_ids': []})
ss = result.get('self_state', {})
print('runtime:', ss.get('runtime', {}).get('location'))
print('identity present:', bool(ss.get('identity')))
"
```
Expected: `runtime: local` (or railway), `identity present: True`.

- [ ] **Step 4: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/brain/loop.py truman/brain/nodes.py
git commit -m "Phase B4: self_awareness node populates state.self_state per turn"
```

---

### Task B5: Add `tool_retrieval` node + refactor `call_llm` to use it

**Files:**
- Modify: `truman/brain/loop.py`
- Modify: `truman/brain/nodes.py`

- [ ] **Step 1: Add tool_retrieval_node function in nodes.py**

```python
def tool_retrieval_node(state: dict) -> dict:
    """Retrieve top-K tools for this message."""
    from truman.brain.tool_retrieval import retrieve
    try:
        routing = state.get("routing") or {}
        tier = routing.get("tier", "normal")
        pool = routing.get("pool", "general")
        state["retrieved_tools"] = retrieve(state.get("user_input", ""), tier, pool)
    except Exception as e:
        state.setdefault("node_errors", {})["tool_retrieval"] = str(e)
        state["retrieved_tools"] = []
    return state
```

- [ ] **Step 2: Wire after self_awareness in loop.py**

```python
g.add_node("tool_retrieval", tool_retrieval_node)
g.add_edge("self_awareness", "tool_retrieval")
g.add_edge("tool_retrieval", "load_goals")  # was self_awareness → load_goals
```

(Replace the old `g.add_edge("self_awareness", "load_goals")`.)

- [ ] **Step 3: Refactor `call_llm` node to use retrieval + dynamic prompt**

Find `call_llm` node in nodes.py. Replace its body so it:
1. Reads `state["retrieved_tools"]` and binds those (not ALL_TOOLS)
2. Reads `state["self_state"]` and uses `render_system_prompt()` instead of static SYSTEM
3. Captures any LLM tool_calls into `state["llm_tool_calls"]`

Locate the existing call_llm function. Modify the LLM call section:

```python
# At top of call_llm node body:
from truman.brain.self_awareness import render_system_prompt
from truman.brain.memory import resolve_memory, build_memory_prompt

# Build dynamic system prompt
self_state = state.get("self_state") or {}
mem_bundle = resolve_memory(state)
memory_block = build_memory_prompt(mem_bundle)
if self_state:
    system_prompt = render_system_prompt(self_state, memory_block)
else:
    # Fallback to static persona if self_state missing
    from truman.core.persona import SYSTEM
    system_prompt = SYSTEM + "\n" + memory_block

# Use retrieved tools instead of all
tools = state.get("retrieved_tools") or []

# ... existing LLM call code ...
# Replace bind_tools(ALL_TOOLS) with bind_tools(tools)
# After LLM responds, capture tool_calls:
state["llm_tool_calls"] = getattr(response, "tool_calls", []) or []
```

(Specific edits depend on exact existing call_llm body — Sonnet: read first, then minimal-diff edit.)

- [ ] **Step 4: Verify graph runs and uses dynamic prompt**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
from truman.brain.loop import get_graph
g = get_graph()
r = g.invoke({'user_input': 'are you on railway?', 'session_id': 'test', 'attach_ids': []})
print('response:', r.get('response', '')[:200])
"
```
Expected: response should mention 'local' or 'railway' correctly.

- [ ] **Step 5: All tests pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/ -v
```
Expected: 31 PASSED.

- [ ] **Step 6: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/brain/loop.py truman/brain/nodes.py
git commit -m "Phase B5: tool_retrieval node + call_llm uses dynamic prompt + retrieved tools"
```

---

### Task B6: Move `risk_gate` to AFTER `call_llm`

**Files:**
- Modify: `truman/brain/loop.py`
- Modify: `truman/brain/nodes.py`

- [ ] **Step 1: Write failing test for new risk_gate behavior**

Create `tests/test_risk_gate.py`:

```python
from unittest.mock import patch
from truman.brain import nodes

def test_risk_gate_safe_tool_passes(tmp_db):
    state = {
        "user_input":     "hi",
        "llm_tool_calls": [{"name": "web_search", "args": {"query": "x"}, "id": "1"}],
    }
    out = nodes.risk_gate_node(state)
    assert out.get("awaiting_confirm") is not True

def test_risk_gate_risky_tool_pauses(tmp_db):
    state = {
        "user_input":     "write a file",
        "llm_tool_calls": [{"name": "write_mac_file",
                            "args": {"path": "/tmp/x", "content": "hi"}, "id": "1"}],
    }
    out = nodes.risk_gate_node(state)
    assert out.get("awaiting_confirm") is True
    assert "confirm" in (out.get("response") or "").lower()

def test_risk_gate_no_tool_calls_passes(tmp_db):
    state = {"user_input": "yo", "llm_tool_calls": []}
    out = nodes.risk_gate_node(state)
    assert out.get("awaiting_confirm") is not True
```

- [ ] **Step 2: Run test — verify fails**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/test_risk_gate.py -v
```
Expected: FAIL — `risk_gate_node` either doesn't exist with this signature or doesn't behave this way.

- [ ] **Step 3: Refactor `risk_gate` node in nodes.py**

Find the existing `risk_gate` node (roughly line 200-300 in nodes.py). Replace its body:

```python
def risk_gate_node(state: dict) -> dict:
    """Inspect LLM-picked tool calls. Risky tools pause for confirmation."""
    from truman.core import risk
    from truman.storage import db

    tool_calls = state.get("llm_tool_calls") or []
    if not tool_calls:
        return state

    for tc in tool_calls:
        name = tc.get("name") or tc.get("tool_name", "")
        tier = risk.tier_for(name) if hasattr(risk, "tier_for") else risk.RISK_TIERS.get(name, "safe")
        if tier == "risky":
            try:
                pid = db.save_pending_action(name, tc.get("args", {}), state.get("user_input", ""))
                state["awaiting_confirm"] = True
                state["pending_action_id"] = pid
                state["response"] = (
                    f"want me to run `{name}`? confirm with 'yes' "
                    f"or cancel with 'no'. expires in 5 min."
                )
                # Skip executing this turn
                return state
            except Exception as e:
                state.setdefault("node_errors", {})["risk_gate"] = str(e)
                state["response"] = "couldn't safety-check that — try again"
                return state
    return state
```

- [ ] **Step 4: In loop.py, move risk_gate to AFTER call_llm**

```python
# Old: detect_tool → risk_gate → route_skill → execute_tool → call_llm
# New: ... → call_llm → risk_gate → execute_tool → eval ...

g.add_edge("call_llm", "risk_gate")
g.add_edge("risk_gate", "execute_tool")
```

(Remove old edges `detect_tool → risk_gate` and `risk_gate → route_skill`.)

- [ ] **Step 5: Verify tests pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/test_risk_gate.py -v
```
Expected: 3 PASSED.

- [ ] **Step 6: All tests pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/ -v
```
Expected: 34 PASSED.

- [ ] **Step 7: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/brain/loop.py truman/brain/nodes.py tests/test_risk_gate.py
git commit -m "Phase B6: risk_gate moves AFTER call_llm — inspects LLM picks not regex"
```

---

### Task B7: Add tier-conditional edges (3 lanes)

**Files:**
- Modify: `truman/brain/loop.py`

- [ ] **Step 1: Add a routing function**

In loop.py, add a conditional edge function:

```python
def _route_by_tier(state: dict) -> str:
    """Return next node name based on tier."""
    routing = state.get("routing") or {}
    tier = routing.get("tier", "normal")
    if tier == "trivial":
        return "trivial_lane"
    if tier == "complex":
        return "complex_lane"
    return "normal_lane"
```

- [ ] **Step 2: Wire conditional edges from tier_router**

```python
g.add_conditional_edges(
    "tier_router",
    _route_by_tier,
    {
        "trivial_lane": "classify_mood",     # short path: mood → self_aware → call_llm
        "normal_lane":  "classify_mood",     # standard path
        "complex_lane": "classify_mood",     # full path
    },
)
```

For trivial tier, after self_awareness skip directly to call_llm (skip load_goals, recall_skills, tool_retrieval since K=0):

```python
def _after_self_awareness(state: dict) -> str:
    tier = (state.get("routing") or {}).get("tier", "normal")
    if tier == "trivial":
        return "call_llm"
    return "tool_retrieval"

g.add_conditional_edges(
    "self_awareness",
    _after_self_awareness,
    {"call_llm": "call_llm", "tool_retrieval": "tool_retrieval"},
)
```

For trivial, after call_llm skip risk_gate and eval, go straight to save_memory:

```python
def _after_call_llm(state: dict) -> str:
    tier = (state.get("routing") or {}).get("tier", "normal")
    if tier == "trivial":
        return "save_memory"
    return "risk_gate"

g.add_conditional_edges(
    "call_llm",
    _after_call_llm,
    {"save_memory": "save_memory", "risk_gate": "risk_gate"},
)
```

For trivial+normal, skip LLM eval (state.routing.skip_llm_eval is True):

```python
# Inside evaluate_output node, check state["routing"]["skip_llm_eval"]
# and short-circuit to rule-only check.
```

- [ ] **Step 3: Test trivial path**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
import time
from truman.brain.loop import get_graph
g = get_graph()
t0 = time.time()
r = g.invoke({'user_input': 'yo', 'session_id': 'test', 'attach_ids': []})
print(f'trivial latency: {time.time()-t0:.2f}s')
print('response:', r.get('response', '')[:100])
print('tier:', r.get('routing', {}).get('tier'))
"
```
Expected: latency <3s, tier=trivial.

- [ ] **Step 4: Test complex path**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
import time
from truman.brain.loop import get_graph
g = get_graph()
t0 = time.time()
r = g.invoke({'user_input': 'look up risk_gate in my codebase', 'session_id': 'test', 'attach_ids': []})
print(f'complex latency: {time.time()-t0:.2f}s')
print('response:', r.get('response', '')[:200])
print('tool_calls:', [tc.get('name') for tc in r.get('llm_tool_calls', [])])
"
```
Expected: latency <18s, response references gitnexus output.

- [ ] **Step 5: All tests pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/ -v
```
Expected: 34 PASSED.

- [ ] **Step 6: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/brain/loop.py
git commit -m "Phase B7: tier-conditional edges — trivial 5 nodes, normal 9, complex 12"
```

---

### Task B8: DELETE `_detect_tool` regex execution path

**Files:**
- Modify: `truman/brain/nodes.py`
- Modify: `truman/brain/loop.py`

- [ ] **Step 1: Remove `detect_tool` node from loop.py wiring**

```python
# Remove these lines from loop.py:
# g.add_node("detect_tool", detect_tool_node)
# g.add_edge(..., "detect_tool")
# g.add_edge("detect_tool", ...)
```

- [ ] **Step 2: Remove `route_skill` node from loop.py wiring**

```python
# Remove:
# g.add_node("route_skill", route_skill_node)
# g.add_edge(..., "route_skill")
# g.add_edge("route_skill", ...)
```

- [ ] **Step 3: Update `execute_tool` node — only runs LLM-confirmed tools**

In nodes.py, find `execute_tool` node. Change its body to execute from `state["llm_tool_calls"]` (after risk_gate clears them) OR from `state["pending_action"]` (after Om confirms):

```python
def execute_tool_node(state: dict) -> dict:
    """Execute LLM-picked tools that risk_gate cleared."""
    from truman.tools.all_tools import TOOLS
    if state.get("awaiting_confirm"):
        return state  # risk_gate paused us
    tool_calls = state.get("llm_tool_calls") or []
    if not tool_calls:
        return state
    tool_map = {t.name: t for t in TOOLS}
    results = []
    for tc in tool_calls:
        name = tc.get("name") or tc.get("tool_name")
        if name not in tool_map:
            continue
        try:
            result = tool_map[name].invoke(tc.get("args", {}))
            results.append(f"{name}: {result}")
        except Exception as e:
            results.append(f"{name} failed: {e}")
            state.setdefault("node_errors", {})[f"execute_tool/{name}"] = str(e)
    state["tool_result"] = "\n".join(results)
    state.setdefault("tool_calls_made", []).extend(tc.get("name") for tc in tool_calls)
    return state
```

- [ ] **Step 4: Verify boot + test**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
from truman.brain.loop import get_graph
g = get_graph()
r = g.invoke({'user_input': 'look up risk_gate', 'session_id': 'test', 'attach_ids': []})
print('tool_calls_made:', r.get('tool_calls_made'))
print('response:', r.get('response', '')[:200])
"
```
Expected: tool_calls_made includes a `gitnexus__*` entry, NOT `web_search`.

- [ ] **Step 5: All tests pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/ -v
```
Expected: 34 PASSED.

- [ ] **Step 6: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/brain/nodes.py truman/brain/loop.py
git commit -m "Phase B8: drop detect_tool + route_skill nodes; execute_tool runs LLM picks only"
```

---

### Task B9: Tighten fallback exception in `agent.py`

**Files:**
- Modify: `truman/text/agent.py`

- [ ] **Step 1: Find the fallback handler**

```bash
grep -n "except Exception" /Users/ompandya/Desktop/friday/truman/text/agent.py | head -5
```

Look for the one near line 572 (after `lg_run` call).

- [ ] **Step 2: Add transient error tuple + log_fallback_event helper**

At the top of agent.py (after imports):

```python
import httpx
try:
    import openai as _openai
    _OPENAI_TRANSIENT = (_openai.APIConnectionError, _openai.RateLimitError)
except Exception:
    _OPENAI_TRANSIENT = ()

try:
    from langgraph.errors import GraphRecursionError
except Exception:
    GraphRecursionError = Exception

TRANSIENT_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    GraphRecursionError,
) + _OPENAI_TRANSIENT


def log_fallback_event(reason: str, exception_type: str = "", message: str = "") -> None:
    """Log a langgraph→legacy fallback to events table."""
    try:
        from truman.storage import db
        import json as _json
        with db._conn() as c:
            c.execute(
                "INSERT INTO events (kind, data, ts) VALUES (?, ?, datetime('now'))",
                ("langgraph_fallback",
                 _json.dumps({"reason": reason,
                              "exception_type": exception_type,
                              "message": message[:200]})),
            )
    except Exception:
        pass  # never crash on telemetry
```

- [ ] **Step 3: Replace the broad except**

Find the existing `except Exception as e:` handler around line 572. Replace with:

```python
except TRANSIENT_ERRORS as e:
    log_fallback_event(reason="transient",
                       exception_type=type(e).__name__,
                       message=str(e))
    print(f"[LangGraph→legacy] transient: {type(e).__name__}: {e}")
    result = _run_legacy(user_input, persona_reminder, pool_hint, session_id, attach_ids)
except Exception as e:
    log_fallback_event(reason="bug",
                       exception_type=type(e).__name__,
                       message=str(e))
    print(f"[LangGraph] BUG (re-raising): {type(e).__name__}: {e}")
    raise
```

- [ ] **Step 4: Verify boot + a turn**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
from truman.text.agent import run
r = run('hi', '', None, 'test', [])
print('response:', r.get('response', '')[:100])
"
```
Expected: normal response, no error.

- [ ] **Step 5: All tests pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/ -v
```
Expected: 34 PASSED.

- [ ] **Step 6: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/text/agent.py
git commit -m "Phase B9: tighten fallback exception list + telemetry to events table"
```

---

### Task B10: Phase B integration check

- [ ] **Step 1: Full local boot, smoke 3 messages**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
import time
from truman.brain.loop import get_graph
g = get_graph()
for msg in ['yo', 'what files are on my desktop', 'look up risk_gate in my codebase']:
    t0 = time.time()
    r = g.invoke({'user_input': msg, 'session_id': 'smoke', 'attach_ids': []})
    print(f'[{time.time()-t0:.1f}s] tier={r.get(\"routing\",{}).get(\"tier\")} '
          f'tools={r.get(\"tool_calls_made\")} → {r.get(\"response\",\"\")[:80]}')
"
```
Expected: trivial <3s, normal <10s, complex <18s. No node_errors visible. Tool calls correct.

- [ ] **Step 2: STOP — checkpoint with Om**

Show Om: "Phase B complete — graph surgery done, all tests green, smoke test passed. Ready for Phase C verification suite?" Wait for explicit yes.

---

# Phase C — Verification Suite

### Task C1: Build 30-message tool selection test set

**Files:**
- Create: `tests/verify/tool_selection.json`

- [ ] **Step 1: Create the test set**

Create `tests/verify/tool_selection.json`:

```json
[
  {"msg": "look up risk_gate", "expected_in_topK": ["gitnexus__query", "gitnexus__context"], "tier": "complex"},
  {"msg": "what's the weather in NYC", "expected_in_topK": ["get_weather"], "tier": "normal"},
  {"msg": "remind me to call mom 6pm", "expected_in_topK": ["set_reminder"], "tier": "normal"},
  {"msg": "yo", "expected_in_topK": [], "tier": "trivial"},
  {"msg": "thanks", "expected_in_topK": [], "tier": "trivial"},
  {"msg": "list files on my desktop", "expected_in_topK": ["list_mac_dir", "search_mac_files"], "tier": "normal"},
  {"msg": "search the web for nim docs", "expected_in_topK": ["web_search"], "tier": "normal"},
  {"msg": "what do you know about my coding habits", "expected_in_topK": ["recall", "search_history"], "tier": "normal"},
  {"msg": "show last 5 conversations", "expected_in_topK": ["recent_conversations"], "tier": "normal"},
  {"msg": "add goal: ship phase 1 today", "expected_in_topK": ["add_goal"], "tier": "normal"},
  {"msg": "list my goals", "expected_in_topK": ["list_goals"], "tier": "normal"},
  {"msg": "complete the phase 1 goal", "expected_in_topK": ["complete_goal"], "tier": "normal"},
  {"msg": "drop the phase 1 goal", "expected_in_topK": ["drop_goal"], "tier": "normal"},
  {"msg": "remember that I prefer kimi over llama", "expected_in_topK": ["remember"], "tier": "normal"},
  {"msg": "what's in nodes.py around line 200", "expected_in_topK": ["read_mac_file", "gitnexus__context"], "tier": "complex"},
  {"msg": "find all .py files in my truman dir", "expected_in_topK": ["search_mac_files"], "tier": "normal"},
  {"msg": "write hello world to /tmp/hi.txt", "expected_in_topK": ["write_mac_file"], "tier": "normal"},
  {"msg": "what models do I have access to", "expected_in_topK": ["list_models"], "tier": "normal"},
  {"msg": "switch to kimi-k2", "expected_in_topK": ["set_model"], "tier": "normal"},
  {"msg": "list my reminders", "expected_in_topK": ["list_reminders"], "tier": "normal"},
  {"msg": "I slept 11pm to 7am last night", "expected_in_topK": ["log_sleep"], "tier": "normal"},
  {"msg": "set my brief hour to 8am", "expected_in_topK": ["update_pref"], "tier": "normal"},
  {"msg": "add rule: never use bullet points", "expected_in_topK": ["add_rule"], "tier": "normal"},
  {"msg": "list my rules", "expected_in_topK": ["list_rules"], "tier": "normal"},
  {"msg": "delete rule 3", "expected_in_topK": ["delete_rule"], "tier": "normal"},
  {"msg": "trace which functions call risk_gate", "expected_in_topK": ["gitnexus__impact", "gitnexus__query"], "tier": "complex"},
  {"msg": "what changed in my repo recently", "expected_in_topK": ["gitnexus__detect_changes"], "tier": "complex"},
  {"msg": "search history for the word railway", "expected_in_topK": ["search_history"], "tier": "normal"},
  {"msg": "ok cool", "expected_in_topK": [], "tier": "trivial"},
  {"msg": "lol", "expected_in_topK": [], "tier": "trivial"}
]
```

- [ ] **Step 2: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add tests/verify/tool_selection.json
git commit -m "Phase C1: 30-msg tool selection accuracy test set"
```

---

### Task C2: Build verification runner

**Files:**
- Create: `tests/verify/run_verify.py`

- [ ] **Step 1: Create runner**

Create `tests/verify/run_verify.py`:

```python
"""run_verify.py — End-to-end verification of smart routing.

Run from project root:
  python tests/verify/run_verify.py

Outputs a markdown report to docs/superpowers/verify/<date>-phase1-verify.md
"""
import json
import os
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from truman.storage import db
from truman.brain.tier_router import classify_tier
from truman.brain.tool_retrieval import retrieve, init_tool_embeddings
from truman.tools.all_tools import TOOLS


def main():
    db.init()
    init_tool_embeddings(TOOLS, [])

    cases = json.load(open("tests/verify/tool_selection.json"))

    # ── Test Set 1: Tool Selection Accuracy ──
    correct = 0
    failures = []
    for case in cases:
        d = classify_tier(case["msg"])
        tier = d["tier"]
        # Tier check
        tier_ok = tier == case["tier"]

        if tier == "trivial":
            # Should retrieve nothing
            tools = retrieve(case["msg"], tier, d["pool"])
            tool_ok = (tools == [])
        else:
            tools = retrieve(case["msg"], tier, d["pool"])
            names = [t.name for t in tools]
            expected = case["expected_in_topK"]
            tool_ok = any(e in names for e in expected) if expected else True

        if tier_ok and tool_ok:
            correct += 1
        else:
            failures.append({
                "msg": case["msg"],
                "expected_tier": case["tier"], "got_tier": tier,
                "expected_tools": case["expected_in_topK"],
                "got_tools": [t.name for t in tools] if tier != "trivial" else [],
            })

    accuracy = correct / len(cases) * 100

    # ── Test Set 2: Latency Benchmarks ──
    from truman.brain.loop import get_graph
    g = get_graph()
    latencies = {"trivial": [], "normal": [], "complex": []}
    bench_msgs = {
        "trivial": ["yo", "thanks"],
        "normal":  ["what's on my desktop", "remind me to ship tomorrow"],
        "complex": ["look up risk_gate in my codebase", "find all .py files modified last week"],
    }
    for tier, msgs in bench_msgs.items():
        for msg in msgs:
            for _ in range(3):
                t0 = time.time()
                g.invoke({"user_input": msg, "session_id": f"verify_{tier}", "attach_ids": []})
                latencies[tier].append(time.time() - t0)
    medians = {tier: sorted(v)[len(v)//2] for tier, v in latencies.items()}

    # ── Report ──
    out_path = f"docs/superpowers/verify/{date.today()}-phase1-verify.md"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(f"# Phase 1 Verification Report — {date.today()}\n\n")
        f.write(f"## Tool Selection Accuracy\n")
        f.write(f"- {correct}/{len(cases)} = **{accuracy:.1f}%**\n")
        f.write(f"- PASS criteria: ≥93%\n")
        f.write(f"- Status: {'✅ PASS' if accuracy >= 93 else '❌ FAIL'}\n\n")
        if failures:
            f.write(f"### Failures\n```json\n{json.dumps(failures, indent=2)}\n```\n\n")
        f.write(f"## Latency Benchmarks (median of 3)\n")
        f.write(f"| Tier | Median | Target | Status |\n|---|---|---|---|\n")
        targets = {"trivial": 3.0, "normal": 10.0, "complex": 18.0}
        for tier, med in medians.items():
            ok = med < targets[tier]
            f.write(f"| {tier} | {med:.2f}s | <{targets[tier]}s | {'✅' if ok else '❌'} |\n")

    print(f"Report: {out_path}")
    print(f"Accuracy: {accuracy:.1f}%")
    for tier, med in medians.items():
        print(f"{tier} median: {med:.2f}s")
    return 0 if accuracy >= 93 else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it**

```bash
cd /Users/ompandya/Desktop/friday && python tests/verify/run_verify.py
```
Expected: prints report path + accuracy + medians. If accuracy <93% or any latency over target → STOP, debug.

- [ ] **Step 3: Show Om the report**

```bash
cat docs/superpowers/verify/$(date +%Y-%m-%d)-phase1-verify.md
```

- [ ] **Step 4: Commit verify infrastructure**

```bash
cd /Users/ompandya/Desktop/friday
git add tests/verify/run_verify.py docs/superpowers/verify/
git commit -m "Phase C2: verification runner + first verify report"
```

---

### Task C3: Self-awareness manual tests

- [ ] **Step 1: Test runtime detection (local)**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
from truman.brain.loop import get_graph
g = get_graph()
r = g.invoke({'user_input': 'are you running on Railway?', 'session_id': 'verify', 'attach_ids': []})
print(r.get('response', ''))
" | grep -iE "local|railway|mac"
```
Expected: response contains "local" or "mac".

- [ ] **Step 2: Test capability awareness**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
from truman.brain.loop import get_graph
g = get_graph()
r = g.invoke({'user_input': 'what tools do you have right now?', 'session_id': 'verify', 'attach_ids': []})
print(r.get('response', ''))
"
```
Expected: response lists actual current tools (not generic).

- [ ] **Step 3: Document results**

Append to today's verify report (`docs/superpowers/verify/<date>-phase1-verify.md`):

```markdown
## Self-Awareness Manual Tests
- ✅ Runtime detection (local): correct
- ✅ Capability listing: real tools shown
```

- [ ] **Step 4: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add docs/superpowers/verify/
git commit -m "Phase C3: self-awareness manual verification"
```

---

### Task C4: Risk gate verification

- [ ] **Step 1: Test write_mac_file pause**

```bash
cd /Users/ompandya/Desktop/friday && python -c "
from truman.brain.loop import get_graph
g = get_graph()
r = g.invoke({'user_input': 'write hello to /tmp/test.txt', 'session_id': 'verify', 'attach_ids': []})
print('awaiting_confirm:', r.get('awaiting_confirm'))
print('response:', r.get('response'))
"
```
Expected: `awaiting_confirm: True`, response asks for confirmation.

- [ ] **Step 2: Verify file NOT written**

```bash
ls /tmp/test.txt 2>&1
```
Expected: `No such file` (file should NOT exist).

- [ ] **Step 3: Document + commit**

Append to verify report. Commit.

---

### Task C5: STOP — Phase C complete checkpoint

- [ ] Show Om the full verify report.
- [ ] Show all green checkmarks.
- [ ] Wait for Om's explicit "approved, push to Railway" before Phase D.

---

# Phase D — Ship + Canary

### Task D1: Show diff + get push approval

- [ ] **Step 1: Show full diff since last good commit**

```bash
cd /Users/ompandya/Desktop/friday && git log --oneline 5237e82..HEAD
```

- [ ] **Step 2: Show file count + line count changed**

```bash
cd /Users/ompandya/Desktop/friday && git diff --stat 5237e82..HEAD
```

- [ ] **Step 3: STOP — wait for explicit "push" from Om**

---

### Task D2: Push to Railway

- [ ] **Step 1: Push**

```bash
cd /Users/ompandya/Desktop/friday && git push origin main
```

- [ ] **Step 2: Wait + watch deploy**

```bash
sleep 90 && curl -s https://truman-production.up.railway.app/health
```
Expected: `{"status":"ok",...}`.

- [ ] **Step 3: Smoke test 5 messages on Railway**

```bash
for msg in "yo" "what's the weather in NYC" "look up risk_gate" "are you on railway" "list my goals"; do
  echo "=== $msg ==="
  curl -s -X POST https://truman-production.up.railway.app/api/chat \
    -H "Content-Type: application/json" \
    -d "{\"message\":\"$msg\",\"session_id\":\"verify_railway\"}" \
    --max-time 30 | python3 -m json.tool | head -20
done
```
Expected: all 5 return responses, no 504s, tool_calls present where appropriate.

- [ ] **Step 4: Set up canary monitoring**

Use the Control Panel → Fallbacks tab. Note baseline: 0 fallbacks.

- [ ] **Step 5: Tell Om: "Shipped. 48h canary started. Check Control Panel daily."**

---

### Task D3: 48h canary monitoring

For 48 hours after Phase D2, every ~12 hours:

- [ ] Check `https://truman-production.up.railway.app/api/control/fallback-stats`
- [ ] Confirm fallback rate <1%
- [ ] Confirm no high-severity events
- [ ] If breach → execute rollback:
  ```bash
  cd /Users/ompandya/Desktop/friday && git revert HEAD && git push origin main
  ```

After 48h zero-fallback → proceed to Phase E.

---

# Phase E — Cleanup

### Task E1: Delete legacy code

- [ ] **Step 1: Confirm canary passed**

Check Control Panel: 48h zero fallback banner visible.

- [ ] **Step 2: Delete legacy functions**

In `truman/text/agent.py`, delete:
- `_run_legacy()` function (~110 lines)
- `_call_llm()` function (~16 lines)
- `_call_llm_with_tools()` function (~45 lines)
- `_detect_tool()` function (~30 lines)
- `_extract_arg()` function (~80 lines)
- `_TOOL_PATTERNS` list (~25 lines)

- [ ] **Step 3: Update agent.py `run()` — remove fallback path**

Since legacy is gone, the LangGraph path is the only path. The TRANSIENT_ERRORS handler should now log + raise (not fall back):

```python
except TRANSIENT_ERRORS as e:
    log_fallback_event(reason="transient_no_fallback",
                       exception_type=type(e).__name__, message=str(e))
    raise  # surface to user — no legacy left
```

- [ ] **Step 4: All tests still pass**

```bash
cd /Users/ompandya/Desktop/friday && python -m pytest tests/ -v
```
Expected: 34 PASSED.

- [ ] **Step 5: Smoke test boot**

```bash
cd /Users/ompandya/Desktop/friday && timeout 15 python -m truman.main 2>&1 | grep -iE "online|error" | head -5
```
Expected: TRUMAN ONLINE banner, no errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/ompandya/Desktop/friday
git add truman/text/agent.py
git commit -m "Phase E: delete legacy fallback path (~306 lines) — canary passed"
```

- [ ] **Step 7: Show Om diff + ask permission to push**

```bash
cd /Users/ompandya/Desktop/friday && git log --oneline -1 && git diff HEAD~1 --stat
```

- [ ] **Step 8: Push after approval**

```bash
cd /Users/ompandya/Desktop/friday && git push origin main
```

- [ ] **Step 9: Verify Railway**

```bash
sleep 90 && curl -s https://truman-production.up.railway.app/health
```

- [ ] **Step 10: Done. Tell Om: "Phase 1 redo complete. Smart routing live, legacy gone."**

---

## Final Success Verification

Before marking the plan COMPLETE, verify all 10 success criteria from the spec:

- [ ] Trivial latency <2s on 3 trivial test messages
- [ ] Tool-using latency <8s on 3 normal test messages
- [ ] Heavy latency <15s on 3 complex test messages
- [ ] Tool selection accuracy ≥93% on 30-msg verify report
- [ ] Fallback rate <1% over 48h Railway canary
- [ ] "look up risk_gate" → gitnexus tool, never web_search
- [ ] "are you on Railway" → correct answer (depends on env)
- [ ] node_errors empty on normal turns
- [ ] Persona tone preserved (manual check by Om)
- [ ] No data loss: `db.recent_turns(10)` returns same 10 turns as before push

If any unchecked → STOP, debug, do not claim done.
