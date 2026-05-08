"""
loop.py — Truman's LangGraph brain loop.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRUMAN CORE FUNCTION:
  A message arrives → Truman reads it, picks the right
  tool/pool, calls the LLM, and returns a reply.
  Everything else in the system exists to make THIS better.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Node roles:
  CORE   — classify_mood, detect_pool, detect_tool, risk_gate,
            route_skill, execute_tool, call_llm, evaluate_output, save_memory
  SUPPORT— load_memory, load_goals
           (enrich the reply; fail soft; never block the loop)

Sequential graph: mood → memory → pool → tool → llm → eval → save → event
Each node is isolated, fails soft, errors surface in the events drawer.
"""
import time
from langgraph.graph import StateGraph, END
from truman.brain.state import TrumanState
from truman.brain import nodes


def _route_after_tool_retrieval(state: dict) -> str:
    """Trivial tier skips load_goals + recall_skills — go straight to detect_pool."""
    tier = (state.get("routing") or {}).get("tier", "normal")
    return "detect_pool" if tier == "trivial" else "load_goals"


def _route_after_call_llm(state: dict) -> str:
    """Trivial tier skips post-LLM risk gate — go straight to evaluate_output."""
    tier = (state.get("routing") or {}).get("tier", "normal")
    return "evaluate_output" if tier == "trivial" else "risk_gate_node"


def _build_graph():
    g = StateGraph(TrumanState)

    g.add_node("tier_router",     nodes.tier_router_node)
    g.add_node("classify_mood",  nodes.classify_mood)
    g.add_node("load_memory",    nodes.load_memory)
    g.add_node("self_awareness",  nodes.self_awareness_node)
    g.add_node("tool_retrieval",  nodes.tool_retrieval_node)
    g.add_node("load_goals",      nodes.load_goals)
    g.add_node("recall_skills",  nodes.recall_skills)
    g.add_node("detect_pool",    nodes.detect_pool)
    g.add_node("risk_gate",      nodes.risk_gate)    # handles "do it" confirmations
    g.add_node("call_llm",        nodes.call_llm)
    g.add_node("risk_gate_node",  nodes.risk_gate_node)
    g.add_node("evaluate_output", nodes.evaluate_output)
    g.add_node("save_memory",     nodes.save_memory)

    g.set_entry_point("tier_router")
    g.add_edge("tier_router",     "classify_mood")
    g.add_edge("classify_mood",   "load_memory")
    g.add_edge("load_memory",     "self_awareness")
    g.add_edge("self_awareness",  "tool_retrieval")
    g.add_conditional_edges(
        "tool_retrieval",
        _route_after_tool_retrieval,
        {"load_goals": "load_goals", "detect_pool": "detect_pool"},
    )
    g.add_edge("load_goals",      "recall_skills")
    g.add_edge("recall_skills",   "detect_pool")
    g.add_edge("detect_pool",     "risk_gate")     # risk_gate handles "do it" confirmations
    g.add_edge("risk_gate",       "call_llm")
    g.add_conditional_edges(
        "call_llm",
        _route_after_call_llm,
        {"risk_gate_node": "risk_gate_node", "evaluate_output": "evaluate_output"},
    )
    g.add_edge("risk_gate_node",  "evaluate_output")   # eval before save — no bad drafts in memory
    g.add_edge("evaluate_output", "save_memory")
    g.add_edge("save_memory",     END)

    return g.compile()


# compiled once at import time
_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


def run(user_input: str, session_id: str = "default", pool_hint: str = None, attach_ids: list = None) -> dict:
    """
    Run the LangGraph brain loop.
    Returns same shape as agent.run() — response, model, pool, tool_calls, mood.
    """
    # ── Kill switch check (Om-only — Truman cannot bypass this) ──────────────
    try:
        from truman.storage.db import killswitch_active
        if killswitch_active():
            return {
                "response":   "i'm off. om turned me off.",
                "model":      "none",
                "pool":       "none",
                "tool_calls": [],
                "mood":       "neutral",
                "warnings":   [],
            }
    except Exception:
        pass

    t_start = time.time()

    import uuid as _uuid
    turn_id = str(_uuid.uuid4())[:8]

    initial_state: TrumanState = {
        "session_id":       session_id,
        "user_input":       user_input,
        "turn_id":          turn_id,
        "pool_hint":        pool_hint,
        "mood":             "neutral",
        "memory_context":   "",
        "goals_context":    "",
        "skills_context":   "",
        "risk_tier":          "safe",
        "pending_action_id":  None,
        "awaiting_confirm":   False,
        "chosen_pool":      "general",
        "tool_name":        None,
        "tool_result":      None,
        "tool_calls_made":  [],
        "skill_name":       None,
        "messages":         [],
        "response":         "",
        "model_label":      "none",
        "attach_ids":       list(attach_ids or []),
        "node_errors":      {},
        "fatal_error":      "",
        "eval_score":       "skip",
        "eval_issues":      [],
        "eval_action":      "accept",
        "eval_type":        "none",
        # smart routing fields
        "routing":          {},
        "self_state":       {},
        "retrieved_tools":  [],
        "llm_tool_calls":   [],
    }

    final_state = get_graph().invoke(initial_state)
    elapsed_ms = int((time.time() - t_start) * 1000)

    # emit event after we know elapsed time
    nodes.emit_event(final_state, elapsed_ms=elapsed_ms)

    return {
        "response":   final_state.get("response", ""),
        "model":      final_state.get("model_label", "none"),
        "pool":       final_state.get("chosen_pool", "general"),
        "tool_calls": final_state.get("tool_calls_made", []),
        "mood":       final_state.get("mood", "neutral"),
        "warnings":   list((final_state.get("node_errors") or {}).values()),
        "skill":      final_state.get("skill_name") or "",
    }
