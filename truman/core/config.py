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
POOL_GENERAL  = os.getenv("POOL_GENERAL",  "nvidia:deepseek-ai/deepseek-v3.2,nvidia:stepfun-ai/step-3.5-flash,nvidia:moonshotai/kimi-k2-instruct")
POOL_CODING   = os.getenv("POOL_CODING",   "nvidia:deepseek-ai/deepseek-v3.2,nvidia:zai-org/glm-4.7,nvidia:qwen/qwen3-coder-480b-a35b-instruct")
POOL_REASONING= os.getenv("POOL_REASONING","nvidia:moonshotai/kimi-k2-thinking,nvidia:deepseek-ai/deepseek-v3.2")
POOL_CREATIVE = os.getenv("POOL_CREATIVE", "nvidia:moonshotai/kimi-k2-thinking,nvidia:mistralai/mistral-large-3-675b-instruct-2512,nvidia:meta/llama-4-maverick-17b-128e-instruct")
POOL_DESIGN   = os.getenv("POOL_DESIGN",   "nvidia:deepseek-ai/deepseek-v3.2,nvidia:zai-org/glm-4.7,nvidia:nvidia/mistral-nemotron")
POOL_DOCS     = os.getenv("POOL_DOCS",     "nvidia:meta/llama-4-maverick-17b-128e-instruct,nvidia:mistralai/mistral-medium-3-instruct,nvidia:minimaxai/minimax-m2.7")
POOL_VISION   = os.getenv("POOL_VISION",   "nvidia:meta/llama-4-maverick-17b-128e-instruct,nvidia:mistralai/mistral-large-3-675b-instruct-2512")
POOL_FAST     = os.getenv("POOL_FAST",     "nvidia:stepfun-ai/step-3.5-flash,nvidia:nvidia/mistral-nemotron")
POOL_AGENTIC  = os.getenv("POOL_AGENTIC",  "nvidia:qwen/qwen3-coder-480b-a35b-instruct,nvidia:moonshotai/kimi-k2-instruct,nvidia:mistralai/devstral-2-123b-instruct-2512")

# ── LLM builder used by get_agent() (ReAct loop) ─────────────────────────────
def get_llm(temperature: float = 0.7, json_mode: bool = False):
    """NVIDIA-only: deepseek-v3.2 → mistral-nemotron. Used by reflect.py."""
    from langchain_openai import ChatOpenAI

    def _nv(model):
        kwargs = dict(model=model, api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL,
                      temperature=temperature, timeout=30)
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        return ChatOpenAI(**kwargs)

    if not NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY not set.")
    primary = _nv("deepseek-ai/deepseek-v3.2")
    f1      = _nv("nvidia/mistral-nemotron")
    return primary.with_fallbacks([f1])

# ── Feature flags (Railway vars override) ────────────────────────────────────
# Set these in Railway env panel — defaults safe for production
import os as _os
_os.environ.setdefault("ENABLE_LANGGRAPH",   "1")
_os.environ.setdefault("ENABLE_COGNEE",      "1")
_os.environ.setdefault("ENABLE_MCP",         "1")
_os.environ.setdefault("ENABLE_MCP_FILES",   "1")
_os.environ.setdefault("ENABLE_MCP_WEB",     "1")
_os.environ.setdefault("ENABLE_MCP_GITHUB",  "1")

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
