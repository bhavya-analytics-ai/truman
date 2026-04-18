#!/usr/bin/env python3
"""
reflect.py — Nightly reflection loop for Truman (Level 5b).

Runs at 2am via launchd (com.om.truman-reflect.plist). For every ended
session that doesn't yet have a summary:
  1. Pull its turns from SQLite
  2. Ask GPT-4o for a short summary + list of durable facts about Om
  3. Write the summary to session_summaries
  4. Push each new fact to Mem0 via memory.add

Run manually any time:
    python reflect.py
"""

import json
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import db  # noqa: E402
from config import get_llm  # noqa: E402


REFLECT_PROMPT = """You are a reflection agent. Read this voice conversation between Om and his AI assistant Truman.

Produce:
1. A 2-3 sentence SUMMARY of what they talked about, decisions made, and anything unresolved.
2. A list of durable FACTS about Om worth remembering long-term — projects, preferences, locations, plans, state changes, opinions. Skip small talk, greetings, filler.

Return STRICT JSON (no markdown, no commentary):
{"summary": "...", "facts": ["fact 1", "fact 2", ...]}

If the conversation is too short or trivial to extract anything, return:
{"summary": "Brief check-in, nothing notable.", "facts": []}

Conversation:
---
%s
---"""


def _unsummarized_sessions() -> list[int]:
    """Return ids of ended sessions that have turns but no summary yet."""
    with db._conn() as c:
        rows = c.execute(
            """
            SELECT s.id
            FROM sessions s
            LEFT JOIN session_summaries ss ON ss.session_id = s.id
            WHERE s.ended_at IS NOT NULL
              AND ss.session_id IS NULL
              AND EXISTS (SELECT 1 FROM turns t WHERE t.session_id = s.id)
            ORDER BY s.id
            """
        ).fetchall()
    return [r["id"] for r in rows]


def _format_turns(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        role = "Om" if t["role"] == "user" else "Truman"
        lines.append(f"{role}: {t['content']}")
    return "\n".join(lines)


def _call_llm(convo: str) -> dict | None:
    """Single-shot reflection call. Returns {"summary": str, "facts": [str]} or None on failure.

    Uses get_llm() which auto-falls-back from OpenAI to Groq on quota/rate errors.
    One retry on malformed JSON before giving up.
    """
    try:
        # lazy import so the script doesn't pay the LangChain load cost unless needed
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = get_llm(temperature=0.2, json_mode=True)
        messages = [
            SystemMessage(content="You are a precise reflection agent. You only return JSON."),
            HumanMessage(content=REFLECT_PROMPT % convo),
        ]

        for attempt in range(2):  # primary call + 1 retry on bad JSON
            resp = llm.invoke(messages)
            try:
                return json.loads(resp.content)
            except json.JSONDecodeError:
                if attempt == 0:
                    print("[reflect] malformed JSON, retrying once", file=sys.stderr)
                    continue
                print(f"[reflect] JSON retry failed. Raw: {resp.content[:200]}", file=sys.stderr)
                return None
    except Exception as e:
        print(f"[reflect] LLM call failed: {e}", file=sys.stderr)
        traceback.print_exc()
        return None


def _push_facts(facts: list[str]):
    if not facts:
        return
    try:
        from agent import memory, USER_ID
    except Exception as e:
        print(f"[reflect] Mem0 import failed: {e}", file=sys.stderr)
        return
    for f in facts:
        f = (f or "").strip()
        if not f:
            continue
        try:
            memory.add([{"role": "user", "content": f}], user_id=USER_ID)
            print(f"[reflect]   + fact: {f}")
        except Exception as e:
            print(f"[reflect]   ! failed to add fact {f!r}: {e}", file=sys.stderr)


def reflect_on(session_id: int) -> bool:
    turns = db.session_turns(session_id)
    if not turns:
        return False

    convo = _format_turns(turns)
    # skip trivially short sessions (< 2 turns means it never actually exchanged)
    if len(turns) < 2:
        db.set_session_summary(session_id, "Session opened but no exchange.")
        return True

    print(f"[reflect] session {session_id}: {len(turns)} turns")
    result = _call_llm(convo)
    if not result:
        return False

    summary = (result.get("summary") or "").strip()
    facts   = result.get("facts") or []
    if not summary:
        summary = "No summary produced."

    db.set_session_summary(session_id, summary)
    print(f"[reflect]   summary: {summary}")

    if isinstance(facts, list):
        _push_facts([str(f) for f in facts])

    return True


def main():
    db.init()
    pending = _unsummarized_sessions()
    if not pending:
        print("[reflect] no sessions pending")
        return
    print(f"[reflect] {len(pending)} session(s) to reflect on")
    for sid in pending:
        try:
            reflect_on(sid)
        except Exception as e:
            print(f"[reflect] session {sid} crashed: {e}", file=sys.stderr)
            traceback.print_exc()


if __name__ == "__main__":
    main()
