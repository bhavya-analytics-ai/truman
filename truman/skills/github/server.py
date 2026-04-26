"""
github/server.py — GitHub skill.
ingest_repo: clone a repo + ingest all text files into Cognee concept graph
read_file:   read a single file from a cloned repo
list_repo:   list files in a cloned repo
Kill switch: ENABLE_MCP_GITHUB=1 (under ENABLE_MCP master)
Repos cloned to truman/data/repos/ (gitignored).
"""
import os
import subprocess
import tempfile
import shutil
from truman.skills.base import SkillBase
from truman.skills._blacklist import is_blocked

_REPOS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "repos",
)
_TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".txt", ".yaml", ".yml",
    ".toml", ".json", ".html", ".css", ".sh", ".go", ".rs", ".java", ".cpp",
    ".c", ".h", ".rb", ".php", ".swift", ".kt", ".sql", ".env.example",
}
_MAX_FILE = 50_000  # chars per file for ingest
_MAX_INGEST_FILES = 200


class GitHubSkill(SkillBase):
    name        = "github"
    description = "Clone GitHub repos and ingest them into Truman's concept graph"
    enabled_env = "ENABLE_MCP_GITHUB"

    def is_available(self) -> bool:
        master = os.environ.get("ENABLE_MCP", "1") == "1"
        git_ok = shutil.which("git") is not None
        return master and git_ok and super().is_available()

    def list_tools(self) -> list[dict]:
        return [
            {"name": "ingest_repo", "description": "Clone a GitHub repo and ingest into concept graph", "args": ["url"]},
            {"name": "list_repo",   "description": "List files in a cloned repo", "args": ["repo_name"]},
            {"name": "read_file",   "description": "Read a file from a cloned repo", "args": ["repo_name", "path"]},
        ]

    def call(self, tool_name: str, **kwargs) -> str:
        try:
            ui = kwargs.get("user_input", "")
            if tool_name == "ingest_repo": return self._ingest(self._extract_url(ui, kwargs.get("url", "")))
            if tool_name == "list_repo":   return self._list(kwargs.get("repo_name", ""))
            if tool_name == "read_file":   return self._read(kwargs.get("repo_name", ""), kwargs.get("path", ""))
            return f"[github] unknown tool: {tool_name}"
        except Exception as e:
            return f"[github] error: {e}"

    def _extract_url(self, user_input: str, url: str) -> str:
        """Pull github URL out of natural language if explicit url not given."""
        if url:
            return url
        import re
        m = re.search(r"https?://github\.com/[^\s]+", user_input)
        return m.group(0) if m else ""

    def _repo_name(self, url: str) -> str:
        return url.rstrip("/").split("/")[-1].replace(".git", "")

    def _clone_path(self, repo_name: str) -> str:
        return os.path.join(_REPOS_DIR, repo_name)

    def _ingest(self, url: str) -> str:
        if not url:
            return "[github] no URL found in message"
        if "github.com" not in url:
            return f"[github] not a GitHub URL: {url}"

        repo_name  = self._repo_name(url)
        clone_path = self._clone_path(repo_name)
        os.makedirs(_REPOS_DIR, exist_ok=True)

        # clone or pull
        if os.path.isdir(clone_path):
            subprocess.run(["git", "-C", clone_path, "pull", "--quiet"], timeout=60)
            status = "updated"
        else:
            result = subprocess.run(
                ["git", "clone", "--depth=1", "--quiet", url, clone_path],
                timeout=120, capture_output=True, text=True
            )
            if result.returncode != 0:
                return f"[github] clone failed: {result.stderr[:300]}"
            status = "cloned"

        # collect text files
        files_text = []
        count = 0
        for root, dirs, files in os.walk(clone_path):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build")]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in _TEXT_EXTS:
                    continue
                fpath = os.path.join(root, fname)
                if is_blocked(fpath):
                    continue
                try:
                    with open(fpath, "r", errors="replace") as f:
                        content = f.read(_MAX_FILE)
                    rel = os.path.relpath(fpath, clone_path)
                    files_text.append(f"# {rel}\n{content}")
                    count += 1
                except Exception:
                    continue
                if count >= _MAX_INGEST_FILES:
                    break
            if count >= _MAX_INGEST_FILES:
                break

        if not files_text:
            return f"[github] {status} {repo_name} but no text files found"

        # ingest into Cognee
        try:
            from truman.brain.concepts import ingest
            full_text = f"REPO: {url}\n\n" + "\n\n---\n\n".join(files_text)
            ingest(full_text, dataset=f"repo_{repo_name}")
            return f"{status} + ingested {repo_name} ({count} files) into concept graph. Truman now knows this repo."
        except Exception as e:
            return f"{status} {repo_name} ({count} files) — Cognee ingest failed: {e}"

    def _list(self, repo_name: str) -> str:
        clone_path = self._clone_path(repo_name)
        if not os.path.isdir(clone_path):
            return f"[github] repo not cloned yet: {repo_name}"
        items = []
        for root, dirs, files in os.walk(clone_path):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), clone_path)
                items.append(rel)
            if len(items) > 300:
                break
        return "\n".join(sorted(items)[:300])

    def _read(self, repo_name: str, path: str) -> str:
        clone_path = self._clone_path(repo_name)
        fpath = os.path.join(clone_path, path)
        abs_f = os.path.abspath(fpath)
        if not abs_f.startswith(clone_path):
            return "[github] path outside repo"
        if not os.path.isfile(abs_f):
            return f"[github] file not found: {path}"
        with open(abs_f, "r", errors="replace") as f:
            return f.read(_MAX_FILE)
