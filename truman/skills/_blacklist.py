"""
_blacklist.py — Paths and patterns skills can NEVER touch.
Truman has no tool that bypasses this. Checked in every file-write operation.
"""
import os
import re

_HOME = os.path.expanduser("~")

# Absolute paths that are always off-limits
BLOCKED_PATHS = [
    os.path.join(_HOME, ".ssh"),
    os.path.join(_HOME, ".aws"),
    os.path.join(_HOME, "Library", "Keychains"),
    os.path.join(_HOME, "Library", "Application Support", "1Password"),
]

# Path substring patterns — if any match, block it
BLOCKED_PATTERNS = [
    r"\.killswitch",
    r"\.env$",
    r"credentials",
    r"secret",
    r"private.?key",
    r"\.pem$",
    r"\.key$",
    r"keychain",
    r"password",
    r"token",
]

_COMPILED = [re.compile(p, re.I) for p in BLOCKED_PATTERNS]


def is_blocked(path: str) -> bool:
    """Return True if this path must not be touched by any skill."""
    abs_path = os.path.abspath(os.path.expanduser(path))
    for blocked in BLOCKED_PATHS:
        if abs_path.startswith(blocked):
            return True
    for pat in _COMPILED:
        if pat.search(abs_path):
            return True
    return False
