"""
base.py — SkillBase: every skill inherits this.
Provides: name, description, list_tools(), call(tool_name, **kwargs)
"""
from abc import ABC, abstractmethod


class SkillBase(ABC):
    name: str = ""
    description: str = ""
    enabled_env: str = ""      # env var that must be "1" to activate this skill

    @abstractmethod
    def list_tools(self) -> list[dict]:
        """Return list of {name, description, args} dicts."""
        ...

    @abstractmethod
    def call(self, tool_name: str, **kwargs) -> str:
        """Execute a tool. Returns string result. Never raises — catches internally."""
        ...

    def is_available(self) -> bool:
        import os
        if self.enabled_env:
            return os.environ.get(self.enabled_env, "0") == "1"
        return True
