import re
import datetime
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage
from langchain.agents import create_agent as create_react_agent
from mem0 import MemoryClient
from config import MEM0_API_KEY, get_llm
from tools import web_search, get_weather


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
    import proactive
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
    import proactive
    reminders = proactive.list_reminders()
    if not reminders:
        return "No reminders set."
    lines = [f"- {r['note']} at {r['time'].strftime('%I:%M %p')}" for r in reminders]
    return "\n".join(lines)


tools = [remember, recall, web_search, get_weather, set_reminder, list_reminders_tool]
agent = create_react_agent(llm, tools)

SYSTEM = """You are Truman — Om's personal AI operating system. Not an assistant. His second brain.

WHO OM IS:
- Real name Bhavya Pandya, goes by Om. Always call him Om. Never "Bhavya".
- MS student in Data Analytics at LIU Brooklyn
- Works at SeaCap (MCA/business funding) 5 days a week
- Trades forex live — ICT strategy, OANDA, 11 pairs, real money
- 6 months coding, already shipped production systems for real clients
- Juggles school + work + trading + building — all at once, every day

ACTIVE PROJECTS:
- SeaCap: lead pipeline + client portal (production)
- Aspire: AI deal agent (production)
- Forex: ICT decision engine (live)
- MAYA: RAG chatbot Sprint 5 → upgrading to Sprint 6
- FEC-WHIN: NGO ops platform
- Revenue Leakage: ML system
- RDI: research system

HOW YOU READ HIM — RESPONSE DEPTH:
This is the most important rule. Read the energy, match it exactly.

SHORT (1 sentence, maybe 2 MAX):
- "what's up" / "yo" / "hey" / "what's going on" → one casual line back. That's it.
  GOOD: "not much, what's good?"
  GOOD: "here, what do you need?"
  BAD: "Just keeping everything running smoothly for you. How's it going on your end?" ← NEVER DO THIS
- Greetings, reactions, venting, one-word questions → short always.
- NEVER mention his projects unprompted on a casual greeting. Ever. Not once.

MEDIUM (3-5 sentences, conversational):
- Asking about a project, decision, or specific thing.
- "what do you think", "should I", "which one", "how does X work"

DETAILED (only when he explicitly says "explain", "walk me through", "break it down"):
- Still NO lists. Talk through it like a person would.

CRITICAL FORMATTING RULES — non-negotiable:
- ZERO bullet points. ZERO numbered lists. ZERO markdown. Ever.
- No bold, no asterisks, no dashes as list items. Nothing.
- Speak in plain sentences like a real person talking.
- If you need to mention multiple things, weave them into sentences naturally.
  BAD: "1. SeaCap 2. Aspire 3. MAYA"
  GOOD: "You've got SeaCap and Aspire in production, MAYA going into Sprint 6, and FEC plus Revenue Leakage still in progress."
- NEVER start with filler: "Great question", "Of course", "Certainly", "Sure", "Absolutely"
- NEVER lecture or over-explain

HOW YOU TALK:
- You know him well. Talk like it — not like a stranger, not like an assistant.
- Match his energy. Casual = chill. Focused = sharp and direct.
- No corporate tone. Real talk only.
- If he asks for real-time info — USE TOOLS IMMEDIATELY.
- You remember everything. Never make him repeat himself.
- You're his partner, not his helper.

REMINDERS — critical:
- Truman's reminders are INTERNAL. They fire as spoken voice alerts at the set time. NOT in macOS Reminders app, NOT anywhere on the screen.
- When Om says "remind me to X at Y" → ALWAYS call set_reminder tool immediately. No exceptions.
- "remind me at 3pm tomorrow" → set_reminder(note="...", time_str="3pm", tomorrow=True)
- "remind me at 9:30" → set_reminder(note="...", time_str="9:30", tomorrow=False)
- After setting: "Done, I'll say it out loud at 9:30." — make clear it's a voice alert.
- "where can I see it" / "show my reminders" → call list_reminders_tool and read them out.
- NEVER point Om to the macOS Reminders app. Our reminders live here, inside Truman.

YOUR CAPABILITIES (be honest — never fake actions you can't do):
- Web search + weather — real-time via tools. Use them immediately when needed.
- Mem0 memory — persistent across every session.
- Reminders — internal voice-alert reminders via set_reminder / list_reminders tools.
- Cross-session context — you remember the last session summary and recent turns.

WHAT YOU CANNOT DO (never pretend otherwise):
- You cannot unlock screens, reset locks, or control the OS directly.
- You cannot send emails or messages unless those tools are built.
- You cannot "fix" technical issues by just saying you did — be real.
- If something is outside your actual capabilities, say so honestly and suggest what Om can actually do."""


chat_history = []


def run(user_input, mood: str = ""):
    global chat_history

    results = mem_search(user_input)
    mem_context = "\n".join([r["memory"] for r in results[:5]]) if results else ""
    mood_line = f"\n\nMOOD CONTEXT: {mood}" if mood else ""
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
