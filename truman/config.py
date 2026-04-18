import os
import warnings
import logging
warnings.filterwarnings("ignore")
logging.getLogger("phonemizer").setLevel(logging.ERROR)
logging.getLogger("RealtimeSTT").setLevel(logging.ERROR)
logging.getLogger("RealtimeTTS").setLevel(logging.ERROR)
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"  # suppress SDL2 duplicate warnings on Mac
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")
LANGCHAIN_API_KEY   = os.getenv("LANGCHAIN_API_KEY")
MEM0_API_KEY        = os.getenv("MEM0_API_KEY")
HUGGINGFACE_TOKEN   = os.getenv("HUGGINGFACE_TOKEN")
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

# Groq fallback — automatic failover when OpenAI hits quota / rate limits.
# Set GROQ_API_KEY in .env to enable; leave unset to stay pure OpenAI.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "moonshotai/kimi-k2-instruct")


def get_llm(temperature: float = 0.7, json_mode: bool = False):
    """Build a ChatOpenAI with automatic Groq fallback.

    Primary: GPT-4o on OpenAI.
    Fallback: Kimi K2 on Groq (engages only if OpenAI raises — quota/429/5xx).
    If GROQ_API_KEY is unset, returns the primary LLM alone.
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

    if not GROQ_API_KEY:
        return primary

    from langchain_groq import ChatGroq
    groq_kwargs = {
        "model": GROQ_MODEL,
        "api_key": GROQ_API_KEY,
        "temperature": temperature,
    }
    if json_mode:
        groq_kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    fallback = ChatGroq(**groq_kwargs)

    return primary.with_fallbacks([fallback])

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
