"""
web/server.py — Web skill.
search: DuckDuckGo (upgraded from existing tool — returns richer output)
fetch_url: fetch a URL and return clean text
summarize: fetch + ask NIM to summarize
Kill switch: ENABLE_MCP_WEB=1 (under ENABLE_MCP master)
"""
import os
from truman.skills.base import SkillBase


class WebSkill(SkillBase):
    name        = "web"
    description = "Search the web, fetch URLs, summarize pages"
    enabled_env = "ENABLE_MCP_WEB"

    def is_available(self) -> bool:
        master = os.environ.get("ENABLE_MCP", "1") == "1"
        return master and super().is_available()

    def list_tools(self) -> list[dict]:
        return [
            {"name": "search",     "description": "Search DuckDuckGo and return top results", "args": ["query", "max_results"]},
            {"name": "fetch_url",  "description": "Fetch a URL and return clean text", "args": ["url"]},
        ]

    def call(self, tool_name: str, **kwargs) -> str:
        try:
            if tool_name == "search":    return self._search(kwargs.get("user_input") or kwargs.get("query", ""))
            if tool_name == "fetch_url": return self._fetch(kwargs.get("url", ""))
            return f"[web] unknown tool: {tool_name}"
        except Exception as e:
            return f"[web] error: {e}"

    def _search(self, query: str, max_results: int = 6) -> str:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(f"**{r['title']}**\n{r['href']}\n{r.get('body', '')[:300]}")
        return "\n\n".join(results) or "no results"

    def _fetch(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return "[web] invalid URL"
        import requests
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
        except Exception as e:
            return f"[web] fetch failed: {e}"
        # strip HTML tags
        import re
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s{3,}", "\n\n", text)
        return text[:10_000]
