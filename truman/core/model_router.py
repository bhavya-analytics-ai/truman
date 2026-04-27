"""
model_router.py — Clean multi-provider model router for Truman.

Providers (prefix in pool slug):
  nvidia:     → NVIDIA NIM (primary, free)
  openrouter: → OpenRouter (last resort, free tier)
  bare slug   → assumes nvidia:

9 pools — one per agent type:
  coding, creative, design, docs, vision, general, reasoning, fast, agentic

Rules:
  - ONE model per request. Pipeline only fires when Om explicitly calls pipeline_mode tool.
  - Complexity detection picks the RIGHT pool — never runs multiple models simultaneously.
  - Dead/paid model → router tries next, pushes warning into response so Om sees it in dashboard.
  - Session model override → forced model tried first, falls back to pool on failure.
"""

import re
from typing import Literal

# ── Pool type ─────────────────────────────────────────────────────────────────
PoolName = Literal["coding", "creative", "design", "docs", "vision",
                   "general", "reasoning", "fast", "agentic"]

# ── Model metadata ────────────────────────────────────────────────────────────
MODEL_INFO: dict[str, str] = {
    # NVIDIA NIM
    "nvidia:qwen3-coder-480b-a35b-instruct":    "480B/35B active, agentic coding, 256K ctx",
    "nvidia:devstral-2-123b-instruct-2512":      "Mistral code model, deep reasoning, 256K ctx",
    "nvidia:glm-4.7":                            "tool calling, agentic coding, multilingual",
    "nvidia:kimi-k2-thinking":                   "reasoning + creative, 256K ctx, tool use",
    "nvidia:mistral-large-3-675b-instruct-2512": "675B MoE VLM, creative, multimodal",
    "nvidia:deepseek-v3.2":                      "685B reasoning, long context, agentic tools",
    "nvidia:step-3.5-flash":                     "200B sparse MoE, frontier agentic AI",
    "nvidia:minimax-m2.7":                       "230B, trained on Word/Excel/PPT workflows",
    "nvidia:mistral-medium-3-instruct":          "multimodal, software dev, data analysis",
    "nvidia:llama-4-maverick-17b-128e-instruct": "multimodal, 128 MoE, vision capable",
    "nvidia:deepseek-v3.1-terminus":             "hybrid Think/Non-Think, strict function calling",
    "nvidia:mistral-nemotron":                   "agentic workflows, coding, function calling",
    # OpenRouter
    "openrouter:deepseek/deepseek-r1:free":     "reasoning, last resort",
    "openrouter:openai/gpt-oss-120b:free":      "general, last resort",
}

# ── Agent system prompts — injected per pool ──────────────────────────────────
AGENT_PROMPTS: dict[str, str] = {
    "coding":    "You are a senior software engineer. Write clean, production-ready code. Be precise, no fluff. If something is wrong, say so directly.",
    "creative":  "You are a creative thinker and storyteller. Generate bold ideas, fresh angles, compelling narratives. Think laterally. Be imaginative but grounded.",
    "design":    "You are a system architect and innovation strategist. Think in systems, trade-offs, and scalability. Propose structured, well-reasoned designs.",
    "docs":      "You are a document specialist. Generate clean, well-structured Word docs, Excel sheets, and PowerPoint content. Be precise with formatting and data.",
    "vision":    "You are a vision analysis expert. Analyze images, diagrams, and visual content with precision. Describe what you see clearly and extract useful information.",
    "general":   "You are Truman, Om's personal AI. Be direct, casual, sharp. Match his energy.",
    "reasoning": "You are a deep reasoning engine. Think step by step, consider all angles, then give a clear well-justified answer.",
    "fast":      "You are Truman. Answer fast and direct. One or two sentences max unless more is needed.",
    "agentic":   "You are an autonomous agent. Plan, execute, use tools, iterate. Complete the task fully without waiting for confirmation unless destructive.",
}

# ── Session-level model override ──────────────────────────────────────────────
_session_model: str | None = None

def set_session_model(slug: str) -> str:
    global _session_model
    _session_model = _resolve_slug(slug)
    return _session_model

def clear_session_model():
    global _session_model
    _session_model = None

def get_session_model() -> str | None:
    return _session_model

# ── Slug resolver ─────────────────────────────────────────────────────────────
_ALIASES = {
    "glm":       "nvidia:glm-4.7",
    "qwen":      "nvidia:qwen3-coder-480b-a35b-instruct",
    "devstral":  "nvidia:devstral-2-123b-instruct-2512",
    "kimi":      "nvidia:kimi-k2-thinking",
    "mistral":   "nvidia:mistral-large-3-675b-instruct-2512",
    "deepseek":  "nvidia:deepseek-v3.2",
    "step":      "nvidia:step-3.5-flash",
    "minimax":   "nvidia:minimax-m2.7",
    "maverick":  "nvidia:llama-4-maverick-17b-128e-instruct",
    "terminus":  "nvidia:deepseek-v3.1-terminus",
    "nemotron":  "nvidia:mistral-nemotron",
}

def _resolve_slug(slug: str) -> str:
    s = slug.strip().lower()
    if s in _ALIASES:
        return _ALIASES[s]
    # bare slug with no prefix → assume nvidia
    if not any(s.startswith(p) for p in ("nvidia:", "openrouter:")):
        return f"nvidia:{s}"
    return s

# ── Pool loader ───────────────────────────────────────────────────────────────
def _parse_pool(env_val: str) -> list[str]:
    return [s.strip() for s in env_val.split(",") if s.strip()]

def _load_pools() -> dict[str, list[str]]:
    from truman.core.config import (
        POOL_CODING, POOL_CREATIVE, POOL_DESIGN, POOL_DOCS, POOL_VISION,
        POOL_GENERAL, POOL_REASONING, POOL_FAST, POOL_AGENTIC,
    )
    return {
        "coding":    _parse_pool(POOL_CODING),
        "creative":  _parse_pool(POOL_CREATIVE),
        "design":    _parse_pool(POOL_DESIGN),
        "docs":      _parse_pool(POOL_DOCS),
        "vision":    _parse_pool(POOL_VISION),
        "general":   _parse_pool(POOL_GENERAL),
        "reasoning": _parse_pool(POOL_REASONING),
        "fast":      _parse_pool(POOL_FAST),
        "agentic":   _parse_pool(POOL_AGENTIC),
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

# ── Intent detection → pool ───────────────────────────────────────────────────
_CODING_KW    = re.compile(r"\b(code|debug|function|script|class|implement|refactor|bug|syntax|compile|endpoint|import|module|variable|method|library|package|git\s+clone|git\s+push|git\s+pull|pull\s+request|lint|async|await|sql\s+query|json\s+parse|write\s+a\s+function|write\s+a\s+script|write\s+code|fix\s+this\s+code|fix\s+the\s+bug|run\s+this\s+script)\b", re.I)
_CREATIVE_KW  = re.compile(r"\b(idea|creative|brainstorm|polish|improve|suggest|what if|innovate|vision|concept|pitch|story|name|brand|spin|angle|rethink)\b", re.I)
_DESIGN_KW    = re.compile(r"\b(structure|architect|best way|organize|schema|database|approach|strategy|stack|framework|scalable|workflow)\b", re.I)
_DOCS_KW      = re.compile(r"\b(document|doc|word|excel|spreadsheet|pptx|powerpoint|slide|table|report|template|pdf|xlsx|docx|sheet|presentation|write.?up)\b", re.I)
_VISION_KW    = re.compile(r"\b(image|photo|screenshot|picture|diagram|chart|visual|look at|read this image|what.?s in|analyze this|describe this)\b", re.I)
_REASONING_KW = re.compile(r"\b(why|analyze|analyse|compare|explain|trade.?off|difference between|pros and cons|break.?down|walk.?me.?through|deep.?dive|evaluate|assess|implications)\b", re.I)
_FAST_KW      = re.compile(r"\b(quick|fast|briefly|tldr|short|just tell me|one line|simple)\b", re.I)
_AGENTIC_KW   = re.compile(r"\b(do it|execute|run this|automate|agent|autonomously|go ahead|just do)\b", re.I)

def detect_pool(message: str) -> PoolName:
    msg = message.lower()
    scores = {
        "coding":    len(_CODING_KW.findall(msg)),
        "creative":  len(_CREATIVE_KW.findall(msg)),
        "design":    len(_DESIGN_KW.findall(msg)),
        "docs":      len(_DOCS_KW.findall(msg)),
        "vision":    len(_VISION_KW.findall(msg)),
        "reasoning": len(_REASONING_KW.findall(msg)),
        "fast":      len(_FAST_KW.findall(msg)),
        "agentic":   len(_AGENTIC_KW.findall(msg)),
    }
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "general"
    # tiebreaker: coding beats design (they share structural words)
    if scores["coding"] == scores["design"] and scores["coding"] > 0:
        return "coding"
    return best

# ── Short display label ───────────────────────────────────────────────────────
def short_label(slug: str) -> str:
    if slug.startswith("openrouter:"):
        return "or:" + slug.split("/")[-1].split(":")[0]
    model = slug.replace("nvidia:", "").split(":")[0]
    short = {
        "qwen3-coder-480b-a35b-instruct":    "qwen3-coder-480b",
        "devstral-2-123b-instruct-2512":      "devstral-2-123b",
        "mistral-large-3-675b-instruct-2512": "mistral-large-675b",
        "llama-4-maverick-17b-128e-instruct": "llama4-maverick",
        "deepseek-v3.1-terminus":             "deepseek-v3.1",
        "mistral-medium-3-instruct":          "mistral-medium-3",
    }
    return short.get(model, model)

# ── Error classifier ──────────────────────────────────────────────────────────
def _classify_error(e: Exception, slug: str) -> tuple[bool, str]:
    msg = str(e).lower()
    label = short_label(slug)
    if any(x in msg for x in ("402", "insufficient credits", "out of credits", "payment", "billing", "quota exceeded")):
        return True, f"⚠️ {label} went paid/out of credits — switched to next model. Update POOL_* in Railway to swap it out."
    if any(x in msg for x in ("404", "no endpoints found", "model not found", "does not exist")):
        return True, f"⚠️ {label} is no longer available — switched to next model. Update POOL_* in Railway to swap it out."
    if any(x in msg for x in ("429", "rate limit", "too many requests", "temporarily")):
        return True, ""   # silent retry
    if any(x in msg for x in ("401", "403", "unauthorized", "invalid api key")):
        return True, f"⚠️ Auth error on {label} — check your API key for that provider."
    return True, f"⚠️ {label} failed ({type(e).__name__}) — switched to next model."

# ── LLM builder ───────────────────────────────────────────────────────────────
def _build_llm(slug: str, temperature: float, tools: list | None = None):
    from langchain_openai import ChatOpenAI
    from truman.core.config import (
        NVIDIA_API_KEY, NVIDIA_BASE_URL,
        OPENROUTER_API_KEY, OPENROUTER_BASE_URL,
    )
    if slug.startswith("openrouter:"):
        llm = ChatOpenAI(model=slug[11:], api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL, temperature=temperature)
    else:
        model = slug.replace("nvidia:", "")
        llm = ChatOpenAI(model=model, api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL, temperature=temperature)
    return llm.bind_tools(tools) if tools else llm

# ── Core executor ─────────────────────────────────────────────────────────────
def run_with_pool(
    messages: list,
    pool: PoolName | None = None,
    user_message: str = "",
    temperature: float = 0.7,
    tools: list | None = None,
) -> dict:
    """
    Single model per request. Cascading fallback across providers.
    Dead/paid model warnings surface in the response so Om sees them in dashboard.
    """
    pools       = _get_pools()
    chosen_pool = pool or detect_pool(user_message)
    model_list  = list(pools.get(chosen_pool, pools["general"]))

    # Session override → try forced model first
    if _session_model:
        model_list = [_session_model] + [m for m in model_list if m != _session_model]

    warnings_out: list[str] = []
    last_error:   str       = ""

    for slug in model_list:
        # Skip if provider key missing
        from truman.core.config import NVIDIA_API_KEY, OPENROUTER_API_KEY
        if slug.startswith("openrouter:") and not OPENROUTER_API_KEY:
            continue
        if not slug.startswith("openrouter:") and not NVIDIA_API_KEY:
            continue

        try:
            llm  = _build_llm(slug, temperature, tools)
            resp = llm.invoke(messages)

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
                "pool":       chosen_pool,
                "tool_calls": tool_calls,
                "warnings":   warnings_out,
            }

        except Exception as e:
            _, warn = _classify_error(e, slug)
            if warn:
                warnings_out.append(warn)
                print(warn)
            last_error = str(e)
            continue

    return {
        "content":    f"all models in the {chosen_pool} pool failed. last error: {last_error}",
        "model":      "none",
        "pool":       chosen_pool,
        "tool_calls": [],
        "warnings":   warnings_out,
    }

# ── Pipeline mode (explicit only — never auto) ────────────────────────────────
def run_pipeline(user_message: str, pool: PoolName = "coding") -> dict:
    """
    3-stage pipeline. Only runs when Om explicitly triggers it.
    Stage 1 — deepseek-v3.2 : reason and plan
    Stage 2 — pool primary  : generate from plan
    Stage 3 — glm-4.7       : review and finalise
    """
    from langchain_core.messages import SystemMessage, HumanMessage

    REASONER  = "nvidia:deepseek-v3.2"
    REVIEWER  = "nvidia:glm-4.7"
    pools     = _get_pools()
    generator = pools.get(pool, pools["coding"])[0]

    warnings: list[str] = []
    stages:   list[dict] = []

    def _call(slug, sys_msg, human_msg, temp=0.3):
        try:
            llm  = _build_llm(slug, temp)
            resp = llm.invoke([SystemMessage(content=sys_msg), HumanMessage(content=human_msg)])
            return resp.content or ""
        except Exception as e:
            _, w = _classify_error(e, slug)
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
