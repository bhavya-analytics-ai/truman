"""
main_cloud.py — Truman entry point for Railway (cloud).

Differences from main.py (local Mac):
  - No hotkey (pynput needs a display)
  - No Kokoro TTS boot message (no audio device)
  - No browser auto-open
  - No Apple Reminders (osascript mac-only)
  - Mac Bridge SERVER side — accepts connections from the mac daemon
  - Dashboard served at /dashboard
  - Port from $PORT env var (Railway sets this)
"""
from truman.core import config  # noqa: F401 — must be first

import os
import time
import threading
from truman.voice import orb
from truman.scheduling import proactive
from truman.voice import realtime
from truman.text import agent


def _start_nightly_reflection():
    """Runs reflect.main() every night at 2am UTC. Daemon thread."""
    def _loop():
        import datetime
        while True:
            now = datetime.datetime.utcnow()
            target = now.replace(hour=2, minute=0, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            time.sleep((target - now).total_seconds())
            try:
                from truman.storage.reflect import main as _reflect
                _reflect()
            except Exception as e:
                print(f"[Reflect] error: {e}")
            time.sleep(60)
    threading.Thread(target=_loop, daemon=True, name="nightly-reflect").start()


def _noop_speak(text):
    """On Railway, no local TTS — log instead."""
    print(f"[Cloud TTS] {text}")


def main():
    port = int(os.environ.get("PORT", 5001))

    # Mount MCP servers if configured
    from truman.tools.mcp_config import MCP_SERVERS
    if MCP_SERVERS:
        from truman.tools.mcp_bridge import mount_server
        from truman.tools.all_tools import TOOLS
        for sid, cfg in MCP_SERVERS.items():
            try:
                mounted = mount_server(sid, cfg["command"], cfg["args"])
                TOOLS.extend(mounted)
                print(f"[MCP] mounted: {', '.join(t.name for t in mounted)}")
            except Exception as e:
                print(f"[MCP] mount failed for {sid}: {e}")

    agent.get_agent()
    _start_nightly_reflection()
    proactive.start_proactive_push(agent.run)

    # Telegram poller — runs on Railway so it works even when Mac is off (Phase 12)
    try:
        from truman.delivery.telegram import start_poller as _tg_start
        _tg_start(agent.run)
    except Exception as e:
        print(f"[Cloud] Telegram poller failed to start: {e}")

    # Gmail poller — 15min IMAP poll, LLM 3-tier triage, Telegram approval flow
    if os.environ.get("ENABLE_GMAIL_POLLING", "0") == "1":
        try:
            from truman.integrations.gmail_poller import start as _gmail_start
            _gmail_start()
            print("[Cloud] Gmail poller started")
        except Exception as e:
            print(f"[Cloud] Gmail poller failed to start: {e}")

    realtime.start()

    print(f"[Cloud] Truman running on port {port}")
    # On Railway, Flask must run in the main thread (blocks) so the process stays alive.
    # orb.run() uses a daemon thread (fine locally), but Railway exits when main() returns.
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    orb.app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
