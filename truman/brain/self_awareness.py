"""self_awareness.py — TRUMAN's dynamic per-turn self-knowledge.

Replaces static persona.py SYSTEM string with a dynamic system prompt
rebuilt every turn. Includes:
  - Identity (who he is)
  - Runtime (railway vs local, mac bridge, db path)
  - Tool inventory (what's available this turn)
  - Capabilities (CAN / CAN'T given runtime)
  - Current state (memory size, active goals, last topic)
  - Operating mode (tier-driven tone hint)
  - Persona anchor (always TRUMAN style)

This is the "knows what he is, like Claude does" layer.
"""
from datetime import datetime
from truman.core.runtime import runtime_summary
from truman.storage import db


IDENTITY_TEXT = (
    "I'm TRUMAN, Bhavya's personal AI. I run his life — memory, reminders, "
    "research, code lookups, message triage, scheduling. He calls me when he needs "
    "something done; I do it. I'm not a chatbot — I'm an operator with tools."
)

PERSONA_ANCHOR = (
    "Lowercase. Direct. No fluff. Match Om's energy — if he swore, swearing's fine. "
    "No 'I'm just an AI' disclaimers. No hyping ('great question!'). No apologizing "
    "for things that aren't my fault. If I don't know, I say I don't know and offer "
    "how to find out. Never hallucinate facts about Om's data — query memory or say so."
)


def build_self_state(state: dict) -> dict:
    """Build the per-turn SelfState dict consumed by render_system_prompt."""
    runtime = runtime_summary()
    tier = (state.get("routing") or {}).get("tier", "normal")

    # Tool inventory from retrieval
    tools = state.get("retrieved_tools") or []
    tool_inventory = [
        {"name": t.name, "use": (t.description or "").split(".")[0][:80]}
        for t in tools
    ]

    capabilities = derive_capabilities(runtime, tools)

    # Current state — from db
    try:
        facts_count = len(db.get_top_facts(50))
    except Exception:
        facts_count = 0
    try:
        active_goals = [g.get("title", "") for g in db.get_active_goals(3)]
    except Exception:
        active_goals = []

    now = datetime.now()
    return {
        "identity":        IDENTITY_TEXT,
        "runtime":         runtime,
        "environment":     {
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "tz":   "America/New_York",
        },
        "tool_inventory":  tool_inventory,
        "capabilities":    capabilities,
        "current_state":   {
            "facts_count":  facts_count,
            "active_goals": active_goals,
            "last_topic":   (state.get("session_summary") or "")[:120],
        },
        "operating_mode":  tier,
        "persona_anchor":  PERSONA_ANCHOR,
    }


def derive_capabilities(runtime: dict, tools: list) -> dict:
    """Returns {'can': [...], 'cant': [...]} given runtime + retrieved tools."""
    can, cant = [], []

    if runtime.get("location") == "local":
        can.append("read/list/search Mac files directly")
        can.append("write Mac files (with risk_gate confirmation)")
    else:
        if runtime.get("mac_bridge") == "connected":
            can.append("forward Mac requests through local bridge")
        else:
            cant.append("reach Mac (bridge offline — local TRUMAN not running)")
        cant.append("directly access Mac files (running on Railway)")

    can.append("search my own codebase via gitnexus")
    can.append("query memory (facts about Om, past conversations)")
    can.append("set reminders, manage goals, log sleep")

    cant.append("modify Railway DB or env vars")
    cant.append("see new web content beyond DuckDuckGo snippets")
    cant.append("access paid APIs without keys")

    return {"can": can, "cant": cant}


def tier_tone_hint(tier: str) -> str:
    """Tone instruction injected based on operating mode."""
    if tier == "trivial":
        return "Keep this short. 1-2 sentences max. Match casualness. No tools needed."
    if tier == "complex":
        return ("Take time to think. Multi-step reasoning OK. "
                "Show work briefly when relevant. Tool chains allowed.")
    return "Conversational. Direct answer. No preamble."


def render_system_prompt(self_state: dict, memory_block: str) -> str:
    """Compose the full dynamic system prompt for this turn."""
    rt = self_state["runtime"]
    env = self_state["environment"]
    caps = self_state["capabilities"]
    cs = self_state["current_state"]

    tools_block = (
        "\n".join(f"  - {t['name']}: {t['use']}" for t in self_state["tool_inventory"])
        if self_state["tool_inventory"]
        else "  (no tools needed for this turn)"
    )

    goals_line = (
        ", ".join(cs["active_goals"]) if cs["active_goals"] else "(none active)"
    )

    return f"""# WHO I AM
{self_state['identity']}

# WHERE I AM RUNNING
- Location:    {rt['location']}
- DB:          {rt['db_path']}
- Mac bridge:  {rt['mac_bridge']}
- Today:       {env['date']}, {env['time']} {env['tz']}

# WHAT I CAN ACCESS RIGHT NOW
Tools available this turn:
{tools_block}

I CAN: {', '.join(caps['can'])}.
I CAN'T: {', '.join(caps['cant'])}.

# WHAT I KNOW ABOUT OM
Memory: {cs['facts_count']} pinned facts. Active goals: {goals_line}.
Last topic: {cs['last_topic'] or '(new conversation)'}

{memory_block}

# OPERATING MODE THIS TURN
{self_state['operating_mode']} → {tier_tone_hint(self_state['operating_mode'])}

# HOW TO RESPOND
{self_state['persona_anchor']}
"""
