"""
main.py — Truman core
Realtime API voice loop + proactive system + orb UI + ambient events
"""
import time
import threading
import config   # noqa: F401 — sets env vars before anything else
import orb
import proactive
import realtime
import hotkey
import agent
import lockdown
import gestures
from voice import speak


# ── Ambient events (cough / double clap) ──────────────────────────────────────
def handle_ambient(event: str):
    """Called from ambient monitor thread when cough or clap is detected."""
    if event == "cough":
        orb.set_state(orb.THINKING)
        response = agent.run("Om just coughed. Check in naturally, super short.", mood="")
        orb.set_state(orb.SPEAKING)
        speak(response)
    elif event == "double_clap":
        orb.set_state(orb.THINKING)
        response = agent.run("Om double clapped. Acknowledge, one line.", mood="")
        orb.set_state(orb.SPEAKING)
        speak(response)


# ── Startup ────────────────────────────────────────────────────────────────────
def main():
    # 1. Orb — open browser tab
    orb.run()

    # 2. Proactive system — morning brief + idle check-in + reminders
    proactive.start_all(speak, agent.run, idle_minutes=20)

    # 3. Realtime engine — event loop + playback thread
    realtime.start()

    # 4. Global hotkey — Cmd+Shift+T toggles session
    hotkey.start(realtime.toggle_session)

    # Boot message
    speak("Truman online. Press Command Shift T to talk.")

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
