"""
registry.py — Skill registry. Loads all skills, routes tool calls.
Skills register themselves here. Brain's route_skill node calls route().
"""
import os
from truman.skills.base import SkillBase

_SKILLS: dict[str, SkillBase] = {}
_TOOL_INDEX: dict[str, str] = {}   # tool_name → skill_name


def _load_skills():
    global _SKILLS, _TOOL_INDEX
    if _SKILLS:
        return
    if os.environ.get("ENABLE_MCP", "1") != "1":
        return

    from truman.skills.files.server  import FilesSkill
    from truman.skills.web.server    import WebSkill
    from truman.skills.github.server import GitHubSkill

    candidates = [FilesSkill(), WebSkill(), GitHubSkill()]
    for skill in candidates:
        if skill.is_available():
            _SKILLS[skill.name] = skill
            for tool in skill.list_tools():
                _TOOL_INDEX[tool["name"]] = skill.name
            print(f"[skills] loaded: {skill.name}")


def detect_skill(user_input: str) -> tuple[str | None, str | None]:
    """
    Return (skill_name, tool_name) if user input matches a skill tool, else (None, None).
    Simple keyword matching — fast, no LLM call.
    """
    _load_skills()
    text = user_input.lower()

    # GitHub: URL detected — route by EXPLICIT intent keyword.
    # Phase 2.0A: never auto-ingest on bare URL paste — ask intent first.
    if "github.com/" in text and "github" in _SKILLS:
        # Explicit clone/learn/ingest request → ingest_repo (still needs confirmed=True inside)
        if any(k in text for k in ("clone", "ingest", "learn this repo", "learn the repo",
                                    "add this repo", "index this repo", "index the repo",
                                    "add as skill", "register this repo")):
            return "github", "ingest_repo"
        # Explicit inspect-only request → metadata + README, no clone
        if any(k in text for k in ("inspect", "what is this repo", "tell me about this repo",
                                    "about this repo", "what does this repo", "summarize this repo",
                                    "describe this repo", "show me this repo", "info on this repo",
                                    "what's this repo", "whats this repo")):
            return "github", "inspect_repo"
        # Bare URL with no action keyword → ask intent, do nothing else
        return "github", "ask_intent"

    # GitHub: list all repos Truman knows
    if any(k in text for k in ("list repos", "what repos", "which repos", "repos you know",
                                "what github", "repos truman", "show repos")):
        if "github" in _SKILLS:
            return "github", "list_repos"

    # GitHub: read a specific file from a cloned repo (readme, filenames)
    if any(k in text for k in ("readme", "read the file", "open the file", "show me the file",
                                "read file from", "open file from")):
        if "github" in _SKILLS:
            return "github", "read_file"

    # GitHub: list files in a cloned repo (general or specific subfolder)
    if any(k in text for k in ("list files in", "show files in", "what files are in",
                                "files in the repo", "files in that repo",
                                "what's inside", "whats inside", "what is inside",
                                "inside the folder", "inside the dir",
                                "in the folder", "in the directory",
                                "folder contents", "list the folder", "show the folder",
                                "show me the folder", "what files in the")):
        if "github" in _SKILLS:
            return "github", "list_repo"

    # GitHub: search within a specific repo
    if any(k in text for k in ("search in repo", "search repo", "find in repo", "find in the repo",
                                "from the repo", "from that repo", "in the repo", "about the repo",
                                "what did you learn", "what do you know about the", "tell me about the",
                                "what's in the", "summarize the repo", "what does the repo")):
        if "github" in _SKILLS:
            return "github", "search_in_repo"

    # Files skill keywords
    if any(k in text for k in ("read file", "open file", "search my files", "find in my", "list files",
                                "what's in my", "look at my", "read my", "show me my")):
        if "files" in _SKILLS:
            return "files", "search_files"

    # Web skill keywords
    if any(k in text for k in ("fetch url", "read this page", "summarize this url", "open this link")):
        if "web" in _SKILLS:
            return "web", "fetch_url"

    return None, None


def route(skill_name: str, tool_name: str, user_input: str, **kwargs) -> str:
    """Call a specific skill tool. Returns string result."""
    _load_skills()
    skill = _SKILLS.get(skill_name)
    if not skill:
        return f"[skill:{skill_name}] not available"
    try:
        return skill.call(tool_name, user_input=user_input, **kwargs)
    except Exception as e:
        return f"[skill:{skill_name}.{tool_name}] error: {e}"


def list_all() -> dict:
    """Return all loaded skills + their tools. Used by dashboard."""
    _load_skills()
    return {
        name: skill.list_tools()
        for name, skill in _SKILLS.items()
    }
