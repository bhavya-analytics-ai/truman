"""
whatsapp_bridge.py — Python wrapper for the local whatsapp-web.js bridge.

The Node bridge runs on localhost:3099.
Start it with: node truman/integrations/whatsapp_bridge.js

Usage:
    from truman.integrations.whatsapp_bridge import send_whatsapp, is_bridge_up
    ok = send_whatsapp("+12345678901", "Hey, got your message!")
"""
import os
import requests

_BRIDGE_URL = os.getenv("WA_BRIDGE_URL", "http://127.0.0.1:3099")
_TIMEOUT    = 8   # seconds


def is_bridge_up() -> bool:
    """Returns True if the Node bridge is running and WhatsApp is connected."""
    try:
        r = requests.get(f"{_BRIDGE_URL}/status", timeout=3)
        return r.json().get("ok", False)
    except Exception:
        return False


def bridge_state() -> str:
    """Returns 'CONNECTED', 'QR_PENDING', 'DOWN', or 'UNREACHABLE'."""
    try:
        r = requests.get(f"{_BRIDGE_URL}/status", timeout=3)
        return r.json().get("state", "DOWN")
    except Exception:
        return "UNREACHABLE"


def send_whatsapp(to: str, text: str) -> bool:
    """
    Send a WhatsApp message via the local bridge.

    to   — phone number, any format (+1..., 1..., digits only)
    text — message body

    Returns True on success, False on any failure (bridge down, not connected, etc.)
    """
    if not to or not text:
        return False
    try:
        # Normalise: strip everything except digits
        digits = "".join(c for c in to if c.isdigit())
        r = requests.post(
            f"{_BRIDGE_URL}/send",
            json={"to": digits, "text": text},
            timeout=_TIMEOUT,
        )
        return r.json().get("ok", False)
    except Exception as e:
        print(f"[WA Bridge] send_whatsapp failed: {e}")
        return False
