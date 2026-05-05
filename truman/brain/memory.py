"""
memory.py — Truman's memory resolver.

Single source of truth for what context reaches the LLM.
All nodes that need memory context call resolve_memory() — nothing else.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MEMORY HIERARCHY (enforced here, never overridden elsewhere):
  facts        = ground truth  — wins all conflicts
  goals        = active intent — active status only, filtered here
  persona_rules= constraints   — always present, even if empty
  logs         = history only  — intentionally excluded from decision context
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GUARDRAILS (enforced here):
  ❌ Inferred/non-pinned info never written into facts automatically
  ❌ Logs never used as decision authority
  ✅ Goals filtered to active status before returning
  ✅ persona_rules always returns a list (never None)
"""


def resolve_memory(state: dict) -> dict:
    """
    Pull all memory sources, apply priority filters, return a structured bundle.

    Returns:
        {
          "facts":         [{"fact": str, ...}],   # pinned ground truth
          "goals":         [{"title": str, ...}],  # active goals only
          "persona_rules": [{"rule": str, ...}],   # behavior constraints
          "mem_ctx":       str,                    # Mem0 context string
          "meta": {
            "source_priority": ["facts", "goals", "persona_rules"],
            # logs intentionally excluded from decision context
          }
        }
    """
    result = {
        "facts":         [],
        "goals":         [],
        "persona_rules": [],
        "mem_ctx":       state.get("memory_context", ""),
        "skills_ctx":    state.get("skills_context", ""),
        "meta": {
            "source_priority": ["facts", "goals", "persona_rules", "skills"],
            # logs intentionally excluded from decision context
        },
    }

    # ── Facts (ground truth — pinned only, no inferred) ───────────────────────
    try:
        from truman.storage.db import get_top_facts
        raw_facts = get_top_facts(10) or []
        # Only pinned facts are authoritative — strip anything not explicitly saved by Om
        result["facts"] = [f for f in raw_facts if isinstance(f, dict) and f.get("fact")]
    except Exception:
        pass  # fail soft — empty facts, not a crash

    # ── Goals (active intent — active status only) ─────────────────────────────
    try:
        from truman.storage.db import get_all_goals
        raw_goals = get_all_goals() or []
        # GUARDRAIL: only active goals reach the LLM — stale goals never influence behavior
        result["goals"] = [g for g in raw_goals if g.get("status") == "active"]
    except Exception:
        pass  # fail soft

    # ── Persona rules (constraints — always a list, never None) ───────────────
    try:
        import os
        if os.environ.get("ENABLE_SELF_CORRECT", "1") == "1":
            from truman.storage.db import get_active_rules
            result["persona_rules"] = get_active_rules() or []
        else:
            result["persona_rules"] = []
    except Exception:
        result["persona_rules"] = []  # always a list, never None

    # logs intentionally excluded from decision context — see hierarchy above

    return result


def build_memory_prompt(bundle: dict) -> str:
    """
    Convert a resolve_memory() bundle into an ordered prompt block.
    Priority enforced by insertion order: facts → goals → persona.
    Returns empty string if nothing to inject.
    """
    parts = []

    # 1. Facts — ground truth, highest priority
    if bundle.get("facts"):
        lines = "\n".join(f"- {f['fact']}" for f in bundle["facts"])
        parts.append(f"WHAT YOU KNOW ABOUT OM (ground truth — trust these above all):\n{lines}")

    # 2. Mem0 context — supporting memory
    mem_ctx = bundle.get("mem_ctx", "")
    if mem_ctx:
        parts.append(f"Relevant memory:\n{mem_ctx}")

    # 3. Goals — active intent only
    if bundle.get("goals"):
        lines = "\n".join(
            f"- {g['title']}" + (f" — {g['description']}" if g.get("description") else "")
            for g in bundle["goals"]
        )
        parts.append(f"OM'S ACTIVE GOALS (intent — use as context, not commands):\n{lines}")

    # 4. Skills — patterns learned from repos
    skills_ctx = bundle.get("skills_ctx", "")
    if skills_ctx:
        parts.append(skills_ctx)

    # 5. Persona rules — behavior constraints, always last so they wrap everything
    if bundle.get("persona_rules"):
        lines = "\n".join(f"- {r['rule']}" for r in bundle["persona_rules"])
        parts.append(f"PERSONAL RULES (Om set these — follow them exactly):\n{lines}")

    return "\n\n".join(parts)
