"""
main.py — Truman core
Realtime API voice loop + proactive system + orb UI
"""
import time
import threading
import config   # noqa: F401 — sets env vars before anything else
import orb
import proactive
import realtime
import hotkey
import agent
from voice import speak


# ── Startup ────────────────────────────────────────────────────────────────────
def main():
    # 1. Orb — open browser tab
    orb.run()

    # 2. Proactive system — morning brief + idle check-in + reminders
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
