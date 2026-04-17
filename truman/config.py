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
