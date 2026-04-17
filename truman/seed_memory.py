import config
from mem0 import MemoryClient

memory = MemoryClient(api_key=config.MEM0_API_KEY)
USER_ID = "om"

memories = [
    "Om's real name is Bhavya Pandya but always call him Om.",
    "Om is an MS student in Data Analytics at LIU Brooklyn.",
    "Om works at SeaCap, an MCA/business funding broker, 5 days a week. Jewish company schedule.",
    "Om trades forex using ICT strategy. Uses OANDA API across 11 pairs: XAU_USD, XAG_USD, GBP_USD, EUR_USD, EUR_GBP, USD_JPY, GBP_JPY, EUR_JPY, CHF_JPY, CAD_JPY, NZD_JPY.",
    "Om's forex engine uses ICT concepts: Order Blocks, FVGs, Liquidity Sweeps, MSS, CHoCH, Premium/Discount zones. Bayesian scorer gives P(win) and EV. Flask dashboard at localhost:5000.",
    "Om has been coding for 6 months and built multiple production systems for real clients in that time.",
    "SeaCap lead pipeline: CSV drop, watchdog, cleans and verifies leads using MillionVerifier, Google Maps, Cobalt Intelligence, deduplication. Logs to Supabase. Runs via LaunchAgent.",
    "SeaCap portal: React + Vite + Tailwind frontend, Node.js + Express backend, MongoDB, Puppeteer PDF, Nodemailer email, canvas signature, auto application numbers SEA-2026-XXXXXX.",
    "Aspire deal agent: FastAPI backend, GPT tool-calling, fills Excel templates for 9 underwriters, voice dashboard with Whisper STT and OpenAI TTS, Supabase memory.",
    "MAYA is Om's Sprint 5 bootcamp project — RAG chatbot on 221 Corona toilet reviews, ChromaDB, GPT-4o-mini, dual-mode auth, LangSmith tracing, Chart.js charts.",
    "Sprint 6 goal: upgrade MAYA from RAG chatbot to full LangChain multi-agent with tools — weather, web search, DB query, table generator, code execution, MCP.",
    "FEC-WHIN is Om's NGO client. Built on Google Apps Script + Sheets. 6 modules: Intake, Feedback, Inventory, Sign-In, Events, Partnerships. Data rows start at row 4, never delete rows.",
    "Om wants to rebuild FEC as SaaS for 30 branches at $99-200/month. Supabase backend, multi-tenant auth, super admin view.",
    "Om's tech stack: Python, FastAPI, Node.js, Express, React, Vite, Tailwind, Supabase, MongoDB, LangChain, ChromaDB, OpenAI, Railway, Vercel, LaunchAgent.",
    "Om runs Truman — his personal AI OS built with LangChain + LangGraph + GPT-4o-mini + Mem0 + Whisper + OpenAI TTS.",
    "Om prefers short, direct answers. No lectures, no fluff. Real talk only. He's an experienced builder, not a beginner.",
    "Om has 3 Claude Pro accounts that he rotates. Uses OpenAI API credits for his own projects.",
    "Om does forex trading between work tasks, monitoring charts while coding simultaneously.",
]

for m in memories:
    memory.add([{"role": "user", "content": m}], user_id=USER_ID)
    print(f"Seeded: {m[:70]}...")

print("\nDone. Truman knows Om fully.")
