# Truman

Om's personal AI. Voice + text. Always on via Railway. Talks back, remembers everything, runs tools.

**Status as of 2026-04-25:** Levels 1–5 + Option B shipped. NVIDIA NIM primary (kimi-k2-instruct → step-3.5-flash). No Groq on text agent. Static files extracted from orb.py. Sticky pool routing, session UUID tabs, image upload, pool badge, logs modal all live.

---

## What Truman Does Today

- **Voice chat** via OpenAI Realtime API (`gpt-4o-mini-realtime-preview`, voice `ash`). Session auto-starts when browser connects.
- **Dashboard** at `/dashboard` — mobile-first chat UI. Text + voice unified. Voice turns show as chat bubbles. History loads from SQLite on page open.
- **Browser-hosted audio** — mic + speaker in browser tab. WebRTC AEC. 200ms jitter buffer. Linear interpolation downsampling.
- **Always-on Railway deploy** at `https://truman-production.up.railway.app`. Entry: `truman/main_cloud.py`. SQLite on persistent disk.
- **Mac Bridge** — `mac_bridge.py` daemon on Mac, persistent WS to Railway. Tools: `read_mac_file`, `list_mac_dir`, `search_mac_files`, `write_mac_file`.
- **Long-term memory** via Mem0 hosted. Durable facts persist across sessions. Smart filter — only meaningful turns saved, dedup via semantic search.
- **Reminders** — voice or text. Fires as spoken voice alert at set time.
- **Nightly reflection** — 2am launchd, summarizes sessions, promotes facts to Mem0.
- **Mood-aware** — local regex classifier (zero API calls). Instant, no cost.
- **9-pool model router** — coding/creative/design/docs/vision/general/reasoning/fast/agentic. Intent detection auto-picks pool. Sticky routing — stays on active pool mid-conversation unless topic clearly changes.
- **Pool badge** — header shows which pool handled the last message. Updates live.
- **Pipeline mode** — deepseek-v3.2 reasons → pool model generates → glm-4.7 reviews. Explicit only, never auto.
- **Session tabs** — each tab gets a UUID, isolated chat history. Mem0 + SQLite shared across all tabs.
- **Image upload** — shows in chat, waits for send, analyzed via llama-4-maverick vision model (maverick via NVIDIA NIM).
- **File upload** — pdf/doc/xlsx shows pill in input, waits for send, routes to docs pool.
- **Error log modal** — "logs" button shows last 50 requests with timing, model, pool, status.
- **Model tools** — `list_models`, `set_model`, `pipeline_mode`. Ask "what models do I have" or "use deepseek".
- **History tools** — `search_history` FTS5 + `recent_conversations`.
- **Web Intel tools** — `scrape_site`, `deep_search`, `extract_data`. Powered by self-hosted Firecrawl + SearXNG on Hetzner (46.224.203.138:3002). Search routes through Webshare residential proxies. "Scrape this site: [url]", "deep search: X", "extract price and title from [url]".

---

## Architecture

```
Phone/Mac Browser
  │  /dashboard  (text chat + voice) — served from static/dashboard.html
  │  /           (orb UI) — served from static/orb.html
  │  /audio WS   (binary PCM + JSON control)
  ▼
Railway (truman-production.up.railway.app)
  orb.py (Flask + flask-sock, ~470 lines — routes only)
  ├── /api/chat  → tool detection → direct execution → kimi-k2 / step-3.5-flash
  ├── /api/upload → text extraction / vision model for images
  ├── /api/logs  → error log ring buffer (last 50)
  ├── /api/history → SQLite turn restore on page load
  ├── /audio WS  → mic_in / audio_out queues → realtime.py
  ├── /mac-bridge WS ← mac_bridge.py (Mac daemon)
  └── /health, /state, /logs

realtime.py — OpenAI Realtime WS (gpt-4o-mini-realtime-preview, voice only)
model_router.py — 9 pools, sticky routing, session override, pipeline mode
agent.py — keyword tool detection, direct execution, per-session chat_history dict
```

---

## File Map

| File | Role |
|---|---|
| `truman/main.py` | Local orchestrator |
| `truman/main_cloud.py` | Railway entry — no hotkey/TTS/browser-open |
| `truman/mac_bridge.py` | Mac daemon — persistent WS to Railway |
| `truman/core/config.py` | Env loader, `get_llm()`, POOL_* defaults (9 pools) |
| `truman/core/persona.py` | SYSTEM prompt — identity, style, mood, tool rules, features list |
| `truman/core/model_router.py` | 9 pools, sticky routing, session override, pipeline mode |
| `truman/text/agent.py` | Tool detection, direct execution, per-session history, mood classifier |
| `truman/voice/realtime.py` | Realtime WS loop, filters, context injection, transcript push |
| `truman/voice/orb.py` | Flask routes + WebSocket handlers — serves static/ |
| `truman/voice/static/dashboard.html` | Dashboard UI — HTML + CSS + JS |
| `truman/voice/static/orb.html` | Orb animation UI — HTML + CSS + JS |
| `truman/tools/all_tools.py` | 26 tools — single source for voice + text (includes scrape_site, deep_search, extract_data) |
| `truman/tools/dispatch.py` | Schema conversion + dispatch for Realtime path |
| `truman/storage/db.py` | SQLite (WAL + FTS5) |
| `truman/storage/reflect.py` | Nightly summarization + Mem0 fact promotion |
| `truman/scheduling/proactive.py` | In-process reminder firing (LLM calls disabled on Railway) |
| `truman/scheduling/scheduler.py` | Standalone launchd reminder firer |
| `truman/plists/` | LaunchAgent plists |

---

## Text Agent Models

Default chain (no pool routing — chat fallback):
```
kimi-k2-instruct (8s timeout) → step-3.5-flash (10s timeout)
```

---

## Model Pools

All NVIDIA NIM. Override any pool via Railway env var.

```
POOL_GENERAL   = kimi-k2-instruct, step-3.5-flash
POOL_CODING    = deepseek-v3.2, glm-4.7, qwen3-coder-480b
POOL_REASONING = kimi-k2-thinking, deepseek-v3.2
POOL_CREATIVE  = kimi-k2-thinking, mistral-large-3, llama-4-maverick
POOL_DESIGN    = deepseek-v3.2, glm-4.7, mistral-nemotron
POOL_DOCS      = llama-4-maverick, mistral-medium-3, minimax-m2.7
POOL_VISION    = llama-4-maverick, mistral-large-3
POOL_FAST      = step-3.5-flash, mistral-nemotron
POOL_AGENTIC   = qwen3-coder-480b, kimi-k2-instruct, devstral-2-123b
```

Swap a pool: `railway variables set POOL_CODING="nvidia:model1,nvidia:model2"`

---

## Running Locally

```bash
cd /Users/ompandya/Desktop/friday
python -m truman.main
```

Boot: DB → Realtime engine → browser opens at localhost:5001 → Cmd+Option+T to toggle voice.

---

## Railway Deploy

```bash
railway up
railway logs
railway variables set KEY="value"
```

**Env vars live on Railway, NOT in .env** — `.env` is gitignored and not deployed.

---

## Environment Variables

```
OPENAI_API_KEY          voice only (gpt-4o-mini-realtime-preview)
NVIDIA_API_KEY          primary text model provider (all pools)
GROQ_API_KEY            optional pool fallback (not used by text agent default)
OPENROUTER_API_KEY      optional pool fallback (not used by mood classifier — that's local now)
MEM0_API_KEY
LANGCHAIN_API_KEY
ELEVENLABS_API_KEY
ELEVENLABS_VOICE_ID
RAILWAY_URL=https://truman-production.up.railway.app
BRIDGE_SECRET=truman-bridge-secret
IDLE_TIMEOUT_SEC=600
POOL_CODING / POOL_CREATIVE / POOL_DESIGN / POOL_DOCS / POOL_VISION
POOL_GENERAL / POOL_REASONING / POOL_FAST / POOL_AGENTIC
```

---

## macOS Setup (one-time)

**Accessibility** for global hotkey: System Settings → Privacy → Accessibility → add Python binary → ON.

```bash
cp truman/plists/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.om.truman-scheduler.plist
launchctl load ~/Library/LaunchAgents/com.om.truman-reflect.plist
```

---

## Cost

Voice (Realtime API) is the only real cost (~$0.10–0.15/min). All text is free (NVIDIA NIM free tier). Target: $20/month.
