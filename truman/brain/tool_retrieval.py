"""tool_retrieval.py — semantic top-K tool binding.

Replaces bind_tools(ALL_TOOLS) with bind_tools(retrieve(msg)).
At boot: embed every tool description (cached in SQLite).
Per turn: embed user message, cosine similarity, return top-K.
"""
import hashlib
import math
import pickle
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
