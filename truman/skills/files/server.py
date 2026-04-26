"""
files/server.py — Files skill.
Read, write, search, list files under Om's Desktop.
Blocked paths enforced via _blacklist.py.
Kill switch: ENABLE_MCP_FILES=1 (falls under ENABLE_MCP master)
On Railway: ~/Desktop doesn't exist → skill reports dormant.
"""
import os
import fnmatch
from truman.skills.base import SkillBase
from truman.skills._blacklist import is_blocked

_ROOT = os.path.expanduser("~/Desktop")
_MAX_READ   = 50_000   # chars
_MAX_WRITE  = 1_000_000  # bytes
_WRITE_EXTS = {".py", ".js", ".ts", ".md", ".txt", ".json", ".yaml", ".yml",
               ".toml", ".csv", ".html", ".css", ".sh", ".env.example"}


class FilesSkill(SkillBase):
    name        = "files"
    description = "Read, write, search files on Om's Desktop"
    enabled_env = "ENABLE_MCP_FILES"

    def is_available(self) -> bool:
        if not super().is_available():
            return False
        master = os.environ.get("ENABLE_MCP", "1") == "1"
        desktop_exists = os.path.isdir(_ROOT)
        return master and desktop_exists

    def list_tools(self) -> list[dict]:
        return [
            {"name": "read_file",    "description": "Read a file from Om's Desktop", "args": ["path"]},
            {"name": "write_file",   "description": "Write content to a file on Om's Desktop", "args": ["path", "content"]},
            {"name": "list_files",   "description": "List files in a directory on Om's Desktop", "args": ["path", "pattern"]},
            {"name": "search_files", "description": "Search for text in files on Om's Desktop", "args": ["query", "path", "pattern"]},
        ]

    def call(self, tool_name: str, **kwargs) -> str:
        try:
            if tool_name == "read_file":   return self._read(kwargs.get("path", ""))
            if tool_name == "write_file":  return self._write(kwargs.get("path", ""), kwargs.get("content", ""))
            if tool_name == "list_files":  return self._list(kwargs.get("path", ""), kwargs.get("pattern", "*"))
            if tool_name == "search_files":return self._search(kwargs.get("user_input", ""), kwargs.get("path", ""), kwargs.get("pattern", "*"))
            return f"[files] unknown tool: {tool_name}"
        except Exception as e:
            return f"[files] error: {e}"

    def _safe_path(self, path: str) -> str:
        """Resolve and guard path. Must stay within ~/Desktop."""
        if not path:
            return _ROOT
        p = os.path.join(_ROOT, path) if not os.path.isabs(path) else path
        abs_p = os.path.abspath(p)
        if not abs_p.startswith(_ROOT):
            raise PermissionError(f"path outside Desktop: {abs_p}")
        if is_blocked(abs_p):
            raise PermissionError(f"path blocked by blacklist: {abs_p}")
        return abs_p

    def _read(self, path: str) -> str:
        abs_p = self._safe_path(path)
        if not os.path.isfile(abs_p):
            return f"[files] not found: {path}"
        with open(abs_p, "r", errors="replace") as f:
            content = f.read(_MAX_READ)
        truncated = len(content) == _MAX_READ
        return content + ("\n\n[truncated at 50k chars]" if truncated else "")

    def _write(self, path: str, content: str) -> str:
        abs_p = self._safe_path(path)
        ext = os.path.splitext(abs_p)[1].lower()
        if ext not in _WRITE_EXTS:
            return f"[files] write blocked for extension {ext!r}"
        if len(content.encode()) > _MAX_WRITE:
            return "[files] content too large (>1MB)"
        os.makedirs(os.path.dirname(abs_p), exist_ok=True)
        with open(abs_p, "w") as f:
            f.write(content)
        return f"written: {abs_p}"

    def _list(self, path: str, pattern: str = "*") -> str:
        abs_p = self._safe_path(path)
        if not os.path.isdir(abs_p):
            return f"[files] not a directory: {path}"
        items = []
        for entry in sorted(os.scandir(abs_p), key=lambda e: e.name):
            if fnmatch.fnmatch(entry.name, pattern):
                kind = "dir" if entry.is_dir() else "file"
                size = f" ({entry.stat().st_size:,}b)" if entry.is_file() else ""
                items.append(f"{kind}  {entry.name}{size}")
        return "\n".join(items[:200]) or "(empty)"

    def _search(self, query: str, path: str = "", pattern: str = "*.py") -> str:
        abs_p = self._safe_path(path)
        hits = []
        for root, dirs, files in os.walk(abs_p):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if not fnmatch.fnmatch(fname, pattern):
                    continue
                fpath = os.path.join(root, fname)
                if is_blocked(fpath):
                    continue
                try:
                    with open(fpath, "r", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if query.lower() in line.lower():
                                rel = os.path.relpath(fpath, _ROOT)
                                hits.append(f"{rel}:{i}: {line.rstrip()}")
                                if len(hits) >= 50:
                                    break
                except Exception:
                    continue
                if len(hits) >= 50:
                    break
        return "\n".join(hits) or f"no results for '{query}'"
