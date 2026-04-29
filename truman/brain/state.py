"""
state.py — Truman's LangGraph state object.
One TypedDict travels through every node. Each node reads what it needs,
writes what it produces. Nothing shared globally.
"""
from typing import TypedDict, Optional


class TrumanState(TypedDict):
    # ── Input ────────────────────────────────────────────────────────────────
    session_id:      str
    user_input:      str
    pool_hint:       Optional[str]   # explicit pool from caller (file upload etc)

    # ── Produced by nodes ────────────────────────────────────────────────────
    mood:            str             # classify_mood
    memory_context:  str             # load_memory
    chosen_pool:     str             # detect_pool
    tool_name:       Optional[str]   # detect_tool
    tool_result:     Optional[str]   # execute_tool / route_skill
    tool_calls_made: list            # execute_tool / route_skill
    skill_name:      Optional[str]   # route_skill — which skill ran

    goals_context:   str             # load_goals — top active goals
    curiosity_context: str           # curiosity — Cognee search on active goals

    # ── Risk gate ────────────────────────────────────────────────────────────
    risk_tier:         str           # safe | caution | risky
    pending_action_id: Optional[str] # set when awaiting confirm
    awaiting_confirm:  bool          # True = blocked waiting for "do it"

    # ── LLM output ───────────────────────────────────────────────────────────
    messages:        list            # built before call_llm
    response:        str             # call_llm
    model_label:     str             # call_llm

    # ── Error tracking ───────────────────────────────────────────────────────
    node_errors:     dict            # {node_name: error_str} — soft failures
    fatal_error:     str             # if whole graph failed
