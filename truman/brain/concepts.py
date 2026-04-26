"""
concepts.py — Truman's concept graph wrapper around Cognee.

Cognee builds a knowledge graph from text:
  - entity extraction + dedup
  - relationship inference
  - semantic search across the graph

We abstract it here so if Cognee ever dies we swap once, nothing else changes.
All ops are async internally; sync wrappers here for compatibility with the
existing agent/loop code.

LLM: NVIDIA NIM (free) — used for entity extraction
Embeddings: OpenAI (we already pay, cost is near-zero at this scale)
Storage: truman/data/cognee/
"""
import asyncio
import os
import threading

# ── Paths ──────────────────────────────────────────────────────────────────────
_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "cognee",
)

_initialized = False
_init_lock   = threading.Lock()


# ── Async helpers ─────────────────────────────────────────────────────────────
def _run_async(coro):
    """Run an async coroutine from sync code safely."""
    try:
        loop = asyncio.get_running_loop()
        # already inside an event loop — schedule as task, wait with thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(asyncio.run, coro)
            return future.result(timeout=30)
    except RuntimeError:
        # no event loop running — safe to use asyncio.run()
        return asyncio.run(coro)


# ── Init ──────────────────────────────────────────────────────────────────────
def init():
    """Configure Cognee once. Safe to call multiple times."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        try:
            import cognee

            # point storage to our project directory
            cognee.config.system_root_directory(_DATA_DIR)
            cognee.config.data_root_directory(_DATA_DIR)

            # LLM: NIM (free) — use openai-compatible provider
            from truman.core.config import NVIDIA_API_KEY, NVIDIA_BASE_URL
            # skip 30s LLM connection test on boot
            os.environ["COGNEE_SKIP_CONNECTION_TEST"] = "true"

            cognee.config.set_llm_provider("openai")
            cognee.config.set_llm_endpoint(NVIDIA_BASE_URL)
            cognee.config.set_llm_api_key(NVIDIA_API_KEY)
            cognee.config.set_llm_model("stepfun-ai/step-3.5-flash")  # cheap + fast

            # Embeddings: OpenAI (near-zero cost at this scale)
            from truman.core.config import OPENAI_API_KEY
            cognee.config.set_embedding_provider("openai")
            cognee.config.set_embedding_model("text-embedding-3-small")
            cognee.config.set_embedding_api_key(OPENAI_API_KEY)

            _initialized = True
            print("[Cognee] initialized — concept graph ready")
        except Exception as e:
            print(f"[Cognee] init failed: {e}")
            raise


# ── Public API ────────────────────────────────────────────────────────────────
def ingest(text: str, dataset: str = "truman") -> bool:
    """
    Feed text into the concept graph.
    Cognee extracts entities + relationships automatically.
    Returns True on success, False on failure.
    """
    if not text or len(text.strip()) < 20:
        return False
    try:
        init()
        import cognee

        async def _ingest():
            await cognee.add(text, dataset_name=dataset)
            await cognee.cognify(datasets=[dataset])

        _run_async(_ingest())
        return True
    except Exception as e:
        print(f"[Cognee] ingest error: {e}")
        return False


def search(query: str, top_k: int = 5) -> list[str]:
    """
    Search the concept graph for relevant context.
    Returns list of text snippets, most relevant first.
    """
    if not query.strip():
        return []
    try:
        init()
        import cognee
        from cognee import SearchType

        async def _search():
            results = await cognee.search(SearchType.GRAPH_COMPLETION, query=query)
            return results

        raw = _run_async(_search())
        if not raw:
            return []

        out = []
        for r in raw[:top_k]:
            # Cognee returns dicts or strings depending on version
            if isinstance(r, dict):
                chunk = r.get("text") or r.get("content") or r.get("answer") or str(r)
            else:
                chunk = str(r)
            if chunk and chunk not in out:
                out.append(chunk)
        return out

    except Exception as e:
        print(f"[Cognee] search error: {e}")
        return []


def ingest_background(text: str, dataset: str = "truman") -> None:
    """Fire-and-forget ingest — doesn't block the brain loop."""
    threading.Thread(target=ingest, args=(text, dataset), daemon=True).start()


def search_sync(query: str, top_k: int = 5) -> str:
    """Return concept context as a single string for injection into system prompt."""
    results = search(query, top_k=top_k)
    if not results:
        return ""
    return "\n".join(f"- {r}" for r in results)
