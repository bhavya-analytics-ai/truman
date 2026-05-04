"""
model_router.py — Clean multi-provider model router for Truman.

Providers (prefix in pool slug):
  nvidia:     → NVIDIA NIM (primary, free)
  openrouter: → OpenRouter (last resort, free tier)
  bare slug   → assumes nvidia:

6 pools — strict priority routing, no scoring, no randomness:
  general, coding, reasoning, agentic, vision, docs

Rules:
  - ONE model per request. Priority chain: first match wins, no ties.
  - 1 primary + 1 fallback per pool. Primary retried once before fallback fires.
  - Dead/paid model → router tries fallback, pushes warning into response.
  - Session model override → forced model tried first, falls back to pool on failure.
"""

from __future__ import annotations

import re
import time
from typing import Literal, Optional

# ── Pool type ─────────────────────────────────────────────────────────────────
PoolName = Literal["general", "coding", "reasoning", "agentic", "vision", "docs"]

# ── Model metadata ────────────────────────────────────────────────────────────
MODEL_INFO: dict[str, str] = {
    "nvidia:meta/llama-3.1-8b-instruct":               "8B, ultra-fast (<1s), strong instruction follow",
    "nvidia:nvidia/llama-3.1-nemotron-nano-8b-v1":     "8B nano, NVIDIA-optimized for speed",
    "nvidia:nvidia/llama-3.3-nemotron-super-49b-v1":   "49B, fast, agentic, strong instruction follow",
    "nvidia:moonshotai/kimi-k2-instruct":               "MoE, general + coding, 128K ctx",
    "nvidia:moonshotai/kimi-k2-thinking":               "reasoning, 256K ctx, deep think",
    "nvidia:stepfun-ai/step-3.5-flash":                 "200B sparse MoE, fast agentic AI",
    "nvidia:qwen/qwen3-coder-480b-a35b-instruct":       "480B/35B active, best coder, 256K ctx",
    "nvidia:meta/llama-3.3-70b-instruct":               "70B, solid general + coding, fast",
    "nvidia:meta/llama-3.2-90b-vision-instruct":        "90B, top-tier vision, best image accuracy",
    "nvidia:meta/llama-4-scout-17b-16e-instruct":       "17B MoE, fast vision fallback",
    "nvidia:meta/llama-4-maverick-17b-128e-instruct":   "1M ctx, doc processing, multimodal",
    "nvidia:mistralai/devstral-2-123b-instruct-2512":   "Mistral code model, deep reasoning, 256K ctx",
    "openrouter:deepseek/deepseek-r1:free":             "reasoning, last resort",
    "openrouter:openai/gpt-oss-120b:free":              "general, last resort",
}

# ── Agent system prompts — injected per pool ──────────────────────────────────
AGENT_PROMPTS: dict[str, str] = {
    "coding":    "You are a senior software engineer. Write clean, production-ready code. Be precise, no fluff. If something is wrong, say so directly.",
    "docs":      "You are a document specialist. Generate clean, well-structured content. Be precise with formatting and data.",
    "vision":    "You are a vision analysis expert. Analyze images, diagrams, and visual content with precision. Describe what you see clearly and extract useful information.",
    "general":   "You are Truman, Om's personal AI. Be direct, casual, sharp. Match his energy.",
    "reasoning": "You are a deep reasoning engine. Think step by step, consider all angles, then give a clear well-justified answer.",
    "agentic":   "You are an autonomous agent. Plan, execute, use tools, iterate. Complete the task fully without waiting for confirmation unless destructive.",
}

# ── Session-level model override ──────────────────────────────────────────────
_session_model: Optional[str] = None

def set_session_model(slug: str) -> str:
    global _session_model
    _session_model = _resolve_slug(slug)
    return _session_model

def clear_session_model():
    global _session_model
    _session_model = None

def get_session_model() -> Optional[str]:
    return _session_model

# ── Slug resolver ─────────────────────────────────────────────────────────────
_ALIASES = {
    "llama8b":       "nvidia:meta/llama-3.1-8b-instruct",
    "llama-8b":      "nvidia:meta/llama-3.1-8b-instruct",
    "fast":          "nvidia:meta/llama-3.1-8b-instruct",
    "nano":          "nvidia:nvidia/llama-3.1-nemotron-nano-8b-v1",
    "nemotron-nano": "nvidia:nvidia/llama-3.1-nemotron-nano-8b-v1",
    "nemotron":      "nvidia:nvidia/llama-3.3-nemotron-super-49b-v1",
    "kimi":          "nvidia:moonshotai/kimi-k2-instruct",
    "kimi-think":    "nvidia:moonshotai/kimi-k2-thinking",
    "step":          "nvidia:stepfun-ai/step-3.5-flash",
    "qwen":          "nvidia:qwen/qwen3-coder-480b-a35b-instruct",
    "llama":         "nvidia:meta/llama-3.3-70b-instruct",
    "llama70":       "nvidia:meta/llama-3.3-70b-instruct",
    "maverick":      "nvidia:meta/llama-4-maverick-17b-128e-instruct",
    "devstral":      "nvidia:mistralai/devstral-2-123b-instruct-2512",
}

def _resolve_slug(slug: str) -> str:
    s = slug.strip().lower()
    if s in _ALIASES:
        return _ALIASES[s]
    if not any(s.startswith(p) for p in ("nvidia:", "openrouter:")):
        return f"nvidia:{s}"
    return s

# ── Pool loader ───────────────────────────────────────────────────────────────
def _parse_pool(env_val: str) -> list[str]:
    return [s.strip() for s in env_val.split(",") if s.strip()]

def _load_pools() -> dict[str, list[str]]:
    from truman.core.config import (
        POOL_GENERAL, POOL_CODING, POOL_REASONING,
        POOL_AGENTIC, POOL_VISION, POOL_DOCS,
    )
    return {
        "general":   _parse_pool(POOL_GENERAL),
        "coding":    _parse_pool(POOL_CODING),
        "reasoning": _parse_pool(POOL_REASONING),
        "agentic":   _parse_pool(POOL_AGENTIC),
        "vision":    _parse_pool(POOL_VISION),
        "docs":      _parse_pool(POOL_DOCS),
    }

POOLS: dict[str, list[str]] = {}

def _get_pools() -> dict[str, list[str]]:
    global POOLS
    if not POOLS:
        POOLS = _load_pools()
    return POOLS

def list_pool_models(pool: str | None = None) -> dict[str, list[dict]]:
    pools = _get_pools()
    target = {pool: pools[pool]} if pool and pool in pools else pools
    return {
        p: [{"slug": s, "info": MODEL_INFO.get(s, "no description")} for s in slugs]
        for p, slugs in target.items()
    }

# ── Intent detection helpers ──────────────────────────────────────────────────

def _mentions_code_context(text: str) -> bool:
    """Detect code/debug context — catches raw logs and stack traces too."""
    t = text.lower()
    # keyword hits
    if any(k in t for k in ["error", "traceback", "exception", "stack", "bug", "crash", "fails", "code"]):
        return True
    # explicit stack trace header
    if "traceback (most recent call last)" in t:
        return True
    # log-style patterns
    if any(p in t for p in ["line ", "file ", " at line", " -> "]):
        return True
    # code fence present
    if "```" in text:
        return True
    return False


_CODE_ACTIONS = {"write", "fix", "implement", "refactor", "build", "compile", "debug"}
_CODE_RUN_TERMS = {"script", "code", "program", "test", "function", "class"}

def _is_pure_code_request(text: str) -> bool:
    """True for action-verb code requests. 'run' only counts if paired with code terms."""
    t = text.lower()
    # code fence = always code
    if "```" in text:
        return True
    # standard action verbs
    if any(a in t for a in _CODE_ACTIONS):
        return True
    # 'run' only when paired with code terms (avoids "run through the idea")
    if "run" in t and any(k in t for k in _CODE_RUN_TERMS):
        return True
    return False


_REASONING_KW = {
    "why", "analyze", "analyse", "compare", "explain", "trade-off", "tradeoff",
    "difference between", "pros and cons", "break down", "walk me through",
    "deep dive", "evaluate", "assess", "implications", "pros", "cons",
}

def _is_reasoning_or_explain(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in _REASONING_KW)


_DOC_KW = {
    "pdf", "document", "docx", "excel", "spreadsheet", "pptx", "powerpoint",
    "report", "template", "xlsx", "presentation", "summarize this file",
    "summarize this document", "read this file", "read this document",
    "analyze this report", "this pdf",
}

def _is_doc_request(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in _DOC_KW)


# ── Priority router ───────────────────────────────────────────────────────────

def detect_pool_with_reason(
    message: str,
    has_image: bool = False,
    tool_detected: Optional[str] = None,
) -> tuple:
    """
    Strict priority chain — first match wins, no scoring, no ties.
    Returns (pool, reason_code, matched_tokens).
    Safe wrapper — always returns ("general", "ROUTER_ERROR", "none") on failure.
    """
    try:
        t = message.lower()

        if has_image:
            return "vision", "HAS_IMAGE", "image_attached"

        if tool_detected:
            return "agentic", "TOOL_DETECTED", tool_detected

        if _is_doc_request(message):
            matched = [k for k in _DOC_KW if k in t]
            return "docs", "DOC_KEYWORD", ",".join(matched[:3])

        if _is_pure_code_request(message):
            matched = [a for a in _CODE_ACTIONS if a in t]
            if "```" in message:
                matched.append("code_fence")
            return "coding", "CODE_ACTION_VERB", ",".join(matched[:3]) or "code_fence"

        if _is_reasoning_or_explain(message):
            if _mentions_code_context(message):
                matched = [k for k in ["error","traceback","bug","crash","code","exception"] if k in t]
                if "```" in message: matched.append("code_fence")
                return "coding", "CODE_CONTEXT", ",".join(matched[:3])
            matched = [k for k in _REASONING_KW if k in t]
            return "reasoning", "EXPLAIN_KEYWORD", ",".join(list(matched)[:3])

        # Raw stack traces / error dumps with no action verb or explain keyword
        if _mentions_code_context(message):
            matched = [k for k in ["error","traceback","bug","crash","code","exception","line ","file "] if k in t]
            if "```" in message: matched.append("code_fence")
            return "coding", "CODE_CONTEXT_DIRECT", ",".join(matched[:3])

        return "general", "NO_MATCH", "none"

    except Exception:
        return "general", "ROUTER_ERROR", "none"


def detect_pool(
    message: str,
    has_image: bool = False,
    tool_detected: Optional[str] = None,
) -> str:
    pool, _, _ = detect_pool_with_reason(message, has_image=has_image, tool_detected=tool_detected)
    return pool


# ── Short display label ───────────────────────────────────────────────────────
def short_label(slug: str) -> str:
    if slug.startswith("openrouter:"):
        return "or:" + slug.split("/")[-1].split(":")[0]
    model = slug.replace("nvidia:", "").split(":")[0]
    short = {
        "meta/llama-3.1-8b-instruct":               "llama3.1-8b",
        "nvidia/llama-3.1-nemotron-nano-8b-v1":     "nemotron-nano",
        "nvidia/llama-3.3-nemotron-super-49b-v1":   "nemotron-49b",
        "moonshotai/kimi-k2-instruct":               "kimi-k2",
        "moonshotai/kimi-k2-thinking":               "kimi-k2-think",
        "stepfun-ai/step-3.5-flash":                 "step-flash",
        "qwen/qwen3-coder-480b-a35b-instruct":       "qwen3-coder",
        "meta/llama-3.3-70b-instruct":               "llama3.3-70b",
        "meta/llama-3.2-90b-vision-instruct":        "llama3.2-90b-vision",
        "meta/llama-4-scout-17b-16e-instruct":       "llama4-scout",
        "meta/llama-4-maverick-17b-128e-instruct":   "llama4-maverick",
        "mistralai/devstral-2-123b-instruct-2512":   "devstral-123b",
    }
    return short.get(model, model.split("/")[-1])


# ── Error classifier ──────────────────────────────────────────────────────────
def _classify_error(e: Exception, slug: str) -> tuple:
    """Returns (is_error, warn_msg, fail_reason)."""
    msg = str(e).lower()
    label = short_label(slug)
    if any(x in msg for x in ("402", "insufficient credits", "out of credits", "payment", "billing", "quota exceeded")):
        return True, f"⚠️ {label} went paid/out of credits — switched to next model.", "rate_limit"
    if any(x in msg for x in ("404", "no endpoints found", "model not found", "does not exist")):
        return True, f"⚠️ {label} is no longer available — switched to next model.", "http_error"
    if any(x in msg for x in ("429", "rate limit", "too many requests", "temporarily")):
        return True, "", "rate_limit"
    if any(x in msg for x in ("401", "403", "unauthorized", "invalid api key")):
        return True, f"⚠️ Auth error on {label} — check your API key.", "http_error"
    if any(x in msg for x in ("timeout", "timed out", "read timeout", "connect timeout")):
        return True, "", "timeout"
    return True, f"⚠️ {label} failed ({type(e).__name__}) — switched to next model.", "http_error"


# ── LLM builder ───────────────────────────────────────────────────────────────
def _build_llm(slug: str, temperature: float, tools: Optional[list] = None, timeout: int = 10):
    from langchain_openai import ChatOpenAI
    from truman.core.config import (
        NVIDIA_API_KEY, NVIDIA_BASE_URL,
        OPENROUTER_API_KEY, OPENROUTER_BASE_URL,
    )
    if slug.startswith("openrouter:"):
        llm = ChatOpenAI(model=slug[11:], api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL,
                         temperature=temperature, timeout=timeout, max_retries=0)
    else:
        model = slug.replace("nvidia:", "")
        llm = ChatOpenAI(model=model, api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL,
                         temperature=temperature, timeout=timeout, max_retries=0)
    return llm.bind_tools(tools) if tools else llm


def _extract_result(resp, slug: str, pool: str, warnings: list) -> dict:
    tool_calls: list[dict] = []
    if hasattr(resp, "tool_calls") and resp.tool_calls:
        for tc in resp.tool_calls:
            tool_calls.append({"name": tc.get("name", ""), "args": tc.get("args", {})})
    elif hasattr(resp, "additional_kwargs"):
        for tc in (resp.additional_kwargs.get("tool_calls") or []):
            fn = tc.get("function", {})
            tool_calls.append({"name": fn.get("name", ""), "args": fn.get("arguments", "{}")})
    return {
        "content":    resp.content or "",
        "model":      short_label(slug),
        "pool":       pool,
        "tool_calls": tool_calls,
        "warnings":   warnings,
    }


# ── Core executor ─────────────────────────────────────────────────────────────
def run_with_pool(
    messages: list,
    pool: Optional[str] = None,
    user_message: str = "",
    temperature: float = 0.7,
    tools: Optional[list] = None,
    has_image: bool = False,
    tool_detected: Optional[str] = None,
) -> dict:
    """
    1 primary + 1 fallback per pool.
    Retry sequence: primary (6s) → retry primary (3s) → fallback (10s).
    All failures logged with fail_reason + latency breakdown.
    """
    pools = _get_pools()
    chosen_pool, route_reason, matched = detect_pool_with_reason(
        user_message, has_image=has_image, tool_detected=tool_detected
    )
    if pool:
        chosen_pool = pool   # explicit override from caller

    model_list = list(pools.get(chosen_pool, pools["general"]))

    # Session override → forced model first
    if _session_model:
        model_list = [_session_model] + [m for m in model_list if m != _session_model]

    primary  = model_list[0] if model_list else "nvidia:meta/llama-3.3-70b-instruct"
    fallback = model_list[1] if len(model_list) > 1 else "nvidia:meta/llama-3.1-8b-instruct"

    warnings_out: list[str] = []

    from truman.core.config import NVIDIA_API_KEY, OPENROUTER_API_KEY

    def _has_key(slug: str) -> bool:
        if slug.startswith("openrouter:"):
            return bool(OPENROUTER_API_KEY)
        return bool(NVIDIA_API_KEY)

    # ── Attempt 1: primary, 6s ────────────────────────────────────────────────
    t0 = time.time()
    primary_fail_reason = None
    if _has_key(primary):
        try:
            resp = _build_llm(primary, temperature, tools, timeout=6).invoke(messages)
            latency_primary = round(time.time() - t0, 1)
            print(f"[MODEL] primary={short_label(primary)} status=ok latency_primary={latency_primary}s total={latency_primary}s")
            result = _extract_result(resp, primary, chosen_pool, warnings_out)
            result["latency"] = {"primary": latency_primary, "total": latency_primary}
            return result
        except Exception as e:
            latency_primary = round(time.time() - t0, 1)
            _, warn, primary_fail_reason = _classify_error(e, primary)
            if warn:
                warnings_out.append(warn)
                print(warn)

    # ── Attempt 2: retry primary, 3s ─────────────────────────────────────────
    t1 = time.time()
    retry_fail_reason = None
    if _has_key(primary):
        try:
            resp = _build_llm(primary, temperature, tools, timeout=3).invoke(messages)
            latency_primary = round(time.time() - t0 - (time.time() - t1), 1)  # approx
            latency_retry   = round(time.time() - t1, 1)
            total = round(time.time() - t0, 1)
            print(f"[MODEL] primary={short_label(primary)} status=failed_{primary_fail_reason} retry=retry_ok latency_primary={latency_primary}s latency_retry={latency_retry}s total={total}s")
            result = _extract_result(resp, primary, chosen_pool, warnings_out)
            result["latency"] = {"primary": latency_primary, "retry": latency_retry, "total": total}
            return result
        except Exception as e:
            latency_retry = round(time.time() - t1, 1)
            _, _, retry_fail_reason = _classify_error(e, primary)

    # ── Attempt 3: fallback, 10s ──────────────────────────────────────────────
    t2 = time.time()
    if _has_key(fallback) and fallback != primary:
        try:
            resp = _build_llm(fallback, temperature, tools, timeout=10).invoke(messages)
            latency_fallback = round(time.time() - t2, 1)
            total = round(time.time() - t0, 1)
            print(f"[MODEL] primary={short_label(primary)} status=failed_{primary_fail_reason} retry=failed_{retry_fail_reason} fallback={short_label(fallback)} status=fallback_ok latency_fallback={latency_fallback}s total={total}s")
            warn_msg = f"⚠️ {short_label(primary)} unavailable — used {short_label(fallback)}"
            warnings_out.append(warn_msg)
            result = _extract_result(resp, fallback, chosen_pool, warnings_out)
            result["latency"] = {"fallback": latency_fallback, "total": total}
            return result
        except Exception as e:
            latency_fallback = round(time.time() - t2, 1)
            _, warn, _ = _classify_error(e, fallback)
            if warn:
                warnings_out.append(warn)

    # ── Last resort: hardcoded reliable models ────────────────────────────────
    _LAST_RESORT = [
        "nvidia:meta/llama-3.3-70b-instruct",
        "nvidia:meta/llama-3.1-8b-instruct",
        "nvidia:moonshotai/kimi-k2-instruct",
    ]
    for slug in _LAST_RESORT:
        if slug in (primary, fallback):
            continue
        try:
            resp = _build_llm(slug, temperature, timeout=10).invoke(messages)
            total = round(time.time() - t0, 1)
            print(f"[MODEL] last_resort={short_label(slug)} status=ok total={total}s")
            result = _extract_result(resp, slug, chosen_pool, warnings_out)
            result["warnings"].append(f"⚠️ pool '{chosen_pool}' primary+fallback failed — used last resort {short_label(slug)}")
            return result
        except Exception:
            continue

    total = round(time.time() - t0, 1)
    print(f"[MODEL] all_failed pool={chosen_pool} total={total}s")
    return {
        "content":    f"all models in the {chosen_pool} pool failed — please try again",
        "model":      "none",
        "pool":       chosen_pool,
        "tool_calls": [],
        "warnings":   warnings_out,
        "latency":    {"total": total},
    }


# ── Pipeline mode (explicit only — never auto) ────────────────────────────────
def run_pipeline(user_message: str, pool: PoolName = "coding") -> dict:
    """
    3-stage pipeline. Only runs when Om explicitly triggers it.
    Stage 1 — kimi-k2-thinking : reason and plan
    Stage 2 — pool primary     : generate from plan
    Stage 3 — llama-3.3-70b   : review and finalise
    """
    from langchain_core.messages import SystemMessage, HumanMessage

    REASONER  = "nvidia:moonshotai/kimi-k2-thinking"
    REVIEWER  = "nvidia:meta/llama-3.3-70b-instruct"
    pools     = _get_pools()
    generator = pools.get(pool, pools["coding"])[0]

    warnings: list[str] = []
    stages:   list[dict] = []

    def _call(slug, sys_msg, human_msg, temp=0.3):
        try:
            llm  = _build_llm(slug, temp, timeout=30)
            resp = llm.invoke([SystemMessage(content=sys_msg), HumanMessage(content=human_msg)])
            return resp.content or ""
        except Exception as e:
            _, w, _ = _classify_error(e, slug)
            if w: warnings.append(w)
            return None

    plan = _call(REASONER,
                 "You are a planning engine. Think step by step and produce a clear numbered plan. Do NOT write the final output yet.",
                 user_message) or user_message
    stages.append({"stage": "reason", "model": short_label(REASONER), "output": plan})

    generated = _call(generator,
                      "You are a precise generator. Execute the plan below exactly. Produce final output only.",
                      f"Request:\n{user_message}\n\nPlan:\n{plan}", temp=0.5) or plan
    stages.append({"stage": "generate", "model": short_label(generator), "output": generated})

    final = _call(REVIEWER,
                  "You are a senior reviewer. Fix anything wrong and return the final polished version only.",
                  f"Request:\n{user_message}\n\nOutput:\n{generated}") or generated
    stages.append({"stage": "review", "model": short_label(REVIEWER), "output": final})

    used = " → ".join(s["model"] for s in stages)
    return {
        "content":         f"[pipeline: {used}]\n\n{final}",
        "model":           used,
        "pool":            pool,
        "tool_calls":      [],
        "warnings":        warnings,
        "pipeline_stages": stages,
    }
