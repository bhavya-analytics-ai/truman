from unittest.mock import MagicMock
from truman.brain import tool_retrieval


def _make_tool(name, description):
    t = MagicMock()
    t.name = name
    t.description = description
    return t


def test_init_tool_embeddings_populates_dict(tmp_db, mock_nim_embed):
    tools = [
        _make_tool("get_weather", "Get current weather for a location"),
        _make_tool("set_reminder", "Schedule a reminder at a future time"),
    ]
    tool_retrieval._TOOL_VECTORS.clear()
    tool_retrieval.init_tool_embeddings(tools, [])
    assert "get_weather" in tool_retrieval._TOOL_VECTORS
    assert "set_reminder" in tool_retrieval._TOOL_VECTORS
    assert len(tool_retrieval._TOOL_VECTORS["get_weather"]) == 8


def test_retrieve_returns_topk(tmp_db, mock_nim_embed):
    tools = [
        _make_tool("get_weather", "Get current weather for a location"),
        _make_tool("set_reminder", "Schedule a reminder"),
        _make_tool("web_search", "Search the web for information"),
    ]
    tool_retrieval._TOOL_VECTORS.clear()
    tool_retrieval.init_tool_embeddings(tools, [])
    result = tool_retrieval.retrieve("what's the weather like", tier="normal", pool="general", k=2)
    assert len(result) == 2
    names = [t.name for t in result]
    assert all(n in {"get_weather", "set_reminder", "web_search"} for n in names)


def test_retrieve_trivial_returns_empty(tmp_db, mock_nim_embed):
    tools = [_make_tool("web_search", "Search the web")]
    tool_retrieval._TOOL_VECTORS.clear()
    tool_retrieval.init_tool_embeddings(tools, [])
    result = tool_retrieval.retrieve("yo", tier="trivial", pool="general")
    assert result == []


def test_retrieve_falls_back_to_all_tools_on_embed_failure(tmp_db, monkeypatch):
    tools = [_make_tool("a", "tool a"), _make_tool("b", "tool b")]
    tool_retrieval._TOOL_VECTORS.clear()
    tool_retrieval._ALL_TOOLS = tools  # populated by init normally
    tool_retrieval._TOOL_BY_NAME = {t.name: t for t in tools}

    def broken_embed(text):
        raise RuntimeError("NIM API down")

    monkeypatch.setattr(tool_retrieval, "_embed", broken_embed)
    result = tool_retrieval.retrieve("anything", tier="normal", pool="general")
    assert len(result) == 2  # all tools returned


def test_pool_boost_coding_pushes_gitnexus(tmp_db, mock_nim_embed):
    tools = [
        _make_tool("web_search", "Search the web"),
        _make_tool("gitnexus__query", "Query the codebase knowledge graph"),
    ]
    tool_retrieval._TOOL_VECTORS.clear()
    tool_retrieval.init_tool_embeddings(tools, [])
    result = tool_retrieval.retrieve("look up something", tier="complex", pool="coding", k=2)
    names = [t.name for t in result]
    assert "gitnexus__query" in names


def test_cosine_similarity_basic():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    assert abs(tool_retrieval._cosine(v1, v2) - 1.0) < 1e-6
    v3 = [0.0, 1.0, 0.0]
    assert abs(tool_retrieval._cosine(v1, v3)) < 1e-6
