---
name: Projects — SeaCap System and Aspire Deal Agent
description: SeaCap lead pipeline + portal, and Aspire MCA underwriting agent details
type: project
---

## SeaCap System (Production — Real Business)
**Company:** SeaCap USA — MCA/business funding broker. Om works here 5 days/week.

**Built:**
- **Lead Pipeline:** CSV drop → watchdog auto-detects → cleans, verifies (MillionVerifier email, Google Maps business, Cobalt Intelligence SOS, duplicate detection) → sorts into 4 lists (Qualified, Needs Fixing, DNC, Funded) → logs to Supabase `pipeline_logs` → LaunchAgent runs on boot
- **SeaCap Portal:** Full stack React + Vite + Tailwind frontend, Node.js + Express backend, MongoDB, Puppeteer PDF generation, Nodemailer dual email system, canvas draw signature, multi-step form with smart ownership routing, auto-generated application numbers `SEA-2026-XXXXXX`

**Pending:**
- Twilio phone verification
- Close CRM push (key exists)
- VanillaSoft push (key pending)
- SeaCap Agent — reads Close CRM + VanillaSoft + GoHighLevel, answers deal questions

**Stack:** Python, Node.js, React, Vite, Tailwind, MongoDB, Supabase, FastAPI, LaunchAgent (macOS)

---

## Aspire Deal Agent (Production — Real Business)
**Company:** Aspire — MCA underwriting

**Built:**
- `install_templates.py` — drops blank Excel templates into all 9 underwriter folders
- `fill_templates.py` — reads merchant folders, fills Deal Summary + MCA Positions using GPT
- `watch_deals.py` — watches all 9 underwriter folders, auto-refills on new file detection
- `agent_backend.py` — FastAPI backend, tool-calling loop up to 8 iterations
- Tools: `search_merchant` (3-level fuzzy), `read_template`, `list_documents`, `read_document` (vision)
- Dashboard: dark theme chat UI, voice mode (whisper-1 STT → agent → tts-1 TTS), push-to-talk, follow-up chips, conversation memory
- Supabase: `agent_conversations`, `agent_notes`

**Pending:**
- Document reader auto-fill with data integrity layer
- Supabase Auth
- Azure OpenAI switch before go-live
- Railway deployment
- LangSmith tracing

**Stack:** Python, FastAPI, OpenAI (GPT/Whisper/TTS), Supabase, HTML/JS dashboard
