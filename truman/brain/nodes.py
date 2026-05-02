"""
nodes.py — Each step in Truman's brain loop.
Every node: reads state, returns partial state update, never throws.
Failures are soft — logged to node_errors, rest of graph continues.
"""
import time
from truman.brain.state import TrumanState


# ── Trace helper ─────────────────────────────────────────────────────────────
def _t(state: TrumanState, node: str, status: str,
       summary: str = "", args: dict = None, result: str = None, duration_ms: int = None):
    """Fire-and-forget trace event. Never raises."""
    try:
        import threading
        from truman.storage.notifications import push_trace
        threading.Thread(
            target=push_trace,
            kwargs=dict(
                session_id=state.get("session_id", ""),
                turn_id=state.get("turn_id", ""),
                node=node, status=status, summary=summary,
                args=args, result=result, duration_ms=duration_ms,
            ),
            daemon=True,
        ).start()
    except Exception:
        pass


# ── Node 1: classify_mood ─────────────────────────────────────────────────────
def classify_mood(state: TrumanState) -> dict:
    _t(state, "classify_mood", "start", summary=f'"{state["user_input"][:60]}"')
    t0 = time.time()
    try:
        from truman.text.agent import _classify_mood
        mood = _classify_mood(state["user_input"])
        _t(state, "classify_mood", "end", summary=f"mood → {mood}", duration_ms=int((time.time()-t0)*1000))
        return {"mood": mood}
    except Exception as e:
        _t(state, "classify_mood", "error", summary=str(e))
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
    t0 = time.time()
    if os.environ.get("ENABLE_COGNEE", "1") != "1":
        _t(state, "concept_lookup", "end", summary="skipped (disabled)")
        return {}
    _ui = state["user_input"].strip()
    _GREETINGS = {"yo", "hey", "hi", "sup", "what's up", "whats up", "yoo", "heyy", "wassup"}
    _FILE_TOOLS = {"list_mac_dir", "read_mac_file", "search_mac_files", "write_mac_file"}
    from truman.text.agent import _detect_tool
    if len(_ui) < 50 or _ui.lower().rstrip("!?.") in _GREETINGS or _detect_tool(_ui) in _FILE_TOOLS:
        _t(state, "concept_lookup", "end", summary="skipped (short/greeting/file tool)")
        return {}
    _t(state, "concept_lookup", "start", summary="searching concept graph")
    try:
        from truman.brain.concepts import search_sync, ingest_background
        concept_ctx = search_sync(state["user_input"], top_k=4)
        ingest_background(state["user_input"])
        ms = int((time.time()-t0)*1000)
        if concept_ctx:
            existing = state.get("memory_context", "")
            combined = f"{existing}\n\nCONCEPT GRAPH:\n{concept_ctx}" if existing else f"CONCEPT GRAPH:\n{concept_ctx}"
            _t(state, "concept_lookup", "end", summary="found concept context", result=concept_ctx[:200], duration_ms=ms)
            return {"memory_context": combined}
        _t(state, "concept_lookup", "end", summary="no concept matches", duration_ms=ms)
        return {}
    except Exception as e:
        _t(state, "concept_lookup", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["concept_lookup"] = str(e)
        return {"node_errors": errs}


# ── Node 3: load_memory (Mem0 facts) ─────────────────────────────────────────
def load_memory(state: TrumanState) -> dict:
    t0 = time.time()
    _ui = state["user_input"].strip()
    _GREETINGS = {"yo", "hey", "hi", "sup", "what's up", "whats up", "yoo", "heyy", "wassup"}
    _FILE_TOOLS = {"list_mac_dir", "read_mac_file", "search_mac_files", "write_mac_file"}
    from truman.text.agent import _detect_tool
    if len(_ui) < 50 or _ui.lower().rstrip("!?.") in _GREETINGS or _detect_tool(_ui) in _FILE_TOOLS:
        _t(state, "load_memory", "end", summary="skipped (short/greeting/file tool)")
        return {"memory_context": ""}
    _t(state, "load_memory", "start", summary="searching Mem0")
    try:
        from truman.text.agent import mem_search
        results = mem_search(state["user_input"])
        ctx = "\n".join([r["memory"] for r in results[:5]]) if results else ""
        ms = int((time.time()-t0)*1000)
        summary = f"{len(results)} mem0 facts loaded" if results else "no mem0 matches"
        _t(state, "load_memory", "end", summary=summary, result=ctx[:200] if ctx else None, duration_ms=ms)
        return {"memory_context": ctx}
    except Exception as e:
        _t(state, "load_memory", "error", summary=str(e))
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
    t0 = time.time()
    if os.environ.get("ENABLE_GOALS", "1") != "1":
        _t(state, "load_goals", "end", summary="skipped (disabled)")
        return {"goals_context": ""}
    _t(state, "load_goals", "start", summary="loading active goals")
    try:
        from truman.storage.db import get_active_goals
        goals = get_active_goals(limit=3)
        ms = int((time.time()-t0)*1000)
        if not goals:
            _t(state, "load_goals", "end", summary="no active goals", duration_ms=ms)
            return {"goals_context": ""}
        lines = ["ACTIVE GOALS:"]
        for g in goals:
            line = f"- {g['title']}"
            if g.get("description"):
                line += f": {g['description']}"
            lines.append(line)
        ctx = "\n".join(lines)
        _t(state, "load_goals", "end", summary=f"{len(goals)} goals loaded", result=ctx, duration_ms=ms)
        return {"goals_context": ctx}
    except Exception as e:
        _t(state, "load_goals", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["load_goals"] = str(e)
        return {"goals_context": "", "node_errors": errs}


# ── Node 3c: curiosity ───────────────────────────────────────────────────────
def curiosity(state: TrumanState) -> dict:
    """
    Background curiosity layer — searches Cognee concept graph for context
    related to active goals. Runs only if ENABLE_CURIOSITY=1 and goals exist.
    Injects a short 'CURIOSITY:' block into curiosity_context.
    Fails soft — graph continues without it.
    """
    import os
    t0 = time.time()
    if os.environ.get("ENABLE_CURIOSITY", "1") != "1":
        _t(state, "curiosity", "end", summary="skipped (disabled)")
        return {"curiosity_context": ""}
    goals_ctx = state.get("goals_context", "")
    if not goals_ctx:
        _t(state, "curiosity", "end", summary="skipped (no active goals)")
        return {"curiosity_context": ""}
    _ui = state["user_input"].strip()
    _FILE_TOOLS = {"list_mac_dir", "read_mac_file", "search_mac_files", "write_mac_file"}
    from truman.text.agent import _detect_tool
    if len(_ui) < 50 or _detect_tool(_ui) in _FILE_TOOLS:
        _t(state, "curiosity", "end", summary="skipped (short/file tool)")
        return {"curiosity_context": ""}
    _t(state, "curiosity", "start", summary="searching concept graph for goal context")
    try:
        from truman.brain.concepts import search_sync
        lines = [l.lstrip("- ").split(":")[0].strip()
                 for l in goals_ctx.splitlines() if l.startswith("-")]
        if not lines:
            _t(state, "curiosity", "end", summary="no goal titles parsed")
            return {"curiosity_context": ""}
        query = " ".join(lines[:2])
        result = search_sync(query, top_k=3)
        ms = int((time.time()-t0)*1000)
        if not result:
            _t(state, "curiosity", "end", summary="no concept matches for goals", duration_ms=ms)
            return {"curiosity_context": ""}
        _t(state, "curiosity", "end", summary="curiosity context found", result=result[:200], duration_ms=ms)
        return {"curiosity_context": f"CURIOSITY (concept graph on your goals):\n{result}"}
    except Exception as e:
        _t(state, "curiosity", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["curiosity"] = str(e)
        return {"curiosity_context": "", "node_errors": errs}


# ── Node 3: detect_pool ───────────────────────────────────────────────────────
def detect_pool(state: TrumanState) -> dict:
    t0 = time.time()
    try:
        from truman.core.model_router import detect_pool as _detect_pool
        from truman.text.agent import _detect_tool

        pool_hint = state.get("pool_hint")
        if pool_hint:
            _t(state, "detect_pool", "end", summary=f"pool → {pool_hint} (hint)", duration_ms=int((time.time()-t0)*1000))
            return {"chosen_pool": pool_hint}

        _FILE_TOOLS = {"list_mac_dir", "read_mac_file", "search_mac_files", "write_mac_file", "tree_mac_dir"}
        if _detect_tool(state["user_input"]) in _FILE_TOOLS:
            _t(state, "detect_pool", "end", summary="pool → fast (file tool)", duration_ms=int((time.time()-t0)*1000))
            return {"chosen_pool": "fast"}

        chosen = _detect_pool(state["user_input"])
        _t(state, "detect_pool", "end", summary=f"pool → {chosen}", duration_ms=int((time.time()-t0)*1000))
        return {"chosen_pool": chosen}
    except Exception as e:
        _t(state, "detect_pool", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["detect_pool"] = str(e)
        return {"chosen_pool": "general", "node_errors": errs}


# ── Node 4: detect_tool ───────────────────────────────────────────────────────
def detect_tool(state: TrumanState) -> dict:
    t0 = time.time()
    try:
        from truman.text.agent import _detect_tool
        tool = _detect_tool(state["user_input"])
        summary = f"tool → {tool}" if tool else "no tool detected"
        _t(state, "detect_tool", "end", summary=summary, duration_ms=int((time.time()-t0)*1000))
        return {"tool_name": tool}
    except Exception as e:
        _t(state, "detect_tool", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["detect_tool"] = str(e)
        return {"tool_name": None, "node_errors": errs}


# ── Node 4a: risk_gate ───────────────────────────────────────────────────────
import re as _re_rg
# Only unambiguous words — "yes"/"no"/"stop" are too common in normal speech
_CONFIRM_RE = _re_rg.compile(r"\b(do it|confirm|go ahead|yeah do it|proceed)\b", _re_rg.I)
_CANCEL_RE  = _re_rg.compile(r"\b(cancel|nevermind|nope|abort)\b", _re_rg.I)

def risk_gate(state: TrumanState) -> dict:
    """
    Intercepts risky tool calls and waits for explicit confirmation.
    - safe/caution tools: pass straight through (zero overhead)
    - risky tools: block, store in pending_actions, return preview message
    - "do it" / "cancel" on next turn: execute or discard
    ENABLE_RISK_GATE=1 kill switch.
    """
    import os
    t0 = time.time()
    if os.environ.get("ENABLE_RISK_GATE", "1") != "1":
        _t(state, "risk_gate", "end", summary="skipped (disabled)")
        return {"risk_tier": "safe", "awaiting_confirm": False}
    try:
        from truman.storage.db import (
            get_pending_action, clear_pending_action,
            expire_pending_actions, save_pending_action,
        )
        from truman.core.risk import get_tier

        expire_pending_actions()
        user_input = state["user_input"]
        tool_name  = state.get("tool_name")

        # Check if Om is confirming / cancelling a pending action
        pending = get_pending_action()
        if pending:
            if _CONFIRM_RE.search(user_input):
                clear_pending_action(pending["id"])
                import json as _j
                from truman.tools.all_tools import TOOLS
                args = _j.loads(pending["args"])
                tool_map = {t.name: t for t in TOOLS}
                try:
                    result = str(tool_map[pending["tool_name"]].invoke(args))
                except Exception as ex:
                    result = f"tool error: {ex}"
                try:
                    from truman.storage.notifications import push as _push
                    _push(f"✓ {pending['tool_name']} confirmed — {result[:80]}", kind="toast")
                except Exception:
                    pass
                return {
                    "tool_name":         pending["tool_name"],
                    "tool_result":       result,
                    "tool_calls_made":   [{"name": pending["tool_name"]}],
                    "risk_tier":         "risky",
                    "awaiting_confirm":  False,
                    "pending_action_id": None,
                }
            elif _CANCEL_RE.search(user_input):
                clear_pending_action(pending["id"])
                return {
                    "tool_name":         None,
                    "risk_tier":         "safe",
                    "awaiting_confirm":  False,
                    "pending_action_id": None,
                    "tool_result":       "cancelled.",
                }

        if not tool_name:
            return {"risk_tier": "safe", "awaiting_confirm": False}

        tier = get_tier(tool_name)

        if tier == "risky":
            from truman.text.agent import _extract_arg
            args = _extract_arg(user_input, tool_name)
            pid  = save_pending_action(tool_name, args, user_input)
            preview = f"`{tool_name}`"
            if isinstance(args, dict):
                first = next(iter(args.values()), None)
                if first:
                    preview += f" — {str(first)[:80]}"
            elif args:
                preview += f" — {str(args)[:80]}"
            return {
                "tool_name":         None,        # block execution this turn
                "risk_tier":         "risky",
                "awaiting_confirm":  True,
                "pending_action_id": pid,
                "tool_result":       f"[risk gate] about to run {preview}. say 'do it' to confirm or 'cancel'",
            }

        _t(state, "risk_gate", "end", summary=f"tier → {tier}", duration_ms=int((time.time()-t0)*1000))
        return {"risk_tier": tier, "awaiting_confirm": False, "pending_action_id": None}
    except Exception as e:
        _t(state, "risk_gate", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["risk_gate"] = str(e)
        return {"risk_tier": "safe", "awaiting_confirm": False, "node_errors": errs}


# ── Node 4b: route_skill ─────────────────────────────────────────────────────
def route_skill(state: TrumanState) -> dict:
    """
    Check if user input matches a skill (GitHub, files, web).
    If yes, execute the skill and set tool_result + skill_name.
    Falls through silently if ENABLE_MCP=0 or no skill matches.
    Runs before execute_tool — skill result takes priority.
    """
    import os
    t0 = time.time()
    if os.environ.get("ENABLE_MCP", "1") != "1":
        _t(state, "route_skill", "end", summary="skipped (MCP disabled)")
        return {"skill_name": None}
    try:
        from truman.skills.registry import detect_skill, route
        skill_name, tool_name = detect_skill(state["user_input"])
        if not skill_name:
            _t(state, "route_skill", "end", summary="no skill match", duration_ms=int((time.time()-t0)*1000))
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
        ms = int((time.time()-t0)*1000)
        _t(state, "route_skill", "end", summary=f"skill → {skill_name}.{tool_name}",
           result=str(result)[:200], duration_ms=ms)
        return {
            "skill_name":      skill_name,
            "tool_result":     result,
            "tool_calls_made": [{"name": f"{skill_name}.{tool_name}"}],
        }
    except Exception as e:
        _t(state, "route_skill", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["route_skill"] = str(e)
        return {"skill_name": None, "node_errors": errs}


# ── Node 5: execute_tool ──────────────────────────────────────────────────────
def execute_tool(state: TrumanState) -> dict:
    t0 = time.time()
    if state.get("skill_name"):
        _t(state, "execute_tool", "end", summary="skipped (skill handled)")
        return {}
    if state.get("tool_calls_made") or state.get("awaiting_confirm"):
        _t(state, "execute_tool", "end", summary="skipped (risk gate handled)")
        return {}
    tool_name = state.get("tool_name")
    if not tool_name:
        _t(state, "execute_tool", "end", summary="no tool to run")
        return {"tool_result": None, "tool_calls_made": []}
    _t(state, "execute_tool", "start", summary=f"running {tool_name}", args={"tool": tool_name})
    try:
        from truman.tools.all_tools import TOOLS
        from truman.text.agent import _extract_arg
        tool_map = {t.name: t for t in TOOLS}
        if tool_name not in tool_map:
            _t(state, "execute_tool", "error", summary=f"tool {tool_name} not found")
            return {"tool_result": None, "tool_calls_made": []}
        args = _extract_arg(state["user_input"], tool_name)
        result = tool_map[tool_name].invoke(args)
        ms = int((time.time()-t0)*1000)
        _t(state, "execute_tool", "end", summary=f"{tool_name} completed",
           args=args, result=str(result)[:300], duration_ms=ms)
        try:
            from truman.storage.notifications import push as _push
            _push(f"✓ {tool_name} — {str(result)[:80]}", kind="toast")
        except Exception:
            pass
        return {
            "tool_result":     str(result),
            "tool_calls_made": [{"name": tool_name}],
        }
    except Exception as e:
        _t(state, "execute_tool", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["execute_tool"] = str(e)
        return {"tool_result": f"tool error: {e}", "tool_calls_made": [], "node_errors": errs}


# ── Node 6: call_llm ──────────────────────────────────────────────────────────
def call_llm(state: TrumanState) -> dict:
    # Risk gate blocked this turn — return the gate message directly, no LLM call
    if state.get("awaiting_confirm") and state.get("tool_result"):
        gate_msg = state["tool_result"].replace("[risk gate] ", "", 1)
        return {"response": gate_msg, "model_label": "risk-gate"}

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
        persona_reminder = "\n\nCRITICAL: You are texting Om on his dashboard. Be direct, casual, lowercase. No bullet points. No asking permission. Commit to your answer. Match Om's energy. NEVER claim which model you are — just respond. NEVER write '[Tool result...]' or '(hypothetical output)' or invent bracket-blocks."
        last_session_ctx = _last_session_str()

        goals_ctx     = state.get("goals_context", "")
        curiosity_ctx = state.get("curiosity_context", "")

        # load top user facts (cross-chat persistent memory about Om)
        facts_ctx = ""
        try:
            from truman.storage.db import get_top_facts
            facts = get_top_facts(10)
            if facts:
                lines = "\n".join(f"- {f['fact']}" for f in facts)
                facts_ctx = f"\n\nWHAT YOU KNOW ABOUT OM (pinned facts):\n{lines}"
        except Exception:
            pass

        # load active persona rules (Phase 13 — self-correcting persona)
        import os as _os
        rules_ctx = ""
        if _os.environ.get("ENABLE_SELF_CORRECT", "1") == "1":
            try:
                from truman.storage.db import get_active_rules
                rules = get_active_rules()
                if rules:
                    lines = "\n".join(f"- {r['rule']}" for r in rules)
                    rules_ctx = f"\n\nPERSONAL RULES (Om set these — follow them exactly):\n{lines}"
            except Exception:
                pass

        system_content = (
            SYSTEM + clock_line
            + (f"\n\nRelevant memory:\n{mem_ctx}" if mem_ctx else "")
            + facts_ctx
            + rules_ctx
            + (f"\n\n{goals_ctx}" if goals_ctx else "")
            + (f"\n\n{curiosity_ctx}" if curiosity_ctx else "")
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
        _t(state, "call_llm", "start", summary=f"calling {state.get('chosen_pool','general')} pool",
           args={"pool": state.get("chosen_pool","general"), "tool_result": bool(tool_result)})
        t0 = time.time()
        result = run_with_pool(messages, pool=state.get("chosen_pool", "general"), user_message=user_input)
        raw = result["content"]
        model_label = result["model"]
        response = strip_markdown(raw)
        # strip hallucinated tool/model blocks
        response = _re.sub(r'\[Tool result[^\]]*\][:\s]*[^\n]*\n?', '', response)
        response = _re.sub(r'\[[^\]]{1,40}\]\s*\([^\)]*hypothetical[^\)]*\)[^\n]*\n?', '', response, flags=_re.I)
        response = _re.sub(r'\(hypothetical output[^\)]*\)[^\n]*\n?', '', response, flags=_re.I)
        response = _re.sub(r'\[MODEL:[^\]]*\]', '', response, flags=_re.I)
        response = response.strip()

        # update chat history
        chat_history.append({"role": "user",      "content": user_input})
        chat_history.append({"role": "assistant",  "content": response})
        if len(chat_history) > 32:
            _chat_histories[session_id] = chat_history[-32:]

        ms = int((time.time()-t0)*1000)
        _t(state, "call_llm", "end", summary=f"{model_label} → {len(response)} chars",
           result=response[:200], duration_ms=ms)
        return {"response": response, "model_label": model_label}
    except Exception as e:
        _t(state, "call_llm", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["call_llm"] = str(e)
        return {"response": "", "model_label": "none", "node_errors": errs, "fatal_error": str(e)}


# ── Node 7: save_memory ───────────────────────────────────────────────────────
def save_memory(state: TrumanState) -> dict:
    _t(state, "save_memory", "start", summary="saving turn to Mem0 (background)")
    try:
        import threading
        from truman.text.agent import _mem_add_smart
        threading.Thread(
            target=_mem_add_smart,
            args=(state["user_input"], state.get("response", "")),
            daemon=True,
        ).start()
        _t(state, "save_memory", "end", summary="queued to Mem0")
    except Exception as e:
        _t(state, "save_memory", "error", summary=str(e))
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
