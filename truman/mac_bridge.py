#!/usr/bin/env python3
"""
mac_bridge.py — Truman Mac Bridge

Runs as a lightweight daemon on Om's Mac. Maintains a persistent WebSocket
connection TO the Railway server (Mac initiates — no port forwarding needed).
Handles file read/list/search requests from Truman running on Railway.

When the Mac is asleep (lid closed), Power Nap keeps network alive so the
bridge stays connected and can handle requests.

Run manually:
    cd /Users/ompandya/Desktop/friday
    python -m truman.mac_bridge

Or it auto-starts as part of truman main if RAILWAY_URL is set in .env.

Protocol (JSON over WebSocket):
  Railway → Mac:  {"id": "...", "action": "read_file"|"list_dir"|"search_files"|"ping", "path": "..."}
  Mac → Railway:  {"id": "...", "ok": true, "result": "..."} or {"id": "...", "ok": false, "error": "..."}
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import websockets

from truman.core import config  # loads .env

RAILWAY_URL   = os.getenv("RAILWAY_URL", "")        # e.g. wss://truman-om.up.railway.app/mac-bridge
BRIDGE_SECRET = os.getenv("BRIDGE_SECRET", "truman-bridge-secret")
RECONNECT_DELAY = 10  # seconds between reconnect attempts


# ── File handlers ─────────────────────────────────────────────────────────────

def _read_file(path: str, max_bytes: int = 50_000) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"No file at {path}")
    if not p.is_file():
        raise ValueError(f"{path} is not a file")
    size = p.stat().st_size
    content = p.read_text(errors="replace")
    if size > max_bytes:
        content = content[:max_bytes] + f"\n\n[truncated — file is {size} bytes]"
    return content


def _list_dir(path: str, max_entries: int = 200) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"No directory at {path}")
    if not p.is_dir():
        raise ValueError(f"{path} is not a directory")
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
    lines = []
    for e in entries[:max_entries]:
        kind = "FILE" if e.is_file() else "DIR "
        size = f"{e.stat().st_size:>10,}b" if e.is_file() else "           "
        lines.append(f"{kind}  {size}  {e.name}")
    if len(entries) > max_entries:
        lines.append(f"... ({len(entries) - max_entries} more entries)")
    return "\n".join(lines)


def _search_files(root: str, pattern: str, max_results: int = 50) -> str:
    """Recursive glob search under root."""
    p = Path(root).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"No directory at {root}")
    matches = list(p.rglob(pattern))[:max_results]
    if not matches:
        return f"No files matching '{pattern}' under {root}"
    return "\n".join(str(m) for m in matches)


def _run_shell(cmd: str, cwd: str | None = None, timeout: int = 30) -> str:
    """Run a shell command safely. No destructive commands allowed."""
    blocked = ["rm ", "rmdir", "del ", "format", "mkfs", "dd ", ":(){", "sudo"]
    cmd_lower = cmd.lower()
    for b in blocked:
        if b in cmd_lower:
            return f"Blocked: '{b}' not allowed via mac bridge."
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        timeout=timeout, cwd=cwd or os.path.expanduser("~")
    )
    out = (result.stdout or "") + (result.stderr or "")
    return out.strip()[:10_000] or "(no output)"


# ── Dispatcher ────────────────────────────────────────────────────────────────

def _write_file(path: str, content: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Written {len(content)} chars to {p}"


def _get_chrome_cookies(url: str) -> list[dict]:
    """
    Extract Om's real Chrome cookies for a given URL using browser-cookie3.
    Works while Chrome is running — reads the encrypted SQLite DB directly.
    Returns list of {name, value, domain, path} dicts for Playwright injection.
    """
    try:
        import browser_cookie3
        from urllib.parse import urlparse
        domain = urlparse(url).netloc  # e.g. "www.linkedin.com"
        # Extract root domain for cookie matching
        parts = domain.split(".")
        root = "." + ".".join(parts[-2:])  # e.g. ".linkedin.com"
        jar = browser_cookie3.chrome(domain_name=root)
        cookies = []
        for c in jar:
            cookies.append({
                "name":   c.name,
                "value":  c.value,
                "domain": c.domain,
                "path":   c.path or "/",
            })
        return cookies
    except Exception as e:
        print(f"[Bridge] cookie extract failed: {e}")
        return []


def _scrape_with_browser(url: str, timeout: int = 30) -> str:
    """
    Scrape any URL using Om's real Chrome cookies — bypasses LinkedIn, Twitter,
    Instagram, Reddit, Facebook auth walls. Runs Playwright in a thread
    (mac_bridge is async; asyncio.run can't nest).
    """
    import concurrent.futures

    # Pull cookies from real Chrome BEFORE entering thread (main thread = safe)
    cookies = _get_chrome_cookies(url)

    def _run_in_thread():
        import asyncio

        async def _scrape():
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                return "playwright not installed on Mac"

            async with async_playwright() as p:
                # Use real installed Chrome (not Playwright's Chromium) so
                # LinkedIn/Twitter/etc see a real fingerprint + real cookies
                try:
                    browser = await p.chromium.launch(
                        channel="chrome",   # uses /Applications/Google Chrome.app
                        headless=True,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                        ]
                    )
                except Exception:
                    # Fallback to bundled Chromium if Chrome isn't installed
                    browser = await p.chromium.launch(
                        headless=True,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                        ]
                    )
                ctx = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                )

                # Inject all of Om's Chrome cookies for this domain
                if cookies:
                    await ctx.add_cookies(cookies)

                page = await ctx.new_page()

                # Mask automation signals
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = { runtime: {} };
                """)

                try:
                    await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(2500)  # let JS render

                    content = await page.evaluate("""() => {
                        ['script','style','nav','footer','header','aside',
                         '[role=dialog]','[aria-modal]'].forEach(sel => {
                            document.querySelectorAll(sel).forEach(el => el.remove());
                        });
                        return document.body ? document.body.innerText.trim() : '';
                    }""")
                    title = await page.title()

                    if not content or len(content) < 50:
                        return f"page loaded but content empty — may still need login. url: {url}"
                    return f"# {title}\n\n{content[:10000]}"
                finally:
                    await page.close()
                    await browser.close()

        return asyncio.run(_scrape())

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_run_in_thread)
            return future.result(timeout=timeout + 15)
    except concurrent.futures.TimeoutError:
        return f"browser scrape timed out after {timeout}s"
    except Exception as e:
        return f"browser scrape failed: {e}"


def _open_login_browser(url: str = "https://www.linkedin.com") -> str:
    """
    Open URL in Om's default browser (real Chrome with real cookies).
    No Playwright, no separate profile — just opens the page so Om can log in.
    Session is already saved in his real Chrome.
    """
    try:
        # macOS: open in default browser (Chrome) and bring to front
        subprocess.run(["open", url], check=True)
        subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to activate'],
            capture_output=True
        )
        return "opened in your browser — log in, then come back and ask me to scrape"
    except Exception as e:
        return f"failed to open browser: {e}"


def _dispatch(action: str, payload: dict) -> str:
    if action == "ping":
        return "pong"
    if action == "read_file":
        return _read_file(payload.get("path", ""))
    if action == "list_dir":
        return _list_dir(payload.get("path", "~"))
    if action == "search_files":
        return _search_files(payload.get("root", "~"), payload.get("pattern", "*"))
    if action == "write_file":
        return _write_file(payload.get("path", ""), payload.get("content", ""))
    if action == "run_shell":
        return _run_shell(payload.get("cmd", ""), payload.get("cwd"))
    if action == "scrape_browser":
        return _scrape_with_browser(payload.get("url", ""), payload.get("timeout", 30))
    if action == "open_login_browser":
        return _open_login_browser(payload.get("url", "https://www.linkedin.com"))
    raise ValueError(f"Unknown action: {action}")


# ── WebSocket loop ────────────────────────────────────────────────────────────

async def _handle(ws):
    print("[Bridge] Connected to Railway.")
    # Authenticate
    await ws.send(json.dumps({"type": "auth", "secret": BRIDGE_SECRET}))

    loop = asyncio.get_event_loop()

    async for raw in ws:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        req_id = msg.get("id", "")
        action = msg.get("action", "")

        # Run dispatch in a thread executor so the async event loop stays free
        # to process WebSocket pings — prevents disconnects on long scrapes
        try:
            result = await loop.run_in_executor(
                None, lambda: _dispatch(action, msg)
            )
            await ws.send(json.dumps({"id": req_id, "ok": True, "result": result}))
        except Exception as e:
            await ws.send(json.dumps({"id": req_id, "ok": False, "error": str(e)}))


async def _run():
    if not RAILWAY_URL:
        print("[Bridge] RAILWAY_URL not set — mac bridge disabled.")
        return

    url = RAILWAY_URL.replace("https://", "wss://").replace("http://", "ws://")
    if not url.endswith("/mac-bridge"):
        url = url.rstrip("/") + "/mac-bridge"

    print(f"[Bridge] Connecting to {url}")
    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=30,
                ping_timeout=10,
                additional_headers={"X-Bridge-Secret": BRIDGE_SECRET},
            ) as ws:
                await _handle(ws)
        except (websockets.exceptions.ConnectionClosed,
                websockets.exceptions.WebSocketException,
                OSError) as e:
            print(f"[Bridge] Disconnected ({e}). Reconnecting in {RECONNECT_DELAY}s...")
        except Exception as e:
            print(f"[Bridge] Unexpected error: {e}. Reconnecting in {RECONNECT_DELAY}s...")
        await asyncio.sleep(RECONNECT_DELAY)


def start_background():
    """Start the bridge in a background thread (called from main.py if RAILWAY_URL is set)."""
    import threading
    def _thread():
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_run())
    t = threading.Thread(target=_thread, daemon=True, name="mac-bridge")
    t.start()
    print("[Bridge] Mac bridge started in background.")


def main():
    """Run standalone."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
