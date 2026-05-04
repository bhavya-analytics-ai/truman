"""
eval.py — Truman's hybrid output evaluator (Phase 5).

Flow per turn:
  Rule check (instant, no LLM)
    → clean   → score=good, action=accept, done
    → flagged → LLM evaluator (llama-3.1-8b)
                → good  → accept
                → weak  → accept + log as optimization_candidate
                → bad   → retry once (same pool, injected hint)

Key design constraints:
  - TOOL_IGNORED uses deterministic token extraction (entities/IDs/numbers)
  - FACT_ANCHOR_MISMATCH only escalates if fact was active in prompt context
  - eval result keyed by turn_id — async cannot mutate execution path
  - retry hint is non-cumulative — only latest eval snapshot injected
  - async eval path never blocks response delivery
"""
from __future__ import annotations

import re
import string
from typing import Optional

# ── Issue codes ───────────────────────────────────────────────────────────────
EMPTY_SHORT          = "EMPTY_SHORT"
HALLUCINATED_BRACKET = "HALLUCINATED_BRACKET"
TOOL_IGNORED         = "TOOL_IGNORED"
GENERIC_RESPONSE     = "GENERIC_RESPONSE"
FACT_ANCHOR_MISMATCH = "FACT_ANCHOR_MISMATCH"

# ── Token extractor (deterministic — no vibes) ────────────────────────────────
_STOPWORDS = {
    "the","a","an","is","in","on","at","to","of","and","or","but","for",
    "with","this","that","it","as","be","by","from","are","was","were",
    "has","have","had","not","no","so","if","do","did","its","your","my",
    "we","i","you","he","she","they","their","our","result","error","ok",
    "true","false","none","null","success","failed","done","yes","no",
}

_BOILERPLATE = re.compile(
    r'(\{"result"|\[ok\]|\[error\]|status:|"status"|content:|"content")',
    re.I,
)

def _extract_tokens(text: str) -> set[str]:
    """
    Extract high-signal tokens: numbers, URLs, filenames, IDs (≥4 alphanum chars),
    capitalized identifiers. Exclude stopwords + tool boilerplate.
    """
    if not text:
        return set()

    tokens: set[str] = set()

    # numbers (including floats, percentages, currency)
    for m in re.finditer(r'\b\d[\d.,:%$]*\b', text):
        tokens.add(m.group())

    # URLs
    for m in re.finditer(r'https?://\S+', text):
        tokens.add(m.group()[:80])

    # filenames  (word.ext pattern)
    for m in re.finditer(r'\b\w+\.\w{2,5}\b', text):
        tokens.add(m.group().lower())

    # IDs / codes: ≥4 alphanumeric chars that aren't pure stopwords
    for m in re.finditer(r'\b[A-Za-z0-9_\-]{4,}\b', text):
        tok = m.group()
        if tok.lower() not in _STOPWORDS and not _BOILERPLATE.search(tok):
            tokens.add(tok.lower())

    # capitalized identifiers (proper nouns, class names, config keys)
    for m in re.finditer(r'\b[A-Z][a-zA-Z0-9_]{2,}\b', text):
        tok = m.group()
        if tok.lower() not in _STOPWORDS:
            tokens.add(tok.lower())

    return tokens


# ── Rule layer ────────────────────────────────────────────────────────────────

_HALLUCINATION_RE = re.compile(
    r'\[Tool result[^\]]*\]|\(hypothetical[^\)]*\)|\[MODEL:[^\]]*\]|'
    r'\[INTERNAL:[^\]]*\]|\[tool call[^\]]*\]',
    re.I,
)

_HARD_GENERIC_RE = re.compile(
    r'\bas an ai\b|\bi am an ai\b|\bi\'m an ai\b|\bcannot (help|assist|answer)\b',
    re.I,
)
_SOFT_UNCERTAINTY_RE = re.compile(
    r"\bi'?m not sure\b|\bi don'?t know\b|\buncertain\b",
    re.I,
)


def _rule_check(
    user_input: str,
    response: str,
    tool_result: Optional[str],
    tool_name: Optional[str],
    active_facts: list,   # facts that were in prompt context this turn
) -> dict:
    issues: list[str] = []

    # 1. EMPTY / TOO SHORT
    word_count = len(response.split()) if response else 0
    if word_count < 8:
        issues.append(EMPTY_SHORT)

    # 2. HALLUCINATED BRACKETS
    if _HALLUCINATION_RE.search(response or ""):
        issues.append(HALLUCINATED_BRACKET)

    # 3. TOOL IGNORED (soft token match — not strict string presence)
    if tool_result and tool_name and response:
        tool_tokens  = _extract_tokens(tool_result)
        resp_tokens  = _extract_tokens(response)
        overlap      = tool_tokens & resp_tokens
        # flagged only if tool had signal tokens AND none appear in response
        if tool_tokens and not overlap:
            issues.append(TOOL_IGNORED)

    # 4. GENERIC RESPONSE (hard fail only — not allowable uncertainty)
    if _HARD_GENERIC_RE.search(response or ""):
        issues.append(GENERIC_RESPONSE)
    elif _SOFT_UNCERTAINTY_RE.search(response or ""):
        # allowable if there's also content (word count > 20)
        if word_count < 20:
            issues.append(GENERIC_RESPONSE)

    # 5. FACT_ANCHOR_MISMATCH — only against facts active in this turn's prompt
    for fact_obj in active_facts:
        fact_str = fact_obj.get("fact", "") if isinstance(fact_obj, dict) else str(fact_obj)
        if not fact_str:
            continue
        # extract anchor tokens from fact
        fact_tokens = _extract_tokens(fact_str)
        if not fact_tokens:
            continue
        resp_lower = (response or "").lower()
        # flag only if response explicitly contains key fact tokens but contradicts core value
        # lightweight: check if numeric/ID tokens from fact appear with opposing context words
        _NEGATION = re.compile(r'\b(not|no|never|isn\'t|wasn\'t|aren\'t|doesn\'t|wrong)\b', re.I)
        for tok in fact_tokens:
            if re.search(r'\d', tok) and tok in resp_lower:
                # number from fact mentioned in response — check for negation nearby
                idx = resp_lower.find(tok)
                window = resp_lower[max(0, idx-40):idx+40]
                if _NEGATION.search(window):
                    issues.append(FACT_ANCHOR_MISMATCH)
                    break

    return {"flagged": bool(issues), "issues": issues}


# ── LLM evaluator ─────────────────────────────────────────────────────────────

_EVAL_SYSTEM = """You are a strict response quality evaluator. Evaluate the AI reply against the user's question.

Return JSON only — no other text:
{"score": "good"|"weak"|"bad", "issues": [...], "reason": "one line"}

Scoring:
- bad:  didn't answer, completely wrong, incoherent, empty, or ignored tool output
- weak: answered but incomplete, off-topic, vague, or missed key details
- good: answered correctly and completely

Issues list (use these codes only):
DID_NOT_ANSWER, INCOMPLETE, OFF_TOPIC, IGNORED_TOOL, INCOHERENT, VAGUE"""


def _llm_eval(user_input: str, response: str, tool_result: Optional[str] = None) -> dict:
    """Call llama-3.1-8b to score response. Returns {score, issues, reason}."""
    try:
        import json as _j
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage
        from truman.core.config import NVIDIA_API_KEY, NVIDIA_BASE_URL

        tool_block = f"\n\nTool output that should be used:\n{tool_result[:500]}" if tool_result else ""
        human = (
            f"User asked: {user_input[:300]}\n\n"
            f"AI replied: {response[:800]}"
            f"{tool_block}"
        )

        llm = ChatOpenAI(
            model="meta/llama-3.1-8b-instruct",
            api_key=NVIDIA_API_KEY,
            base_url=NVIDIA_BASE_URL,
            temperature=0.0,
            timeout=8,
            max_retries=0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        resp = llm.invoke([SystemMessage(content=_EVAL_SYSTEM), HumanMessage(content=human)])
        data = _j.loads(resp.content or "{}")
        score = data.get("score", "weak")
        if score not in ("good", "weak", "bad"):
            score = "weak"
        return {
            "score":  score,
            "issues": data.get("issues", []),
            "reason": data.get("reason", ""),
        }
    except Exception as e:
        # LLM eval failed → treat as weak (don't retry on eval failure)
        return {"score": "weak", "issues": ["EVAL_LLM_FAILED"], "reason": str(e)[:80]}


# ── Public interface ──────────────────────────────────────────────────────────

def evaluate(
    turn_id:      str,
    user_input:   str,
    response:     str,
    tool_result:  Optional[str] = None,
    tool_name:    Optional[str] = None,
    active_facts: list          = None,
) -> dict:
    """
    Hybrid evaluator. Returns eval bundle keyed by turn_id.
    Result is frozen — async path cannot mutate after this returns.

    Returns:
        {
          "turn_id":    str,
          "score":      "good" | "weak" | "bad",
          "issues":     [...],
          "action":     "accept" | "retry",
          "eval_type":  "rule" | "llm" | "none",
          "reason":     str,
          "weak_meta":  { "model": str, "pool": str, "issues": [...] } | None
        }
    """
    active_facts = active_facts or []

    # ── Rule layer ────────────────────────────────────────────────────────────
    rule = _rule_check(user_input, response, tool_result, tool_name, active_facts)

    if not rule["flagged"]:
        return {
            "turn_id":   turn_id,
            "score":     "good",
            "issues":    [],
            "action":    "accept",
            "eval_type": "rule",
            "reason":    "",
            "weak_meta": None,
        }

    # ── LLM layer (only on flagged) ───────────────────────────────────────────
    llm = _llm_eval(user_input, response, tool_result)
    score   = llm["score"]
    issues  = list(set(rule["issues"] + llm["issues"]))
    action  = "retry" if score == "bad" else "accept"

    weak_meta = None
    if score == "weak":
        weak_meta = {"issues": issues}   # model/pool added by node caller

    return {
        "turn_id":   turn_id,
        "score":     score,
        "issues":    issues,
        "action":    action,
        "eval_type": "llm",
        "reason":    llm.get("reason", ""),
        "weak_meta": weak_meta,
    }


def build_retry_hint(eval_result: dict) -> str:
    """
    One-line hint injected into system prompt on retry.
    Non-cumulative — only this eval's snapshot is used.
    """
    issues = ", ".join(eval_result.get("issues", [])) or "quality issue"
    return f"[EVAL RETRY] previous draft had issues: {issues}. give a complete, direct answer."
