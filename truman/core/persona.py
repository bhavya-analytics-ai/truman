"""
persona.py — re-exports SYSTEM from the new system_prompt builder.

The chat path (truman.text.chat) uses system_prompt.py directly.
This file exists only for legacy callers (proactive nudges, realtime.py)
that import SYSTEM.
"""
from truman.text.system_prompt import build_system_prompt as _build

# Built once at import. Legacy callers get a proper prompt.
SYSTEM = _build()
