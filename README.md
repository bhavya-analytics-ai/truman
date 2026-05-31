# Truman

A personal AI operating system. Voice + text. Runs always-on in the cloud, reaches into the operator's Mac through a persistent outbound bridge, and serves a single operator (Om).

---

## 1. Executive Summary

Truman is a single-operator AI platform deployed on Railway. It exposes a Flask HTTP + WebSocket server that:

- Serves a chat dashboard and an orb UI from one Python process.
- Runs a streaming, single-call LLM chat path (claude-shape) over the NVIDIA NIM API.
- Routes requests across six model pools (general, coding, reasoning, agentic, vision, docs) with strict primary/fallback priority.
- Executes 28 first-party tools (web, files, memory, scheduling, model control, Mac access, web intelligence) plus an MCP bridge for local code-intelligence.
- Reaches the operator's Mac through a persistent outbound WebSocket from a small daemon (`mac_bridge.py`) — no port forwarding, no inbound exposure on the Mac.
- Holds durable identity facts in Mem0, episodic context in SQLite, and ephemeral session state in process memory.
- Runs an OpenAI Realtime API voice loop with browser-side audio capture and playback.
- Polls Telegram as a primary off-device inbound channel.

It is not a general assistant. It is one operator's persistent runtime.

---

## 2. Core Philosophy

| Principle | Practical consequence |
|---|---|
| One operator | No multi-tenancy, no auth UI, no per-user scopes. Identity is hardcoded. |
| Single LLM call by default | The default text path is one bind-tools invocation. No regex pre-emption. |
| Strict-priority routing | Model selection is deterministic — first match wins, no scoring. |
| Reach outward, not inward | The Mac never accepts inbound traffic. It dials Railway. |
| Containment over cleverness | File bodies, tool payloads, and assistant scaffolding are stripped before they reach storage or the next turn's context. |
| Verify in production, not in claims | Every architectural change ships behind a kill switch and lands in the verification log only after a real Railway test. |
| The repo is the source of truth | Documentation reflects what is in the code today, not what was promised. |

---

## 3. System Goals

1. Reliable text chat with sub-second tool execution and useful streaming.
2. A consistent identity across sessions, devices, and inbound channels.
3. Read/write access to the operator's Mac filesystem and browser session.
4. Voice interaction with native barge-in.
5. Inbound reach beyond the operator's laptop — Telegram and iPhone Shortcuts.
6. Operational visibility — events, traces, evals, control panel — over a single dashboard.

---

## 4. Current Production Status

| Subsystem | Status |
|---|---|
| Flask + healthcheck | LIVE — Railway healthcheck passes in under 300 ms |
| claude-shape streaming chat (default) | LIVE |
| LangGraph brain (fallback) | LIVE — secondary path; runs on transient errors or attachments |
| 6-pool model router (NVIDIA NIM) | LIVE |
| 28-tool catalog + MCP bridge | LIVE |
| Mac Bridge daemon + authenticated scraping | LIVE |
| Telegram inbound poller | LIVE |
| iPhone Shortcut inbound (`/api/boss_message`) | LIVE |
| Push notifications (VAPID) | LIVE |
| Realtime voice (`gpt-4o-realtime-preview`) | LIVE |
| Mem0 fact memory + nightly reflection | LIVE |
| SQLite persistence (WAL + FTS5) | LIVE |
| Export to JSON (single-day v1) | LIVE |
| Gmail poller | EXPERIMENTAL — disabled by default |
| WhatsApp bridge (`wa-bridge/`) | EXPERIMENTAL — separate service |

The README describes the system as it runs today. Forward-looking work is tracked in `TRUMAN_OPERATOR_COOKBOOK.md` and `TRUMAN_CLEANUP_HANDOFF.md`.

---

## 5. High-Level Architecture

```
                    ┌────────────────────────────────────────────┐
                    │             Operator devices               │
                    │  Mac browser · iPhone Shortcut · Telegram  │
                    └─────────────────────┬──────────────────────┘
                                          │ HTTPS / WSS
                                          ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │                       Railway (truman.main_cloud)                     │
   │                                                                      │
   │   Flask + flask-sock (truman/voice/orb.py)                            │
   │   ├─ HTTP   /api/chat  /api/chat/stream  /api/sessions  /api/history │
   │   │         /api/upload  /api/events  /api/trace  /api/control/*    │
   │   ├─ SSE    /api/chat/stream   /api/stream                          │
   │   ├─ WS     /audio   (browser ↔ realtime voice loop)                │
   │   └─ WS     /mac-bridge   (Mac dials in)                            │
   │                                                                      │
   │   Background (daemon threads, started after Flask binds):            │
   │   ├─ agent warmup            ├─ proactive push                       │
   │   ├─ Telegram poller         ├─ nightly reflection (02:00 UTC)      │
   │   ├─ MCP server mounts       └─ realtime voice bridge                │
   │                                                                      │
   │   SQLite (/data/truman.db, WAL + FTS5)                                │
   │   Mem0 hosted (durable facts, user_id="om")                           │
   │   NVIDIA NIM (chat + embeddings)                                      │
   │   OpenAI Realtime API (voice only)                                    │
   └──────────────────────────────────────────────────────────────────────┘
                                          ▲
                                          │ outbound WebSocket
                                          │ (Mac dials Railway,
                                          │  no inbound ports on Mac)
                                          │
                    ┌─────────────────────┴──────────────────────┐
                    │           Mac Bridge daemon                │
                    │             (truman/mac_bridge.py)         │
                    │                                            │
                    │   Dispatches: read_file · list_dir ·       │
                    │   search_files · write_file · run_shell ·  │
                    │   scrape_browser · open_login_browser ·    │
                    │   ping                                     │
                    │                                            │
                    │   Real Chrome via Playwright +             │
                    │   browser-cookie3 cookie injection         │
                    └────────────────────────────────────────────┘
```

Truman runs as one Python process. It does not shard into microservices. The Mac Bridge is a small auxiliary daemon that dials in when present; the server runs fully without it.

---

## 6. Runtime Architecture

### 6.1 Entry points

| Entry | Command | Purpose |
|---|---|---|
| Cloud | `bash start.sh` → `python -m truman.main_cloud` | Railway production runtime |
| Local | `bash run.sh` → `python truman/main.py` | Mac development runtime |
| WhatsApp bridge | `start.sh` with `SERVICE_TYPE=wa-bridge` → `node wa-bridge/index.js` | Separate Node service |

### 6.2 Startup order (cloud)

```
t = 0.00s    main_cloud.main()
             ├─ spawn _background_init() daemon thread
             └─ orb.app.run(host=0.0.0.0, port=$PORT)        ← Flask binds
t ≈ 0.26s    /health  →  200 OK                              ← Railway happy
t ≈ 2.5s     background: import langchain_openai, mem0
t ≈ 2.6s     background: mount MCP servers (skipped on Railway)
t ≈ 2.7s     background: init_tool_embeddings(TOOLS)
t ≈ 3.0s     background: agent.get_agent() warmup
t ≈ 3.1s     background: start Telegram poller
t ≈ 3.2s     background: start nightly reflection scheduler
t ≈ 3.3s     background: start proactive push
t ≈ 3.4s     background: start realtime voice bridge
```

Heavy imports (`langchain_openai`, `mem0`) are deliberately kept out of module scope so Flask binds first and Railway's healthcheck never races startup.

### 6.3 HTTP and WebSocket surface

Defined in `truman/voice/orb.py`.

| Route | Method | Purpose |
|---|---|---|
| `/` and `/dashboard` | GET | Chat dashboard (static/dashboard.html, no-cache) |
| `/orb` | GET | Orb UI (static/orb.html) |
| `/health` | GET | Railway healthcheck + Mac bridge status |
| `/api/chat` | POST | Non-streaming chat, returns full assistant turn |
| `/api/chat/stream` | GET (SSE) | Streaming chat — tokens, tool calls, final |
| `/api/sessions` | GET | All sessions grouped by day (sidebar) |
| `/api/sessions/<id>` | PATCH, DELETE | Rename / delete session |
| `/api/history` | GET | Past turns for a session |
| `/api/upload` | POST | File/image upload, text extraction, attach_id |
| `/api/attachments/<id>` | GET | Serve uploaded file by id |
| `/api/attachments/session/<id>` | GET | Sticky attachments for a session |
| `/api/events` | GET | Persisted event ring buffer (last 100) |
| `/api/trace` | GET | Brain trace (LangGraph node history) |
| `/api/logs` | GET | Per-turn error log (last 50) |
| `/api/stream` | GET (SSE) | Notification stream (tasks done, errors) |
| `/api/tasks` | GET | Active background tasks (repo ingests) |
| `/api/control/*` | GET / PATCH | Flags, pools, eval, storage panels |
| `/api/facts`, `/api/rules`, `/api/contacts` | CRUD | Operator identity surface |
| `/api/boss_message` | POST | iPhone Shortcut inbound (WhatsApp/iMessage) |
| `/api/push/*` | POST | VAPID push subscription |
| `/audio` | WS | Browser ↔ Realtime voice bridge (binary PCM + JSON control) |
| `/mac-bridge` | WS | Mac daemon ↔ Railway (secret-gated) |

All HTML routes ship with `Cache-Control: no-store` so the operator never sees a stale dashboard.

---

## 7. Routing and Model Architecture

### 7.1 Two chat paths, one default

```
┌─────────────────────────────────────────────────────────────────┐
│                       /api/chat[/stream]                        │
│                                                                 │
│            ┌──────────────────┐                                 │
│            │   agent.run()    │ truman/text/agent.py            │
│            └────────┬─────────┘                                 │
│                     │                                           │
│                     │ ENABLE_CLAUDE_SHAPE=1 (default)           │
│                     ▼                                           │
│          ┌──────────────────────┐                               │
│          │  truman/text/chat.py │ ← single LLM call             │
│          │  (claude-shape)      │   native bind_tools           │
│          └──────────┬───────────┘                               │
│                     │ on TRANSIENT_ERROR (timeout, rate limit)  │
│                     │ or attachments present                    │
│                     ▼                                           │
│          ┌──────────────────────┐                               │
│          │ truman/brain/loop.py │ ← 13-node LangGraph           │
│          │ (fallback)           │   tier router + retrieval     │
│          └──────────────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
```

**Default path: claude-shape (`truman/text/chat.py`)**
A single streaming call to NIM with the system prompt, the last 16 turns, and the bound tool catalog. The LLM decides if and when to fire a tool. Tools are de-duplicated within a turn. Save and eval are queued asynchronously after the response streams out.

**Fallback path: LangGraph brain (`truman/brain/loop.py`, `nodes.py`)**
Used when claude-shape raises a transient error (`httpx.TimeoutException`, `httpx.ConnectError`, `openai.APIConnectionError`, `openai.RateLimitError`, `GraphRecursionError`) or when the request carries attachments. The graph is 13 nodes with two conditional skips for the trivial tier:

```
tier_router → classify_mood → load_memory → self_awareness → tool_retrieval
            ├─[non-trivial]→ load_goals → recall_skills ┐
            └─[trivial]──────────────────────────────────┤
                                                         ▼
                                detect_pool → risk_gate → call_llm
            ├─[non-trivial]→ risk_gate_node ┐
            └─[trivial]──────────────────────┤
                                             ▼
                              evaluate_output → save_memory → END
```

Notable nodes:
- `tier_router` — regex with char-normalization (`yoo` → `yo`, `heyyy` → `hey`). Classifies as trivial / normal / complex and picks a pool.
- `self_awareness` — builds the system prompt per turn from runtime info (railway/local, db path, Mac bridge status) and the retrieved tool set.
- `tool_retrieval` — semantic top-K via NIM `nv-embed-v1`, cached in SQLite (`tool_embeddings` keyed by description MD5). K is 0 for trivial, 5 for normal, 12 for complex. Pool-specific boosts bias toward the right family of tools.
- `risk_gate_node` — runs after the LLM, inspects `llm_tool_calls`, gates risky tools via a `pending_action` row and a "do it" confirmation regex.
- `evaluate_output` — hybrid rule-pass plus optional LLM eval (`llama-3.1-8b`). Result is one of `good`, `weak`, `bad`. A `bad` score triggers a single retry with the eval hint injected.

The LangGraph path is documented because it ships in production as the resilience floor. It is not the default.

### 7.2 Model pools

`truman/core/model_router.py` defines six pools. Each has one primary and one fallback model.

| Pool | Primary | Fallback |
|---|---|---|
| general | `meta/llama-3.3-70b-instruct` | `meta/llama-3.1-8b-instruct` |
| coding | `qwen/qwen3-coder-480b-a35b-instruct` | `moonshotai/kimi-k2-instruct` |
| reasoning | `moonshotai/kimi-k2-thinking` | `meta/llama-3.3-70b-instruct` |
| agentic | `qwen/qwen3-coder-480b-a35b-instruct` | `moonshotai/kimi-k2-instruct` |
| vision | `meta/llama-3.2-90b-vision-instruct` | `meta/llama-4-scout-17b-16e-instruct` |
| docs | `meta/llama-4-maverick-17b-128e-instruct` | `meta/llama-3.3-70b-instruct` |

All models are NVIDIA NIM. The `openrouter:` prefix is reserved for last-resort fallback and is not on a hot path today.

### 7.3 Pool selection

Pool selection is deterministic — first rule that matches wins:

1. Attachments include an image → `vision`
2. Tool intent detected → `agentic`
3. Document keywords (`.pdf`, `.docx`, `.xlsx`, `presentation`, `document`) → `docs`
4. Code action verb (`write`, `fix`, `debug`, `refactor`, file paths with code extensions) → `coding`
5. Reasoning verb (`why`, `explain`, `compare`, `analyze`) → `reasoning`
6. Stack trace or code context → `coding`
7. None of the above → `general`

Session-level overrides (`set_model`) jump the selection — the forced model is tried first; failure falls back to the pool.

### 7.4 Claude-shape per-pool model list

The claude-shape path mirrors the pool router with its own per-pool tuple so the operator gets a llama-70b primary on general chat and a coding-tuned primary on coding turns, without re-routing through the LangGraph node graph.

| Pool | Primary | Fallback |
|---|---|---|
| general | llama-70b | nemotron-nano |
| coding | qwen3-coder-480b | llama-70b |
| reasoning | qwen3-coder-480b | llama-70b |
| agentic | qwen3-coder-480b | llama-70b |
| docs | llama-4-maverick | llama-70b |
| vision | llama-3.2-90b-vision | llama-4-maverick |

### 7.5 Pipeline mode

A three-stage explicit mode: `kimi-k2-thinking` (reason) → pool primary (generate) → `llama-3.3-70b` (review). Never auto-triggered. Used when the operator explicitly requests it.

---

## 8. Tool Execution Architecture

### 8.1 Catalog

28 first-party tools live in `truman/tools/all_tools.py`. Their categories:

| Category | Tools |
|---|---|
| Knowledge | `web_search`, `get_weather`, `scrape_site`, `deep_search`, `extract_data` |
| Memory | `remember`, `recall`, `search_history`, `recent_conversations` |
| Mac files | `read_mac_file`, `list_mac_dir`, `search_mac_files`, `write_mac_file` |
| Scheduling | `set_reminder`, `list_reminders` |
| Model control | `list_models`, `set_model` |
| Goals | `add_goal`, `list_goals`, `complete_goal`, `drop_goal` |
| Rules / Prefs | `add_rule`, `list_rules`, `delete_rule`, `update_pref` |
| Wellbeing | `log_sleep` |
| Browser | `browser_login`, `save_result` |

Tools that touch the Mac (`*_mac_file`, `*_mac_dir`, `scrape_site` for auth-walled domains, `browser_login`) dispatch through the Mac Bridge when the server is running on Railway and short-circuit to local Python helpers when running on the operator's Mac.

### 8.2 Execution in the default path

```
User turn
  └─> chat.chat_stream(user_input, session_id, pool)
         ├─ build messages: [system_prompt, last_16_turns, user_input]
         ├─ resolve pool via detect_pool() (rule chain above)
         ├─ resolve model list via _POOL_CHAT_MODELS[pool]
         ├─ call _call_llm_with_tools(messages, TOOLS, tool_map, pool=pool)
         │     └─ raw NIM SSE stream → tokens out
         │        on tool_call delta:
         │          tool_map[name].invoke(args)
         │          append ToolMessage to working_msgs
         │          continue streaming
         └─ enqueue_save(session_id, user_input, response, model, pool, tools, latency_ms)
```

There is no regex pre-emption. The LLM picks the tool. Tools are deduplicated per turn via `_turn_cache` so a model that fires the same `recall` twice on one turn pays the cost once.

### 8.3 Execution in the LangGraph path

The LangGraph path retrieves a semantic top-K of tools from the SQLite embedding cache, binds only those to the LLM, runs the risk gate against `llm_tool_calls`, and routes risky tools through a confirmation handshake (`pending_action` row, "do it" / "cancel" regex on the next turn).

### 8.4 MCP integration

`truman/tools/mcp_config.py` registers `gitnexus` as an MCP server. It is mounted at boot when running locally and skipped on Railway (gitnexus needs the local repo to mean anything). Mounted MCP tools are appended to `TOOLS` and become callable from both chat paths.

### 8.5 Web intelligence routing

`scrape_site` decides at call-time whether to route through Firecrawl, the Mac Bridge, or `web_intel.extract`:

```
URL in {linkedin, twitter, x, instagram, facebook, tiktok, reddit, threads}
  └─ try Mac Bridge scrape_browser  ← real Chrome + injected cookies
  └─ fall back to Firecrawl
  └─ fall back to web_intel.extract

URL on a public site
  └─ try Firecrawl                  ← fastest
  └─ fall back to Mac Bridge scrape_browser
  └─ fall back to web_intel.extract
```

The fallback chain favors authenticated access for sites Truman has logged into via `browser_login`.

---

## 9. Memory Architecture

Memory is layered. Each layer answers a different question.

| Layer | Substrate | Lifetime | Question it answers |
|---|---|---|---|
| Identity block | `text/system_prompt.py` (code) | Permanent | Who is the operator and how does Truman talk to him? |
| Mem0 facts | Mem0 hosted, `user_id="om"` | Durable, cross-session | What does Truman know about Om's life? |
| Episodic | `memory_episodic` SQLite table | Indefinite (local) | What happened on a given day? |
| Session summaries | `session_summaries` SQLite table | Indefinite | What did a finished session boil down to? |
| Turn history | `turns` SQLite table (FTS5) | Indefinite | Verbatim record of every message. |
| Session context | In-process `_HISTORY` dict | Process lifetime | What did we just say (last 16 turns)? |

The identity block is hardcoded — the operator's name, role, projects, and style are not pulled from a database. This was deliberate: an earlier system auto-extracted "facts" into the system prompt and produced unstable behavior. The block now lives next to the persona text.

Mem0 is written only by the nightly reflection job. Per-turn writes are deliberately not done — the reflection job extracts durable facts from a session's transcripts, deduplicates against Mem0, and pushes only what survives.

### 9.1 Nightly reflection

```
02:00 UTC daily
  reflect.main()
    for each session ended since last run, with no summary row:
      format turns as Om/Truman lines
      call reflection LLM with REFLECT_PROMPT
      receive JSON: { summary, tasks_completed, key_decisions, errors, fixes,
                       next_day_priorities, facts }
      write to session_summaries
      push facts (+ decisions, + errors) to Mem0
```

Reflection is a daemon thread in `main_cloud.py`. It does not block the chat path and survives crashes — the next-day pass will pick up anything missed.

---

## 10. Storage and Data Model

SQLite at `/data/truman.db` on Railway and `truman/truman.db` locally. WAL mode, FTS5 over `turns.content` via triggers.

```
┌──────────────────────────────────────────────────────────────────┐
│                          SQLite schema                            │
│                                                                  │
│   sessions          turns          tool_calls     events         │
│   ┌─────────┐      ┌─────────┐    ┌─────────┐    ┌─────────┐    │
│   │ id PK   │◄─────│ session │    │ session │    │ id PK   │    │
│   │ browser │      │ role    │    │ name    │    │ kind    │    │
│   │ label   │      │ content │    │ args    │    │ source  │    │
│   │ started │      │ ts      │    │ result  │    │ status  │    │
│   └─────────┘      │ FTS5    │    │ ts      │    │ detail  │    │
│                    └─────────┘    └─────────┘    └─────────┘    │
│                                                                  │
│   session_summaries     memory_episodic     attachments         │
│   ┌─────────────────┐   ┌──────────────┐    ┌─────────────┐     │
│   │ session_id PK   │   │ id PK (uuid) │    │ id PK (uuid)│     │
│   │ summary (JSON)  │   │ source       │    │ filename    │     │
│   │ created_at      │   │ summary      │    │ mime        │     │
│   └─────────────────┘   │ tags (JSON)  │    │ data (blob) │     │
│                         │ session_id   │    │ created_at  │     │
│                         └──────────────┘    └─────────────┘     │
│                                                                  │
│   reminders   persona_rules   user_facts   user_prefs            │
│   tool_embeddings   trace_events   learned_skills   push_subs    │
└──────────────────────────────────────────────────────────────────┘
```

Browser sessions are addressed by UUID (`browser_id`) and mapped to the integer primary key on first write. Deletes manually cascade to `turns`, `session_summaries`, and `tool_calls` because the schema's FK inheritance is incomplete from earlier migrations.

Events are a persisted ring buffer trimmed to 1000 rows. They power the activity drawer in the dashboard and are written by both chat paths and the fallback handler.

---

## 11. Attachment and Document Handling

### 11.1 Upload pipeline

```
POST /api/upload (multipart)
  └─ extract text:
        image  → store raw bytes, defer base64 to turn time
        pdf    → pdfplumber text; if <50 char/page average, render as images
        docx   → python-docx
        xlsx   → openpyxl (capped at 200 rows)
        csv    → text rows (capped)
        code   → text + syntax hint
  └─ INSERT INTO attachments (id, filename, mime, data, created_at)
  └─ register in session_state with TTL=10 turns
  └─ return {attach_id, filename, text, mime}
```

### 11.2 Loading into a turn

`multimodal/loader.py::load_attachment(attach_id)` returns a typed block for the LLM message list:
- Image → `image_url` block (base64).
- PDF → text block, plus image blocks for the scanned pages.
- Tabular → markdown table block.
- Other → text block.

Caps: 20 PDF pages, 200 sheet rows, 12,000 text characters per attachment.

### 11.3 Sticky attachments

`multimodal/session_state.py` keeps a per-session list of `{attach_id, mime, turns_left}` with a default TTL of 10 turns. `tick_turn()` decrements after each response. Operator commands recognized in the user input:

- `"look again"` → reset TTL on existing attachments.
- `"drop file"` / `"drop image"` / `"drop all"` → clear of that kind.

### 11.4 Pollution containment

File bodies and tool outputs are stripped from both the persisted turn record and the in-process history before the next turn loads. The chat path stores a marker (e.g. `[File: name.pdf]`) instead of the body, so the operator can scroll back without flooding the next prompt with a 20-page transcript. The save path receives the already-stripped input — there is no second strip downstream.

---

## 12. Voice and Orb Architecture

```
Browser tab
  ├─ getUserMedia({ echoCancellation, noiseSuppression, autoGainControl })
  ├─ 48kHz Float32 → 24kHz Int16 PCM (downsample, clip, scale)
  └─ WebSocket /audio (binary frames + JSON control)
              │
              ▼
   ┌──────────────────────────────────────────────────────┐
   │  truman/voice/orb.py     (Flask + flask-sock)        │
   │                                                      │
   │   mic_in   ──────►┐                                  │
   │                   │                                  │
   │              ┌────▼────────────────────────────┐     │
   │              │   truman/voice/realtime.py      │     │
   │              │                                 │     │
   │              │   WebSocket → OpenAI Realtime   │     │
   │              │   model = gpt-4o-realtime-preview     │
   │              │   voice = ash                   │     │
   │              │   VAD: threshold 0.55,          │     │
   │              │        silence 800 ms           │     │
   │              │                                 │     │
   │              │   on response.audio.delta:      │     │
   │              │     audio_out.put(pcm)          │     │
   │              │   on input_audio_buffer.        │     │
   │              │        speech_started:          │     │
   │              │     drain audio_out             │     │
   │              │     send response.cancel        │     │
   │              │   on response.done:             │     │
   │              │     push transcripts to         │     │
   │              │     audio_out as JSON           │     │
   │              └────┬────────────────────────────┘     │
   │                   │                                  │
   │   audio_out ◄─────┘                                  │
   │     ├─ binary PCM  → browser playback                │
   │     └─ JSON ctrl   → flush, transcript               │
   └──────────────────────────────────────────────────────┘
```

The browser owns echo cancellation — the platform's WebRTC implementation handles it. The server never sees the operator's voice mixed with its own playback.

Barge-in is two-way: the OpenAI side commits a turn on a `speech_started` event, and the server drains the outbound audio queue and forwards a `flush` control message so the browser immediately stops any audio source nodes it has scheduled.

One browser tab owns the audio stream at a time. New tabs evict the previous owner with an `{"type":"evicted"}` JSON frame, so the operator never hears two Trumans at once.

The orb UI (`static/orb.html`) is the idle visualizer. It does not host the chat — it is a presence signal.

---

## 13. Dashboard Architecture

The dashboard is one HTML file (`truman/voice/static/dashboard.html`) served at `/` and `/dashboard`. It speaks five protocols against the server:

| Protocol | Endpoint | Purpose |
|---|---|---|
| HTTP POST | `/api/chat` | Non-streaming send |
| SSE GET | `/api/chat/stream` | Token + tool stream |
| HTTP CRUD | `/api/sessions`, `/api/history`, `/api/facts`, `/api/rules` | Session and identity surfaces |
| SSE GET | `/api/stream` | Notifications (tasks done, errors) |
| WS | `/audio` | Voice |

Session state (`browser_id`, active session, theme) lives in `localStorage` and is versioned so a deploy that changes its shape can wipe stale clients.

The activity drawer reads `/api/events` (persistent) and falls back to `/api/logs` (in-memory) if events are unavailable. The trace drawer reads `/api/trace` (LangGraph node-level trace).

---

## 14. GitHub Skill Intake Pipeline

GitHub repo intake is a first-class subsystem because cloning random URLs is the single most dangerous operation Truman is asked to do. Every step gates the next.

```
┌──────────────────────────────────────────────────────────────────────┐
│  User message contains "github.com/owner/repo"                       │
│                            │                                         │
│                            ▼                                         │
│         truman/skills/registry.py::detect_skill()                    │
│         (keyword pre-check, runs BEFORE the LLM)                     │
│                            │                                         │
│           ┌────────────────┼────────────────────┐                    │
│           │                │                    │                    │
│           ▼                ▼                    ▼                    │
│   bare URL paste    "inspect" / "tell    "clone" / "ingest" /        │
│   (no verb)         me about" / "show"   "learn this repo"           │
│           │                │                    │                    │
│           ▼                ▼                    ▼                    │
│      ask_intent       inspect_repo         ingest_repo               │
│      (no clone)       (GitHub API +        (confirmed=False          │
│      offer 4 paths    README ≤ 3 KB,       on first call)            │
│      to operator)     no clone)                                      │
│                                                  │                   │
│                                  returns: "this will clone X         │
│                                            to Y, ~Z files,           │
│                                            reply 'confirm clone'"    │
│                                                  │                   │
│                            on operator: "confirm clone"              │
│                                                  ▼                   │
│                                       ingest_repo(confirmed=True)    │
│                                                  │                   │
│                                                  ▼                   │
│                            background thread:                        │
│                              shallow clone                           │
│                              walk ≤ 200 text files                   │
│                              extract 3–5 patterns per file (LLM)     │
│                              INSERT INTO learned_skills              │
│                              push completion notification            │
│                                                                      │
│                                                  (future)            │
│                                                  ▼                   │
│                                       skill registration             │
│                                       — not implemented today        │
└──────────────────────────────────────────────────────────────────────┘
```

The path is gated by `ENABLE_MCP_GITHUB`. Inspect-only and clone-and-learn are wired end-to-end. The "install CLI" option offered in `ask_intent` is a placeholder — Truman acknowledges the intent but does not execute it today.

The pre-check intercepts a GitHub URL before the LLM ever sees the message. The LLM cannot accidentally infer "the user wants me to clone this" from a passing reference.

---

## 15. Operator Safety Model

Truman is a single-operator system, but it talks to a real Mac and a real bank of API keys. The safety model is layered.

| Layer | Mechanism | Where |
|---|---|---|
| Risk tiers per tool | `safe` / `caution` / `risky` (`core/risk.py`) | All tools |
| Post-LLM risk gate | Inspects `llm_tool_calls`, blocks risky tools, persists `pending_action` row, requires "do it" / "confirm" on next turn | LangGraph path |
| GitHub clone gate | Two-step: `confirmed=False` returns a preview, `confirmed=True` clones | GitHub skill |
| Shell command blacklist | `rm`, `rmdir`, `del`, `format`, `mkfs`, `dd`, `sudo` rejected before Mac Bridge executes | `mac_bridge.py::_run_shell` |
| File path containment | File skill restricted to `~/Desktop`; blacklist on sensitive globs | `skills/files/server.py`, `skills/_blacklist.py` |
| Bridge auth | `X-Bridge-Secret` header + JSON auth message on connect | `/mac-bridge` WS |
| Pollution containment | Strip file bodies and tool payloads before save and before context replay | `text/chat.py`, `storage/save.py` |
| Kill switches | Every major subsystem ships behind an `ENABLE_*` env flag, mutable via `/api/control/flags` | `core/config.py` |

The control panel (`/api/control/*`) exposes the live state of every flag, pool, eval threshold, and storage table to a single dashboard view — by design, the operator can flip the system back to a previous shape without redeploying.

---

## 16. Deployment Architecture

```
GitHub (main branch)
   │
   │ push
   ▼
Railway build (Nixpacks)
   ├─ providers: ["python"]
   ├─ install: pip install -r requirements.txt
   └─ apt: git (for skills/github)
   │
   ▼
Railway runtime
   ├─ start command: bash start.sh
   │    ├─ SERVICE_TYPE=wa-bridge  → node wa-bridge/index.js
   │    └─ default                 → python -m truman.main_cloud
   ├─ port: $PORT (Railway-assigned)
   ├─ healthcheck: GET /health, 60s timeout, restart always
   └─ volume: /data (SQLite DB persisted across deploys)
```

Key environment variables:

| Variable | Purpose |
|---|---|
| `PORT` | Railway-assigned port for Flask |
| `RAILWAY_ENVIRONMENT` | Set by Railway, used by code to detect cloud vs local |
| `RAILWAY_URL` | Mac Bridge target, dialed by the daemon |
| `BRIDGE_SECRET` | Shared secret for `/mac-bridge` WS |
| `NVIDIA_API_KEY` | NIM access (chat + embeddings) |
| `OPENAI_API_KEY` | Realtime voice only |
| `MEM0_API_KEY` | Mem0 hosted facts memory |
| `REALTIME_MODEL`, `REALTIME_VOICE` | Voice configuration |
| `POOL_GENERAL`, `POOL_CODING`, `POOL_REASONING`, `POOL_AGENTIC`, `POOL_VISION`, `POOL_DOCS` | Pool composition (comma-separated model slugs) |
| `ENABLE_CLAUDE_SHAPE`, `ENABLE_LANGGRAPH`, `ENABLE_EVAL`, `ENABLE_RISK_GATE`, `ENABLE_MCP_GITHUB`, `ENABLE_MCP_FILES`, `ENABLE_MCP_WEB`, `ENABLE_GMAIL_POLLING`, ... | Subsystem kill switches |
| `SERVICE_TYPE` | Selects Python vs Node service in `start.sh` |

`.railwayignore` keeps the local SQLite directory and the WhatsApp web cache out of deploys.

---

## 17. Background Services

All non-HTTP work runs in daemon threads started inside `_background_init` after Flask binds.

| Service | Schedule | Purpose |
|---|---|---|
| Agent warmup | Once at boot | Lazy-import LangChain + Mem0 so the first request is fast |
| MCP mount | Once at boot, local only | Mount `gitnexus` and extend the tool catalog |
| Tool embeddings init | Once at boot | Embed every tool description for semantic retrieval |
| Telegram poller | Continuous | Primary off-device inbound — works when the laptop is closed |
| Nightly reflection | 02:00 UTC daily | Summarize finished sessions and push facts to Mem0 |
| Proactive push | Cron-style | Morning brief, idle nudge, goal nudge |
| Gmail poller | Continuous, gated `ENABLE_GMAIL_POLLING=1` | Secondary inbound |
| Realtime voice | Continuous | WebSocket bridge to OpenAI Realtime API |

Every service is wrapped in a `try/except` that prints and continues. A failed background service does not bring down the HTTP server.

---

## 18. Operational Modes

| Mode | Trigger | Effect |
|---|---|---|
| Trivial | Tier router classifies as greeting / ack / simple math / punctuation only | Tool retrieval returns K=0; LangGraph skips `load_goals`, `recall_skills`, and the post-LLM risk gate; eval skipped |
| Normal | Default | Top-5 tools, full graph, full eval |
| Complex | Multi-step or code-introspection cues | Top-12 tools, full graph, larger context window |
| Vision | Attachment includes an image | Pool forced to `vision`, complex tier |
| Pipeline | Operator says "use pipeline" | Three-stage reason → generate → review |
| Forced model | Operator says "use kimi" / `set_model` | Session-pinned model jumps to the front of the fallback chain |
| Risk-gate hold | LLM emits a risky tool call | Tool blocked, `pending_action` saved, operator must say "do it" or "cancel" on the next turn |

---

## 19. Current Operator Workflow

The system's day-to-day shape from the operator's seat.

```
 Operator (Om)
     │
     │ opens dashboard, types or speaks
     ▼
 Dashboard (browser, /)
     │   - session UUID in localStorage
     │   - last 16 turns shown
     │   - activity drawer + trace drawer + sessions sidebar
     │
     │ /api/chat/stream (SSE)
     ▼
 Chat path (truman/text/chat.py — claude-shape)
     │   - resolve pool (rule chain)
     │   - bind TOOLS
     │   - stream tokens + tool deltas
     │
     │ if tool call emitted by LLM
     ▼
 Tool execution
     │   - first-party tool (truman/tools/all_tools.py), OR
     │   - skill route (truman/skills/registry.py), OR
     │   - Mac Bridge dispatch (Railway → operator's Mac)
     │
     │ result streamed back into the turn
     ▼
 Memory + storage
     │   - turns INSERT (FTS5 indexed)
     │   - events INSERT (ring buffer)
     │   - eval queued async
     │   - response history kept in process (last 16)
     │   nightly:
     │     reflect → session_summaries
     │     reflect → Mem0 fact push
     │
     │ on /health, /api/control/*, /api/events, /api/trace
     ▼
 Verification surface
         - Railway healthcheck (continuous)
         - TRUMAN_VERIFICATION_LOG.md (per-change record)
         - TRUMAN_OPERATOR_COOKBOOK.md (runbook)
         - dashboard activity / trace drawers
```

Inbound channels other than the dashboard:
- **Telegram** — primary, works when the laptop is closed. Poller in `delivery/telegram.py` calls `agent.run` directly.
- **iPhone Shortcut** — `POST /api/boss_message` accepts a WhatsApp/iMessage payload from a Shortcut, drafts a reply, and offers approval via Telegram before delivery.
- **Voice (`/audio` WS)** — sub-second voice loop, full barge-in.

---

## 20. Testing and Verification Strategy

Truman has three quality surfaces.

| Surface | Format | Cadence |
|---|---|---|
| `pytest` (`tests/`) | Unit + verification tests for tier router, tool retrieval, self awareness, risk gate, runtime | On every change to the brain modules |
| `TRUMAN_VERIFICATION_LOG.md` | Phase-by-phase manual production tests with timestamps, commit hashes, and pass/fail | Every Railway deploy that changes a subsystem |
| `TRUMAN_OPERATOR_COOKBOOK.md` | Live capability matrix + known bugs + how to test each | Continuous |

The verification log is the canonical record of what is known to work in production. A change is not "done" until it lands in the log with a production-pass entry. If the README and the verification log disagree, the verification log wins.

---

## 21. Repository Layout

```
truman/
├── main.py                # Local entry — adds hotkey, opens browser, runs in foreground
├── main_cloud.py          # Railway entry — Flask first, heavy init in background
├── mac_bridge.py          # Outbound WS daemon (runs on the operator's Mac)
│
├── voice/
│   ├── orb.py             # Flask + WS routes (HTTP, /audio, /mac-bridge)
│   ├── realtime.py        # OpenAI Realtime client
│   └── static/
│       ├── dashboard.html # Chat UI (drag/drop, paste, mic, drawers)
│       └── orb.html       # Idle visualizer
│
├── text/
│   ├── chat.py            # claude-shape streaming path (default)
│   ├── agent.py           # Path dispatcher + LangGraph fallback handler
│   └── system_prompt.py   # Identity block + persona + style anchor
│
├── brain/
│   ├── loop.py            # LangGraph topology
│   ├── nodes.py           # Node implementations
│   ├── state.py           # TrumanState TypedDict
│   ├── tier_router.py     # Trivial / normal / complex classifier
│   ├── tool_retrieval.py  # Semantic top-K (NIM nv-embed-v1)
│   ├── self_awareness.py  # Dynamic system prompt builder
│   ├── memory.py          # Memory loader node
│   └── eval.py            # Hybrid rule + LLM eval
│
├── core/
│   ├── config.py          # Env loader, pool defaults, kill switches
│   ├── model_router.py    # 6 pools, strict priority, session override
│   ├── runtime.py         # is_railway(), db_location(), mac_bridge_status()
│   └── risk.py            # safe / caution / risky tiers per tool
│
├── tools/
│   ├── all_tools.py       # 28 first-party tools
│   ├── dispatch.py        # OpenAI Realtime adapter for tool schemas
│   ├── mcp_config.py      # gitnexus server registration (local only)
│   └── mcp_bridge.py      # MCP stdio transport + schema mapper
│
├── skills/
│   ├── registry.py        # detect_skill keyword matcher + router
│   ├── base.py            # SkillBase ABC
│   ├── github/server.py   # ask_intent, inspect_repo, ingest_repo
│   ├── files/server.py    # Desktop-constrained file ops
│   └── web/server.py      # DuckDuckGo + fetch_url
│
├── storage/
│   ├── db.py              # SQLite schema (WAL + FTS5), helpers
│   ├── reflect.py         # Nightly reflection
│   ├── save.py            # Post-turn save + eval enqueue
│   └── notifications.py   # Push fanout
│
├── memory/                # Mem0 wrapper utilities
│
├── multimodal/
│   ├── loader.py          # Type-aware attachment loaders
│   ├── call.py            # Build multi-block messages for the LLM
│   └── session_state.py   # Sticky attachments (TTL=10 turns)
│
├── delivery/
│   └── telegram.py        # Inbound poller
│
├── integrations/
│   └── gmail_poller.py    # Gated inbound (ENABLE_GMAIL_POLLING)
│
├── scheduling/
│   ├── proactive.py       # Morning brief, idle nudge
│   └── scheduler.py       # Standalone reminder firer (launchd target)
│
└── plists/                # LaunchAgent plists for local Mac services
```

---

## 22. Architectural Constraints

These are design choices, not deficiencies. They define what Truman is and what it deliberately is not.

| Constraint | Why it is the way it is |
|---|---|
| Single operator | Identity is hardcoded; there is no auth surface, no per-user scope, no tenancy. The system is a personal runtime, not a product. |
| Single Python process | The whole server is one Flask app. There are no microservices, no message bus, no separate workers. Background threads carry the support work. |
| Mac access is outbound-only | The Mac never accepts inbound traffic. The bridge daemon dials Railway. No port forwarding, no inbound firewall holes, no exposure if Railway is compromised. |
| Mem0 is reflection-fed, not turn-fed | Per-turn fact writes were tried and discarded — they produced unstable identity drift. Facts now enter Mem0 only through the nightly reflection pass after de-duplication. |
| Identity lives in code, not data | The operator's profile is in `text/system_prompt.py`. An earlier auto-extracted "facts in prompt" design was removed because the resulting persona was non-deterministic across deploys. |
| LangGraph is the resilience floor, not the default | The 13-node graph runs only when the default path raises a transient error or when attachments are present. Keeping it wired buys recovery without paying its cost on every turn. |
| One LLM call per turn by default | The claude-shape path issues a single bind-tools invocation. Multi-call planners were rejected as the default because they multiplied latency on the 80 % of turns that did not need them. |
| Every risky operation requires explicit consent | GitHub clones, risky tool calls, and shell commands all gate on operator confirmation. There is no silent escalation path. |

---

## 23. Related Documents

- `TRUMAN_VERIFICATION_LOG.md` — phase-by-phase production verification record.
- `TRUMAN_OPERATOR_COOKBOOK.md` — live capability matrix and runbook.
- `VOICE_PIPELINE.md` — voice subsystem walkthrough.
- `BUILD_LOG.md` — historical implementation log. Reference only.

---

*Truman is a single-operator runtime. The repository, not this document, is the source of truth.*
