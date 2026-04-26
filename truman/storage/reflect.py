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
import sys
import traceback

from truman.storage import db
from truman.core.config import get_llm


REFLECT_PROMPT = """You are a reflection agent for Om's personal AI system. Read this conversation between Om and Truman.

Extract structured intelligence — not a story, not a summary. Logic that can be acted on.

Return STRICT JSON only (no markdown, no commentary):
{
  "summary": "2-3 sentence overview of what happened",
  "tasks_completed": ["task 1", "task 2"],
  "key_decisions": ["decision 1", "decision 2"],
  "errors": ["what broke or failed"],
  "fixes": ["what was done to fix it"],
  "next_day_priorities": ["what Om should focus on next"],
  "facts": ["durable fact about Om worth remembering long-term"]
}

Rules:
- tasks_completed: things Om actually finished or shipped this session
- key_decisions: architectural, strategic, or personal choices made (e.g. "moved to Railway", "changed model pool", "adjusted forex risk rule")
- errors: failures, bugs, broken things — not code errors, actual problems encountered
- fixes: what resolved each error
- next_day_priorities: 2-3 most important things to pick up next session
- facts: durable info about Om (projects, preferences, locations, plans, opinions) — skip small talk
- If a field has nothing relevant, return an empty list []

If the conversation is too short or trivial:
{"summary": "Brief check-in, nothing notable.", "tasks_completed": [], "key_decisions": [], "errors": [], "fixes": [], "next_day_priorities": [], "facts": []}

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

        # json_mode=False — NIM doesn't support response_format:json_object
        # prompt already demands strict JSON, we parse + strip markdown fences
        llm = get_llm(temperature=0.2, json_mode=False)
        messages = [
            SystemMessage(content="You are a precise reflection agent. Return only raw JSON, no markdown, no code fences."),
            HumanMessage(content=REFLECT_PROMPT % convo),
        ]

        for attempt in range(2):  # primary call + 1 retry on bad JSON
            resp = llm.invoke(messages)
            raw = resp.content.strip()
            # strip markdown code fences if model wraps in ```json ... ```
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            try:
                return json.loads(raw)
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
        from truman.text.agent import memory, USER_ID
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
    if len(turns) < 2:
        db.set_session_summary(session_id, json.dumps({
            "summary": "Session opened but no exchange.",
            "tasks_completed": [], "key_decisions": [], "errors": [],
            "fixes": [], "next_day_priorities": [], "facts": []
        }))
        return True

    print(f"[reflect] session {session_id}: {len(turns)} turns")
    result = _call_llm(convo)
    if not result:
        return False

    r = result
    structured = {
        "summary":             (r.get("summary") or "No summary.").strip(),
        "tasks_completed":     r.get("tasks_completed") or [],
        "key_decisions":       r.get("key_decisions") or [],
        "errors":              r.get("errors") or [],
        "fixes":               r.get("fixes") or [],
        "next_day_priorities": r.get("next_day_priorities") or [],
        "facts":               r.get("facts") or [],
    }
    db.set_session_summary(session_id, json.dumps(structured))
    print(f"[reflect]   summary: {structured['summary']}")

    mem_facts = structured["facts"] + \
                [f"Decision: {d}" for d in structured["key_decisions"]] + \
                [f"Error: {e}" for e in structured["errors"]]
    _push_facts(mem_facts)
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
