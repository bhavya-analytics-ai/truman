"""
call.py — Build NIM-compatible message lists for multimodal + text turns.

Replaces the inline multimodal block in nodes.py call_llm.
Handles: images, PDFs, DOCX, XLSX, CSV, code, plain text attachments.
"""
from __future__ import annotations
import re as _re


# ── Page-pin regex ─────────────────────────────────────────────────────────────
# Matches: "page 3", "pg 3", "p.3", "page three" → returns int
_PAGE_RE = _re.compile(
    r"\b(?:page|pg|p\.)\s*(\d+)\b", _re.I
)


def extract_page_hint(user_input: str) -> int | None:
    """Return the first page number mentioned in user_input, or None."""
    m = _PAGE_RE.search(user_input)
    if m:
        return int(m.group(1))
    return None


# ── Main builder ───────────────────────────────────────────────────────────────

def build_messages(
    system_content: str,
    chat_history: list[dict],
    user_input: str,
    attach_ids: list[str],
    tool_result: str | None = None,
    tool_name: str | None = None,
    history_window: int = 16,
) -> list:
    """
    Build the full message list for a NIM call.

    Args:
        system_content:  Fully assembled system prompt (persona + context + hints).
                         Multimodal type hints are injected here if attach_ids present.
        chat_history:    List of {"role": "user"|"assistant", "content": str}.
        user_input:      Raw user message for this turn.
        attach_ids:      List of DB attach_ids to load.
        tool_result:     Optional tool output string to append to human message.
        tool_name:       Name of the tool that produced tool_result.
        history_window:  How many recent history messages to include.

    Returns:
        List of LangChain message objects ready to pass to run_with_pool().
    """
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage  # lazy
    from truman.multimodal.prompts import get_system_injection_typed
    from truman.multimodal.loader import load_attachment, get_attachment_meta

    # 1. Inject type-specific system hint
    if attach_ids:
        try:
            metas = []
            for aid in attach_ids:
                meta = get_attachment_meta(aid)
                if meta:
                    metas.append(meta)
            hint = get_system_injection_typed(metas)
            if hint:
                system_content = system_content + hint
        except Exception as _e:
            print(f"[call.build_messages] prompt hint error: {_e}")

    messages: list = [SystemMessage(content=system_content)]

    # 2. Chat history
    for h in chat_history[-history_window:]:
        if h["role"] == "user":
            messages.append(HumanMessage(content=h["content"]))
        else:
            messages.append(AIMessage(content=h["content"]))

    # 3. Human message (possibly multimodal)
    text_part = user_input
    if tool_result:
        text_part += f"\n\n[Tool result from {tool_name}]:\n{tool_result}"

    if not attach_ids:
        messages.append(HumanMessage(content=text_part))
        return messages

    # 4. Load attachments and build content blocks
    page_hint = extract_page_hint(user_input)
    content_blocks: list[dict] = []
    inline_texts:   list[str]  = []

    for aid in attach_ids:
        try:
            result = load_attachment(aid, page_hint=page_hint)
            if result["kind"] == "image" or result["kind"] == "pdf_scan":
                # Image/scanned-PDF blocks go directly as content blocks
                content_blocks.extend(result["blocks"])
            else:
                # Text-based types: accumulate inline text
                if result["text_inline"]:
                    inline_texts.append(result["text_inline"])
        except Exception as _e:
            print(f"[call.build_messages] load error for {aid}: {_e}")

    # Combine inline texts + user message into a single text block
    combined_text = text_part
    if inline_texts:
        combined_text = "\n\n".join(inline_texts) + "\n\n---\n\n" + text_part

    if content_blocks:
        # Visual attachments: interleave image blocks + text block at end
        content_blocks.append({"type": "text", "text": combined_text})
        try:
            messages.append(HumanMessage(content=content_blocks))
        except Exception as _e:
            # Fallback: some models don't support multipart — send text only
            print(f"[call.build_messages] multipart fallback: {_e}")
            messages.append(HumanMessage(content=combined_text))
    else:
        # Text-only attachments: just send as rich text
        messages.append(HumanMessage(content=combined_text))

    return messages
