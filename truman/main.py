"""
main.py — Truman core
Realtime API voice loop + proactive system + orb UI
"""
# ── config MUST be first module-level import ──────────────────────────────────
# load_dotenv(override=True) fires when truman.core.config loads. Any import
# placed before this line at module level that reads env vars (directly or
# transitively) would pick up stale shell env instead of .env values.
from truman.core import config  # noqa: F401

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
    # 1. Orb — open browser tab
    orb.run()

    # 2. Proactive system — morning brief + idle check-in + reminders
    # Mount MCP servers FIRST so their tools land in TOOLS before the agent
    # binds. create_react_agent captures the tool list at construction time,
    # so any tools appended later would be invisible to the text path.
    # (Voice path reads tool_schemas() lazily per-session, so it sees them
    # either way — but we align both paths on the same build-time snapshot.)
    from truman.tools.mcp_config import MCP_SERVERS
    if MCP_SERVERS:
        from truman.tools.mcp_bridge import mount_server  # lazy import — only cost on actual use
        from truman.tools.all_tools import TOOLS
        mcp_added: list[str] = []
        for sid, cfg in MCP_SERVERS.items():
            try:
                mounted = mount_server(sid, cfg["command"], cfg["args"])
                TOOLS.extend(mounted)
                mcp_added.extend(t.name for t in mounted)
            except Exception as e:
                print(f"[MCP] mount failed for {sid}: {e}")
        if mcp_added:
            print(f"[MCP] mounted: {', '.join(mcp_added)}")

    # Force-build the text agent before proactive starts so morning briefing
    # and idle check-in callbacks never race the lazy-init inside agent.run.
    agent.get_agent()
    proactive.start_all(speak, agent.run, idle_minutes=20)

    # 3. Realtime engine — event loop + playback thread
    realtime.start()

    # 4. Global hotkey — Cmd+Option+T toggles session
    hotkey.start(realtime.toggle_session)

    # Boot message
    speak("Truman online. Press Command Option T to talk.")

    # 5. Main thread — keep alive, handle shutdown
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[Truman] Shutting down.")
        realtime.end_session()
        import os
        os._exit(0)


if __name__ == "__main__":
    main()
