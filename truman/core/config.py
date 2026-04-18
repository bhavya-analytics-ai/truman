import os
import warnings
import logging
warnings.filterwarnings("ignore")
# silence the third-party log noise (torch, huggingface_hub, misaki, etc.)
for _name in ("phonemizer", "RealtimeSTT", "RealtimeTTS",
              "huggingface_hub", "huggingface_hub.utils._http",
              "transformers", "torch", "urllib3"):
    logging.getLogger(_name).setLevel(logging.ERROR)
# stop misaki / torch.jit DeprecationWarnings from printing
warnings.filterwarnings("ignore", category=DeprecationWarning)
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"  # suppress SDL2 duplicate warnings on Mac
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
from dotenv import load_dotenv

# override=True: .env wins over any stale keys exported from the shell
# (e.g. old OPENAI_API_KEY in ~/.zshrc). Without this, load_dotenv leaves
# existing env vars alone — which silently uses the wrong key.
# config.py lives at truman/core/config.py; .env lives at friday/.env
# Two `..` hops: truman/core/ → truman/ → friday/
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'), override=True)

OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")
LANGCHAIN_API_KEY   = os.getenv("LANGCHAIN_API_KEY")
MEM0_API_KEY        = os.getenv("MEM0_API_KEY")
HUGGINGFACE_TOKEN   = os.getenv("HUGGINGFACE_TOKEN")
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

# OpenRouter fallback chain — automatic failover when OpenAI is down/out of quota.
# Primary fallback: gpt-oss-120b (OpenAI's open-weight model, same DNA as GPT-4o).
# Secondary fallback: Kimi K2.5 (agentic, strong tool-use) when gpt-oss is rate-limited.
# All free. Set OPENROUTER_API_KEY in .env to enable; leave unset for pure OpenAI.
OPENROUTER_API_KEY      = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL        = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")
OPENROUTER_MODEL_FALLBACK = os.getenv("OPENROUTER_MODEL_FALLBACK", "moonshotai/kimi-k2.5")
OPENROUTER_BASE_URL     = "https://openrouter.ai/api/v1"

# Groq support kept for legacy but unused — prefer OpenRouter.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "moonshotai/kimi-k2-instruct")


def _openrouter_llm(model: str, temperature: float, json_mode: bool):
    """Build a ChatOpenAI pointed at OpenRouter for the given free model."""
    from langchain_openai import ChatOpenAI
    kwargs = {
        "model": model,
        "api_key": OPENROUTER_API_KEY,
        "base_url": OPENROUTER_BASE_URL,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatOpenAI(**kwargs)


def get_llm(temperature: float = 0.7, json_mode: bool = False):
    """Build a ChatOpenAI with a two-deep OpenRouter fallback chain.

    Primary:    GPT-4o on OpenAI.
    Fallback 1: gpt-oss-120b on OpenRouter (free, OpenAI open-weight).
    Fallback 2: Kimi K2.5 on OpenRouter  (free, agentic/tool-use).
    If OPENROUTER_API_KEY is unset, returns the primary alone.
    """
    from langchain_openai import ChatOpenAI

    oai_kwargs = {
        "model": "gpt-4o",
        "api_key": OPENAI_API_KEY,
        "temperature": temperature,
    }
    if json_mode:
        oai_kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    primary = ChatOpenAI(**oai_kwargs)

    if not OPENROUTER_API_KEY:
        return primary

    fallbacks = [
        _openrouter_llm(OPENROUTER_MODEL,          temperature, json_mode),
        _openrouter_llm(OPENROUTER_MODEL_FALLBACK, temperature, json_mode),
    ]
    return primary.with_fallbacks(fallbacks)

os.environ["HUGGINGFACE_TOKEN"] = HUGGINGFACE_TOKEN or ""

os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "truman"
os.environ["LANGCHAIN_API_KEY"] = LANGCHAIN_API_KEY

# Security challenge — change the answer here
SECURITY_QUESTION = "What's Om's birthdate?"
SECURITY_ANSWERS  = ["2001", "january", "jan"]   # any of these in the answer = pass

# Realtime API
REALTIME_MODEL = "gpt-4o-mini-realtime-preview"
REALTIME_VOICE = "ash"   # options: alloy, ash, ballad, coral, echo, sage, shimmer, verse
