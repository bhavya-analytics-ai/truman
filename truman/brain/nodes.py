"""
nodes.py — Each step in Truman's brain loop.
Every node: reads state, returns partial state update, never throws.
Failures are soft — logged to node_errors, rest of graph continues.
"""
import time
from truman.brain.state import TrumanState


# ── Node 1: classify_mood ─────────────────────────────────────────────────────
def classify_mood(state: TrumanState) -> dict:
    try:
        from truman.text.agent import _classify_mood
        mood = _classify_mood(state["user_input"])
        return {"mood": mood}
    except Exception as e:
        errs = dict(state.get("node_errors") or {})
        errs["classify_mood"] = str(e)
        return {"mood": "neutral", "node_errors": errs}


# ── Node 2: concept_lookup ────────────────────────────────────────────────────
def concept_lookup(state: TrumanState) -> dict:
    """
    Search the Cognee concept graph for domain knowledge related to user input.
    Runs only if ENABLE_COGNEE=1. Fails soft — graph continues without it.
    Also fires a background ingest of the current input to grow the graph.
    """
    import os
    if os.environ.get("ENABLE_COGNEE", "1") != "1":
        return {}
    try:
        from truman.brain.concepts import search_sync, ingest_background
        # search existing graph
        concept_ctx = search_sync(state["user_input"], top_k=4)
        # grow graph in background (non-blocking)
        ingest_background(state["user_input"])
        if concept_ctx:
            # append to memory context
            existing = state.get("memory_context", "")
            combined = f"{existing}\n\nCONCEPT GRAPH:\n{concept_ctx}" if existing else f"CONCEPT GRAPH:\n{concept_ctx}"
            return {"memory_context": combined}
        return {}
    except Exception as e:
        errs = dict(state.get("node_errors") or {})
        errs["concept_lookup"] = str(e)
        return {"node_errors": errs}


# ── Node 3: load_memory (Mem0 facts) ─────────────────────────────────────────
def load_memory(state: TrumanState) -> dict:
    try:
        from truman.text.agent import mem_search
        results = mem_search(state["user_input"])
        ctx = "\n".join([r["memory"] for r in results[:5]]) if results else ""
        return {"memory_context": ctx}
    except Exception as e:
        errs = dict(state.get("node_errors") or {})
        errs["load_memory"] = str(e)
        return {"memory_context": "", "node_errors": errs}


# ── Node 3b: load_goals ──────────────────────────────────────────────────────
def load_goals(state: TrumanState) -> dict:
    """
    Pull top 3 active goals from SQLite and format as a short context string.
    Runs only if ENABLE_GOALS=1. Fails soft — empty string if anything breaks.
    """
    import os
    if os.environ.get("ENABLE_GOALS", "1") != "1":
        return {"goals_context": ""}
    try:
        from truman.storage.db import get_active_goals
        goals = get_active_goals(limit=3)
        if not goals:
            return {"goals_context": ""}
        lines = ["ACTIVE GOALS:"]
        for g in goals:
            line = f"- {g['title']}"
            if g.get("description"):
                line += f": {g['description']}"
            lines.append(line)
        return {"goals_context": "\n".join(lines)}
    except Exception as e:
        errs = dict(state.get("node_errors") or {})
        errs["load_goals"] = str(e)
        return {"goals_context": "", "node_errors": errs}


# ── Node 3: detect_pool ───────────────────────────────────────────────────────
def detect_pool(state: TrumanState) -> dict:
    try:
        from truman.core.model_router import detect_pool as _detect_pool

        pool_hint = state.get("pool_hint")
        if pool_hint:
            return {"chosen_pool": pool_hint}

        chosen = _detect_pool(state["user_input"])
        return {"chosen_pool": chosen}
    except Exception as e:
        errs = dict(state.get("node_errors") or {})
        errs["detect_pool"] = str(e)
        return {"chosen_pool": "general", "node_errors": errs}


# ── Node 4: detect_tool ───────────────────────────────────────────────────────
def detect_tool(state: TrumanState) -> dict:
    try:
        from truman.text.agent import _detect_tool
        tool = _detect_tool(state["user_input"])
        return {"tool_name": tool}
    except Exception as e:
        errs = dict(state.get("node_errors") or {})
        errs["detect_tool"] = str(e)
        return {"tool_name": None, "node_errors": errs}


# ── Node 4b: route_skill ─────────────────────────────────────────────────────
def route_skill(state: TrumanState) -> dict:
    """
    Check if user input matches a skill (GitHub, files, web).
    If yes, execute the skill and set tool_result + skill_name.
    Falls through silently if ENABLE_MCP=0 or no skill matches.
    Runs before execute_tool — skill result takes priority.
    """
    import os
    if os.environ.get("ENABLE_MCP", "1") != "1":
        return {"skill_name": None}
    try:
        from truman.skills.registry import detect_skill, route
        skill_name, tool_name = detect_skill(state["user_input"])
        if not skill_name:
            return {"skill_name": None}
        result = route(skill_name, tool_name, state["user_input"])
        # log skill invocation to events drawer (sync skill calls only;
        # github fire-and-forget logs its own background completion)
        try:
            import threading, json as _j
            from truman.storage import db as _db
            failed = isinstance(result, str) and result.startswith("[skill") and "error" in result
            threading.Thread(
                target=_db.log_event_db,
                kwargs=dict(
                    kind="skill", source=skill_name,
                    session_id=None, pool="", model="",
                    elapsed_ms=0,
                    status="error" if failed else "ok",
                    detail=_j.dumps({"msg": state["user_input"][:120],
                                      "tools": [f"{skill_name}.{tool_name}"]}),
                    error=result if failed else None,
                ),
                daemon=True,
            ).start()
        except Exception:
            pass
        return {
            "skill_name":      skill_name,
            "tool_result":     result,
            "tool_calls_made": [{"name": f"{skill_name}.{tool_name}"}],
        }
    except Exception as e:
        errs = dict(state.get("node_errors") or {})
        errs["route_skill"] = str(e)
        return {"skill_name": None, "node_errors": errs}


# ── Node 5: execute_tool ──────────────────────────────────────────────────────
def execute_tool(state: TrumanState) -> dict:
    # If a skill already handled the request, don't run a legacy tool on top
    # (would clobber tool_result and tool_calls_made set by route_skill)
    if state.get("skill_name"):
        return {}
    tool_name = state.get("tool_name")
    if not tool_name:
        return {"tool_result": None, "tool_calls_made": []}
    try:
        from truman.tools.all_tools import TOOLS
        from truman.text.agent import _extract_arg
        tool_map = {t.name: t for t in TOOLS}
        if tool_name not in tool_map:
            return {"tool_result": None, "tool_calls_made": []}
        args = _extract_arg(state["user_input"], tool_name)
        result = tool_map[tool_name].invoke(args)
        return {
            "tool_result":     str(result),
            "tool_calls_made": [{"name": tool_name}],
        }
    except Exception as e:
        errs = dict(state.get("node_errors") or {})
        errs["execute_tool"] = str(e)
        return {"tool_result": f"tool error: {e}", "tool_calls_made": [], "node_errors": errs}


# ── Node 6: call_llm ──────────────────────────────────────────────────────────
def call_llm(state: TrumanState) -> dict:
    try:
        from datetime import datetime, timezone, timedelta
        from zoneinfo import ZoneInfo
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
        from truman.core.persona import SYSTEM
        from truman.text.agent import _last_session_str, _chat_histories

        session_id = state["session_id"]
        chat_history = _chat_histories.setdefault(session_id, [])

        try:
            now_et = datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            now_et = datetime.now(timezone(timedelta(hours=-4)))  # EDT fallback
        clock_line = f"\n\nCURRENT TIME: {now_et.strftime('%A, %b %d %Y, %I:%M %p ET')}"
        mem_ctx = state.get("memory_context", "")
        mood = state.get("mood", "neutral")
        mood_line = f"\n\nMOOD CONTEXT: {mood}" if mood and mood != "neutral" else ""
        persona_reminder = "\n\nCRITICAL: You are texting Om on his dashboard. Be direct, casual, lowercase. No bullet points. No asking permission. Commit to your answer. Match Om's energy."
        last_session_ctx = _last_session_str()

        goals_ctx = state.get("goals_context", "")
        system_content = (
            SYSTEM + clock_line
            + (f"\n\nRelevant memory:\n{mem_ctx}" if mem_ctx else "")
            + (f"\n\n{goals_ctx}" if goals_ctx else "")
            + last_session_ctx + mood_line + persona_reminder
        )

        # node errors context (so Truman can mention if tools silently failed)
        node_errors = state.get("node_errors") or {}
        if node_errors:
            system_content += f"\n\n[INTERNAL: some steps had soft failures: {node_errors}]"

        messages = [SystemMessage(content=system_content)]
        for h in chat_history[-16:]:
            if h["role"] == "user":
                messages.append(HumanMessage(content=h["content"]))
            else:
                messages.append(AIMessage(content=h["content"]))

        user_input = state["user_input"]
        tool_result = state.get("tool_result")
        tool_name   = state.get("tool_name")
        if tool_result:
            messages.append(HumanMessage(content=f"{user_input}\n\n[Tool result from {tool_name}]:\n{tool_result}"))
        else:
            messages.append(HumanMessage(content=user_input))

        import re as _re
        from truman.text.agent import strip_markdown
        from truman.core.model_router import run_with_pool
        result = run_with_pool(messages, pool=state.get("chosen_pool", "general"), user_message=user_input)
        raw = result["content"]
        model_label = result["model"]
        response = strip_markdown(raw)
        # strip any fake [Tool result ...] blocks the LLM hallucinated
        response = _re.sub(r'\[Tool result[^\]]*\][:\s]*[^\n]*\n?', '', response).strip()

        # update chat history
        chat_history.append({"role": "user",      "content": user_input})
        chat_history.append({"role": "assistant",  "content": response})
        if len(chat_history) > 32:
            _chat_histories[session_id] = chat_history[-32:]

        return {"response": response, "model_label": model_label}
    except Exception as e:
        errs = dict(state.get("node_errors") or {})
        errs["call_llm"] = str(e)
        return {"response": "", "model_label": "none", "node_errors": errs, "fatal_error": str(e)}


# ── Node 7: save_memory ───────────────────────────────────────────────────────
def save_memory(state: TrumanState) -> dict:
    try:
        import threading
        from truman.text.agent import _mem_add_smart
        threading.Thread(
            target=_mem_add_smart,
            args=(state["user_input"], state.get("response", "")),
            daemon=True,
        ).start()
    except Exception as e:
        errs = dict(state.get("node_errors") or {})
        errs["save_memory"] = str(e)
        return {"node_errors": errs}
    return {}


# ── Node 8: emit_event ────────────────────────────────────────────────────────
def emit_event(state: TrumanState, elapsed_ms: int = 0) -> dict:
    try:
        import json as _j, threading
        from truman.storage import db as _db
        node_errors = state.get("node_errors") or {}
        fatal = state.get("fatal_error", "")
        status = "error" if fatal else ("warn" if node_errors else "ok")
        detail = _j.dumps({
            "msg":   state["user_input"][:120],
            "tools": [t["name"] for t in (state.get("tool_calls_made") or [])],
            "node_errors": node_errors,
        })
        threading.Thread(
            target=_db.log_event_db,
            kwargs=dict(
                kind="chat", source="text",
                session_id=state["session_id"],
                pool=state.get("chosen_pool", ""),
                model=state.get("model_label", ""),
                elapsed_ms=elapsed_ms,
                status=status,
                detail=detail,
                error=fatal or (str(node_errors) if node_errors else None),
            ),
            daemon=True,
        ).start()
    except Exception:
        pass
    return {}
