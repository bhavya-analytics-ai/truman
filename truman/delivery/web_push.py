"""
web_push.py — VAPID web push delivery for Truman (Phase 14)

Sends push notifications to all subscribed browsers/devices.
VAPID keys are auto-generated on first use and stored in user_prefs (SQLite).
No Apple developer account needed — uses standard Web Push (VAPID).

Kill switch: ENABLE_WEB_PUSH=1 (default on)
"""
import json
import os


# ── VAPID key management ──────────────────────────────────────────────────────

def _get_or_create_vapid_keys() -> tuple[str | None, str | None]:
    """Auto-generate VAPID keys on first call. Stored in SQLite user_prefs."""
    try:
        from truman.storage.db import get_pref, set_pref
        pub  = get_pref("vapid_public_key")
        priv = get_pref("vapid_private_key")
        if pub and priv:
            return pub, priv
        # Generate fresh keys
        from py_vapid import Vapid
        v = Vapid()
        v.generate_keys()
        pub  = v.public_key.decode()  if isinstance(v.public_key,  bytes) else str(v.public_key)
        priv = v.private_key.decode() if isinstance(v.private_key, bytes) else str(v.private_key)
        set_pref("vapid_public_key",  pub)
        set_pref("vapid_private_key", priv)
        print(f"[WebPush] VAPID keys generated and stored.")
        return pub, priv
    except ImportError:
        print("[WebPush] py_vapid not installed — run: pip install pywebpush")
        return None, None
    except Exception as e:
        print(f"[WebPush] VAPID key error: {e}")
        return None, None


def get_public_key() -> str:
    """Return the VAPID public key (for frontend subscription)."""
    try:
        from truman.storage.db import get_pref
        key = get_pref("vapid_public_key")
        if not key:
            key, _ = _get_or_create_vapid_keys()
        return key or ""
    except Exception:
        return ""


# ── Send push to all subscribed devices ──────────────────────────────────────

def send_push(title: str, body: str, url: str = "/dashboard") -> None:
    """
    Fire a web push notification to all subscribed devices.
    Fail-soft — never raises. Dead subscriptions are auto-removed.
    """
    if os.environ.get("ENABLE_WEB_PUSH", "1") != "1":
        return
    try:
        from pywebpush import webpush, WebPushException
        from truman.storage.db import get_all_push_subs, delete_push_sub
    except ImportError:
        print("[WebPush] pywebpush not installed — run: pip install pywebpush")
        return

    _, priv = _get_or_create_vapid_keys()
    if not priv:
        return

    subs = []
    try:
        from truman.storage.db import get_all_push_subs
        subs = get_all_push_subs()
    except Exception as e:
        print(f"[WebPush] DB read failed: {e}")
        return

    if not subs:
        return

    payload = json.dumps({"title": title, "body": body, "url": url})
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys":     {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=priv,
                vapid_claims={"sub": "mailto:truman@local"},
            )
        except WebPushException as ex:
            # 404/410 = subscription expired or revoked → remove it
            if ex.response is not None and ex.response.status_code in (404, 410):
                try:
                    from truman.storage.db import delete_push_sub
                    delete_push_sub(sub["endpoint"])
                    print(f"[WebPush] Removed dead subscription {sub['endpoint'][:40]}...")
                except Exception:
                    pass
        except Exception as ex:
            print(f"[WebPush] Push failed: {ex}")
