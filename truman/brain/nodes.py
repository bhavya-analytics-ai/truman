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
    _t(state, "load_memory", "start", summary="searching memory")
    try:
        from truman.text.agent import mem_search
        results = mem_search(state["user_input"])
        ctx = "\n".join([r["memory"] for r in results[:5]]) if results else ""
        ms = int((time.time()-t0)*1000)
        summary = f"{len(results)} facts loaded" if results else "no memory matches"
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


# ── Node 3c: recall_skills ───────────────────────────────────────────────────
def recall_skills(state: TrumanState) -> dict:
    """
    Search learned_skills table for patterns relevant to the current message.
    Appends a short LEARNED SKILLS block to memory_context if matches found.
    SUPPORT node — fails soft, never blocks the loop.
    """
    import os
    t0 = time.time()
    if os.environ.get("ENABLE_REPO_LEARNING", "1") != "1":
        return {"skills_context": ""}
    user_input = state.get("user_input", "").strip()
    # skip for short greetings / single-word messages
    if len(user_input.split()) < 3:
        return {"skills_context": ""}
    try:
        from truman.storage.db import search_learned_skills
        hits = search_learned_skills(user_input, limit=4)
        ms = int((time.time()-t0)*1000)
        if not hits:
            _t(state, "recall_skills", "end", summary="no skill matches", duration_ms=ms)
            return {"skills_context": ""}
        lines = ["LEARNED FROM REPOS:"]
        for h in hits:
            repo = h["repo_name"]
            pat  = h["pattern"]
            desc = h["description"] or ""
            lines.append(f"- [{repo}] {pat}: {desc}")
        ctx = "\n".join(lines)
        _t(state, "recall_skills", "end", summary=f"{len(hits)} skills recalled", result=ctx, duration_ms=ms)
        return {"skills_context": ctx}
    except Exception as e:
        _t(state, "recall_skills", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["recall_skills"] = str(e)
        return {"skills_context": "", "node_errors": errs}


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
        detected_tool = _detect_tool(state["user_input"])
        if detected_tool in _FILE_TOOLS:
            _t(state, "detect_pool", "end", summary="pool → general (file tool)", duration_ms=int((time.time()-t0)*1000))
            print(f"[ROUTING] pool=general  reason=FILE_TOOL  matched={detected_tool}")
            return {"chosen_pool": "general", "routing_reason": "FILE_TOOL", "routing_matched": detected_tool}

        from truman.core.model_router import detect_pool_with_reason
        has_image = bool(state.get("attach_ids"))
        chosen, reason, matched = detect_pool_with_reason(
            state["user_input"], has_image=has_image, tool_detected=detected_tool or None
        )
        print(f"[ROUTING] pool={chosen}  reason={reason}  matched={matched}")
        _t(state, "detect_pool", "end", summary=f"pool → {chosen} ({reason})", duration_ms=int((time.time()-t0)*1000))
        return {"chosen_pool": chosen, "routing_reason": reason, "routing_matched": matched}
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
        mood = state.get("mood", "neutral")
        mood_line = f"\n\nMOOD CONTEXT: {mood}" if mood and mood != "neutral" else ""
        persona_reminder = "\n\nCRITICAL: You are texting Om on his dashboard. Be direct, casual, lowercase. No bullet points. No asking permission. Commit to your answer. Match Om's energy. NEVER claim which model you are — just respond. NEVER write '[Tool result...]' or '(hypothetical output)' or invent bracket-blocks."
        last_session_ctx = _last_session_str()

        # ── Memory resolver (Phase 3) — single source, enforced priority ─────
        # facts → goals → persona_rules | logs intentionally excluded
        from truman.brain.memory import resolve_memory, build_memory_prompt
        mem_bundle  = resolve_memory(state)
        memory_block = build_memory_prompt(mem_bundle)

        system_content = (
            SYSTEM + clock_line
            + (f"\n\n{memory_block}" if memory_block else "")
            + last_session_ctx + mood_line + persona_reminder
        )

        # node errors context (so Truman can mention if tools silently failed)
        node_errors = state.get("node_errors") or {}
        if node_errors:
            failed_nodes = ", ".join(node_errors.keys())
            system_content += f"\n\nINTERNAL NOTE: these nodes had soft failures this turn: {failed_nodes}. If the user's request is affected by one of these, mention it naturally in your reply."

        # Build full message list via multimodal/call.py (L3 — type-aware builder)
        attach_ids  = state.get("attach_ids") or []
        user_input  = state["user_input"]
        tool_result = state.get("tool_result")
        tool_name   = state.get("tool_name")

        try:
            from truman.multimodal.call import build_messages
            messages = build_messages(
                system_content=system_content,
                chat_history=chat_history,
                user_input=user_input,
                attach_ids=attach_ids,
                tool_result=tool_result,
                tool_name=tool_name,
                history_window=16,
            )
        except Exception as _mm_err:
            print(f"[call_llm] multimodal build_messages fallback: {_mm_err}")
            # Fallback: plain text, no multimodal
            from langchain_core.messages import SystemMessage as _SM, HumanMessage as _HM, AIMessage as _AM
            messages = [_SM(content=system_content)]
            for h in chat_history[-16:]:
                if h["role"] == "user":
                    messages.append(_HM(content=h["content"]))
                else:
                    messages.append(_AM(content=h["content"]))
            txt = user_input + (f"\n\n[Tool result from {tool_name}]:\n{tool_result}" if tool_result else "")
            messages.append(_HM(content=txt))

        import re as _re
        from truman.text.agent import strip_markdown
        from truman.core.model_router import run_with_pool

        # ── Mode hint for GENERAL pool (soft nudge — one line, after persona) ─
        chosen_pool = state.get("chosen_pool", "general")
        if chosen_pool == "general":
            _ui_lower = user_input.lower()
            _creative_cues = {"story", "poem", "creative", "imagine", "write a", "invent", "name idea", "pitch"}
            _doc_cues = {"draft an email", "write a report", "format this", "summarize", "write up"}
            if any(c in _ui_lower for c in _creative_cues):
                system_content += "\nRespond creatively."
            elif any(c in _ui_lower for c in _doc_cues):
                system_content += "\nBe structured and clear."

        _t(state, "call_llm", "start", summary=f"calling {chosen_pool} pool",
           args={"pool": chosen_pool, "tool_result": bool(tool_result)})
        t0 = time.time()

        # ── TOOL AGENCY FIX ───────────────────────────────────────────────────
        # Always bind tools so LLM has agency. If a tool already ran via
        # regex/detect_tool, route_skill, or risk-gate, its result is already
        # baked into `messages` — but the LLM can still call additional tools
        # (e.g. override an incorrect regex pick by calling the right tool).
        # Risk-gate awaiting_confirm path is handled at the top of this node
        # and never reaches here.
        dyn_tool_calls: list = []
        from truman.text.agent import _call_llm_with_tools, _is_complex
        from truman.tools.all_tools import TOOLS as _NATIVE_TOOLS
        _tool_map = {t.name: t for t in _NATIVE_TOOLS}
        raw, model_label, dyn_tool_calls = _call_llm_with_tools(
            messages, _NATIVE_TOOLS, _tool_map,
            complex_msg=_is_complex(user_input),
        )

        total_lat = round(time.time() - t0, 1)
        print(f"[MODEL] model={model_label}  pool={chosen_pool}  total={total_lat}s  dyn_tools={len(dyn_tool_calls)}")
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
        _t(state, "call_llm", "end", summary=f"{model_label} → {len(response)} chars  dyn_tools={len(dyn_tool_calls)}",
           result=response[:200], duration_ms=ms)

        # merge any tools the LLM called dynamically into tool_calls_made
        existing_calls = list(state.get("tool_calls_made") or [])
        return {
            "response":        response,
            "model_label":     model_label,
            "tool_calls_made": existing_calls + dyn_tool_calls,
        }
    except Exception as e:
        _t(state, "call_llm", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["call_llm"] = str(e)
        return {"response": "", "model_label": "none", "node_errors": errs, "fatal_error": str(e)}


# ── Node 6b: evaluate_output ─────────────────────────────────────────────────
def evaluate_output(state: TrumanState) -> dict:
    """
    Hybrid evaluator: rule check → conditional LLM → retry on bad.
    Runs BEFORE save_memory so only the accepted output is stored.
    ENABLE_EVAL=0 → pass-through, zero overhead.
    """
    import os
    t0 = time.time()

    _SKIP = {"eval_score": "skip", "eval_issues": [], "eval_action": "accept", "eval_type": "none"}

    if os.environ.get("ENABLE_EVAL", "1") != "1":
        return _SKIP

    # Nothing to evaluate on risk-gate turns
    if state.get("awaiting_confirm") or not state.get("response"):
        return _SKIP

    try:
        from truman.brain.eval import evaluate, build_retry_hint
        from truman.brain.memory import resolve_memory

        turn_id      = state.get("turn_id", "")
        user_input   = state["user_input"]
        response     = state.get("response", "")
        tool_result  = state.get("tool_result")
        tool_name    = state.get("tool_name")

        # active_facts — only facts that were in prompt context this turn
        try:
            mem_bundle  = resolve_memory(state)
            active_facts = mem_bundle.get("facts", [])
        except Exception:
            active_facts = []

        # ── Evaluate (result frozen by turn_id) ──────────────────────────────
        result = evaluate(
            turn_id=turn_id,
            user_input=user_input,
            response=response,
            tool_result=tool_result,
            tool_name=tool_name,
            active_facts=active_facts,
        )

        score     = result["score"]
        action    = result["action"]
        issues    = result["issues"]
        eval_type = result["eval_type"]
        reason    = result.get("reason", "")

        ms = int((time.time() - t0) * 1000)
        print(f"[EVAL] score={score}  action={action}  type={eval_type}  issues={issues or 'none'}  reason={reason[:60] if reason else ''}")
        _t(state, "evaluate_output", "end",
           summary=f"score={score} action={action}",
           result=str(issues), duration_ms=ms)

        # ── Log every eval result to eval_log (background) ──────────────────
        try:
            import threading
            from truman.storage.db import log_eval as _log_eval
            threading.Thread(
                target=_log_eval,
                kwargs=dict(
                    turn_id=turn_id,
                    session_id=state.get("session_id", ""),
                    model=state.get("model_label", ""),
                    pool=state.get("chosen_pool", ""),
                    score=score,
                    issues=issues,
                    reason=reason,
                    action=action,
                    retry_fired=0,   # updated below if retry fires
                ),
                daemon=True,
            ).start()
        except Exception:
            pass

        # ── Log weak as optimization candidate ───────────────────────────────
        if score == "weak":
            try:
                import json as _j, threading
                from truman.storage import db as _db
                threading.Thread(
                    target=_db.log_event_db,
                    kwargs=dict(
                        kind="eval_weak", source="evaluate_output",
                        session_id=state.get("session_id"),
                        pool=state.get("chosen_pool", ""),
                        model=state.get("model_label", ""),
                        elapsed_ms=ms,
                        status="weak",
                        detail=_j.dumps({
                            "issues": issues,
                            "reason": reason,
                            "msg":    user_input[:120],
                        }),
                        error=None,
                    ),
                    daemon=True,
                ).start()
            except Exception:
                pass

        # ── Retry on bad (one retry, frozen hint from this eval snapshot) ────
        if action == "retry":
            try:
                from truman.core.model_router import run_with_pool
                from truman.core.persona import SYSTEM

                # non-cumulative: build hint only from THIS eval result
                hint = build_retry_hint(result)
                print(f"[EVAL] retry firing  hint={hint}")

                # get the existing messages and inject hint (replace, don't append)
                retry_messages = list(state.get("messages") or [])
                if retry_messages:
                    # inject into system message (index 0)
                    from langchain_core.messages import SystemMessage
                    orig_sys = retry_messages[0].content if hasattr(retry_messages[0], "content") else ""
                    # strip any previous eval hint to prevent bloat
                    import re as _re_eval
                    orig_sys = _re_eval.sub(r'\[EVAL RETRY\][^\n]*\n?', '', orig_sys)
                    retry_messages[0] = SystemMessage(content=orig_sys + f"\n{hint}")

                retry_result = run_with_pool(
                    retry_messages,
                    pool=state.get("chosen_pool", "general"),
                    user_message=user_input,
                )
                new_response  = retry_result.get("content", response)
                new_model     = retry_result.get("model", state.get("model_label", ""))
                retry_ms = int((time.time() - t0) * 1000)
                print(f"[EVAL] retry done  model={new_model}  latency={retry_ms}ms")

                # log retry outcome
                try:
                    import threading
                    from truman.storage.db import log_eval as _log_eval
                    threading.Thread(
                        target=_log_eval,
                        kwargs=dict(
                            turn_id=turn_id, session_id=state.get("session_id",""),
                            model=new_model, pool=state.get("chosen_pool",""),
                            score=score, issues=issues, reason=reason,
                            action=action, retry_fired=1, score_after="unknown",
                        ),
                        daemon=True,
                    ).start()
                except Exception:
                    pass

                return {
                    "response":    new_response,
                    "model_label": new_model,
                    "eval_score":  score,
                    "eval_issues": issues,
                    "eval_action": action,
                    "eval_type":   eval_type,
                }
            except Exception as retry_err:
                # retry failed — keep original response, log error
                print(f"[EVAL] retry failed: {retry_err}")

        return {
            "eval_score":  score,
            "eval_issues": issues,
            "eval_action": action,
            "eval_type":   eval_type,
        }

    except Exception as e:
        _t(state, "evaluate_output", "error", summary=str(e))
        errs = dict(state.get("node_errors") or {})
        errs["evaluate_output"] = str(e)
        return {**_SKIP, "node_errors": errs}


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
