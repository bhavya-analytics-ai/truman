"""tier_router.py — first node in the new graph.

Returns a RoutingDecision telling the rest of the graph:
  - which tier to use (trivial / normal / complex)
  - which model pool to use
  - what runtime context applies
  - reasons for the decision (for telemetry)

Regex first (fast), tiny LLM fallback if regex is unsure.
"""
import re
from truman.core.runtime import is_railway

# Regex patterns — each maps to (tier, pool, reason)
_TRIVIAL_PATTERNS = [
    (r"^\s*(yo|hi|hey|sup|hello|hola|gm|gn|good\s*(morning|night))\s*[!?.]*\s*$", "greeting"),
    (r"^\s*(thanks?|ty|thx|thank you|cool|nice|ok|okay|sure|got it|sweet|lol|ok cool|sounds good|fair enough|makes sense)\s*(man|bro|dude|mate|yo|boss)?\s*[!?.]*\s*$", "ack"),
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
