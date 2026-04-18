import requests
from langchain_core.tools import tool
from ddgs import DDGS


@tool
def web_search(query: str) -> str:
    """Search the web for real-time information — news, prices, facts, anything current."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
        if not results:
            return "No results found."
        return "\n".join([f"{r['title']}: {r['body']}" for r in results])
    except Exception as e:
        return f"Search failed: {e}"


@tool
def get_weather(location: str) -> str:
    """Get current weather for any location."""
    try:
        url = f"https://wttr.in/{location.replace(' ', '+')}?format=3"
        response = requests.get(url, timeout=5)
        return response.text.strip()
    except Exception as e:
        return f"Weather lookup failed: {e}"
