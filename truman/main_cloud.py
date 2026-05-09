"""
main_cloud.py — Truman entry point for Railway (cloud).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRUMAN CORE FUNCTION:
  Watch incoming messages → triage → draft reply →
  send when Om approves.
  One sentence. Everything else is support.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Startup order:
  [CORE]    agent warmup          — brain ready to handle messages
  [CORE]    Telegram poller       — primary inbound channel
  [CORE]    Flask app             — HTTP API + dashboard
  [SUPPORT] nightly reflection    — maintenance, runs 2am UTC
  [SUPPORT] proactive push        — morning brief, idle nudge, goal nudge
  [SUPPORT] Gmail poller          — secondary inbound (gated: ENABLE_GMAIL_POLLING)
  [SUPPORT] realtime              — WebRTC audio bridge

Differences from main.py (local Mac):
  - No hotkey, no TTS, no browser auto-open, no Apple Reminders
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


def _background_init():
    """Heavy init in background so Flask binds first and healthcheck passes."""
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

    # Smart routing: embed all tools at boot for semantic retrieval
    try:
        from truman.brain.tool_retrieval import init_tool_embeddings
        from truman.tools.all_tools import TOOLS as _ALL_TOOLS
        init_tool_embeddings(_ALL_TOOLS, [])
        print(f"[Smart Routing] Embedded {len(_ALL_TOOLS)} tools for retrieval")
    except Exception as e:
        print(f"[Smart Routing] init_tool_embeddings failed: {e}")

    # ── [CORE] Message handling infrastructure ────────────────────────────────
    agent.get_agent()   # warm up brain

    # [CORE] Telegram poller — primary inbound channel (works when Mac is off)
    try:
        from truman.delivery.telegram import start_poller as _tg_start
        _tg_start(agent.run)
    except Exception as e:
        print(f"[Cloud] Telegram poller failed to start: {e}")

    # ── [SUPPORT] Background services ────────────────────────────────────────
    _start_nightly_reflection()                  # 2am UTC maintenance pass
    proactive.start_proactive_push(agent.run)    # morning brief + nudges

    # [SUPPORT] Gmail poller — secondary inbound (gated, off by default)
    if os.environ.get("ENABLE_GMAIL_POLLING", "0") == "1":
        try:
            from truman.integrations.gmail_poller import start as _gmail_start
            _gmail_start()
            print("[Cloud] Gmail poller started")
        except Exception as e:
            print(f"[Cloud] Gmail poller failed to start: {e}")

    realtime.start()    # [SUPPORT] WebRTC audio bridge
    print("[Cloud] Background init complete.")


def main():
    port = int(os.environ.get("PORT", 5001))

    # Kick off all heavy init in background — Flask binds immediately so
    # Railway's healthcheck passes before agent warmup finishes.
    threading.Thread(target=_background_init, daemon=False, name="startup-init").start()

    print(f"[Cloud] Truman running on port {port}")
    # Flask runs in the main thread (blocks) so the process stays alive.
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    orb.app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
