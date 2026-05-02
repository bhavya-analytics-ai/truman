"""
orb.py — Truman's visual presence + browser audio bridge
Flask on :5001 serves:
  /         → orb UI (canvas animation)
  /state    → current visual state (polled by UI)
  /audio    → WebSocket carrying 24kHz int16 PCM both ways

The browser handles mic capture + speaker playback. getUserMedia(echoCancellation:true)
gives us production-grade AEC so Truman doesn't hear himself.

States: idle | listening | thinking | speaking
"""

import json
import os
import subprocess
import sys
import threading
import webbrowser
from flask import Flask, jsonify, send_from_directory, request
from flask_sock import Sock

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

ORB_URL = "http://localhost:5001"

# ── State constants ───────────────────────────────────────────────────────────
IDLE      = "idle"
LISTENING = "listening"
THINKING  = "thinking"
SPEAKING  = "speaking"

# ── Shared state ──────────────────────────────────────────────────────────────
_state      = IDLE
_state_lock = threading.Lock()

# ── Single-client audio guard ─────────────────────────────────────────────────
# Only ONE browser tab can own the audio stream at a time. If a second tab
# connects, it evicts the first. Without this, multiple tabs split the audio
# queue and you hear fragmented "2-3 bot" echo.
_active_ws          = None
_active_ws_stop_ev  = None
_active_ws_lock     = threading.Lock()

app  = Flask(__name__)
sock = Sock(app)


def set_state(state: str):
    global _state
    with _state_lock:
        _state = state


def get_state() -> str:
    with _state_lock:
        return _state


# ── Flask routes ──────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "truman", "mac": "connected" if _mac_ws else "disconnected"})


@app.route("/state")
def state_endpoint():
    return jsonify({"state": get_state()})


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "orb.html")


@app.route("/dashboard")
def dashboard():
    return send_from_directory(STATIC_DIR, "dashboard.html")


@app.route("/logs")
def logs_page():
    try:
        from truman.storage import db
        turns = db.recent_turns(50)
        rows = "".join(
            f'<div class="row {"user" if t["role"]=="user" else "bot"}">'
            f'<span class="who">{"Om" if t["role"]=="user" else "Truman"}</span>'
            f'<span class="ts">{(t.get("ts") or "")[:16]}</span>'
            f'<span class="txt">{t["content"][:300]}</span></div>'
            for t in turns
        )
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Truman Logs</title>
<style>
body{{background:#0a0a0f;color:#e8e8f0;font-family:monospace;padding:16px;font-size:13px;}}
h2{{color:#a78bfa;margin-bottom:16px;}}
.row{{padding:8px 0;border-bottom:1px solid #1a1a2e;display:flex;gap:10px;flex-wrap:wrap;}}
.who{{color:#4f46e5;min-width:50px;font-weight:bold;}}
.who.bot{{color:#a78bfa;}}
.ts{{color:#444460;font-size:11px;min-width:100px;}}
.txt{{color:#c8c8e0;flex:1;}}
.user .who{{color:#4f46e5;}}
a{{color:#a78bfa;text-decoration:none;}}
</style></head><body>
<h2>TRUMAN LOGS</h2>
<a href="/dashboard">← dashboard</a>&nbsp;&nbsp;<a href="/health">health</a>
<br><br>{rows or "<p style='color:#444'>no turns yet</p>"}
</body></html>"""
    except Exception as e:
        return f"<pre>error: {e}</pre>", 500


_EMOTIONAL_KW = {"i feel","i'm","im ","i am","i can't","i cant","she ","he ","my ","i've","ive ","i was","i don't","i dont","i need","i want","i hate","i love","honestly","tbh","ngl","bro","man ","struggling","hard","frustrated","anxious","stressed","worried","distracted","sad","lonely","angry","pissed","hurt","confused","lost","scared"}

def _auto_extract_facts(user_input: str) -> None:
    """Background: if message is personal/emotional, extract facts via fast LLM and save."""
    try:
        if len(user_input) < 60:
            return
        lower = user_input.lower()
        if not any(kw in lower for kw in _EMOTIONAL_KW):
            return
        from langchain_core.messages import HumanMessage as _HM
        from truman.core.model_router import run_with_pool
        from truman.storage.db import save_fact, get_all_facts
        existing = [f["fact"].lower() for f in get_all_facts()]
        prompt = (
            "Extract 1-3 short factual statements about the person from this message. "
            "Only extract clear personal facts (feelings, situations, relationships, struggles). "
            "Return ONLY a plain list, one fact per line, no bullets, no numbers, no extra text.\n\n"
            f"Message: {user_input[:600]}"
        )
        result = run_with_pool([_HM(content=prompt)], pool="fast")
        if not result or not result.get("content"):
            return
        for line in result["content"].strip().split("\n"):
            fact = line.strip().lstrip("-•·123456789. ").strip()
            if len(fact) < 10 or len(fact) > 250:
                continue
            # skip if too similar to existing
            if any(fact.lower()[:40] in ex for ex in existing):
                continue
            save_fact(fact, importance=3, source="auto")
    except Exception:
        pass


@app.route("/api/chat", methods=["POST"])
def api_chat():
    from flask import request
    import concurrent.futures
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()
    session_id = (data.get("session_id") or "default").strip()
    pool_hint  = (data.get("pool") or None)
    if not user_input:
        return jsonify({"error": "empty message"}), 400
    try:
        from truman.text.agent import run as agent_run
        from truman.storage import db as _db

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(agent_run, user_input, "", pool_hint, session_id)
            try:
                result = future.result(timeout=45)
            except concurrent.futures.TimeoutError:
                return jsonify({"error": "response timed out — try again"}), 504

        # log to SQLite
        try:
            sid = _db.start_session() if not hasattr(api_chat, '_sid') else api_chat._sid
            api_chat._sid = sid
            _db.log_turn(sid, "user", user_input)
            _db.log_turn(sid, "assistant", result["response"])
        except Exception:
            pass

        # auto-extract personal facts in background (zero latency impact)
        threading.Thread(
            target=_auto_extract_facts,
            args=(user_input,),
            daemon=True
        ).start()

        mac_status = "connected" if _mac_ws else "disconnected"
        return jsonify({
            "response":   result["response"],
            "model":      result["model"],
            "pool":       result["pool"],
            "tool_calls": result["tool_calls"],
            "mood":       result["mood"],
            "warnings":   result.get("warnings", []),
            "skill":      result.get("skill", ""),
            "mac":        mac_status,
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/logs")
def api_logs():
    from truman.text.agent import get_error_log
    return jsonify({"logs": get_error_log()})


@app.route("/api/tasks")
def api_tasks():
    """Live status of background tasks (currently: repo ingests).
    Dashboard polls this every 2s while tasks are active."""
    try:
        from truman.storage import db
        tasks = db.active_repo_tasks()
        return jsonify({"tasks": [
            {
                "kind":     "repo",
                "name":     t["name"],
                "url":      t["url"],
                "status":   t["status"],
                "stage":    t.get("stage") or "",
                "progress": t.get("progress") or 0,
                "total":    t.get("total") or 0,
                "files":    t.get("file_count") or 0,
                "error":    t.get("error") or "",
            }
            for t in tasks
        ]})
    except Exception as e:
        return jsonify({"tasks": [], "error": str(e)})


@app.route("/api/power", methods=["GET", "POST"])
def api_power():
    """Om's master kill switch. GET=status, POST=toggle. Truman has no tool for this."""
    from truman.storage.db import killswitch_active, killswitch_set
    if request.method == "GET":
        return jsonify({"on": not killswitch_active()})
    # POST — toggle
    currently_off = killswitch_active()
    killswitch_set(off=currently_off)  # flip
    return jsonify({"on": currently_off})  # was off → now on, and vice versa


@app.route("/api/stream")
def api_stream():
    """SSE endpoint — browser subscribes once, server pushes notifications (task done, errors, etc.)."""
    from flask import Response, stream_with_context
    from truman.storage import notifications as _notif
    import json as _json

    def generate():
        q = _notif.subscribe()
        try:
            yield "data: {\"type\":\"connected\"}\n\n"
            while True:
                try:
                    payload = q.get(timeout=25)
                    yield f"data: {_json.dumps(payload)}\n\n"
                except Exception:
                    yield ": keep-alive\n\n"
        finally:
            _notif.unsubscribe(q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/trace")
def api_trace():
    """Return persisted trace history (brain node events) for the activity panel."""
    from flask import request as freq
    try:
        from truman.storage.db import get_trace_history
        session_id = freq.args.get("session_id")
        limit = int(freq.args.get("limit", 300))
        rows = get_trace_history(session_id=session_id, limit=limit)
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/events")
def api_events():
    """Return last 100 events from DB events table (persisted ring buffer)."""
    from flask import request as freq
    try:
        from truman.storage import db
        kind = freq.args.get("kind")
        date = freq.args.get("date")
        events = db.get_events(limit=100, kind=kind, date=date)
        return jsonify({"events": events})
    except Exception as e:
        return jsonify({"events": [], "error": str(e)})


@app.route("/api/history")
def api_history():
    """Return turns from SQLite. If session_id passed, return only that session's turns."""
    try:
        from flask import request as freq
        from truman.storage import db
        sid = freq.args.get("session_id")
        turns = db.session_turns(sid) if sid else db.recent_turns(30)
        return jsonify({"turns": turns})
    except Exception as e:
        return jsonify({"turns": [], "error": str(e)})


# ── User Facts ───────────────────────────────────────────────────────────────
@app.route("/api/facts", methods=["GET"])
def api_facts_get():
    try:
        from truman.storage import db
        return jsonify({"facts": db.get_all_facts()})
    except Exception as e:
        return jsonify({"facts": [], "error": str(e)})

@app.route("/api/facts", methods=["POST"])
def api_facts_post():
    try:
        from truman.storage import db
        from flask import request as freq
        data = freq.get_json(force=True)
        fact = (data.get("fact") or "").strip()
        if not fact:
            return jsonify({"error": "empty fact"}), 400
        importance = int(data.get("importance", 3))
        source = data.get("source", "manual")
        fid = db.save_fact(fact, importance, source)
        return jsonify({"id": fid, "ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/facts/<int:fact_id>", methods=["DELETE"])
def api_facts_delete(fact_id):
    try:
        from truman.storage import db
        db.delete_fact(fact_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── File Upload ───────────────────────────────────────────────────────────────
TEXT_EXTS = {".py",".js",".ts",".html",".css",".json",".md",".txt",".csv",".xml",".yaml",".yml",".sh",".env"}
IMAGE_EXTS = {".png",".jpg",".jpeg",".gif",".webp",".bmp",".tiff"}

def _extract_text(filename: str, data: bytes) -> str:
    import io
    ext = os.path.splitext(filename)[1].lower()
    if ext in TEXT_EXTS:
        return data.decode("utf-8", errors="replace")
    if ext == ".pdf":
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    if ext in (".docx",):
        from docx import Document
        return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    if ext in (".xlsx",):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        rows = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                rows.append("\t".join("" if v is None else str(v) for v in row))
        return "\n".join(rows)
    if ext in (".pptx",):
        from pptx import Presentation
        lines = []
        for slide in Presentation(io.BytesIO(data)).slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    lines.append(shape.text_frame.text)
        return "\n".join(lines)
    if ext in IMAGE_EXTS:
        return "__IMAGE__"   # signal to handler to use vision model
    return data.decode("utf-8", errors="replace")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    from flask import request
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    data = f.read()
    ext  = os.path.splitext(f.filename)[1].lower()
    try:
        text = _extract_text(f.filename, data)
    except Exception as e:
        return jsonify({"error": f"parse failed: {e}"}), 500

    if text == "__IMAGE__":
        # send to NVIDIA vision model
        try:
            import base64
            from langchain_openai import ChatOpenAI
            from truman.core.config import NVIDIA_API_KEY, NVIDIA_BASE_URL
            b64 = base64.b64encode(data).decode()
            mime_map = {".png":"image/png",".gif":"image/gif",".webp":"image/webp",".bmp":"image/bmp"}
            mime = mime_map.get(ext, "image/jpeg")
            llm = ChatOpenAI(model="meta/llama-4-maverick-17b-128e-instruct",
                             api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
            resp = llm.invoke([{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": "Describe this image in detail. Extract any text, data, or key info visible."}
                ]
            }])
            text = resp.content
        except Exception as e:
            return jsonify({"error": f"vision failed: {e}"}), 500

    # trim to 8000 chars to avoid token flood
    if len(text) > 8000:
        text = text[:8000] + "\n\n[...truncated]"

    return jsonify({"filename": f.filename, "text": text})


# ── Mac Bridge WebSocket (Railway side) ──────────────────────────────────────
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "truman-bridge-secret")
_mac_ws = None
_mac_ws_lock = threading.Lock()
_pending: dict = {}   # id → asyncio.Event (not needed — flask-sock is sync)
_pending_results: dict = {}


@sock.route("/mac-bridge")
def mac_bridge_ws(ws):
    """Accepts persistent connection from the Mac Bridge daemon."""
    global _mac_ws
    secret = ws.environ.get("HTTP_X_BRIDGE_SECRET", "")
    if secret != BRIDGE_SECRET:
        ws.close()
        return
    with _mac_ws_lock:
        _mac_ws = ws
    print("[Bridge] Mac connected.")
    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break
            try:
                msg = json.loads(raw)
                req_id = msg.get("id", "")
                if req_id in _pending:
                    _pending_results[req_id] = msg
                    _pending.pop(req_id)
            except Exception:
                pass
    finally:
        with _mac_ws_lock:
            if _mac_ws is ws:
                _mac_ws = None
        print("[Bridge] Mac disconnected.")


def mac_request(action: str, payload: dict, timeout: float = 15.0) -> dict:
    """Send a request to the Mac Bridge and wait for response."""
    import uuid, time as _time
    with _mac_ws_lock:
        ws = _mac_ws
    if not ws:
        return {"ok": False, "error": "Mac bridge not connected — laptop may be asleep."}
    req_id = str(uuid.uuid4())[:8]
    _pending[req_id] = True
    try:
        ws.send(json.dumps({"id": req_id, "action": action, **payload}))
    except Exception as e:
        _pending.pop(req_id, None)
        return {"ok": False, "error": str(e)}
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        if req_id in _pending_results:
            return _pending_results.pop(req_id)
        _time.sleep(0.1)
    _pending.pop(req_id, None)
    return {"ok": False, "error": "Mac bridge timed out."}


# ── Audio WebSocket ───────────────────────────────────────────────────────────
@sock.route("/audio")
def audio_ws(ws):
    """Bridge browser ⇄ realtime.py queues.

    Inbound  (browser binary frames, 24kHz int16 PCM) → realtime.mic_in
    Outbound (realtime.audio_out frames)              → browser binary frames
    A None sentinel on audio_out is translated to a JSON flush message.

    Single-client: when a new tab connects, the previous one is evicted so
    only ONE browser pulls from the audio queue. Prevents "multiple bots
    speaking" echo when old tabs linger across restarts.
    """
    from truman.voice import realtime  # deferred import to avoid circular dep

    # Auto-start Realtime session on Railway (no hotkey available in cloud).
    # If the session was just closing (_session_active briefly True while finalizer runs),
    # wait up to 3s for it to fully close before starting a new one.
    if realtime._session_active:
        # session appears active — could be live OR mid-shutdown.
        # Give it up to 3s to settle; if still active after, assume live (reuse it).
        import time as _t
        deadline = _t.time() + 3.0
        while realtime._session_active and _t.time() < deadline:
            _t.sleep(0.1)
    if not realtime._session_active:
        realtime.start_session()

    global _active_ws, _active_ws_stop_ev
    stop_flag = threading.Event()

    # Evict any prior client before we take over the audio queue
    with _active_ws_lock:
        if _active_ws_stop_ev is not None:
            _active_ws_stop_ev.set()
            try:
                # Tell the old tab to shut itself (prevents auto-reconnect storm)
                _active_ws.send(json.dumps({"type": "evicted"}))
                _active_ws.close()
            except Exception:
                pass
        _active_ws         = ws
        _active_ws_stop_ev = stop_flag
        print("[Orb] Audio client connected (sole consumer)")

    def reader():
        # Browser → OpenAI
        try:
            while not stop_flag.is_set():
                data = ws.receive(timeout=1)
                if data is None:
                    continue
                if isinstance(data, (bytes, bytearray)):
                    try:
                        realtime.mic_in.put_nowait(bytes(data))
                    except Exception:
                        pass   # drop on backpressure
                # text frames (control messages) ignored for now
        except Exception:
            pass
        finally:
            stop_flag.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # OpenAI → Browser
    try:
        while not stop_flag.is_set():
            try:
                frame = realtime.audio_out.get(timeout=0.1)
            except Exception:
                if not t.is_alive():
                    break
                continue

            try:
                if frame is None:
                    ws.send(json.dumps({"type": "flush"}))
                elif isinstance(frame, dict):
                    ws.send(json.dumps(frame))   # transcript / control messages
                else:
                    ws.send(frame)               # binary audio
            except Exception:
                break
    finally:
        stop_flag.set()
        with _active_ws_lock:
            if _active_ws is ws:
                _active_ws         = None
                _active_ws_stop_ev = None


# ── Public API ────────────────────────────────────────────────────────────────
def _open_browser():
    """Open the orb UI in a NEW browser window and bring it to the front.
    Uses osascript on Mac so the window can't hide behind existing tabs/spaces."""
    try:
        if sys.platform == "darwin":
            # osascript: open URL in a brand-new Chrome/Safari/default window AND activate it
            script = f'''
            tell application "System Events"
                set frontApp to name of (first application process whose frontmost is true)
            end tell
            try
                tell application "Google Chrome"
                    activate
                    make new window
                    set URL of active tab of front window to "{ORB_URL}"
                end tell
            on error
                try
                    tell application "Safari"
                        activate
                        make new document with properties {{URL:"{ORB_URL}"}}
                    end tell
                on error
                    do shell script "open '{ORB_URL}'"
                end try
            end try
            '''
            subprocess.Popen(["osascript", "-e", script])
        else:
            webbrowser.open_new(ORB_URL)
        print(f"[Orb] Opened {ORB_URL} in new window")
    except Exception as e:
        print(f"[Orb] Could not auto-open browser ({e}). Visit {ORB_URL} manually.")


def run(port: int = 5001, open_browser: bool = True):
    """Start orb server in background thread. Non-blocking."""
    t = threading.Thread(target=_serve, args=(port,), daemon=True)
    t.start()
    if open_browser:
        threading.Timer(1.5, _open_browser).start()


def start():
    run()


def stop():
    pass   # daemon thread dies with the process


def _serve(port: int = 5001):
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    host = "0.0.0.0" if os.environ.get("RAILWAY_ENVIRONMENT") else "127.0.0.1"
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


# HTML served from static/ — see truman/voice/static/orb.html and dashboard.html
