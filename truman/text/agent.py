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
from collections import deque
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from mem0 import MemoryClient
from truman.core.config import MEM0_API_KEY, NVIDIA_API_KEY, NVIDIA_BASE_URL
from truman.core.persona import SYSTEM
from truman.core.model_router import detect_pool, get_session_model, short_label


def strip_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'`(.*?)`', r'\1', text)
    text = re.sub(r'#{1,6}\s+', '', text)
    text = re.sub(r'^\s*[\*\-\+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # preserve paragraph breaks (\n\n), only collapse lone newlines to space
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    return text.strip()


memory = MemoryClient(api_key=MEM0_API_KEY)
USER_ID = "om"
MEM_FILTER = {"AND": [{"user_id": USER_ID}]}

# ── Error log ring buffer ─────────────────────────────────────────────────────
_error_log: deque = deque(maxlen=50)

def log_event(user_msg: str, model: str, pool: str, elapsed: float,
              tool_calls: list, error: str = ""):
    _error_log.appendleft({
        "ts":         time.strftime("%H:%M:%S"),
        "msg":        user_msg[:60],
        "model":      model,
        "pool":       pool,
        "secs":       round(elapsed, 1),
        "tools":      [t["name"] for t in tool_calls],
        "error":      error,
        "status":     "error" if error else ("slow" if elapsed > 8 else "ok"),
    })

def get_error_log():
    return list(_error_log)


# ── Memory helpers ────────────────────────────────────────────────────────────
_GREETINGS = re.compile(
    r"^(yo+|hey+|hi+|sup|what'?s up|thanks?|thx|nice|ok|okay|cool|lol|haha|got it|sure|yep|nope|no|yes|k|np)[\s!?.]*$",
    re.I
)

def mem_search(query):
    try:
        results = memory.search(query, filters=MEM_FILTER)
        return results.get("results", []) if isinstance(results, dict) else results
    except Exception:
        return []

def _should_save(text: str) -> bool:
    """Return True only if the message is worth saving to Mem0."""
    t = text.strip()
    if len(t) < 20:          return False   # too short
    if _GREETINGS.match(t):  return False   # greeting/reaction
    return True

def _mem_add_smart(user_input: str, response: str):
    """Write to Mem0 only if user message has real substance. Background thread."""
    if not _should_save(user_input):
        return
    try:
        # basic dedup: skip if Mem0 already has very similar entry
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


def mem_add(info):
    try:
        memory.add([{"role": "user", "content": info}], user_id=USER_ID)
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


# ── LLM — NVIDIA only, no groq ───────────────────────────────────────────────
_CHAT_MODELS = [
    ("moonshotai/kimi-k2-instruct", "kimi-k2"),
    ("stepfun-ai/step-3.5-flash",   "step-flash"),
]

def _call_llm(messages: list, complex_msg: bool = False, temperature: float = 0.7):
    """Try each model in order, return (response_text, model_label)."""
    t1 = 12 if complex_msg else 8
    t2 = 15 if complex_msg else 10
    timeouts = [t1, t2]

    for i, (model, label) in enumerate(_CHAT_MODELS):
        try:
            llm = ChatOpenAI(model=model, api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL,
                             temperature=temperature, timeout=timeouts[i])
            resp = llm.invoke(messages)
            return resp.content or "", label
        except Exception as e:
            print(f"[LLM] {label} failed: {e}")
            continue
    return "", "none"


# ── Tool intent detection ─────────────────────────────────────────────────────
_TOOL_PATTERNS = [
    (re.compile(r"\b(search|look up|find|google|news|current|latest|what.*happening)\b", re.I), "web_search"),
    (re.compile(r"\b(weather|temperature|forecast|rain|sunny)\b", re.I), "get_weather"),
    (re.compile(r"\b(remind me|set.*reminder|remind.*at|reminder)\b", re.I), "set_reminder"),
    (re.compile(r"\b(list.*reminder|my reminder|upcoming reminder|show.*reminder)\b", re.I), "list_reminders"),
    (re.compile(r"\b(remember|save.*memory|store.*memory|note.*down)\b", re.I), "remember"),
    (re.compile(r"\b(recall|what.*remember|what.*know about|memory|do you know about)\b", re.I), "recall"),
    (re.compile(r"\b(search.*history|past conversation|what.*talk|history)\b", re.I), "search_history"),
    (re.compile(r"\b(recent conversation|last.*said|what.*said last|recent.*talk)\b", re.I), "recent_conversations"),
    (re.compile(r"\b(read.*file|show.*file|open.*file|read.*mac)\b", re.I), "read_mac_file"),
    (re.compile(r"\b(list.*folder|list.*dir|what.*folder|browse.*folder)\b", re.I), "list_mac_dir"),
    (re.compile(r"\b(find.*file|search.*file|locate.*file)\b", re.I), "search_mac_files"),
    (re.compile(r"\b(write.*file|save.*file|create.*file)\b", re.I), "write_mac_file"),
    (re.compile(r"\b(what model|which model|show.*model|list.*model|model.*have|available model|model.*pool|show me.*model|what.*model.*have)\b", re.I), "list_models"),
    (re.compile(r"\b(use model|switch.*model|set model|switch to)\b", re.I), "set_model"),
    (re.compile(r"\b(pipeline|pipeline mode|double check|3.?stage)\b", re.I), "pipeline_mode"),
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
    if tool_name == "pipeline_mode":
        return {"request": msg, "pool": detect_pool(msg)}
    if tool_name in ("read_mac_file", "list_mac_dir", "search_mac_files", "write_mac_file"):
        return {"path": "~"}
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


def run(user_input: str, mood: str = "", pool: str | None = None, session_id: str = "default") -> dict:
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

    last_session_ctx = _last_session_str()
    system_content = SYSTEM + (f"\n\nRelevant memory:\n{mem_context}" if mem_context else "") + last_session_ctx + mood_line + persona_reminder

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
        raw_text, model_label = _call_llm(messages, complex_msg=_is_complex(user_input))
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

    log_event(user_input, model_label, chosen_pool, elapsed, tool_calls_made, error_str)

    return {
        "response":   final_text,
        "model":      model_label,
        "pool":       chosen_pool,
        "tool_calls": tool_calls_made,
        "warnings":   [],
        "mood":       mood,
    }
