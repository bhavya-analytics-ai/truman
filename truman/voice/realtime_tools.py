"""
realtime_tools.py — Tool definitions for OpenAI Realtime API function calling.
Imports actual logic from tools.py and agent.py — no duplicate implementations.
"""
import datetime
import re
import subprocess
import requests
from ddgs import DDGS
from truman.text.agent import mem_search as _mem_search, mem_add as _mem_add


# ── Time parsing ──────────────────────────────────────────────────────────────
_RELATIVE_RE = re.compile(
    r"""^\s*(?:in\s+)?(\d+)\s*
        (s|sec|secs|second|seconds
        |m|min|mins|minute|minutes
        |h|hr|hrs|hour|hours
        |d|day|days)\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def _parse_time(time_str: str, tomorrow: bool = False) -> datetime.datetime | None:
    """
    Returns the absolute fire datetime, or None if unparseable.
    Handles:
      - Relative: '2 minutes', 'in 5 min', '30s', '1 hour', '2 days'
      - Absolute: '3pm', '9:30am', '15:30'
    """
    now = datetime.datetime.now()
    s = time_str.strip()

    # relative delta
    m = _RELATIVE_RE.match(s)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("s"):        return now + datetime.timedelta(seconds=n)
        if unit.startswith(("m", "min")): return now + datetime.timedelta(minutes=n)
        if unit.startswith(("h", "hr")):  return now + datetime.timedelta(hours=n)
        if unit.startswith("d"):        return now + datetime.timedelta(days=n)

    # absolute clock time
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


# ── Tool schemas (OpenAI Realtime function-call format) ────────────────────────
TOOL_SCHEMAS = [
    {
        "type": "function",
        "name": "web_search",
        "description": "Search the web for real-time info — news, prices, scores, facts, anything current.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }
    },
    {
        "type": "function",
        "name": "get_weather",
        "description": "Get current weather for any location.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City or location name"}
            },
            "required": ["location"]
        }
    },
    {
        "type": "function",
        "name": "remember",
        "description": "Store something important about Om or his projects into long-term memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "info": {"type": "string", "description": "Information to remember"}
            },
            "required": ["info"]
        }
    },
    {
        "type": "function",
        "name": "recall",
        "description": "Search Om's memory for relevant information about past conversations, projects, or preferences.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in memory"}
            },
            "required": ["query"]
        }
    },
    {
        "type": "function",
        "name": "set_reminder",
        "description": "Set a reminder for Om. Always use when Om says 'remind me' or 'set a reminder'. Accepts absolute clock times (e.g. '3pm', '9:30am', '15:30') OR relative deltas (e.g. '2 minutes', 'in 5 min', '1 hour', '30s').",
        "parameters": {
            "type": "object",
            "properties": {
                "note":     {"type": "string",  "description": "What to remind Om about"},
                "time_str": {"type": "string",  "description": "Absolute time ('3pm', '9:30am', '15:30') or relative delta ('2 minutes', 'in 1 hour', '30s')"},
                "tomorrow": {"type": "boolean", "description": "True if Om said tomorrow (ignored for relative deltas), else False"}
            },
            "required": ["note", "time_str"]
        }
    },
    {
        "type": "function",
        "name": "list_reminders",
        "description": "List all upcoming reminders Om has set.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
]


# ── Implementations ────────────────────────────────────────────────────────────
def _web_search(query: str) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if not results:
            return "No results found."
        return "\n".join([f"{r['title']}: {r['body']}" for r in results])
    except Exception as e:
        return f"Search failed: {e}"


def _get_weather(location: str) -> str:
    try:
        url = f"https://wttr.in/{location.replace(' ', '+')}?format=3"
        return requests.get(url, timeout=5).text.strip()
    except Exception as e:
        return f"Weather lookup failed: {e}"


def _remember(info: str) -> str:
    _mem_add(info)
    return f"Remembered: {info}"


def _recall(query: str) -> str:
    results = _mem_search(query)
    if not results:
        return "Nothing in memory for that."
    return "\n".join([r["memory"] for r in results])


def _set_reminder(note: str, time_str: str, tomorrow: bool = False) -> str:
    from truman.scheduling import proactive

    at = _parse_time(time_str, tomorrow=tomorrow)
    if at is None:
        return (
            f"Couldn't parse '{time_str}'. Try '3pm', '9:30am', '15:30', "
            f"'in 2 minutes', '30s', or '1 hour'."
        )

    proactive.add_reminder(note, at)

    # also save to macOS Reminders app
    try:
        date_str = at.strftime("%B %d, %Y %I:%M:%S %p")
        script = (
            f'tell application "Reminders" to make new reminder with properties '
            f'{{name:"{note}", remind me date:date "{date_str}"}}'
        )
        subprocess.Popen(["osascript", "-e", script])
    except Exception:
        pass

    # friendly relative phrasing when close, absolute otherwise
    now = datetime.datetime.now()
    delta = at - now
    if delta.total_seconds() < 3600:
        mins = max(1, round(delta.total_seconds() / 60))
        when = f"in about {mins} minute{'s' if mins != 1 else ''}"
    else:
        day = "tomorrow" if tomorrow or at.date() > now.date() else "today"
        when = f"at {at.strftime('%I:%M %p')} {day}"
    return f"Reminder set: '{note}' {when}."


def _list_reminders() -> str:
    from truman.scheduling import proactive
    reminders = proactive.list_reminders()
    if not reminders:
        return "No reminders set."
    return "\n".join([f"{r['note']} at {r['time'].strftime('%I:%M %p')}" for r in reminders])


# ── Dispatcher ─────────────────────────────────────────────────────────────────
_DISPATCH = {
    "web_search":    lambda a: _web_search(a["query"]),
    "get_weather":   lambda a: _get_weather(a["location"]),
    "remember":      lambda a: _remember(a["info"]),
    "recall":        lambda a: _recall(a["query"]),
    "set_reminder":  lambda a: _set_reminder(a["note"], a["time_str"], a.get("tomorrow", False)),
    "list_reminders": lambda a: _list_reminders(),
}


def dispatch_tool(name: str, args: dict) -> str:
    fn = _DISPATCH.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    try:
        return fn(args)
    except Exception as e:
        return f"Tool error ({name}): {e}"
