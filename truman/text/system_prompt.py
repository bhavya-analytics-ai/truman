"""
system_prompt.py — Truman's system prompt built ONCE at boot, cached in RAM.

No per-turn DB reads. Facts loaded from user_facts at module load time.
Call reload_system_prompt() after new facts are saved.
"""
import datetime
from truman.core.runtime import is_railway

_CACHED: str | None = None

_PERSONA = """You are Truman — Om's second brain. Not an assistant. His person.

Talk like a person: lowercase ok, casual, direct, no markdown, no "Great question!".
Short message = short reply. Greeting = one line back. Real question = 3-5 sentences.
Never lie about what you did. If you don't know, say so.

Tools: only call a tool when Om actually asks for what that tool does.
Never fire tools on greetings, acks, reactions, or small talk."""


def _load_facts() -> str:
    try:
        from truman.storage.db import get_top_facts
        facts = get_top_facts(limit=40)
        if not facts:
            return ""
        lines = [f["fact"] for f in facts]
        return "About Om:\n" + "\n".join(f"- {l}" for l in lines)
    except Exception:
        return ""


def build_system_prompt() -> str:
    today = datetime.date.today().isoformat()
    runtime = "railway" if is_railway() else "local"
    facts = _load_facts()
    parts = [_PERSONA, f"Today: {today}. Runtime: {runtime}.", facts]
    return "\n\n".join(p for p in parts if p)


def get_system_prompt() -> str:
    global _CACHED
    if _CACHED is None:
        _CACHED = build_system_prompt()
    return _CACHED


def reload_system_prompt() -> str:
    global _CACHED
    _CACHED = build_system_prompt()
    return _CACHED
