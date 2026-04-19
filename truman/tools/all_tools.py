"""
all_tools.py — Canonical tool definitions for Truman.

Consumed identically by the text path (LangChain agent via TOOLS) and the
voice path (OpenAI Realtime via truman.tools.dispatch.realtime_schemas).
One source of truth — no more drift.

Docstrings ARE the tool descriptions the LLM sees on both paths. Edit
docstrings here to change tool discoverability everywhere.
"""
import re
import datetime
import subprocess
import requests
from ddgs import DDGS
from langchain_core.tools import tool

from truman.text.agent import mem_add, mem_search


# ── Time parsing helper ───────────────────────────────────────────────────────
_RELATIVE_RE = re.compile(
    r"""^\s*(?:in\s+)?(\d+)\s*
        (s|sec|secs|second|seconds
        |m|min|mins|minute|minutes
        |h|hr|hrs|hour|hours
        |d|day|days)\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def _parse_time(time_str: str, tomorrow: bool = False) -> datetime.datetime | None:
    """Returns the absolute fire datetime, or None if unparseable.

    Handles:
      - Relative: '2 minutes', 'in 5 min', '30s', '1 hour', '2 days'
      - Absolute: '3pm', '9:30am', '15:30'
    """
    now = datetime.datetime.now()
    s = time_str.strip()

    m = _RELATIVE_RE.match(s)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("s"):          return now + datetime.timedelta(seconds=n)
        if unit.startswith(("m", "min")): return now + datetime.timedelta(minutes=n)
        if unit.startswith(("h", "hr")):  return now + datetime.timedelta(hours=n)
        if unit.startswith("d"):          return now + datetime.timedelta(days=n)

    t = s.replace(".", ":").upper()
    parsed = None
    for fmt in ("%I:%M%p", "%I%p", "%H:%M", "%I:%M %p", "%I %p"):
        try:
            parsed = datetime.datetime.strptime(t, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return None

    base = now + datetime.timedelta(days=1) if tomorrow else now
    at = base.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
    if not tomorrow and at < now:
        at += datetime.timedelta(days=1)
    return at


# ── Tools ──────────────────────────────────────────────────────────────────────
@tool
def web_search(query: str) -> str:
    """Search the web for real-time info — news, prices, scores, facts, anything current."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if not results:
            return "No results found."
        return "\n".join([f"{r['title']}: {r['body']}" for r in results])
    except Exception as e:
        return f"Search failed: {e}"


@tool
def get_weather(location: str) -> str:
    """Get current weather for any location."""
    try:
        url = f"https://wttr.in/{location.replace(' ', '+')}?format=3"
        return requests.get(url, timeout=5).text.strip()
    except Exception as e:
        return f"Weather lookup failed: {e}"


@tool
def remember(info: str) -> str:
    """Store something important about Om or his projects into long-term memory."""
    mem_add(info)
    return f"Remembered: {info}"


@tool
def recall(query: str) -> str:
    """Search Om's memory for relevant information about past conversations, projects, or preferences."""
    results = mem_search(query)
    if not results:
        return "Nothing in memory for that."
    return "\n".join([r["memory"] for r in results])


@tool
def set_reminder(note: str, time_str: str, tomorrow: bool = False) -> str:
    """Set a reminder for Om. Always use when Om says 'remind me' or 'set a reminder'. Accepts absolute clock times ('3pm', '9:30am', '15:30') OR relative deltas ('2 minutes', 'in 5 min', '1 hour', '30s'). Pass tomorrow=True if Om says 'tomorrow'."""
    from truman.scheduling import proactive

    at = _parse_time(time_str, tomorrow=tomorrow)
    if at is None:
        return (
            f"Couldn't parse '{time_str}'. Try '3pm', '9:30am', '15:30', "
            f"'in 2 minutes', '30s', or '1 hour'."
        )

    # Try to create Apple reminder and capture its ID for later cleanup
    apple_id: str | None = None
    try:
        date_str = at.strftime("%B %d, %Y %I:%M:%S %p")
        script = (
            'tell application "Reminders"\n'
            f'  set r to make new reminder with properties {{name:"{note}", remind me date:date "{date_str}"}}\n'
            '  return id of r\n'
            'end tell'
        )
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
        captured = res.stdout.strip()
        if captured:
            apple_id = captured
    except Exception:
        pass

    proactive.add_reminder(note, at, apple_reminder_id=apple_id)

    now = datetime.datetime.now()
    delta = at - now
    secs = delta.total_seconds()
    if secs < 60:
        when = f"in about {int(secs)} seconds"
    elif secs < 3600:
        mins = round(secs / 60)
        when = f"in about {mins} minute{'s' if mins != 1 else ''}"
    else:
        day = "tomorrow" if tomorrow or at.date() > now.date() else "today"
        when = f"at {at.strftime('%I:%M %p')} {day}"
    return f"Reminder set: '{note}' {when}."


@tool
def list_reminders() -> str:
    """List all upcoming reminders Om has set."""
    from truman.scheduling import proactive
    reminders = proactive.list_reminders()
    if not reminders:
        return "No reminders set."
    return "\n".join([f"- {r['note']} at {r['time'].strftime('%I:%M %p')}" for r in reminders])


TOOLS = [web_search, get_weather, remember, recall, set_reminder, list_reminders]
