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


@tool
def search_history(query: str, limit: int = 10) -> str:
    """Search EVERY past conversation Om has had with Truman — all sessions, all turns. Use this when Om asks 'what did we talk about', 'what do you have on X', 'what's in your database/history', or references a past exchange. Returns matching turns with who said it and when. FTS5 search, so use keywords not full sentences."""
    from truman.storage import db
    try:
        rows = db.search_turns(query, limit=limit)
    except Exception as e:
        return f"Search failed: {e}"
    if not rows:
        return f"No past turns matched '{query}'."
    lines = []
    for r in rows:
        who = "Om" if r["role"] == "user" else "Truman"
        ts = (r.get("ts") or "")[:16].replace("T", " ")
        content = (r.get("content") or "").strip()
        if len(content) > 160:
            content = content[:157] + "..."
        lines.append(f"[{ts}] {who}: {content}")
    return "\n".join(lines)


@tool
def recent_conversations(n: int = 10) -> str:
    """Pull the last N turns across all sessions, chronological. Use when Om asks 'what did we just talk about', 'remind me what I said last time', or wants recent context Truman doesn't have in the live window. Default 10, cap 50."""
    from truman.storage import db
    n = max(1, min(int(n or 10), 50))
    try:
        rows = db.recent_turns(n)
    except Exception as e:
        return f"Lookup failed: {e}"
    if not rows:
        return "No turns logged yet."
    lines = []
    for r in rows:
        who = "Om" if r["role"] == "user" else "Truman"
        ts = (r.get("ts") or "")[:16].replace("T", " ")
        content = (r.get("content") or "").strip()
        if len(content) > 160:
            content = content[:157] + "..."
        lines.append(f"[{ts}] {who}: {content}")
    return "\n".join(lines)


def _is_local() -> bool:
    """True when running on Om's Mac directly (not Railway)."""
    return not os.environ.get("RAILWAY_ENVIRONMENT")


def _local_read_file(path: str) -> str:
    from pathlib import Path
    p = Path(path).expanduser()
    if not p.exists():
        return f"Error: no file at {path}"
    content = p.read_text(errors="replace")
    if len(content) > 50_000:
        content = content[:50_000] + "\n\n[truncated at 50k chars]"
    return content


def _local_list_dir(path: str = "~") -> str:
    from pathlib import Path
    p = Path(path).expanduser()
    if not p.exists():
        return f"Error: no directory at {path}"
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
    lines = []
    for e in entries[:300]:
        kind = "file" if e.is_file() else "dir "
        size = f" ({e.stat().st_size:,}b)" if e.is_file() else ""
        lines.append(f"{kind}  {e.name}{size}")
    if len(list(p.iterdir())) > 300:
        lines.append("... (truncated at 300 entries)")
    return "\n".join(lines) or "(empty)"


def _local_search_files(root: str, pattern: str) -> str:
    from pathlib import Path
    p = Path(root).expanduser()
    if not p.exists():
        return f"Error: no directory at {root}"
    matches = list(p.rglob(pattern))[:50]
    if not matches:
        return f"no files matching '{pattern}' under {root}"
    return "\n".join(str(m) for m in matches)


def _local_write_file(path: str, content: str) -> str:
    from pathlib import Path
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"written {len(content)} chars to {p}"


@tool
def read_mac_file(path: str) -> str:
    """Read a file from Om's Mac. Use when Om says 'show me that file', 'read X', or references a file on his laptop. Path can be absolute or use ~."""
    if _is_local():
        return _local_read_file(path)
    from truman.voice.orb import mac_request
    result = mac_request("read_file", {"path": path})
    return result.get("result") if result.get("ok") else f"Error: {result.get('error')}"


@tool
def list_mac_dir(path: str = "~") -> str:
    """List files and folders in a directory on Om's Mac. Use when Om asks what's in a folder or wants to browse his files."""
    if _is_local():
        return _local_list_dir(path)
    from truman.voice.orb import mac_request
    result = mac_request("list_dir", {"path": path})
    return result.get("result") if result.get("ok") else f"Error: {result.get('error')}"


@tool
def search_mac_files(root: str, pattern: str) -> str:
    """Search for files matching a pattern on Om's Mac (e.g. pattern='*.py', root='~/Desktop/friday'). Use when Om asks to find a file."""
    if _is_local():
        return _local_search_files(root, pattern)
    from truman.voice.orb import mac_request
    result = mac_request("search_files", {"root": root, "pattern": pattern})
    return result.get("result") if result.get("ok") else f"Error: {result.get('error')}"


@tool
def write_mac_file(path: str, content: str) -> str:
    """Write or create a file on Om's Mac. Use when Om says 'save this', 'create a file', 'write this to my desktop/notes/etc'. iCloud syncs it to his phone automatically. Path supports ~ for home dir."""
    if _is_local():
        return _local_write_file(path, content)
    from truman.voice.orb import mac_request
    result = mac_request("write_file", {"path": path, "content": content})
    return result.get("result") if result.get("ok") else f"Error: {result.get('error')}"


@tool
def list_models(pool: str = "") -> str:
    """List available AI models for a specific pool or all pools. Use when Om asks 'what models do I have', 'what models for coding', 'show me the pools', etc. Pool options: coding, creative, design, docs, vision, general, reasoning, fast, agentic. Leave empty for all pools."""
    from truman.core.model_router import list_pool_models, get_session_model
    target = pool.lower().strip() if pool else None
    data = list_pool_models(target)
    if not data:
        return f"No pool named '{pool}'. Options: coding, creative, design, docs, vision, general, reasoning, fast, agentic."
    from truman.core.model_router import short_label
    lines = []
    override = get_session_model()
    if override:
        lines.append(f"⚡ Session override active: {short_label(override)}\n")
    for p, models in data.items():
        lines.append(f"[{p}]")
        for i, m in enumerate(models):
            marker = "→" if i == 0 else " "
            label = short_label(m['slug'])
            lines.append(f"  {marker} {label}  —  {m['info']}")
    return "\n".join(lines)


@tool
def set_model(model_slug: str) -> str:
    """Force Truman to use a specific model for all text responses this session. Use when Om says 'use qwen', 'switch to deepseek', 'use minimax', etc. Short names: glm, qwen, devstral, kimi, mistral, deepseek, step, minimax, maverick, terminus, nemotron, llama. Pass 'auto' or 'clear' to go back to automatic routing."""
    from truman.core.model_router import set_session_model, clear_session_model, _resolve_slug, MODEL_INFO

    slug = model_slug.strip().lower()

    if slug in ("auto", "clear", "reset", "off"):
        clear_session_model()
        return "Back to automatic pool routing."

    resolved = _resolve_slug(slug)
    set_session_model(resolved)
    info = MODEL_INFO.get(resolved, "")
    return f"Using {resolved}{f' — {info}' if info else ''} for this session. Say 'auto' to switch back."


@tool
def pipeline_mode(request: str, pool: str = "coding") -> str:
    """Run a high-stakes task through the 3-stage pipeline: deepseek-v3.2 reasons → pool model generates → glm-4.7 reviews. Use when Om says 'pipeline this', 'use pipeline', 'double check', or for complex code/architecture tasks. Pool options: coding, creative, design, docs, general, reasoning."""
    from truman.core.model_router import run_pipeline
    pool = pool.lower().strip() or "coding"
    result = run_pipeline(request, pool=pool)
    output = result["content"]
    stages = result.get("pipeline_stages", [])
    if stages:
        used = " → ".join(s["model"].split("/")[-1].split(":")[0] for s in stages)
        output = f"[pipeline: {used}]\n\n{output}"
    return output


@tool
def concept_search(query: str) -> str:
    """Search Truman's concept graph for domain knowledge — relationships between ideas, strategies, patterns. Use when Om asks about how something works conceptually, wants to understand connections, or asks about a domain like forex, seacap, trading. Different from recall which finds facts — this finds relationships."""
    try:
        from truman.brain.concepts import search_sync
        result = search_sync(query, top_k=5)
        return result if result else "nothing in concept graph yet for that — it grows over time as we talk."
    except Exception as e:
        return f"concept graph unavailable: {e}"


@tool
def concept_ingest(text: str) -> str:
    """Add important knowledge to Truman's concept graph — domain knowledge, strategies, how something works. Use when Om shares expertise, explains a strategy, or teaches Truman about a domain. This builds the world model."""
    try:
        from truman.brain.concepts import ingest
        ok = ingest(text)
        return "added to concept graph." if ok else "couldn't add to concept graph right now."
    except Exception as e:
        return f"concept graph write failed: {e}"


@tool
def add_goal(title: str, description: str = "") -> str:
    """Add a new active goal for Om — something he wants to accomplish. Use when Om says 'I want to', 'my goal is', 'add a goal', 'remember I need to ship X'. Stores it persistently and injects into every future session."""
    from truman.storage.db import add_goal as _add
    gid = _add(title, description or None)
    return f"goal added: '{title}'"


@tool
def list_goals() -> str:
    """List all of Om's current active goals. Use when Om asks 'what are my goals', 'show my goals', 'what am I working towards'."""
    from truman.storage.db import get_all_goals
    goals = get_all_goals()
    if not goals:
        return "no goals set yet."
    lines = []
    for g in goals:
        status_icon = {"active": "→", "done": "✓", "dropped": "✗", "paused": "⏸"}.get(g["status"], "?")
        line = f"{status_icon} {g['title']}"
        if g.get("description"):
            line += f" — {g['description']}"
        lines.append(line)
    return "\n".join(lines)


@tool
def complete_goal(query: str) -> str:
    """Mark a goal as completed. Use when Om says 'done with X', 'finished X', 'mark X as done', 'shipped X'. Matches by partial title text."""
    from truman.storage.db import complete_goal as _complete
    ok = _complete(query)
    return f"marked done: '{query}'" if ok else f"couldn't find active goal matching '{query}' — use list_goals to check."


@tool
def drop_goal(query: str) -> str:
    """Drop/cancel a goal. Use when Om says 'drop X', 'cancel X', 'remove goal X', 'not doing X anymore'. Matches by partial title text."""
    from truman.storage.db import drop_goal as _drop
    ok = _drop(query)
    return f"dropped: '{query}'" if ok else f"couldn't find active goal matching '{query}' — use list_goals to check."


TOOLS = [web_search, get_weather, remember, recall, set_reminder, list_reminders,
         search_history, recent_conversations, read_mac_file, list_mac_dir, search_mac_files,
         write_mac_file, list_models, set_model, pipeline_mode, concept_search, concept_ingest,
         add_goal, list_goals, complete_goal, drop_goal]
