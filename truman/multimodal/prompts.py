"""
prompts.py — Type-specific system prompt injections for multimodal turns.
Injected into system message when attachments are present.
"""
from __future__ import annotations

# ── Base accuracy anchor (always appended when any attachment is present) ─────
_BASE_ACCURACY = (
    "\n\nACCURACY RULES — ATTACHMENTS:"
    "\n• Read ALL content precisely. Extract visible/present text verbatim."
    "\n• NEVER invent, hallucinate, or infer content not explicitly shown."
    "\n• If something is unclear, cut off, or unreadable — say so explicitly."
    "\n• Do NOT fill gaps with assumptions or training knowledge."
)

# ── Type-specific hints ───────────────────────────────────────────────────────

_HINTS: dict[str, str] = {

    "image": (
        "\n\nYou are seeing the actual image bytes directly. "
        "Read everything visible precisely. Extract ALL text verbatim. "
        "Never invent or hallucinate content not visible in the image. "
        "If something is unclear or unreadable, say so explicitly."
    ),

    "imessage": (
        "\n\niMessage screenshot rules:"
        "\n• Blue bubble on the RIGHT = the OTHER person (who sent Om the message)."
        "\n• Gray bubble on the LEFT = Om's own past replies."
        "\n• NEVER swap these — this is the opposite of most chat UIs."
        "\n• If a bubble is unclear or unreadable, say so — do NOT guess the sender."
        "\n• Read all visible text exactly as written, including emojis and typos."
    ),

    "whatsapp": (
        "\n\nWhatsApp screenshot rules:"
        "\n• Green/colored bubble on the RIGHT = the OTHER person's message."
        "\n• White/lighter bubble on the LEFT = Om's sent messages."
        "\n• Read all text exactly as shown."
    ),

    "pdf_text": (
        "\n\nA PDF has been extracted as text and provided above."
        "\n• Reference only what is explicitly written in the document."
        "\n• Do NOT infer or guess content from sections you cannot see."
        "\n• If the document is truncated, mention that."
    ),

    "pdf_scan": (
        "\n\nA scanned PDF has been sent as page images."
        "\n• Read text exactly as it appears — OCR artifacts are possible, flag them."
        "\n• Do NOT infer words from partial characters."
        "\n• Reference page numbers when quoting specific content."
    ),

    "docx": (
        "\n\nA Word document (.docx) has been extracted as text above."
        "\n• Use only the content explicitly present in the document."
        "\n• Preserve structure (headings, tables) when summarizing."
        "\n• Do NOT add information not in the document."
    ),

    "xlsx": (
        "\n\nAn Excel spreadsheet has been converted to a markdown table above."
        "\n• Perform calculations or analysis ONLY on the data shown."
        "\n• Do NOT assume values for empty or missing cells."
        "\n• Reference column names exactly as they appear in the table."
        "\n• If rows were capped, mention that only partial data is shown."
    ),

    "csv": (
        "\n\nA CSV file has been converted to a markdown table above."
        "\n• Work with the data as provided — do NOT guess missing values."
        "\n• Reference exact column names when answering."
        "\n• If rows were capped, note only partial data is visible."
    ),

    "code": (
        "\n\nA code file has been provided above."
        "\n• Read the code exactly as written."
        "\n• Do NOT assume or infer logic beyond what is explicitly coded."
        "\n• When referencing code, use exact line numbers or function names from the file."
    ),

    "text": (
        "\n\nA text file has been provided above."
        "\n• Reference only content explicitly present in the file."
        "\n• Do NOT add information beyond what is written."
    ),
}


# ── Filename/mime → kind detector ─────────────────────────────────────────────

def _detect_kind(meta: dict) -> str:
    """
    Given {"filename": str, "mime": str}, return a hint key.
    """
    fname = (meta.get("filename") or "").lower()
    mime  = (meta.get("mime") or "").lower()

    # iMessage screenshots
    if any(k in fname for k in ("imessage", "imsg", "msg_", "chat", "conversation")):
        return "imessage"

    # WhatsApp screenshots
    if any(k in fname for k in ("whatsapp", "wa_", "wa-", "whats_app")):
        return "whatsapp"

    if mime.startswith("image/"):
        # Generic image — could still be a screenshot, but we can't tell from filename
        if "screenshot" in fname or fname.startswith("screen"):
            return "imessage"   # most likely iMessage if Om sent it; safe default
        return "image"

    if mime == "application/pdf" or fname.endswith(".pdf"):
        return "pdf_text"   # prompts.py doesn't distinguish text vs scan — both covered

    if mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ) or fname.endswith((".docx", ".doc")):
        return "docx"

    if mime in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ) or fname.endswith((".xlsx", ".xls")):
        return "xlsx"

    if mime == "text/csv" or fname.endswith(".csv"):
        return "csv"

    # Code extensions
    _CODE = {
        "py","js","ts","tsx","jsx","go","rs","java","kt","swift","c","cpp",
        "h","hpp","cs","rb","php","sh","bash","zsh","sql","html","css","scss",
        "json","yaml","yml","toml","env","dockerfile","makefile",
    }
    ext = fname.rsplit(".", 1)[-1] if "." in fname else fname
    if ext in _CODE:
        return "code"

    if mime.startswith("text/"):
        return "text"

    return "image"   # fallback for unknown binary — try image


# ── Public API ────────────────────────────────────────────────────────────────

def get_system_injection_typed(metas: list[dict]) -> str:
    """
    Given a list of attachment metas (each has "filename" and "mime"),
    return the best system prompt injection for the whole set.

    Priority: imessage > whatsapp > pdf_scan > pdf_text > xlsx > csv > docx > code > text > image.
    Always appends base accuracy rules.
    """
    if not metas:
        return ""

    priority = ["imessage", "whatsapp", "pdf_scan", "pdf_text", "xlsx", "csv", "docx", "code", "text", "image"]
    kinds_found = {_detect_kind(m) for m in metas}

    for p in priority:
        if p in kinds_found and p in _HINTS:
            return _BASE_ACCURACY + _HINTS[p]

    # Fallback: generic image
    return _BASE_ACCURACY + _HINTS.get("image", "")


def get_system_injection(attach_ids: list) -> str:
    """
    Legacy function (Phase 1 compat) — takes attach_ids, loads metas, returns injection.
    Called by nodes.py Phase 1 wiring. Will be replaced by call.py in next refactor.
    """
    if not attach_ids:
        return ""
    try:
        from truman.multimodal.loader import get_attachment_meta
        metas = []
        for aid in attach_ids:
            meta = get_attachment_meta(aid)
            if meta:
                metas.append(meta)
        return get_system_injection_typed(metas)
    except Exception:
        pass
    return _BASE_ACCURACY + _HINTS.get("image", "")
