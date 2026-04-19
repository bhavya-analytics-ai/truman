import re
from langchain_core.messages import SystemMessage
from langchain.agents import create_agent as create_react_agent
from mem0 import MemoryClient
from truman.core.config import MEM0_API_KEY, OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL, get_llm
from truman.core.persona import SYSTEM


def strip_markdown(text: str) -> str:
    """Remove markdown formatting so TTS speaks clean natural text."""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)       # **bold**
    text = re.sub(r'\*(.*?)\*', r'\1', text)             # *italic*
    text = re.sub(r'`(.*?)`', r'\1', text)               # `code`
    text = re.sub(r'#{1,6}\s+', '', text)                # ## headers
    text = re.sub(r'^\s*[\*\-\+]\s+', '', text, flags=re.MULTILINE)   # bullet points
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)      # numbered lists
    text = re.sub(r'\n{3,}', '\n\n', text)               # excess newlines
    text = re.sub(r'\n', ' ', text)                      # flatten to sentences
    return text.strip()


llm = get_llm(temperature=0.7)
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


# ── Agent (lazy-built) ────────────────────────────────────────────────────────
# Tools live in truman.tools.all_tools. We defer building the agent until
# first access (or until main.py force-warms it at boot) so that tool
# imports don't create an import-time cycle: agent.py ← all_tools.py ←
# dispatch.py ← realtime_tools.py ← realtime.py ← (orchestrator).
_agent = None


def build_agent():
    from truman.tools.all_tools import TOOLS
    return create_react_agent(llm, TOOLS)


def get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


# SYSTEM prompt lives in persona.py — single source of truth, imported at top.


# ── Mood classifier (OpenRouter, free) ────────────────────────────────────────
_MOOD_WORDS = {"angry", "sad", "hyped", "affectionate", "frustrated", "focused", "neutral"}


def _classify_mood(user_input: str) -> str:
    """One-word mood tag from Om's message. Free via OpenRouter (gpt-oss-120b).
    Returns 'neutral' silently on any failure — never breaks the main path."""
    if not OPENROUTER_API_KEY or not user_input:
        return "neutral"
    try:
        from langchain_openai import ChatOpenAI
        llm_mood = ChatOpenAI(
            model=OPENROUTER_MODEL,
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
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


chat_history = []


def run(user_input, mood: str = ""):
    global chat_history

    # auto-detect mood when caller didn't pass one — free via OpenRouter
    if not mood:
        mood = _classify_mood(user_input)

    results = mem_search(user_input)
    mem_context = "\n".join([r["memory"] for r in results[:5]]) if results else ""
    mood_line = f"\n\nMOOD CONTEXT: {mood}" if mood and mood != "neutral" else ""
    system = SYSTEM + (f"\n\nRelevant memory:\n{mem_context}" if mem_context else "") + mood_line

    messages = [SystemMessage(content=system)] + chat_history + [{"role": "user", "content": user_input}]

    result = get_agent().invoke({"messages": messages})
    response = strip_markdown(result["messages"][-1].content)

    chat_history.append({"role": "user", "content": user_input})
    chat_history.append({"role": "assistant", "content": response})

    # keep last 10 exchanges in session
    if len(chat_history) > 20:
        chat_history = chat_history[-20:]

    # auto-store every exchange in Mem0 — Mem0 extracts what's worth keeping
    try:
        memory.add(
            [
                {"role": "user",      "content": user_input},
                {"role": "assistant", "content": response},
            ],
            user_id=USER_ID
        )
    except Exception:
        pass

    return response
