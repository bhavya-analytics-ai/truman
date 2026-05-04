"""
risk.py — Risk tier definitions for Truman's risk gate.

Three tiers:
  safe    → run instantly, no prompt
  caution → run instantly, log only
  risky   → pause, preview, wait for "do it" / "cancel"
"""

RISK_TIERS: dict[str, list[str]] = {
    "safe": [
        "web_search", "get_weather", "recall", "list_goals", "list_models",
        "list_reminders", "search_history", "recent_conversations",
        "list_mac_dir", "search_mac_files", "read_mac_file",
    ],
    "caution": [
        "set_reminder", "add_goal", "complete_goal", "drop_goal",
        "remember", "update_pref", "log_sleep",
    ],
    "risky": [
        "write_mac_file", "set_model",
    ],
}


def get_tier(tool_name: str) -> str:
    """Return risk tier for a tool. Unknown tools default to caution."""
    for tier, tools in RISK_TIERS.items():
        if tool_name in tools:
            return tier
    return "caution"
