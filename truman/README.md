# Truman

Om's personal voice assistant. Not a toy — a daily-driver "personal AI operating system" running on Mac with browser-hosted audio, long-term memory, reminders, and a persona tuned to how Om actually talks.

**Status as of 2026-04-19:** Levels 1–6 shipped + unified tool layer + MCP bridge live. Level 7 (Builder Mode) is next.

---

## What Truman Does Today

- **Voice chat** via OpenAI Realtime API (`gpt-4o-mini-realtime-preview`, voice `ash`). Push Cmd+Option+T anywhere on the Mac to toggle a session.
- **Browser-hosted audio** — mic + speaker run in a Chrome/Safari tab so you get WebRTC AEC for free. Orb UI at `localhost:5001`.
- **Long-term memory** via Mem0 hosted (`MemoryClient`, `user_id="om"`). Durable facts persist across every session.
- **Short-term context** from SQLite — last 5 turns + last session summary auto-injected into every session's system prompt.
- **Reminders** — "remind me at 3pm to call SeaCap" → fires as a spoken voice alert. Writes to both Truman DB and macOS Reminders (for iPhone backup). When Truman fires it himself, he deletes the Apple copy so you don't get double-notified.
- **Nightly reflection** — at 2am, every ended session gets summarized + durable facts get promoted to Mem0. Runs via launchd.
- **Mood-aware** — classifies every text turn (free via OpenRouter) as angry/sad/hyped/frustrated/affectionate/focused/neutral and adjusts tone.
- **Persona-strict** — `persona.py` encodes Om's speech style. Short casual replies on greetings, 3-5 sentences on real questions, no filler openers, no lists/bullets, matches Om's lowercase run-on register.
- **Cost control** — auto-closes Realtime session after 3 min of silence; trimmed context window; free OpenRouter text fallback.
- **MCP servers** — external tools (filesystem, databases, APIs) mountable via `tools/mcp_config.py`. Filesystem server live with 14 `fs__*` tools.

---

## Architecture

```
        ┌──────────────┐         ┌──────────────────┐
Browser │ orb UI + mic │◀──WS───▶│ orb.py (Flask)   │
tab     │ + speaker    │         │ audio queues     │
        └──────────────┘         └────────┬─────────┘
                                          │
                            mic_in/audio_out PCM queues
                                          │
                                  ┌───────▼───────┐
                                  │ realtime.py   │───── OpenAI Realtime WS
                                  │ session loop  │
                                  │ idle watchdog │
                                  └───┬───────┬───┘
                                      │       │
                                  tools│       │context
                                      │       │
                        ┌─────────────▼─┐   ┌─▼──────────────────┐
                        │ realtime_tools│   │ Mem0 + db.py       │
                        │ .py           │   │ (facts + history)  │
                        └───────┬───────┘   └────────────────────┘
                                │
                    ┌───────────▼─────────┐
                    │ agent.py            │──── OpenAI GPT-4o
                    │ LangChain agent     │    └─► OpenRouter gpt-oss-120b (free)
                    │ + mood classifier   │        └─► OpenRouter Kimi K2.5 (free)
                    └───────┬─────────────┘
                            │
                    ┌───────▼──────────┐
                    │ persona.py       │  single source of truth
                    │ identity/style/  │  for SYSTEM prompt
                    │ mood/capability  │
                    └──────────────────┘
```

---

## File Map

Layout is a proper Python package — `truman/` at the repo root, subpackages by concern. All imports are absolute (`from truman.core import config`). Run with `python -m truman.main` from the repo root.

| File | Role |
|---|---|
| `truman/main.py` | Orchestrator — boots orb, proactive loop, realtime engine, hotkey. |
| `truman/core/config.py` | Env loader (`override=True`), `get_llm()` with OpenRouter fallback chain, warning suppressors. |
| `truman/core/persona.py` | Identity + style + mood + humor + capability-honesty rules. Single source of truth for the SYSTEM prompt. |
| `truman/core/hotkey.py` | Cmd+Option+T global hotkey via pynput. |
| `truman/text/agent.py` | LangChain agent, Mem0 client, tool definitions, `_classify_mood()`. |
| `truman/voice/realtime.py` | OpenAI Realtime API WS loop, session lifecycle, filters, context injection, idle auto-close. |
| `truman/voice/orb.py` | Flask server + `/audio` WebSocket + browser JS. Single-client audio guard. |
| `truman/voice/realtime_tools.py` | Tool schemas + dispatcher for Realtime function-calling. |
| `truman/voice/voice.py` | Kokoro TTS for boot message only. Stamps `tts_state` after each play. |
| `truman/voice/tts_state.py` | Shared last-spoke timestamp — speak() writes, realtime.py reads for echo cooldown. |
| `truman/tools/all_tools.py` | Canonical tool definitions — single source for both voice and text paths. |
| `truman/tools/dispatch.py` | Schema → Realtime flat format + dispatch. Lazy `_by_name()` so MCP tools are reachable. |
| `truman/tools/mcp_bridge.py` | MCP client bridge. Daemon asyncio loop + AsyncExitStack + JSON Schema → pydantic mapper. |
| `truman/tools/mcp_config.py` | Declarative MCP server list. Uncomment entries to mount at boot. |
| `truman/storage/db.py` | SQLite persistence (WAL + FTS5) — sessions, turns, summaries, reminders, tool_calls. |
| `truman/storage/reflect.py` | Nightly session summarization + fact promotion to Mem0. |
| `truman/storage/seed_memory.py` | One-shot Mem0 seeding script. |
| `truman/scheduling/proactive.py` | In-process reminder firing + morning brief + idle check-in. |
| `truman/scheduling/scheduler.py` | Standalone launchd reminder firer (backup to proactive). |
| `truman/plists/com.om.truman-scheduler.plist` | LaunchAgent, 60s reminder poll. Runs `python -m truman.scheduling.scheduler`. |
| `truman/plists/com.om.truman-reflect.plist` | LaunchAgent, 2am daily reflection. Runs `python -m truman.storage.reflect`. |
| `truman/truman.db` | SQLite store. |

---

## The Fallback Chain

Text path has a two-deep fallback so OpenAI quota death doesn't kill Truman's text brain:

```
gpt-4o (OpenAI)  →  openai/gpt-oss-120b:free  →  moonshotai/kimi-k2.5
```

Both fallbacks are free on OpenRouter. LangChain's `RunnableWithFallbacks` cascades automatically on raise. Wired in `config.py :: get_llm()`.

**Voice path has NO fallback.** Realtime API is OpenAI-only — no other provider speaks the protocol. If OpenAI quota dies, voice dies. Fix = add credits.

---

## Running It

```bash
# one-time: add accessibility permission for pynput (see below)
# one-time: ensure .env has OPENAI_API_KEY + OPENROUTER_API_KEY + MEM0_API_KEY

cd /Users/ompandya/Desktop/friday
python -m truman.main
```

Must be run as a module from the repo root so the absolute `truman.*` imports resolve. `python truman/main.py` will fail.

Expected boot:
1. `[DB] Ready at .../truman.db`
2. `[Realtime] Engine ready. Press Cmd+Option+T to start talking.`
3. `[Hotkey] Cmd+Option+T → toggle Truman listening`
4. Browser auto-opens a new Chrome window at `localhost:5001`
5. Click the orb once (grants mic permission)
6. Voice: "Truman online. Press Command Option T to talk."
7. Cmd+Option+T → orb turns listening blue → talk

---

## Required macOS Setup (one-time)

**Accessibility permission** — pynput needs it to intercept Cmd+Option+T globally. Without this, the hotkey only fires when the terminal is focused.

> System Settings → Privacy & Security → Accessibility → `+` → add `/opt/anaconda3/envs/truman/bin/python` → toggle ON → restart Truman

**Launch agents** — scheduler + reflect. Plists live at `truman/plists/`; copy to `~/Library/LaunchAgents/` before load:

```bash
cp /Users/ompandya/Desktop/friday/truman/plists/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.om.truman-scheduler.plist
launchctl load ~/Library/LaunchAgents/com.om.truman-reflect.plist
launchctl list | grep truman   # should show both
```

Both plists have `WorkingDirectory=/Users/ompandya/Desktop/friday` and invoke Python with `-m truman.scheduling.scheduler` / `-m truman.storage.reflect`.

---

## Environment Variables (`friday/.env`)

```
OPENAI_API_KEY=sk-proj-...          # required — Realtime voice + text primary
OPENROUTER_API_KEY=sk-or-v1-...     # required — free text fallback
OPENROUTER_MODEL=openai/gpt-oss-120b:free
OPENROUTER_MODEL_FALLBACK=moonshotai/kimi-k2.5
MEM0_API_KEY=m0-...                 # required — long-term memory
LANGCHAIN_API_KEY=lsv2_pt_...       # optional — tracing
HUGGINGFACE_TOKEN=hf_...            # optional — silences HF warning
ELEVENLABS_API_KEY=sk_...           # unused in current build
ELEVENLABS_VOICE_ID=...             # unused in current build
```

`config.py` loads with `override=True` — `.env` wins over any stale shell exports (e.g. old `OPENAI_API_KEY` in `~/.zshrc`).

---

## Cost Profile

Voice (Realtime) is the entire expense. Text path costs nothing meaningful (small OpenAI usage when quota has room; free OpenRouter when it doesn't).

Per Realtime settings: roughly **$0.10–0.15 / minute** of active conversation. Level 6 changes aim to stretch that:
- 3-minute idle auto-close stops silent tabs from burning time
- 20 → 5 recent-turn trim cuts per-session input tokens ~60%
- Single-client orb guard prevents multi-tab duplicate billing
- Persona brevity rules cut output tokens on greetings

Target budget: **$20/month.** If you exceed that, Level 7 Builder Mode shifts heavy tasks to free OpenRouter coder models.

---

## Persona

Truman's system prompt lives entirely in `persona.py`. Edit that one file to change how he talks everywhere.

Rules encoded came from observing how Om talks: casual lowercase, commas over periods, run-ons, "bro/man/yo," direct answer first, no filler openers, no lists/bullets, commits to decisions, owns mistakes flat, matches mood/interrupts/sarcasm, dry humor only.

---

## Next Steps

### 🔜 Level 7 — Builder Mode
Truman builds real code for Om's actual projects. First target: **FEC HTML form + Google Sheets integration**.

**What it means:** Say "Truman, build mode — add a submit button to the FEC form" and Truman:
1. Reads the relevant files
2. Makes the change in an isolated git worktree (can NEVER touch main repo directly)
3. Runs a quick test (local server + curl)
4. Reports back by voice: "Done. Added the button, tested the POST, diff is clean."

**Model stack (free):**
- Primary: `qwen/qwen3-coder:free` — top free coding model on OpenRouter
- Fallback: `moonshotai/kimi-k2.5` — strong on agentic/tool-use tasks
- Voice narration: existing Realtime path (already there)

**Build order:**
- **7a** — `builder.py`: new agent with read_file, write_file, list_dir, run_shell tools + worktree isolation
- **7b** — Voice handoff: "build mode" / detected build intent → routes to builder agent, streams status back by voice
- **7c** — Test loop: spin local server, curl endpoints, capture output, auto-retry on fail
- **7d** — Google Sheets: Apps Script webhook OR service account to read/write sheet data
- **7e** — Review mode: "Truman, review this file" → coder model reads + suggests, no writes

---

### 🔜 Level 8 — Always-On Robustness
- `pmset schedule wake` on reminder add — Mac wakes at reminder time even if asleep
- pyannote.audio speaker verification (Resemblyzer was unreliable, upgrade deferred to here)
- Railway cloud fallback — Truman survives laptop closed
- Mobile PWA — orb in the browser on iPhone

---

### 🔜 Level 9+ — Aspirational
9. Orb UI 2.0
10. Calendar integration
11. Comms (email/messages read/send)
12. Dev tools (GitHub, CI status)
13. Forex brain bridge (ICT engine ↔ Truman)
14. Browser automation
15. Media controls
16. Always-on main process (launchd Truman boot)
17. **Mission 1** — MAYA Sprint 6
18. **Mission 2** — FEC SaaS v2

---

## Troubleshooting Cheatsheet

| Symptom | Likely cause | Fix |
|---|---|---|
| `insufficient_quota` on Realtime | Stale `OPENAI_API_KEY` from shell | `load_dotenv(override=True)` already applied. Restart Truman. If still failing, check key against `platform.openai.com/usage`. |
| 2-3 bots echoing | Multiple orb tabs open | Single-client guard evicts stale tabs automatically. Close any "another Truman tab took over" tabs. |
| Cmd+Option+T doesn't fire | Accessibility permission missing | System Settings → Privacy → Accessibility → add python binary. |
| "This process is not trusted" on startup | Same as above | Same fix. |
| Orb window doesn't open | Browser not default / wrong app front | Paste `http://localhost:5001` manually. The `osascript` open-new-window tries Chrome → Safari → fallback `open`. |
| Truman greets first with project talk | Historical bug (fixed Level 6) | Confirm `realtime.py` has no `response.create` after session.update. |
| Fallback never triggers | `langchain-groq` / `langchain-openai` missing | `pip install langchain-groq langchain-openai`. |
| OpenRouter `:free` model errors with 429 | Shared free pool saturated | Swap `OPENROUTER_MODEL` to another free model, or move to paid DeepSeek (pennies). |

---

## Key Design Decisions (and why)

- **Browser audio over native sounddevice** — WebRTC AEC is production-grade, local AEC was a broken echo loop.
- **Persona in one file** — so the voice never drifts between text path and voice path.
- **Mood classifier on free Groq OpenRouter** — every turn tagged without touching OpenAI budget.
- **Idle auto-close, not session timeouts by message count** — Realtime bills on connection seconds, so time-based close saves money even during active silence.
- **Single-client orb WS** — stale tabs from previous restarts used to split audio queues; now they get evicted automatically.
- **Two-deep fallback chain** — one fallback isn't enough when free pools can be rate-limited, two gives real resilience.
- **No wake-word** — hotkey is intentional, avoids always-on mic.
- **Cmd+Option+T not Cmd+Shift+T** — Shift+T collides with Claude Code's "reopen closed tab" in Chrome.

---

## For the Next Claude

When you pick this up cold:
1. Read `~/.claude/projects/-Users-ompandya-Desktop-friday/memory/projects_truman_build_status.md` first — fullest current state.
2. Also read `projects_truman_audio.md` and `feedback_working_style.md` from the same directory.
3. Om's style: casual, lowercase, direct. Match his register. Never start with "Great question", "Of course", "I'd be happy to", "Certainly." Own mistakes flat ("yeah my bad"), not "I apologize for the confusion."
4. Commit to decisions. Don't present menus. Pick one and defend it; he'll push back if he disagrees.
5. The likely next ask is Level 7 — Builder Mode for his FEC project.
