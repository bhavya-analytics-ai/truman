"""
agent.py — Truman text agent.

Architecture:
  - Tool intent detection from message keywords
  - Direct tool execution (no bind_tools)
  - NVIDIA-only model chain (no groq)
  - Smart memory filter — only meaningful turns written to Mem0
  - Error log ring buffer (last 50 events)
"""
import re
import time
import json
import os as _os
from collections import deque, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from truman.core.config import MEM0_API_KEY, NVIDIA_API_KEY, NVIDIA_BASE_URL
from truman.core.persona import SYSTEM
from truman.core.model_router import detect_pool, get_session_model, short_label

# ── Transient errors that justify LangGraph → legacy fallback ─────────────────
import httpx as _httpx
try:
    import openai as _openai
    _OPENAI_TRANSIENT = (_openai.APIConnectionError, _openai.RateLimitError)
except Exception:
    _OPENAI_TRANSIENT = ()

try:
    from langgraph.errors import GraphRecursionError as _GraphRecursionError
except Exception:
    _GraphRecursionError = None

_TRANSIENT_BASE = (_httpx.TimeoutException, _httpx.ConnectError) + _OPENAI_TRANSIENT
TRANSIENT_ERRORS = (_TRANSIENT_BASE + (_GraphRecursionError,)) if _GraphRecursionError else _TRANSIENT_BASE


def log_fallback_event(reason: str, exception_type: str = "", message: str = "") -> None:
    """Log a LangGraph→legacy fallback to events table for telemetry."""
    try:
        from truman.storage import db as _db
        import json as _json
        with _db._conn() as c:
            c.execute(
                "INSERT INTO events (kind, status, detail, ts) VALUES (?, ?, ?, datetime('now'))",
                ("langgraph_fallback", "error",
                 _json.dumps({"reason": reason,
                              "exception_type": exception_type,
                              "message": message[:200]})),
            )
    except Exception:
        pass  # never crash on telemetry


# ── Session tool result cache (last 3 results per session) ───────────────────
_tool_cache: dict[str, deque] = defaultdict(lambda: deque(maxlen=3))

def _cache_tool_result(session_id: str, tool_name: str, args: dict, result: str):
    _tool_cache[session_id].append({"tool": tool_name, "args": args, "result": result})

def _get_cached_tool_context(session_id: str) -> str:
    entries = list(_tool_cache.get(session_id, []))
    if not entries:
        return ""
    lines = ["RECENT TOOL RESULTS (use these before re-calling the same tool):"]
    for e in entries:
        lines.append(f"[{e['tool']}({e['args']})] → {e['result'][:500]}" + ("..." if len(e['result']) > 500 else ""))
    return "\n".join(lines)


def strip_markdown(text: str) -> str:
    # strip persona action narrations e.g. *smiles*, *thinks*, *adjusts glasses*
    text = re.sub(r'(?m)^\s*\*[a-zA-Z][^\n*]{0,50}\*\s*$', '', text)
    text = re.sub(r'\*[a-z][a-z ,.\'-]{1,30}\*', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Memory backend — Mem0 cloud if key is set, SQLite local otherwise ─────────
# All data stays local (SQLite /data/truman.db) when MEM0_API_KEY is unset/empty.
_USE_MEM0 = bool(MEM0_API_KEY)
USER_ID   = "om"
MEM_FILTER = {"AND": [{"user_id": USER_ID}]}

if _USE_MEM0:
    from mem0 import MemoryClient as _MemoryClient
    memory = _MemoryClient(api_key=MEM0_API_KEY)
else:
    memory = None

# ── Error log ring buffer ─────────────────────────────────────────────────────
_error_log: deque = deque(maxlen=50)

def log_event(user_msg: str, model: str, pool: str, elapsed: float,
              tool_calls: list, error: str = "", session_id: str = "default"):
    status = "error" if error else ("slow" if elapsed > 8 else "ok")
    entry = {
        "ts":     time.strftime("%H:%M:%S"),
        "msg":    user_msg[:60],
        "model":  model,
        "pool":   pool,
        "secs":   round(elapsed, 1),
        "tools":  [t["name"] for t in tool_calls],
        "error":  error,
        "status": status,
    }
    _error_log.appendleft(entry)
    # also persist to DB (non-blocking, fire-and-forget)
    try:
        from truman.storage import db as _db
        import threading, json as _j
        detail = _j.dumps({"msg": user_msg[:120], "tools": [t["name"] for t in tool_calls]})
        threading.Thread(
            target=_db.log_event_db,
            kwargs=dict(kind="chat", source="text", session_id=session_id,
                        pool=pool, model=model, elapsed_ms=int(elapsed * 1000),
                        status=status, detail=detail, error=error or None),
            daemon=True,
        ).start()
    except Exception:
        pass

def get_error_log():
    return list(_error_log)


# ── Memory helpers ────────────────────────────────────────────────────────────
_GREETINGS = re.compile(
    r"^(yo+|hey+|hi+|sup|what'?s up|thanks?|thx|nice|ok|okay|cool|lol|haha|got it|sure|yep|nope|no|yes|k|np)[\s!?.]*$",
    re.I
)

def mem_search(query: str) -> list:
    """Search memory. Uses Mem0 if key is set, local SQLite otherwise."""
    if _USE_MEM0:
        try:
            results = memory.search(query, filters=MEM_FILTER)
            return results.get("results", []) if isinstance(results, dict) else results
        except Exception:
            pass
    # Local fallback — search user_facts in SQLite
    try:
        from truman.storage.db import search_facts
        hits = search_facts(query, limit=5)
        # Normalise to same shape as Mem0 results
        return [{"memory": h["fact"], "score": 1.0} for h in hits]
    except Exception:
        return []


def _should_save(text: str) -> bool:
    """Return True only if the message is worth saving to memory."""
    t = text.strip()
    if len(t) < 20:          return False
    if _GREETINGS.match(t):  return False
    return True


def _mem_add_smart(user_input: str, response: str):
    """Write to memory only if user message has real substance. Background thread."""
    if not _should_save(user_input):
        return
    if _USE_MEM0:
        try:
            hits = memory.search(user_input[:80], filters=MEM_FILTER)
            existing = hits.get("results", []) if isinstance(hits, dict) else hits
            for h in existing[:3]:
                if h.get("memory", "")[:60].lower() == user_input[:60].lower():
                    return  # duplicate, skip
            memory.add([
                {"role": "user",      "content": user_input},
                {"role": "assistant", "content": response},
            ], user_id=USER_ID)
        except Exception:
            pass
    # Local: facts are extracted async by _auto_extract_facts in orb.py — nothing extra needed


def mem_add(info: str):
    """Add a fact directly. Uses Mem0 if key is set, local SQLite otherwise."""
    if _USE_MEM0:
        try:
            memory.add([{"role": "user", "content": info}], user_id=USER_ID)
            return
        except Exception:
            pass
    # Local fallback
    try:
        from truman.storage.db import save_fact
        save_fact(info, importance=3, source="mem_add")
    except Exception:
        pass


# ── Last session cache ────────────────────────────────────────────────────────
_last_session_cache: str | None = None

def _last_session_str() -> str:
    global _last_session_cache
    if _last_session_cache is not None:
        return _last_session_cache
    try:
        import json as _j
        from truman.storage import db as _db
        s = _db.last_session_summary()
        if not s or not s.get("summary"):
            _last_session_cache = ""
            return ""
        d = _j.loads(s["summary"])
        parts = [d.get("summary", "")]
        for k, label in [("key_decisions","Decisions"), ("next_day_priorities","Priorities"), ("errors","Errors")]:
            if d.get(k): parts.append(f"{label}: " + ", ".join(d[k]))
        _last_session_cache = "\n\nLAST SESSION: " + " | ".join(p for p in parts if p)
        return _last_session_cache
    except Exception:
        _last_session_cache = ""
        return ""


# ── Complexity detection ──────────────────────────────────────────────────────
_TASK_KW = re.compile(
    r"\b(build|write|code|debug|fix|function|script|class|implement|refactor|"
    r"error|bug|test|api|endpoint|explain|analyze|analyse|compare|why|plan|"
    r"design|architect|create|generate|make|deploy|review|optimize)\b", re.I
)

def _is_complex(msg: str) -> bool:
    return len(msg.split()) > 20 or bool(_TASK_KW.search(msg))


# ── LLM — NVIDIA only, pool-aware model selection ───────────────────────────
# general/reasoning → llama-70b (fast, solid), coding/agentic → kimi-k2 (deep)
_CHAT_MODELS = [
    ("meta/llama-3.3-70b-instruct",  "llama70"),
    ("moonshotai/kimi-k2-instruct",  "kimi-k2"),
]

_POOL_CHAT_MODELS: dict[str, list] = {
    "general":   [("meta/llama-3.3-70b-instruct", "llama70"),  ("moonshotai/kimi-k2-instruct", "kimi-k2")],
    "reasoning": [("moonshotai/kimi-k2-instruct", "kimi-k2"),  ("meta/llama-3.3-70b-instruct", "llama70")],
    "coding":    [("moonshotai/kimi-k2-instruct", "kimi-k2"),  ("stepfun-ai/step-3.5-flash",   "step-flash")],
    "agentic":   [("moonshotai/kimi-k2-instruct", "kimi-k2"),  ("stepfun-ai/step-3.5-flash",   "step-flash")],
    "docs":      [("meta/llama-3.3-70b-instruct", "llama70"),  ("moonshotai/kimi-k2-instruct", "kimi-k2")],
    "vision":    [("meta/llama-3.2-90b-vision-instruct", "llama-vision"), ("meta/llama-4-scout-17b-16e-instruct", "scout")],
}

def _call_llm(messages: list, complex_msg: bool = False, temperature: float = 0.7):
    """Try each model in order, return (response_text, model_label)."""
    t1 = 12 if complex_msg else 8
    t2 = 15 if complex_msg else 10
    timeouts = [t1, t2]

    for i, (model, label) in enumerate(_CHAT_MODELS):
        try:
            t = timeouts[i] if i < len(timeouts) else timeouts[-1]
            llm = ChatOpenAI(model=model, api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL,
                             temperature=temperature, timeout=t)
            resp = llm.invoke(messages)
            return resp.content or "", label
        except Exception as e:
            print(f"[LLM] {label} failed: {e}")
            continue
    return "", "none"


def _lc_messages_to_openai(messages: list) -> list:
    """Convert LangChain message objects (or dicts) to plain OpenAI-format dicts."""
    from langchain_core.messages import ToolMessage as _ToolMessage
    result = []
    for m in messages:
        if isinstance(m, dict):
            result.append(m)
            continue
        mtype = getattr(m, "type", None)
        if mtype == "system":
            result.append({"role": "system", "content": m.content})
        elif mtype == "human":
            result.append({"role": "user", "content": m.content})
        elif mtype == "ai":
            msg: dict = {"role": "assistant", "content": m.content or ""}
            tc = getattr(m, "tool_calls", None)
            if tc:
                msg["tool_calls"] = [
                    {"id": c.get("id", ""), "type": "function",
                     "function": {"name": c.get("name", ""), "arguments": json.dumps(c.get("args", {}))}}
                    for c in tc
                ]
            result.append(msg)
        elif mtype == "tool" or isinstance(m, _ToolMessage):
            result.append({"role": "tool",
                            "tool_call_id": getattr(m, "tool_call_id", ""),
                            "content": m.content})
    return result


def _call_llm_with_tools_stream(messages: list, tools: list, tool_map: dict,
                                 complex_msg: bool = False, pool: str = "general"):
    """
    Streaming LLM with tools. Yields SSE event dicts:
      {"type": "tool_call_start", "name": str, "args": dict}
      {"type": "tool_call_end",   "name": str, "result": str, "elapsed_ms": int}
      {"type": "token",           "delta": str}
      {"type": "done",            "model": str, "pool": str,
                                  "tool_calls": list, "latency_ms": int}

    Uses raw OpenAI client (stream=True) on NVIDIA NIM.
    Falls back through model list if primary errors before first token.
    Handles tool calls: fires tool events, executes, then streams final response.
    """
    from openai import OpenAI

    t_start = time.time()
    model_list = _POOL_CHAT_MODELS.get(pool, _CHAT_MODELS)
    tool_calls_made: list = []
    model_label = "none"

    # Build OpenAI-format tools schema from LangChain StructuredTools
    openai_tools = []
    for t in tools:
        try:
            schema = t.args_schema.model_json_schema() if t.args_schema else {}
            # Remove title field — NIM is strict about unknown fields
            schema.pop("title", None)
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": (t.description or "")[:512],
                    "parameters": schema,
                },
            })
        except Exception:
            pass

    client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL,
                    timeout=18 if complex_msg else 12)
    working_msgs = _lc_messages_to_openai(messages)

    for model_idx, (model, label) in enumerate(model_list):
        try:
            for iteration in range(4):   # max tool loop iterations
                kwargs: dict = dict(model=model, messages=working_msgs, stream=True)
                if openai_tools:
                    kwargs["tools"] = openai_tools

                stream = client.chat.completions.create(**kwargs)

                content_parts: list[str] = []
                pending_tcs: dict[int, dict] = {}   # index → partial tool call
                finish_reason = None

                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason or finish_reason

                    if delta.content:
                        content_parts.append(delta.content)
                        yield {"type": "token", "delta": delta.content}

                    if getattr(delta, "tool_calls", None):
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in pending_tcs:
                                pending_tcs[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc_delta.id:
                                pending_tcs[idx]["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    pending_tcs[idx]["name"] += tc_delta.function.name
                                if tc_delta.function.arguments:
                                    pending_tcs[idx]["arguments"] += tc_delta.function.arguments

                model_label = label

                if not pending_tcs:
                    # No tool calls — we're done streaming
                    break

                # ── Execute tool calls ─────────────────────────────────────
                # Append assistant turn with tool_calls to working_msgs
                working_msgs.append({
                    "role": "assistant",
                    "content": "".join(content_parts) or None,
                    "tool_calls": [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                        for tc in pending_tcs.values() if tc["name"]
                    ],
                })

                for tc in pending_tcs.values():
                    if not tc["name"]:
                        continue
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except Exception:
                        args = {}

                    yield {"type": "tool_call_start", "name": tc["name"], "args": args}
                    t_tool = time.time()

                    if tc["name"] in tool_map:
                        try:
                            result = tool_map[tc["name"]].invoke(args)
                        except Exception as e:
                            result = f"tool error: {e}"
                    else:
                        result = f"unknown tool: {tc['name']}"

                    tool_elapsed = int((time.time() - t_tool) * 1000)
                    tool_calls_made.append({"name": tc["name"]})

                    yield {"type": "tool_call_end", "name": tc["name"],
                           "result": str(result)[:500], "elapsed_ms": tool_elapsed}

                    working_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": str(result)[:8000],
                    })
                # loop again → model streams final answer

            yield {
                "type": "done", "model": model_label, "pool": pool,
                "tool_calls": tool_calls_made,
                "latency_ms": int((time.time() - t_start) * 1000),
            }
            return

        except Exception as e:
            print(f"[LLM stream] {label} failed: {e}")
            continue

    # All models failed — emit done with no content
    yield {
        "type": "done", "model": "none", "pool": pool,
        "tool_calls": tool_calls_made,
        "latency_ms": int((time.time() - t_start) * 1000),
    }


def _call_llm_with_tools(messages: list, tools: list, tool_map: dict,
                          complex_msg: bool = False, temperature: float = 0.7,
                          max_iters: int = 4, pool: str = "general"):
    """LLM with bind_tools — LLM dynamically chooses + calls tools in a loop.

    Returns (final_text, model_label, tool_calls_made).
    Falls back to plain _call_llm if tool calling fails on all models.
    pool selects the model priority list (general→llama70, coding→kimi-k2, etc.)
    """
    from langchain_core.messages import ToolMessage
    t1 = 18 if complex_msg else 12
    t2 = 22 if complex_msg else 15
    timeouts = [t1, t2]
    tool_calls_made: list = []
    model_list = _POOL_CHAT_MODELS.get(pool, _CHAT_MODELS)

    for i, (model, label) in enumerate(model_list):
        try:
            timeout = timeouts[i] if i < len(timeouts) else timeouts[-1]
            llm = ChatOpenAI(model=model, api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL,
                             temperature=temperature, timeout=timeout)
            llm_with_tools = llm.bind_tools(tools)
            working_msgs = list(messages)

            for _ in range(max_iters):
                resp = llm_with_tools.invoke(working_msgs)
                calls = getattr(resp, "tool_calls", None) or []
                if not calls:
                    return resp.content or "", label, tool_calls_made
                working_msgs.append(resp)
                for call in calls:
                    name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                    args = call.get("args", {}) if isinstance(call, dict) else getattr(call, "args", {})
                    call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", "")
                    tool_calls_made.append({"name": name})
                    if name in tool_map:
                        try:
                            result = tool_map[name].invoke(args)
                        except Exception as e:
                            result = f"tool error: {e}"
                    else:
                        result = f"unknown tool: {name}"
                    working_msgs.append(ToolMessage(content=str(result)[:8000], tool_call_id=call_id or name))
            # max iters hit — return last response
            return getattr(resp, "content", "") or "", label, tool_calls_made
        except Exception as e:
            print(f"[LLM tools] {label} failed: {e}")
            continue
    # All tool-capable attempts failed → fall back to plain
    text, label = _call_llm(messages, complex_msg=complex_msg, temperature=temperature)
    return text, label, tool_calls_made


# ── Tool intent detection ─────────────────────────────────────────────────────
_TOOL_PATTERNS = [
    (re.compile(r"\b(search|look up|find|google|news|current|latest|what.*happening)\b", re.I), "web_search"),
    (re.compile(r"\b(weather|temperature|forecast|rain|sunny)\b", re.I), "get_weather"),
    (re.compile(r"\b(remind me|set.*reminder|remind.*at|reminder)\b", re.I), "set_reminder"),
    (re.compile(r"\b(list.*reminder|my reminder|upcoming reminder|show.*reminder)\b", re.I), "list_reminders"),
    (re.compile(r"\b(remember|save.*memory|store.*memory|note.*down)\b", re.I), "remember"),
    (re.compile(r"\b(recall|what.*remember|what do you know about me|memory|do you know about me|what's in.*memory)\b", re.I), "recall"),
    (re.compile(r"\b(search.*history|past conversation|what.*talk|history)\b", re.I), "search_history"),
    (re.compile(r"\b(recent conversation|last.*said|what.*said last|recent.*talk)\b", re.I), "recent_conversations"),
    (re.compile(r"\b(read.*file|show.*file|open.*file|read.*mac)\b", re.I), "read_mac_file"),
    (re.compile(r"\b(list.*folder|list.*dir|what.*folder|browse.*folder|list.*file|what.*file|what.*desktop|show.*desktop|what.*on.*desktop|files.*on.*desktop|desktop.*files|access.*desktop|see.*my.*file|show.*my.*file|what.*in.*desktop)\b", re.I), "list_mac_dir"),
    (re.compile(r"\b(find.*file|search.*file|locate.*file)\b", re.I), "search_mac_files"),
    (re.compile(r"\b(write.*file|save.*file|create.*file)\b", re.I), "write_mac_file"),
    (re.compile(r"\b(what model|which model|show.*model|list.*model|model.*have|available model|model.*pool|show me.*model|what.*model.*have)\b", re.I), "list_models"),
    (re.compile(r"\b(use model|switch.*model|set model|switch to (nemotron|kimi|step|qwen|llama|maverick|devstral)|use (nemotron|kimi|step|qwen|llama|maverick|devstral))\b", re.I), "set_model"),
    (re.compile(r"\b(add.*goals?|set.*goals?|new goal|want to achieve|want to ship|goal is)\b", re.I), "add_goal"),
    (re.compile(r"\b(list.*goals?|show.*goals?|my goals?|what.*goals?|all.*goals?)\b", re.I), "list_goals"),
    (re.compile(r"\b(complete.*goals?|done.*goals?|finished.*goals?|mark.*done|shipped.*goals?)\b", re.I), "complete_goal"),
    (re.compile(r"\b(drop.*goals?|cancel.*goals?|remove.*goals?|not doing)\b", re.I), "drop_goal"),
    (re.compile(r"\b(gonna sleep|going to sleep|slept from|sleeping from|sleep from|waking up at|wake up at)\b", re.I), "log_sleep"),
    (re.compile(r"\b(change.*brief|set.*brief|morning brief.*time|brief.*at|quiet hours?|sleep window|update.*pref|change.*pref|my sleep.*is now|now.*sleep)\b", re.I), "update_pref"),
    (re.compile(r"\b(add.*rule|new rule|rule\s*:|always\s+\w|never\s+say|never\s+do|from now on|stop doing|stop saying|add a rule|set a rule)", re.I), "add_rule"),
    (re.compile(r"\b(list.*rules?|show.*rules?|my rules?|what rules?|rules you have|your rules?)\b", re.I), "list_rules"),
    (re.compile(r"\b(delete.*rule|remove.*rule|forget.*rule)\b", re.I), "delete_rule"),
]


def _detect_tool(message: str):
    for pattern, tool_name in _TOOL_PATTERNS:
        if pattern.search(message):
            return tool_name
    return None


def _extract_arg(message: str, tool_name: str) -> dict:
    msg = message.strip()
    if tool_name == "web_search":
        q = re.sub(r"^(search|look up|find|google|what.*?is|tell me about)\s+", "", msg, flags=re.I).strip()
        return {"query": q or msg}
    if tool_name == "get_weather":
        m = re.search(r"weather.*?(?:in|for|at)\s+(.+?)(?:\?|$)", msg, re.I)
        return {"location": m.group(1).strip() if m else "current location"}
    if tool_name == "set_reminder":
        m = re.search(r"remind me.*?(?:to|about)\s+(.+?)\s+(?:at|in|@)\s+(.+?)(?:\?|$)", msg, re.I)
        if m:
            return {"note": m.group(1).strip(), "time_str": m.group(2).strip()}
        return {"note": msg, "time_str": "in 5 minutes"}
    if tool_name == "remember":
        return {"info": msg}
    if tool_name == "recall":
        q = re.sub(r"^(recall|what.*?know about|do you know about|remember)\s+", "", msg, flags=re.I).strip()
        return {"query": q or msg}
    if tool_name == "search_history":
        q = re.sub(r"^(search.*?history|past conversation.*?about)\s+", "", msg, flags=re.I).strip()
        return {"query": q or msg}
    if tool_name == "recent_conversations":
        return {"n": 10}
    if tool_name == "list_reminders":
        return {}
    if tool_name == "list_models":
        m = re.search(r"(?:for|in|show)\s+(coding|creative|design|docs|vision|general|reasoning|fast|agentic)", msg, re.I)
        return {"pool": m.group(1) if m else ""}
    if tool_name == "set_model":
        m = re.search(r"(?:use|switch to|set model to)\s+(\w[\w\-\.]*)", msg, re.I)
        return {"model_slug": m.group(1) if m else msg}
    if tool_name == "list_mac_dir":
        # 1. absolute/home path explicitly mentioned
        path_m = re.search(r"(~\/[\w/\.\-~ ]+|\/[\w/\.\-~ ]+)", msg, re.I)
        if path_m:
            return {"path": path_m.group(1).strip()}
        # 2. "in <FolderName>" — bare folder name on desktop
        folder_m = re.search(r"(?:in|inside|within|under|what(?:'s| is) in)\s+([A-Za-z][\w\s\-\.]{1,40}?)(?:\?|$|,|\bfolder\b|\bdir\b)", msg, re.I)
        if folder_m:
            folder = folder_m.group(1).strip().rstrip("?., ")
            if folder.lower() not in ("my desktop", "desktop", "home", "mac", "laptop"):
                return {"path": f"~/Desktop/{folder}"}
        # 3. default
        if re.search(r"\bdesktop\b", msg, re.I):
            return {"path": "~/Desktop"}
        return {"path": "~"}
    if tool_name in ("read_mac_file", "search_mac_files", "write_mac_file"):
        path_m = re.search(r"(?:file|path|at|in|under)?\s*([\~/][\w/\.\-~]+)", msg, re.I)
        return {"path": path_m.group(1).strip() if path_m else "~"}
    if tool_name == "add_goal":
        title = re.sub(r"^(add.*goal|set.*goal|new goal|my goal is|i want to|goal is)\s*[:\-]?\s*", "", msg, flags=re.I).strip()
        return {"title": title or msg, "description": ""}
    if tool_name == "list_goals":
        return {}
    if tool_name == "complete_goal":
        q = re.sub(r"^(complete.*goal|done.*goal|finished.*goal|mark.*done|shipped.*goal)\s*[:\-]?\s*", "", msg, flags=re.I).strip()
        return {"query": q or msg}
    if tool_name == "drop_goal":
        q = re.sub(r"^(drop.*goal|cancel.*goal|remove.*goal|not doing)\s*[:\-]?\s*", "", msg, flags=re.I).strip()
        return {"query": q or msg}
    if tool_name == "log_sleep":
        # "gonna sleep from 4 to 8:50" / "slept from 11pm to 7am"
        m = re.search(r"(?:sleep|slept|sleeping)\s+from\s+([^\s]+(?:\s*[ap]m)?)\s+to\s+([^\s]+(?:\s*[ap]m)?)", msg, re.I)
        if m:
            return {"sleep_start": m.group(1).strip(), "sleep_end": m.group(2).strip(), "raw_input": msg}
        # "gonna sleep from 4 to 8.50" (dot instead of colon)
        m2 = re.search(r"(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)?)\s+to\s+(\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)?)", msg, re.I)
        if m2:
            return {"sleep_start": m2.group(1).strip(), "sleep_end": m2.group(2).strip(), "raw_input": msg}
        return {"sleep_start": "00:00", "sleep_end": "08:00", "raw_input": msg}
    if tool_name == "update_pref":
        # "change morning brief to 10am" → key=morning_brief_hour value=10
        m_brief = re.search(r"brief.*?(?:to|at)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", msg, re.I)
        if m_brief:
            return {"key": "morning_brief_hour", "value": m_brief.group(1).strip()}
        # "quiet hours are 1am to 8am" / "sleep window 2am to 9am"
        m_qh = re.search(r"(?:quiet hours?|sleep window).*?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+to\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", msg, re.I)
        if m_qh:
            return {"key": "quiet_start__end", "value": f"{m_qh.group(1).strip()}|{m_qh.group(2).strip()}"}
        return {"key": "general", "value": msg}
    if tool_name == "add_rule":
        # "rule: always respond in bullet points" / "never say sorry" / "from now on X"
        rule = re.sub(r"^(add.*?rule[:\s]+|new rule[:\s]+|rule[:\s]+|from now on[,\s]+|always\s+|never\s+say\s+|never\s+do\s+|stop\s+doing\s+|stop\s+saying\s+|set a rule[:\s]+)", "", msg, flags=re.I).strip()
        return {"rule": rule or msg}
    if tool_name == "list_rules":
        return {}
    if tool_name == "delete_rule":
        m = re.search(r"(?:delete|remove|forget)\s+rule\s+(\d+)", msg, re.I)
        return {"rule_id": int(m.group(1)) if m else 0}
    return {}


# ── Legacy get_agent — kept for voice path ────────────────────────────────────
def get_agent():
    return _SimpleAgent()


class _SimpleAgent:
    def invoke(self, inp):
        msgs = inp.get("messages", [])
        user_msg = ""
        for m in reversed(msgs):
            if hasattr(m, "type") and m.type == "human":
                user_msg = m.content; break
            if isinstance(m, dict) and m.get("role") == "user":
                user_msg = m.get("content", ""); break
        result = run(user_msg)
        return {"messages": msgs + [AIMessage(content=result["response"])]}


# ── Mood classifier — local keyword detection, zero API calls ─────────────────
_MOOD_MAP = [
    ("angry",       re.compile(r"\b(fuck|shit|wtf|retard|idiot|stupid|useless|pissed|angry|mad|rage)\b", re.I)),
    ("frustrated",  re.compile(r"\b(ugh|argh|again|still|broken|why.*not|doesn.t work|keeps|wont)\b", re.I)),
    ("hyped",       re.compile(r"\b(let.?s go|yoo+|hype|fire|sick|banger|finally|yess+|lets do|letsss)\b", re.I)),
    ("sad",         re.compile(r"\b(sad|tired|exhausted|rough|hard day|not good|struggling|overwhelmed)\b", re.I)),
    ("affectionate",re.compile(r"\b(love|miss|appreciate|thanks man|good job|proud|grateful|means a lot)\b", re.I)),
    ("focused",     re.compile(r"\b(let.?s focus|back to|continue|resume|pick up|next step|moving on)\b", re.I)),
]

def _classify_mood(user_input: str) -> str:
    for mood, pattern in _MOOD_MAP:
        if pattern.search(user_input):
            return mood
    return "neutral"


_chat_histories: dict[str, list] = {}   # session_id → list of turns
_session_pools:  dict[str, str]  = {}   # session_id → sticky pool

# pools that count as "strong signal" — stick to them once chosen
_STICKY_POOLS = {"coding", "design", "creative", "docs", "vision", "reasoning", "agentic"}


def _run_legacy(user_input: str, mood: str = "", pool: str | None = None, session_id: str = "default") -> dict:
    global _chat_histories, _session_pools
    chat_history = _chat_histories.setdefault(session_id, [])
    t_start = time.time()
    error_str = ""

    if not mood:
        mood = _classify_mood(user_input)  # instant, local
    results = mem_search(user_input)

    mem_context = "\n".join([r["memory"] for r in results[:5]]) if results else ""
    mood_line = f"\n\nMOOD CONTEXT: {mood}" if mood and mood != "neutral" else ""
    persona_reminder = "\n\nCRITICAL: You are texting Om on his dashboard. Be direct, casual, lowercase. No bullet points. No asking permission. Commit to your answer. Match Om's energy."

    try:
        now_et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        from datetime import timezone, timedelta
        now_et = datetime.now(timezone(timedelta(hours=-4)))  # EDT fallback
    clock_line = f"\n\nCURRENT TIME: {now_et.strftime('%A, %b %d %Y, %I:%M %p ET')}"
    last_session_ctx = _last_session_str()
    import os as _os
    _runtime = "railway" if _os.environ.get("RAILWAY_ENVIRONMENT") else "local"
    runtime_line = f"\n\nRUNTIME: {_runtime}. {'Mac files are accessible via tools.' if _runtime == 'local' else 'Mac files not accessible — running on Railway.'}"
    tool_cache_ctx = _get_cached_tool_context(session_id)
    tool_cache_line = f"\n\n{tool_cache_ctx}" if tool_cache_ctx else ""
    system_content = SYSTEM + clock_line + runtime_line + tool_cache_line + (f"\n\nRelevant memory:\n{mem_context}" if mem_context else "") + last_session_ctx + mood_line + persona_reminder

    from truman.tools.all_tools import TOOLS
    tool_map = {t.name: t for t in TOOLS}

    tool_name    = _detect_tool(user_input)
    tool_result  = None
    tool_calls_made = []

    if tool_name and tool_name in tool_map:
        try:
            args = _extract_arg(user_input, tool_name)
            tool_result = tool_map[tool_name].invoke(args)
            tool_calls_made.append({"name": tool_name})
            _cache_tool_result(session_id, tool_name, args, str(tool_result))
        except Exception as e:
            tool_result = f"tool error: {e}"

    messages = [SystemMessage(content=system_content)]
    for h in chat_history[-16:]:
        if h["role"] == "user":
            messages.append(HumanMessage(content=h["content"]))
        else:
            messages.append(AIMessage(content=h["content"]))

    if tool_result is not None:
        messages.append(HumanMessage(content=f"{user_input}\n\n[Tool result from {tool_name}]:\n{tool_result}"))
    else:
        messages.append(HumanMessage(content=user_input))

    try:
        # Always bind tools so LLM can call any tool dynamically.
        # Regex pre-execution above is just a head-start hint — the LLM can
        # still call additional tools (e.g. gitnexus__*) on top of it.
        raw_text, model_label, dyn_calls = _call_llm_with_tools(
            messages, TOOLS, tool_map, complex_msg=_is_complex(user_input)
        )
        tool_calls_made.extend(dyn_calls)
        final_text = strip_markdown(raw_text)
    except Exception as e:
        error_str = str(e)
        final_text = ""
        model_label = "none"

    chat_history.append({"role": "user", "content": user_input})
    chat_history.append({"role": "assistant", "content": final_text})
    if len(chat_history) > 32:
        _chat_histories[session_id] = chat_history[-32:]

    import threading
    threading.Thread(target=_mem_add_smart, args=(user_input, final_text), daemon=True).start()

    _sm = get_session_model()
    if _sm:
        model_label = short_label(_sm)

    # ── Sticky routing ────────────────────────────────────────────────────────
    if pool:
        # explicit pool passed (e.g. file upload) → use it, update sticky
        chosen_pool = pool
        _session_pools[session_id] = pool
    else:
        detected = detect_pool(user_input)
        sticky   = _session_pools.get(session_id)
        if detected in _STICKY_POOLS:
            # strong signal → switch to new pool, update sticky
            chosen_pool = detected
            _session_pools[session_id] = detected
        elif sticky:
            # weak signal (general/fast) → stay on sticky pool
            chosen_pool = sticky
        else:
            chosen_pool = detected

    elapsed = time.time() - t_start

    log_event(user_input, model_label, chosen_pool, elapsed, tool_calls_made, error_str, session_id)

    return {
        "response":   final_text,
        "model":      model_label,
        "pool":       chosen_pool,
        "tool_calls": tool_calls_made,
        "warnings":   [],
        "mood":       mood,
    }


def run(user_input: str, mood: str = "", pool: str | None = None, session_id: str = "default", attach_ids: list = None) -> dict:
    """
    Primary entry point.
    ENABLE_CLAUDE_SHAPE=1 (default) → single-call claude-shape path
    ENABLE_CLAUDE_SHAPE=0 → LangGraph path (rollback)
    ENABLE_LANGGRAPH=0   → legacy sequential path
    """
    use_claude_shape = _os.environ.get("ENABLE_CLAUDE_SHAPE", "1") == "1"

    # Claude-shape: one LLM call, tools fire natively. Multimodal still uses LangGraph.
    if use_claude_shape and not (attach_ids or []):
        try:
            from truman.text.chat import chat as _chat
            result = _chat(user_input, session_id=session_id, pool=pool)
            return {
                "response":     result["response"],
                "model":        result["model"],
                "pool":         result["pool"],
                "tool_calls":   result["tool_calls"],
                "mood":         "neutral",
                "warnings":     [],
                "skill":        "",
                "attachments":  [],
            }
        except Exception as e:
            print(f"[claude-shape→legacy] {type(e).__name__}: {e}")
            # fall through to LangGraph

    use_lg = _os.environ.get("ENABLE_LANGGRAPH", "1") == "1"
    if use_lg:
        try:
            from truman.brain.loop import run as lg_run
            return lg_run(user_input, session_id=session_id, pool_hint=pool, attach_ids=attach_ids or [])
        except TRANSIENT_ERRORS as e:
            log_fallback_event(reason="transient",
                               exception_type=type(e).__name__,
                               message=str(e))
            print(f"[LangGraph→legacy] transient: {type(e).__name__}: {e}")
        except Exception as e:
            log_fallback_event(reason="bug",
                               exception_type=type(e).__name__,
                               message=str(e))
            print(f"[LangGraph] BUG (re-raising): {type(e).__name__}: {e}")
            raise

    return _run_legacy(user_input, mood=mood, pool=pool, session_id=session_id)
