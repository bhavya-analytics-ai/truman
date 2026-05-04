import os
import warnings
import logging
warnings.filterwarnings("ignore")
for _name in ("phonemizer", "RealtimeSTT", "RealtimeTTS",
              "huggingface_hub", "huggingface_hub.utils._http",
              "transformers", "torch", "urllib3"):
    logging.getLogger(_name).setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=DeprecationWarning)
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'), override=True)

# ── Core keys ─────────────────────────────────────────────────────────────────
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")       # voice only
LANGCHAIN_API_KEY   = os.getenv("LANGCHAIN_API_KEY")
MEM0_API_KEY        = os.getenv("MEM0_API_KEY")
HUGGINGFACE_TOKEN   = os.getenv("HUGGINGFACE_TOKEN")
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

# ── Model providers (text — all free) ─────────────────────────────────────────
NVIDIA_API_KEY   = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL  = "https://integrate.api.nvidia.com/v1"


OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ── Pool defaults — Railway vars override these ───────────────────────────────
# Format: nvidia:provider/model-name  (no groq anywhere)
POOL_GENERAL  = os.getenv("POOL_GENERAL",  "nvidia:meta/llama-3.1-8b-instruct,nvidia:nvidia/llama-3.1-nemotron-nano-8b-v1,nvidia:stepfun-ai/step-3.5-flash,nvidia:nvidia/llama-3.3-nemotron-super-49b-v1,nvidia:moonshotai/kimi-k2-instruct")
POOL_CODING   = os.getenv("POOL_CODING",   "nvidia:qwen/qwen3-coder-480b-a35b-instruct,nvidia:moonshotai/kimi-k2-instruct,nvidia:meta/llama-3.3-70b-instruct")
POOL_REASONING= os.getenv("POOL_REASONING","nvidia:moonshotai/kimi-k2-thinking,nvidia:qwen/qwen3-coder-480b-a35b-instruct")
POOL_CREATIVE = os.getenv("POOL_CREATIVE", "nvidia:moonshotai/kimi-k2-thinking,nvidia:meta/llama-3.3-70b-instruct")
POOL_DESIGN   = os.getenv("POOL_DESIGN",   "nvidia:moonshotai/kimi-k2-thinking,nvidia:qwen/qwen3-coder-480b-a35b-instruct")
POOL_DOCS     = os.getenv("POOL_DOCS",     "nvidia:meta/llama-4-maverick-17b-128e-instruct,nvidia:meta/llama-3.3-70b-instruct,nvidia:moonshotai/kimi-k2-instruct")
POOL_VISION   = os.getenv("POOL_VISION",   "nvidia:meta/llama-4-maverick-17b-128e-instruct")
POOL_FAST     = os.getenv("POOL_FAST",     "nvidia:meta/llama-3.1-8b-instruct,nvidia:nvidia/llama-3.1-nemotron-nano-8b-v1,nvidia:stepfun-ai/step-3.5-flash")
POOL_AGENTIC  = os.getenv("POOL_AGENTIC",  "nvidia:qwen/qwen3-coder-480b-a35b-instruct,nvidia:moonshotai/kimi-k2-instruct,nvidia:meta/llama-3.3-70b-instruct")

# ── LLM builder used by get_agent() (ReAct loop) ─────────────────────────────
def get_llm(temperature: float = 0.7, json_mode: bool = False):
    """NVIDIA-only: nemotron → kimi-k2 → step-flash. Used by reflect.py."""
    from langchain_openai import ChatOpenAI

    def _nv(model):
        kwargs = dict(model=model, api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL,
                      temperature=temperature, timeout=8)
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        return ChatOpenAI(**kwargs)

    if not NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY not set.")
    primary = _nv("nvidia/llama-3.3-nemotron-super-49b-v1")
    f1      = _nv("moonshotai/kimi-k2-instruct")
    f2      = _nv("stepfun-ai/step-3.5-flash")
    return primary.with_fallbacks([f1, f2])

# ── Feature flags (Railway vars override) ────────────────────────────────────
# Set these in Railway env panel — defaults safe for production
import os as _os
_os.environ.setdefault("ENABLE_LANGGRAPH",   "1")
_os.environ.setdefault("ENABLE_COGNEE",      "1")
_os.environ.setdefault("ENABLE_MCP",         "1")
_os.environ.setdefault("ENABLE_MCP_FILES",   "1")
_os.environ.setdefault("ENABLE_MCP_WEB",     "1")
_os.environ.setdefault("ENABLE_MCP_GITHUB",  "1")
_os.environ.setdefault("ENABLE_GOALS",       "1")
_os.environ.setdefault("ENABLE_CURIOSITY",   "1")
_os.environ.setdefault("ENABLE_RISK_GATE",   "1")
_os.environ.setdefault("ENABLE_PROACTIVE",     "1")
_os.environ.setdefault("ENABLE_MORNING_EMAIL", "1")
_os.environ.setdefault("ENABLE_TELEGRAM",      "1")
_os.environ.setdefault("ENABLE_MAC_BANNER",    "1")
_os.environ.setdefault("ENABLE_SELF_CORRECT",  "1")
_os.environ.setdefault("ENABLE_WEB_PUSH",       "1")
_os.environ.setdefault("ENABLE_TG_MEDIA",       "1")
_os.environ.setdefault("ENABLE_BOSS_FLOW",      "0")   # Phase 15: all-channel message intake
_os.environ.setdefault("ENABLE_GMAIL_POLLING",  "0")   # Phase 15: Gmail triage + reply (5min IMAP)
_os.environ.setdefault("ENABLE_IMESSAGE",       "0")   # Phase 15B: iMessage poller (Mac) / iOS Shortcut receive
_os.environ.setdefault("IMESSAGE_VIP_THRESHOLD","0")   # Phase 15B: 0=always ask, N=auto-reply after N approvals

# ── Phase 15C: Pushcut (iMessage send without Mac) ───────────────────────────
# PUSHCUT_URL — webhook URL from Pushcut iOS app → triggers "Send iMessage" Shortcut
# Get it: Pushcut app → Shortcuts → add shortcut → copy webhook URL
PUSHCUT_URL = os.getenv("PUSHCUT_URL", "")

# ── Phase 15C: WhatsApp bridge on Railway worker ─────────────────────────────
# WA_BRIDGE_URL — Railway internal URL for the whatsapp-web.js worker service
# e.g. http://truman-wa-bridge.railway.internal:3099
WA_BRIDGE_URL = os.getenv("WA_BRIDGE_URL", "http://127.0.0.1:3099")

# ── Telegram bot (Phase 12) — fill in .env ───────────────────────────────────
# TELEGRAM_BOT_TOKEN → @BotFather → /newbot → copy token
# TELEGRAM_CHAT_ID   → message your bot once, check the poller log for your id
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")

# ── Morning email (Resend HTTP API — replaces Gmail SMTP which Railway blocks) ─
# RESEND_API_KEY     → sign up free at resend.com → API Keys → Create → copy key
# MORNING_EMAIL_FROM → optional, defaults to Truman <brief@truman.resend.dev>
# MORNING_EMAIL_TO   → where to send the brief (Om's email)
RESEND_API_KEY      = os.getenv("RESEND_API_KEY",      "")
MORNING_EMAIL_FROM  = os.getenv("MORNING_EMAIL_FROM",  "Truman <brief@truman.resend.dev>")
MORNING_EMAIL_TO    = os.getenv("MORNING_EMAIL_TO",    "")

# ── Gmail IMAP polling (Gmail App Password still used for READING inbox) ───────
# GMAIL_APP_PASSWORD  → Google Account → Security → App Passwords → generate
# GMAIL_ADDRESS       → your Gmail (falls back to MORNING_EMAIL_FROM if not set)
GMAIL_APP_PASSWORD  = os.getenv("GMAIL_APP_PASSWORD",  "")
GMAIL_ADDRESS       = os.getenv("GMAIL_ADDRESS", os.getenv("MORNING_EMAIL_FROM", ""))

# ── Misc ──────────────────────────────────────────────────────────────────────
os.environ["COGNEE_SKIP_CONNECTION_TEST"] = "true"
os.environ["HUGGINGFACE_TOKEN"]      = HUGGINGFACE_TOKEN or ""
os.environ["LANGCHAIN_TRACING_V2"]   = "true"
os.environ["LANGCHAIN_PROJECT"]      = "truman"
os.environ["LANGCHAIN_API_KEY"]      = LANGCHAIN_API_KEY or ""

SECURITY_QUESTION = "What's Om's birthdate?"
SECURITY_ANSWERS  = ["2001", "january", "jan"]

REALTIME_MODEL = "gpt-4o-mini-realtime-preview"
REALTIME_VOICE = "ash"
