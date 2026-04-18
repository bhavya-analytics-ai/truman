import re
import datetime
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage
from langchain.agents import create_agent as create_react_agent
from mem0 import MemoryClient
from truman.core.config import MEM0_API_KEY, OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL, get_llm
from truman.tools.tools import web_search, get_weather
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


@tool
def remember(info: str) -> str:
    """Store something important about Om or his projects into long-term memory."""
    mem_add(info)
    return f"Remembered: {info}"


@tool
def recall(query: str) -> str:
    """Search Om's memory for relevant information."""
    results = mem_search(query)
    if not results:
        return "Nothing in memory for that."
    return "\n".join([r["memory"] for r in results])


@tool
def set_reminder(note: str, time_str: str, tomorrow: bool = False) -> str:
    """
    Set a reminder for Om at a specific time.
    note: what to remind him (e.g. 'check the SeaCap pipeline')
    time_str: time as a string (e.g. '3pm', '9:30am', '15:30', '9.30')
    tomorrow: True if Om said 'tomorrow', False for today (default)
    Always use this tool when Om says 'remind me' or 'set a reminder'.
    """
    from truman.scheduling import proactive
    now = datetime.datetime.now()
    try:
        # normalize: replace period with colon, strip spaces
        t = time_str.strip().replace(".", ":").upper()

        parsed = None
        for fmt in ("%I:%M%p", "%I%p", "%H:%M", "%I:%M %p", "%I %p", "%H:%M:%S"):
            try:
                parsed = datetime.datetime.strptime(t, fmt)
                break
            except ValueError:
                continue

        if parsed is None:
            return f"Couldn't parse '{time_str}'. Try '3pm', '9:30am', or '15:30'."

        base = now + datetime.timedelta(days=1) if tomorrow else now
        at = base.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)

        # if not tomorrow and time already passed today, push to tomorrow
        if not tomorrow and at < now:
            at += datetime.timedelta(days=1)

        proactive.add_reminder(note, at)
        day_label = "tomorrow" if tomorrow else "today"
        return f"Done. Reminding you to '{note}' at {at.strftime('%I:%M %p')} {day_label}."
    except Exception as e:
        return f"Failed to set reminder: {e}"


@tool
def list_reminders_tool(placeholder: str = "") -> str:
    """List all upcoming reminders Om has set."""
    from truman.scheduling import proactive
    reminders = proactive.list_reminders()
    if not reminders:
        return "No reminders set."
    lines = [f"- {r['note']} at {r['time'].strftime('%I:%M %p')}" for r in reminders]
    return "\n".join(lines)


tools = [remember, recall, web_search, get_weather, set_reminder, list_reminders_tool]
agent = create_react_agent(llm, tools)

# SYSTEM prompt lives in persona.py — single source of truth, imported at top.


# ── Mood classifier (Groq, free) ──────────────────────────────────────────────
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

    # auto-detect mood when caller didn't pass one — free via Groq
    if not mood:
        mood = _classify_mood(user_input)

    results = mem_search(user_input)
    mem_context = "\n".join([r["memory"] for r in results[:5]]) if results else ""
    mood_line = f"\n\nMOOD CONTEXT: {mood}" if mood and mood != "neutral" else ""
    system = SYSTEM + (f"\n\nRelevant memory:\n{mem_context}" if mem_context else "") + mood_line

    messages = [SystemMessage(content=system)] + chat_history + [{"role": "user", "content": user_input}]

    result = agent.invoke({"messages": messages})
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
