"""
github/server.py — GitHub skill.
ingest_repo:   clone + extract patterns into learned_skills (no Cognee)
list_repos:    show all repos Truman has ingested (from memory_repos table)
list_repo:     list files in a specific cloned repo
read_file:     read a file from a cloned repo
search_in_repo: search text across a cloned repo's files
"""
from __future__ import annotations
import os
import subprocess
import shutil
import fnmatch
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
_MAX_FILE = 50_000
_MAX_INGEST_FILES = 200


class GitHubSkill(SkillBase):
    name        = "github"
    description = "Clone GitHub repos, ingest into concept graph, search across repos"
    enabled_env = "ENABLE_MCP_GITHUB"

    def is_available(self) -> bool:
        master = os.environ.get("ENABLE_MCP", "1") == "1"
        return master and shutil.which("git") is not None and super().is_available()

    def list_tools(self) -> list[dict]:
        return [
            {"name": "ingest_repo",    "description": "Clone a GitHub repo and ingest into concept graph", "args": ["url"]},
            {"name": "list_repos",     "description": "List all repos Truman has ingested", "args": []},
            {"name": "list_repo",      "description": "List files in a specific cloned repo", "args": ["repo_name"]},
            {"name": "read_file",      "description": "Read a file from a cloned repo", "args": ["repo_name", "path"]},
            {"name": "search_in_repo", "description": "Search text across a cloned repo", "args": ["repo_name", "query"]},
        ]

    def call(self, tool_name: str, **kwargs) -> str:
        try:
            ui = kwargs.get("user_input", "")
            if tool_name == "ingest_repo":    return self._ingest(self._extract_url(ui, kwargs.get("url", "")))
            if tool_name == "list_repos":     return self._list_repos()
            if tool_name == "list_repo":      return self._list_repo(kwargs.get("repo_name") or self._guess_repo(ui), subdir=self._guess_subdir(ui))
            if tool_name == "read_file":      return self._read(kwargs.get("repo_name") or self._guess_repo(ui), kwargs.get("path") or self._guess_path(ui))
            if tool_name == "search_in_repo": return self._search_repo(self._guess_repo(ui), kwargs.get("query") or ui)
            return f"[github] unknown tool: {tool_name}"
        except Exception as e:
            return f"[github] error: {e}"

    def _extract_url(self, user_input: str, url: str) -> str:
        if url:
            return url
        import re
        m = re.search(r"https?://github\.com/[^\s]+", user_input)
        return m.group(0) if m else ""

    def _repo_name(self, url: str) -> str:
        return url.rstrip("/").split("/")[-1].replace(".git", "")

    def _clone_path(self, repo_name: str) -> str:
        return os.path.join(_REPOS_DIR, repo_name)

    def _guess_repo(self, user_input: str) -> str:
        """Try to find a repo name mentioned in the user message."""
        try:
            from truman.storage.db import list_repos
            repos = list_repos()
            text = user_input.lower()
            for r in repos:
                if r["name"].lower() in text:
                    return r["name"]
            return repos[0]["name"] if repos else ""
        except Exception:
            return ""

    def _guess_subdir(self, user_input: str) -> str:
        """Extract a subfolder path from user input, e.g. 'agents' from 'what's inside agents folder'."""
        import re
        text = user_input.lower()
        for pattern in [
            r"inside the (\w[\w/.-]*) (?:folder|dir|directory)",
            r"inside (\w[\w/.-]*) (?:folder|dir|directory)",
            r"in the (\w[\w/.-]*) (?:folder|dir|directory)",
            r"in (\w[\w/.-]*) (?:folder|dir|directory)",
            r"what'?s inside (?:the )?(\w[\w/.-]*)",
            r"whats inside (?:the )?(\w[\w/.-]*)",
            r"what is inside (?:the )?(\w[\w/.-]*)",
            r"(?:list|show)(?: me)? (?:the )?(\w[\w/.-]*) (?:folder|dir)",
        ]:
            m = re.search(pattern, text)
            if m:
                candidate = m.group(1)
                # skip generic words that aren't folder names
                if candidate not in ("the", "a", "an", "repo", "repository", "file", "files"):
                    return candidate
        return ""

    def _guess_path(self, user_input: str) -> str:
        """Extract a file path from user input, default to README.md."""
        import re
        # explicit file with extension
        m = re.search(r'\b([\w./-]+\.\w{1,6})\b', user_input)
        if m:
            return m.group(1)
        if "readme" in user_input.lower():
            return "README.md"
        return "README.md"

    def _ingest(self, url: str) -> str:
        """
        Fire-and-forget: spawn a background thread to clone + ingest.
        Returns immediately so chat doesn't hang on slow clones.
        Status visible via list_repos and events drawer.
        """
        if not url:
            return "[github] no URL found"
        if "github.com" not in url:
            return f"[github] not a GitHub URL: {url}"

        repo_name = self._repo_name(url)
        import threading
        threading.Thread(target=self._ingest_worker, args=(url, repo_name), daemon=True).start()
        return f"started cloning {repo_name} in background. ask me 'list repos' in a couple minutes — when it shows up there, i've fully ingested it."

    def _ingest_worker(self, url: str, repo_name: str) -> None:
        """Runs in a background thread. Writes live progress to memory_repos."""
        from truman.storage import db as _db
        import time as _time
        t0 = _time.time()
        clone_path = self._clone_path(repo_name)
        os.makedirs(_REPOS_DIR, exist_ok=True)

        # mark started
        _db.repo_start(repo_name, url, total=0, stage="cloning")

        try:
            if os.path.isdir(clone_path):
                subprocess.run(["git", "-C", clone_path, "pull", "--quiet"], timeout=60)
                git_status = "updated"
            else:
                r = subprocess.run(
                    ["git", "clone", "--depth=1", "--quiet", url, clone_path],
                    timeout=180, capture_output=True, text=True
                )
                if r.returncode != 0:
                    _db.repo_failed(repo_name, f"clone failed: {r.stderr[:200]}")
                    self._log_event(repo_name, status="error", error=f"clone failed: {r.stderr[:200]}", elapsed_ms=int((_time.time()-t0)*1000))
                    return
                git_status = "cloned"
        except Exception as e:
            _db.repo_failed(repo_name, f"git: {e}")
            self._log_event(repo_name, status="error", error=f"git: {e}", elapsed_ms=int((_time.time()-t0)*1000))
            return

        # First pass — count target files for accurate progress %
        target_files = []
        for root, dirs, files in os.walk(clone_path):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build")]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in _TEXT_EXTS:
                    fpath = os.path.join(root, fname)
                    if not is_blocked(fpath):
                        target_files.append(fpath)
                        if len(target_files) >= _MAX_INGEST_FILES:
                            break
            if len(target_files) >= _MAX_INGEST_FILES:
                break

        total = len(target_files)
        _db.repo_progress(repo_name, progress=0, total=total, stage="reading files")

        # Second pass — read + accumulate, update progress every 5 files
        files_text, count = [], 0
        for fpath in target_files:
            try:
                with open(fpath, "r", errors="replace") as f:
                    content = f.read(_MAX_FILE)
                rel = os.path.relpath(fpath, clone_path)
                files_text.append(f"# {rel}\n{content}")
                count += 1
            except Exception:
                continue
            if count % 5 == 0 or count == total:
                _db.repo_progress(repo_name, progress=count, total=total, stage="reading files")

        if not files_text:
            _db.repo_failed(repo_name, f"{git_status} but no text files found")
            self._log_event(repo_name, status="warn", error=f"{git_status} but no text files", elapsed_ms=int((_time.time()-t0)*1000))
            return

        # mark extracting patterns (LLM-based, replaces Cognee)
        _db.repo_progress(repo_name, progress=count, total=total, stage="extracting patterns")

        try:
            if os.environ.get("ENABLE_REPO_LEARNING", "1") == "1":
                self._extract_patterns(repo_name, clone_path, files_text, t0)
            _db.repo_done(repo_name, file_count=count)
            self._log_event(repo_name, status="ok",
                            error=None,
                            detail=f"{git_status} + extracted patterns ({count} files)",
                            elapsed_ms=int((_time.time()-t0)*1000))
            try:
                from truman.storage.notifications import push
                push(f"✅ done — learned {count} files from **{repo_name}**. ask me anything about it.", kind="repo_done")
            except Exception:
                pass
        except Exception as e:
            # extraction failed but files are cloned — mark done anyway
            _db.repo_done(repo_name, file_count=count)
            self._log_event(repo_name, status="warn",
                            error=f"pattern extraction failed: {e}",
                            detail=f"{git_status} ({count} files), patterns not stored",
                            elapsed_ms=int((_time.time()-t0)*1000))
            try:
                from truman.storage.notifications import push
                push(f"⚠️ cloned **{repo_name}** ({count} files) but pattern extraction failed: {str(e)[:80]}", kind="repo_done")
            except Exception:
                pass

    def _extract_patterns(self, repo_name: str, clone_path: str,
                          files_text: list, t0: float) -> None:
        """
        Pick the most important files (README + entry points, max 8),
        call LLM to extract key patterns, store in learned_skills table.
        Fire-and-forget: any exception is caught by caller.
        """
        import json as _json
        from truman.storage import db as _db

        # Priority: README first, then short files close to root
        priority = []
        rest = []
        for text in files_text:
            header = text.split("\n", 1)[0]  # "# path/to/file"
            fname = header.lstrip("# ").strip()
            depth = fname.count("/")
            if fname.lower().startswith("readme"):
                priority.insert(0, (0, fname, text))
            elif depth <= 1:
                priority.append((depth, fname, text))
            else:
                rest.append((depth, fname, text))

        priority.sort(key=lambda x: x[0])
        rest.sort(key=lambda x: x[0])
        candidates = priority + rest

        # Clear old patterns for fresh re-ingest
        _db.delete_skills_for_repo(repo_name)

        skill_count = 0
        for _, fname, content in candidates[:8]:
            try:
                from truman.core.model_router import run_with_pool
                prompt = (
                    f"Analyze this file from the '{repo_name}' repo and extract 3-5 key patterns, "
                    "tools, APIs, or capabilities it defines. Return ONLY a JSON array, no prose:\n"
                    '[{"pattern":"<short name>","kind":"tool|pattern|api|concept|config","description":"<1 sentence>"}]\n\n'
                    f"File: {fname}\n\n{content[:3000]}"
                )
                result = run_with_pool(
                    messages=[
                        {"role": "system", "content": "You extract structured patterns from code files. Return only valid JSON."},
                        {"role": "user",   "content": prompt},
                    ],
                    pool="general",
                    temperature=0.1,
                )
                raw = result.get("content", "").strip()
                # extract JSON array from response
                start = raw.find("[")
                end   = raw.rfind("]") + 1
                if start >= 0 and end > start:
                    items = _json.loads(raw[start:end])
                    for item in (items if isinstance(items, list) else []):
                        p = str(item.get("pattern", "")).strip()
                        if p:
                            _db.save_learned_skill(
                                repo_name=repo_name,
                                file_path=fname,
                                pattern=p,
                                kind=str(item.get("kind", "pattern")),
                                description=str(item.get("description", "")),
                            )
                            skill_count += 1
            except Exception:
                continue  # skip this file, keep going

    def _log_event(self, repo_name: str, status: str, error=None,
                   detail=None, elapsed_ms: int = 0) -> None:
        try:
            from truman.storage import db as _db
            import json as _j
            _db.log_event_db(
                kind="skill", source="github",
                session_id=None, pool="", model="",
                elapsed_ms=elapsed_ms, status=status,
                detail=_j.dumps({"msg": f"github.ingest_repo {repo_name}",
                                  "tools": [f"github.ingest_repo:{repo_name}"],
                                  "info": detail or ""}),
                error=error,
            )
        except Exception:
            pass

    def _list_repos(self) -> str:
        try:
            from truman.storage.db import list_repos
            repos = list_repos()
        except Exception as e:
            return f"[github] db error: {e}"
        if not repos:
            return "no repos ingested yet. give me a github url."
        lines = [f"{'repo':<30} {'files':>5}  {'ingested':<20}  url"]
        lines.append("-" * 80)
        for r in repos:
            ts = (r["ingested_at"] or "")[:16]
            lines.append(f"{r['name']:<30} {r['file_count']:>5}  {ts:<20}  {r['url']}")
        return "\n".join(lines)

    def _list_repo(self, repo_name: str, subdir: str = "") -> str:
        clone_path = self._clone_path(repo_name)
        if not os.path.isdir(clone_path):
            return f"[github] not cloned: {repo_name}"
        items = []
        for root, dirs, files in os.walk(clone_path):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), clone_path)
                # if subdir filter active, only include files under that folder
                if subdir:
                    norm = rel.replace(os.sep, "/")
                    if not (norm.startswith(subdir + "/") or norm == subdir):
                        continue
                items.append(rel)
            if len(items) > 300:
                break
        if not items:
            if subdir:
                return f"no files found in '{subdir}/' within {repo_name} — check the folder name"
            return f"[github] repo '{repo_name}' appears empty"
        header = f"files in {repo_name}/{subdir}:" if subdir else f"files in {repo_name}:"
        return header + "\n" + "\n".join(sorted(items)[:300])

    def _read(self, repo_name: str, path: str) -> str:
        clone_path = self._clone_path(repo_name)
        fpath = os.path.abspath(os.path.join(clone_path, path))
        if not fpath.startswith(clone_path):
            return "[github] path outside repo"
        if not os.path.isfile(fpath):
            return f"[github] not found: {path}"
        with open(fpath, "r", errors="replace") as f:
            return f.read(_MAX_FILE)

    def _search_repo(self, repo_name: str, query: str) -> str:
        if not repo_name:
            return "[github] no repo name — tell me which repo to search"
        clone_path = self._clone_path(repo_name)
        if not os.path.isdir(clone_path):
            return f"[github] not cloned: {repo_name}"
        hits = []
        for root, dirs, files in os.walk(clone_path):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if query.lower() in line.lower():
                                rel = os.path.relpath(fpath, clone_path)
                                hits.append(f"{rel}:{i}: {line.rstrip()}")
                                if len(hits) >= 50:
                                    break
                except Exception:
                    continue
                if len(hits) >= 50:
                    break
        return "\n".join(hits) or f"no matches for '{query}' in {repo_name}"
