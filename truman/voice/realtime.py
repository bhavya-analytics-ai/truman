"""
realtime.py — OpenAI Realtime API voice loop for Truman
Browser-audio edition: mic capture + speaker playback happen in the browser tab
(orb.py) via WebRTC. Browser's built-in AEC handles echo cancellation.

This module:
  - holds two queues bridging the browser WS handler and the OpenAI WS
  - runs the OpenAI Realtime WS client
  - dispatches tool calls and injects Mem0 context

Install deps:
    pip install websockets flask-sock
"""
import asyncio
import base64
import collections
import difflib
import json
import queue
import threading
import time
import websockets

from truman.voice import orb
from truman.scheduling import proactive
from truman.storage import db
from truman.core.config import OPENAI_API_KEY, REALTIME_MODEL, REALTIME_VOICE
from truman.text.agent import SYSTEM, mem_search, memory, USER_ID
from truman.voice.realtime_tools import TOOL_SCHEMAS, dispatch_tool

SAMPLE_RATE = 24000

# ── Transcript filters (5a: hallucinations + echo) ────────────────────────────
# Whisper commonly hallucinates these during silence or background noise.
# Lowercased, stripped of trailing punctuation before comparison.
_HALLUCINATIONS = {
    "thank you for watching",
    "thanks for watching",
    "thank you",
    "thanks",
    "please subscribe",
    "subscribe",
    "like and subscribe",
    "bye",
    "bye bye",
    "おつかれさまでした",
    "ご視聴ありがとうございました",
    "ありがとうございました",
    ".",
    "you",
}

# Recent assistant transcripts; user input that fuzzy-matches one of these
# is the mic picking up Truman's own voice through the speaker (AEC miss).
_recent_assistant = collections.deque(maxlen=10)
_ECHO_SIMILARITY_THRESHOLD = 0.80


def _clean(text: str) -> str:
    return text.lower().strip().rstrip(".,!?;: ")


def _is_hallucination(text: str) -> bool:
    return _clean(text) in _HALLUCINATIONS


def _is_echo(text: str) -> bool:
    t = _clean(text)
    if len(t) < 4:
        return False
    for asst in _recent_assistant:
        ratio = difflib.SequenceMatcher(None, t, _clean(asst)).ratio()
        if ratio >= _ECHO_SIMILARITY_THRESHOLD:
            return True
    return False

WS_URL = f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}"
WS_HEADERS = {
    "Authorization": f"Bearer {OPENAI_API_KEY}",
    "OpenAI-Beta":   "realtime=v1",
}

# ── Audio bridge queues (browser ⇄ OpenAI) ────────────────────────────────────
# browser mic → OpenAI (24kHz int16 PCM bytes)
mic_in    = queue.Queue(maxsize=200)
# OpenAI → browser speaker (24kHz int16 PCM bytes; None = flush signal)
audio_out = queue.Queue(maxsize=200)

# ── Internal state ────────────────────────────────────────────────────────────
_session_active  = False
_ws              = None
_event_loop      = None
_pending_calls   = {}      # call_id → {name, args}
_user_transcript = ""
_asst_transcript = ""
_session_id      = None    # db.sessions.id for the currently-active session
_last_activity   = 0.0     # epoch seconds of last speech event — powers idle auto-close

# ── Idle auto-close (cost control) ────────────────────────────────────────────
# Realtime bills per second of connection, not per message. Leaving a session
# open silently = still burning tokens. Auto-close after this much silence.
IDLE_TIMEOUT_SEC = 180     # 3 min of no speech → hang up


# ── Helpers ───────────────────────────────────────────────────────────────────
def _drain_audio_out():
    """Empty the outbound audio queue (used on barge-in / response end)."""
    while not audio_out.empty():
        try:
            audio_out.get_nowait()
        except queue.Empty:
            break


def _barge_in():
    """Kill any in-flight playback: drain the queue and signal a browser flush."""
    _drain_audio_out()
    try:
        audio_out.put_nowait(None)   # sentinel → WS handler sends {type:'flush'}
    except queue.Full:
        pass


# ── Mic → WebSocket sender ────────────────────────────────────────────────────
async def _mic_sender(ws):
    """Pulls mic frames from `mic_in` (fed by the browser WS) and forwards to OpenAI."""
    loop = asyncio.get_event_loop()
    while _session_active:
        try:
            frame = await loop.run_in_executor(None, _mic_get)
        except queue.Empty:
            continue
        if frame is None:
            continue
        try:
            await ws.send(json.dumps({
                "type":  "input_audio_buffer.append",
                "audio": base64.b64encode(frame).decode(),
            }))
        except websockets.exceptions.ConnectionClosed:
            break


def _mic_get():
    """Blocking get with a short timeout so the executor thread can check _session_active."""
    return mic_in.get(timeout=0.1)


# ── Event handler ─────────────────────────────────────────────────────────────
async def _handle_events(ws):
    global _user_transcript, _asst_transcript, _pending_calls, _session_id, _last_activity

    async for raw in ws:
        if not _session_active:
            break

        event = json.loads(raw)
        etype = event.get("type", "")

        # ── Session ready
        if etype == "session.created":
            try:
                _session_id = db.start_session()
            except Exception as e:
                print(f"[DB] start_session failed: {e}")
                _session_id = None
            _last_activity = time.time()
            print("[Realtime] Connected. Listening...")
            orb.set_state(orb.LISTENING)

        # ── User speaking → barge-in + reset orb
        elif etype == "input_audio_buffer.speech_started":
            _barge_in()
            _last_activity = time.time()
            orb.set_state(orb.LISTENING)
            proactive.record_interaction()

        # ── User stopped → thinking
        elif etype == "input_audio_buffer.speech_stopped":
            orb.set_state(orb.THINKING)

        # ── User transcript (whisper transcription of input)
        elif etype == "conversation.item.input_audio_transcription.completed":
            raw_text = event.get("transcript", "").strip()
            if raw_text and _is_hallucination(raw_text):
                print(f"[Filter] dropped hallucination: {raw_text!r}")
                _user_transcript = ""
            elif raw_text and _is_echo(raw_text):
                print(f"[Filter] dropped echo: {raw_text!r}")
                _user_transcript = ""
            else:
                _user_transcript = raw_text
                if _user_transcript:
                    print(f"\nOm: {_user_transcript}")

        # ── Track function call name when item is added
        elif etype == "response.output_item.added":
            item = event.get("item", {})
            if item.get("type") == "function_call":
                call_id = item.get("call_id", "")
                _pending_calls[call_id] = {"name": item.get("name", ""), "args": ""}

        # ── Accumulate function call args
        elif etype == "response.function_call_arguments.delta":
            call_id = event.get("call_id", "")
            if call_id in _pending_calls:
                _pending_calls[call_id]["args"] += event.get("delta", "")

        # ── Function call complete → dispatch → send result
        elif etype == "response.function_call_arguments.done":
            call_id = event.get("call_id", "")
            call    = _pending_calls.pop(call_id, None)
            if call:
                name = call["name"]
                try:
                    args = json.loads(event.get("arguments", "{}") or "{}")
                except Exception:
                    args = {}

                print(f"[Tool] {name}({args})")
                result = dispatch_tool(name, args)
                print(f"[Tool] → {str(result)[:120]}")
                try:
                    db.log_tool_call(_session_id, name, args, result)
                except Exception as e:
                    print(f"[DB] log_tool_call failed: {e}")

                await ws.send(json.dumps({
                    "type": "conversation.item.create",
                    "item": {
                        "type":    "function_call_output",
                        "call_id": call_id,
                        "output":  str(result),
                    }
                }))
                await ws.send(json.dumps({"type": "response.create"}))

        # ── Audio chunks → browser playback queue
        elif etype == "response.audio.delta":
            audio = base64.b64decode(event["delta"])
            try:
                audio_out.put_nowait(audio)
            except queue.Full:
                pass   # drop on backpressure
            orb.set_state(orb.SPEAKING)

        # ── Transcript delta (assistant text)
        elif etype == "response.audio_transcript.delta":
            _asst_transcript += event.get("delta", "")

        # ── Turn complete
        elif etype == "response.done":
            _last_activity = time.time()
            if _asst_transcript:
                print(f"Truman: {_asst_transcript.strip()}")
                # feed the echo-detection deque so the next user turn can drop speaker bleed
                _recent_assistant.append(_asst_transcript.strip())

            if _user_transcript and _asst_transcript:
                try:
                    memory.add([
                        {"role": "user",      "content": _user_transcript},
                        {"role": "assistant", "content": _asst_transcript},
                    ], user_id=USER_ID)
                except Exception:
                    pass
                try:
                    db.log_turn(_session_id, "user",      _user_transcript)
                    db.log_turn(_session_id, "assistant", _asst_transcript)
                except Exception as e:
                    print(f"[DB] log_turn failed: {e}")

            _user_transcript = ""
            _asst_transcript = ""
            orb.set_state(orb.LISTENING)

        # ── Response cancelled (barge-in mid-utterance) → drop queued audio
        elif etype == "response.cancelled":
            _barge_in()
            orb.set_state(orb.LISTENING)

        elif etype == "error":
            print(f"[Realtime Error] {event.get('error', event)}")


# ── Session config ────────────────────────────────────────────────────────────
def _build_instructions() -> str:
    """System prompt with fresh Mem0 facts + SQLite episodic context injected."""
    # ── Mem0 facts (durable identity / preferences) ───────────────────────────
    queries  = ["Om identity background", "Om projects work", "Om preferences habits", "Om location"]
    seen, memories = set(), []
    for q in queries:
        for r in mem_search(q)[:4]:
            if r["memory"] not in seen:
                seen.add(r["memory"])
                memories.append(r["memory"])
    facts_ctx = "\n".join(memories) if memories else ""

    # ── SQLite episodic context (what we talked about recently) ──────────────
    # 5 turns = last couple minutes of conversation. Long-term thread is kept
    # alive by the session summary (written nightly by reflect.py) — so trimming
    # recent turns from 20 → 5 drops token cost without losing memory of yesterday.
    recent_ctx  = ""
    summary_ctx = ""
    try:
        recent = db.recent_turns(5)
        if recent:
            lines = [f"{t['role']}: {t['content']}" for t in recent if t.get("content")]
            recent_ctx = "\n".join(lines)
        last_sum = db.last_session_summary()
        if last_sum and last_sum.get("summary"):
            summary_ctx = f"[{last_sum.get('started_at', '')}] {last_sum['summary']}"
    except Exception as e:
        print(f"[DB] context pull failed: {e}")

    mem_instructions = """

MEMORY — critical:
- You have two memory tools: `remember` and `recall`. Use them.
- `recall` — search Mem0 for info about Om. Use it whenever Om mentions something personal (location, project, preference) and you're not sure if you know it.
- `remember` — save important new facts Om tells you. Do this automatically when he shares something worth keeping.
- Mem0 is persistent across ALL sessions. If you saved it, it survives restarts.
- You ALSO get a transcript of the most recent turns + a summary of the last session injected below — use it. If Om references "what we just talked about" or "earlier", that context is in RECENT CONTEXT / LAST SESSION.
- NEVER say you don't have memory or that sessions start fresh — that's wrong. Your memory lives in Mem0 + the recent-context log.
- If Om asks how memory works: "I use Mem0 for long-term facts plus a local log of recent turns — I remember yesterday and further back."

RESPONSE LENGTH — non-negotiable:
- Keep responses SHORT. 1-2 sentences max unless Om explicitly asks for more.
- Never monologue. The shorter the better — this is voice, not text.
"""

    blocks = [SYSTEM + mem_instructions]
    if facts_ctx:
        blocks.append(f"\nWhat I remember about Om (Mem0):\n{facts_ctx}")
    if summary_ctx:
        blocks.append(f"\nLAST SESSION (summary):\n{summary_ctx}")
    if recent_ctx:
        blocks.append(f"\nRECENT CONTEXT (last 5 turns, oldest → newest):\n{recent_ctx}")
    return "".join(blocks)


async def _idle_watchdog(ws):
    """Close the Realtime session after IDLE_TIMEOUT_SEC of silence.
    Realtime bills on connection time — an open-but-idle session still costs."""
    global _session_active
    while _session_active:
        await asyncio.sleep(30)
        if _last_activity and (time.time() - _last_activity) > IDLE_TIMEOUT_SEC:
            print(f"[Realtime] Idle {IDLE_TIMEOUT_SEC}s — auto-closing session")
            _session_active = False
            _barge_in()
            try:
                await ws.close()
            except Exception:
                pass
            break


async def _run_session():
    global _ws, _session_active, _last_activity

    try:
        async with websockets.connect(WS_URL, additional_headers=WS_HEADERS) as ws:
            _ws = ws

            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities":                ["audio", "text"],
                    "instructions":              _build_instructions(),
                    "voice":                     REALTIME_VOICE,
                    "input_audio_format":        "pcm16",
                    "output_audio_format":       "pcm16",
                    "input_audio_transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type":                "server_vad",
                        "threshold":           0.5,
                        "prefix_padding_ms":   300,
                        "silence_duration_ms": 700,
                    },
                    "tools":        TOOL_SCHEMAS,
                    "tool_choice":  "auto",
                    "temperature":  0.7,
                }
            }))

            # NO unprompted greeting — Truman just listens. Session instructions
            # + memory are already loaded in session.update above, so he has
            # everything he needs the moment Om actually speaks first.

            _last_activity = time.time()
            await asyncio.gather(
                _mic_sender(ws),
                _handle_events(ws),
                _idle_watchdog(ws),
            )

    except websockets.exceptions.ConnectionClosed:
        print("[Realtime] Connection closed.")
    except Exception as e:
        print(f"[Realtime] Session error: {e}")
    finally:
        global _session_id
        try:
            db.end_session(_session_id)
        except Exception as e:
            print(f"[DB] end_session failed: {e}")
        _session_id = None
        _ws = None
        _session_active = False
        _drain_audio_out()
        orb.set_state(orb.IDLE)


# ── Public API ────────────────────────────────────────────────────────────────
def start():
    """Start event loop. Call once at boot. Audio I/O lives in the browser now."""
    global _event_loop
    try:
        db.init()
    except Exception as e:
        print(f"[DB] init failed: {e}")
    _event_loop = asyncio.new_event_loop()
    threading.Thread(target=_event_loop.run_forever, daemon=True).start()
    print("[Realtime] Engine ready. Press Cmd+Option+T to start talking.")


def start_session():
    global _session_active
    if _session_active:
        return
    _session_active = True
    print("[Realtime] Session ON")
    asyncio.run_coroutine_threadsafe(_run_session(), _event_loop)


def end_session():
    global _session_active, _ws
    _session_active = False
    _barge_in()
    if _ws and _event_loop:
        asyncio.run_coroutine_threadsafe(_ws.close(), _event_loop)
    orb.set_state(orb.IDLE)
    print("[Realtime] Session OFF")


def toggle_session():
    if _session_active:
        end_session()
    else:
        start_session()
