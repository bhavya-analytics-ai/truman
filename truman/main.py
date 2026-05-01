"""
main.py — Truman core
Realtime API voice loop + proactive system + orb UI
"""
# ── silence noisy deprecation chatter before any heavy import ─────────────────
import warnings, os, sys
warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONWARNINGS", "ignore")
# nuclear: monkey-patch warnings.showwarning so even libraries that reset
# the filter (torch, transformers) can't print to stderr
warnings.showwarning = lambda *a, **kw: None
warnings.warn = lambda *a, **kw: None

# ── config MUST be first module-level import ──────────────────────────────────
# load_dotenv(override=True) fires when truman.core.config loads. Any import
# placed before this line at module level that reads env vars (directly or
# transitively) would pick up stale shell env instead of .env values.
from truman.core import config  # noqa: F401

import os
import time
import threading
from truman.voice import orb
from truman.scheduling import proactive
from truman.voice import realtime
from truman.core import hotkey
from truman.text import agent
from truman.voice.voice import speak


# ── Startup ────────────────────────────────────────────────────────────────────
def main():
    # silence Flask's dev-server banner + suppress pyobjc/cython stderr leaks
    import logging as _lg
    _lg.getLogger("werkzeug").setLevel(_lg.ERROR)
    # silence cognee's structlog output (it bypasses warnings module)
    for _noisy in ("cognee", "cognee.shared.logging_utils", "GraphCompletionRetriever",
                   "cognee.infrastructure", "cognee.modules", "structlog"):
        _lg.getLogger(_noisy).setLevel(_lg.CRITICAL)

    # redirect stdout + stderr to swallow library noise + module boot prints.
    # restored before the clean summary so user only sees the labeled banner.
    _real_stdout, _real_stderr = sys.stdout, sys.stderr
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")

    # 1. Orb — open browser tab
    orb.run()

    # 2. MCP servers + agent + proactive
    from truman.tools.mcp_config import MCP_SERVERS
    mcp_added: list[str] = []
    if MCP_SERVERS:
        from truman.tools.mcp_bridge import mount_server
        from truman.tools.all_tools import TOOLS
        for sid, cfg in MCP_SERVERS.items():
            try:
                mounted = mount_server(sid, cfg["command"], cfg["args"])
                TOOLS.extend(mounted)
                mcp_added.extend(t.name for t in mounted)
            except Exception:
                pass

    agent.get_agent()
    proactive.start_all(speak, agent.run, idle_minutes=20)

    # 3. Realtime engine + hotkey
    realtime.start()
    hotkey.start(realtime.toggle_session)

    # 4. Mac Bridge (optional)
    railway_url = os.environ.get("RAILWAY_URL", "")
    bridge_status = "off"
    if railway_url:
        try:
            from truman.mac_bridge import start_background as start_mac_bridge
            start_mac_bridge()
            bridge_status = "on (→ Railway)"
        except Exception:
            bridge_status = "failed"

    # restore stdout + stderr for the clean labeled summary + runtime logs
    sys.stdout, sys.stderr = _real_stdout, _real_stderr

    # ── Clean labeled boot summary ─────────────────────────────────────────────
    bar = "━" * 56
    print(f"\n{bar}")
    print("  TRUMAN — ONLINE")
    print(bar)
    print(f"  Chat dashboard  →  http://localhost:5001/dashboard")
    print(f"  Voice mode      →  Cmd+Option+T  (toggle on/off)")
    print(f"  Voice engine    →  Kokoro af_sky")
    print(f"  Bridge          →  {bridge_status}")
    print(f"  MCP tools       →  {len(mcp_added)} mounted" + (f" ({', '.join(mcp_added)})" if mcp_added else ""))
    print(f"  DB              →  truman/truman.db")
    print(f"{bar}")
    print("  Ctrl+C to shut down.\n")

    speak("Truman online. Press Command Option T to talk.")

    # 5. Main thread — keep alive, handle shutdown
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n  Shutting down...")
        realtime.end_session()
        os._exit(0)


if __name__ == "__main__":
    main()
