"""
test_chat_path.py — TDD tests for claude-shape single-call chat path.
"""
import time
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_llm(monkeypatch):
    mock = MagicMock(return_value=("yo, what's good", "kimi-k2-mock", []))
    monkeypatch.setattr("truman.text.agent._call_llm_with_tools", mock)
    return mock


def test_trivial_message_zero_tools(mock_llm, tmp_db):
    from truman.text.chat import chat
    result = chat("wssup", session_id="test_session")
    assert result["response"]
    assert result["tool_calls"] == []
    assert mock_llm.call_count == 1


def test_trivial_message_under_2s(mock_llm, tmp_db):
    from truman.text.chat import chat
    t0 = time.time()
    chat("wssup", session_id="test_session")
    assert (time.time() - t0) < 2.0


def test_save_runs_in_background(mock_llm, tmp_db, monkeypatch):
    save_calls = []
    def slow_save(turn):
        time.sleep(5)
        save_calls.append(turn)
    monkeypatch.setattr("truman.storage.save._persist_turn", slow_save)
    from truman.text.chat import chat
    t0 = time.time()
    chat("wssup", session_id="test_session")
    assert (time.time() - t0) < 1.0, "chat() blocked on save_memory"


def test_system_prompt_under_250_words(tmp_db):
    from truman.text.system_prompt import build_system_prompt
    prompt = build_system_prompt()
    assert len(prompt.split()) < 250, f"System prompt is {len(prompt.split())} words"
