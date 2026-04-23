"""
agent.py — Truman text agent.

Architecture:
  - Tool intent detection from message keywords
  - Direct tool execution (no bind_tools — avoids API-level tool call format issues)
  - Groq (llama-3.3) formats the final response with tool results injected
  - NVIDIA handles heavy tasks (coding, reasoning) via run_with_pool() in tools
"""
import re
import json
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from mem0 import MemoryClient
from truman.core.config import MEM0_API_KEY, OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from truman.core.config import GROQ_API_KEY, GROQ_BASE_URL, NVIDIA_API_KEY, NVIDIA_BASE_URL
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
    text = re.sub(r'\n', ' ', text)
    return text.strip()


memory = MemoryClient(api_key=MEM0_API_KEY)
USER_ID = "om"
MEM_FILTER = {"AND": [{"user_id": USER_ID}]}


def mem_search(query):
    try:
        results = memory.search(query, filters=MEM_FILTER)
        return results.get("results", []) if isinstance(results, dict) else results
    except Exception:
        return []


def mem_add(info):
    try:
        memory.add([{"role": "user", "content": info}], user_id=USER_ID)
    except Exception:
        pass


_last_session_cache: str | None = None

def _last_session_str() -> str:
    """Return last session's structured reflection — cached for the process lifetime."""
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


def _get_llm(temperature: float = 0.7):
    """deepseek-v3.2 → glm-4.7 → mistral-nemotron (all NVIDIA) → groq last resort."""
    def _nv(model, timeout=5):
        return ChatOpenAI(model=model, api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL,
                          temperature=temperature, timeout=timeout)
    def _gq(model):
        return ChatOpenAI(model=model, api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL,
                          temperature=temperature, timeout=25)

    primary = _nv("glm-4.7",                    timeout=10)
    f1      = _nv("deepseek-ai/deepseek-v3.2", timeout=8)
    f2      = _nv("mistral-nemotron",           timeout=10)
    f3      = _gq("llama-3.3-70b-versatile")   # last resort
    return primary.with_fallbacks([f1, f2, f3])


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
    """Returns (tool_name, None) or None if no tool needed."""
    for pattern, tool_name in _TOOL_PATTERNS:
        if pattern.search(message):
            return tool_name
    return None


def _extract_arg(message: str, tool_name: str) -> dict:
    """Extract the most relevant argument from the message for the given tool."""
    msg = message.strip()
    if tool_name == "web_search":
        # strip filler and use the meaningful part
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


# ── Mood classifier ───────────────────────────────────────────────────────────
_MOOD_WORDS = {"angry", "sad", "hyped", "affectionate", "frustrated", "focused", "neutral"}


def _classify_mood(user_input: str) -> str:
    if not OPENROUTER_API_KEY or not user_input:
        return "neutral"
    try:
        llm_mood = ChatOpenAI(
            model="openai/gpt-oss-120b:free",
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            timeout=5,
            temperature=0.0,
            max_tokens=8,
        )
        prompt = (
            "Classify this message's mood with ONE lowercase word from this list: "
            "angry, sad, hyped, affectionate, frustrated, focused, neutral. "
            "Return ONLY the word — no punctuation, no explanation.\n\n"
            f"Message: {user_input!r}"
        )
        resp = llm_mood.invoke(prompt).content.strip().lower().rstrip(".,!?;:")
        return resp if resp in _MOOD_WORDS else "neutral"
    except Exception:
        return "neutral"


chat_history: list = []


def run(user_input: str, mood: str = "", pool: str | None = None) -> dict:
    """
    Keyword-based tool detection → direct execution → groq formats response.
    No bind_tools — avoids API-level tool call format failures.
    """
    global chat_history

    if not mood:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:
            mood_fut = ex.submit(_classify_mood, user_input)
            mem_fut  = ex.submit(mem_search, user_input)
            mood     = mood_fut.result()
            results  = mem_fut.result()
    else:
        results = mem_search(user_input)

    mem_context = "\n".join([r["memory"] for r in results[:5]]) if results else ""
    mood_line = f"\n\nMOOD CONTEXT: {mood}" if mood and mood != "neutral" else ""
    persona_reminder = "\n\nCRITICAL: You are texting Om on his dashboard. Be direct, casual, lowercase. No bullet points. No asking permission. Commit to your answer. Match Om's energy."

    last_session_ctx = _last_session_str()
    system_content = SYSTEM + (f"\n\nRelevant memory:\n{mem_context}" if mem_context else "") + last_session_ctx + mood_line + persona_reminder

    from truman.tools.all_tools import TOOLS
    tool_map = {t.name: t for t in TOOLS}

    # detect if a tool is needed
    tool_name   = _detect_tool(user_input)
    tool_result = None
    tool_calls_made = []

    if tool_name and tool_name in tool_map:
        try:
            args = _extract_arg(user_input, tool_name)
            tool_result = tool_map[tool_name].invoke(args)
            tool_calls_made.append({"name": tool_name})
        except Exception as e:
            tool_result = f"tool error: {e}"

    # build messages for groq
    messages = [SystemMessage(content=system_content)]
    for h in chat_history[-16:]:
        if h["role"] == "user":
            messages.append(HumanMessage(content=h["content"]))
        else:
            messages.append(AIMessage(content=h["content"]))

    if tool_result is not None:
        messages.append(HumanMessage(
            content=f"{user_input}\n\n[Tool result from {tool_name}]:\n{tool_result}"
        ))
    else:
        messages.append(HumanMessage(content=user_input))

    # get response from groq (no tool binding — plain LLM call)
    llm = _get_llm()
    response = llm.invoke(messages)
    final_text = strip_markdown(response.content or "")

    chat_history.append({"role": "user", "content": user_input})
    chat_history.append({"role": "assistant", "content": final_text})
    if len(chat_history) > 32:
        chat_history = chat_history[-32:]

    import threading
    threading.Thread(target=lambda: memory.add([
        {"role": "user",      "content": user_input},
        {"role": "assistant", "content": final_text},
    ], user_id=USER_ID), daemon=True).start()

    _sm = get_session_model()
    model_label = short_label(_sm) if _sm else "deepseek-v3.2"

    return {
        "response":   final_text,
        "model":      model_label,
        "pool":       pool or detect_pool(user_input),
        "tool_calls": tool_calls_made,
        "warnings":   [],
        "mood":       mood,
    }
