"""
loader.py — Fetch file bytes from DB and build NIM-compatible content blocks.

Images  → {"type": "image_url", "image_url": {"url": "data:<mime>;base64,<b64>"}}
Non-images → None (text already extracted and passed inline)
"""
from __future__ import annotations
import base64


def load_image_block(attach_id: str) -> dict | None:
    """
    Given an attach_id, return a NIM image_url content block.
    Returns None if not found, not an image, or load fails.
    """
    try:
        from truman.storage.db import get_attachment
        att = get_attachment(attach_id)
        if not att:
            print(f"[Multimodal] attach_id {attach_id} not found in DB")
            return None
        mime = att["mime_type"]
        if not mime.startswith("image/"):
            return None  # PDFs/DOCX handled as extracted text — no content block needed
        b64 = base64.b64encode(att["data"]).decode()
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"}
        }
    except Exception as e:
        print(f"[Multimodal] loader error for {attach_id}: {e}")
        return None


def get_attachment_meta(attach_id: str) -> dict | None:
    """Return filename + mime for an attach_id (no bytes)."""
    try:
        from truman.storage.db import get_attachment
        att = get_attachment(attach_id)
        if not att:
            return None
        return {"filename": att.get("filename", ""), "mime": att.get("mime_type", "")}
    except Exception:
        return None
