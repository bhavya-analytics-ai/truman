---
name: Projects — Forex Agent and MAYA
description: Forex ICT decision engine and MAYA Corona review RAG chatbot details
type: project
---

## Forex Agent — ICT Decision Engine (Personal — Live)
**Status:** Paper trading, live dashboard running

**What it does:**
- Pulls H1/M15/M5/M1 candles from OANDA API for 11 pairs
- Multi-TF confluence engine (pullback/breakout/reversal detection)
- ICT concepts: Order Blocks, FVGs, Liquidity Sweeps, MSS, CHoCH, Premium/Discount zones
- Bayesian scorer: P(win) + EV on every signal, two separate likelihood tables
- Two modes: Normal (gold strategy + forex strategy) and News Sniper (auto-activates on HIGH impact ForexFactory events)
- Output: ENTER_NOW / WAIT_RETEST / SKIP + entry/SL/TP1/TP2 + grade (A+/A/B/C)
- Slack alerts for A+ and A signals
- Flask dashboard at localhost:5000 — live, navy theme, refreshes every 30s
- ML pipeline: auto-labels win/loss, updates Bayesian base rates after 50+ signals

**Pairs:** XAU_USD, XAG_USD, GBP_USD, EUR_USD, EUR_GBP, USD_JPY, GBP_JPY, EUR_JPY, CHF_JPY, CAD_JPY, NZD_JPY

**Next:** Phase 4 Unicorn Model (FVG + Breaker Block), Phase 5 retest entries, Phase 6 ML base rates

**Stack:** Python, Flask, OANDA API, ForexFactory JSON, Slack webhooks, scikit-learn

---

## MAYA — Corona Review Intelligence (Bootcamp Sprint 5)
**What it is:** RAG-powered dual-mode AI chatbot on 221 Corona toilet product reviews

**Built:**
- ChromaDB vector store, k=8 retrieval, GPT-4o-mini
- Dual-mode auth: trigger phrase → server-side password validation → analyst mode
- Prompt injection protection: 8 regex patterns checked before LLM call
- 6 chart types inline in analyst chat (Chart.js)
- Surprise Me: 7 rotating insights each with different chart
- Competitor spider chart (Corona vs American Standard, Roca, Kohler)
- Product Liability Radar: separates product defects from service/delivery issues
- Store comparison cards, follow-up chips, structured Fix/Keep/Market/Action briefs
- LangSmith tracing on all core functions
- Interactive node-map presentation (maya_presentation.html)

**Stack:** Python, FastAPI, ChromaDB, LangChain, Chart.js, LangSmith

**Sprint 6 upgrade needed:** Convert MAYA from RAG chatbot → full LangChain agent with tools:
- Weather tool, web search tool, database query tool, table generator, code execution tool, MCP integration
- Multi-agent architecture (MAYA orchestrates sub-agents)
- Keep all Sprint 5 features intact
- Model: gpt-4o-mini
- Meta-flex: Friday (multi-agent system) builds Sprint 6 (multi-agent system)
