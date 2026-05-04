"""
prompts.py — Type-specific system prompt injections for multimodal turns.
Injected into system message when image attach_ids are present.
"""

_IMESSAGE_HINT = (
    "\n\nIMPORTANT — iMessage screenshot rules: "
    "blue bubble on the RIGHT = the OTHER person (who sent Om the message). "
    "gray bubble on the LEFT = Om's own past replies. "
    "Never swap these. If a bubble is unclear or unreadable, say so explicitly — do NOT guess."
)

_IMAGE_HINT = (
    "\n\nYou are seeing the actual image bytes directly. "
    "Read everything precisely. Extract ALL visible text verbatim. "
    "Never invent or hallucinate content not visible in the image. "
    "If something is unclear or unreadable, say so."
)


def get_system_injection(attach_ids: list) -> str:
    """
    Return appropriate system prompt injection based on attached image filenames.
    Checks filenames for iMessage clues; falls back to generic image hint.
    """
    if not attach_ids:
        return ""
    try:
        from truman.multimodal.loader import get_attachment_meta
        for aid in attach_ids:
            meta = get_attachment_meta(aid)
            if not meta:
                continue
            fname = (meta.get("filename") or "").lower()
            if any(k in fname for k in ("imessage", "imsg", "chat", "message", "screenshot", "msg")):
                return _IMESSAGE_HINT
    except Exception:
        pass
    return _IMAGE_HINT
