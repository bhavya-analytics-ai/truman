from truman.brain import nodes


def test_risk_gate_safe_tool_passes(tmp_db):
    state = {
        "user_input":     "hi",
        "llm_tool_calls": [{"name": "web_search", "args": {"query": "x"}, "id": "1"}],
        "node_errors":    {},
    }
    out = nodes.risk_gate_node(state)
    assert out.get("awaiting_confirm") is not True


def test_risk_gate_risky_tool_pauses(tmp_db):
    state = {
        "user_input":     "write a file",
        "llm_tool_calls": [{"name": "write_mac_file",
                            "args": {"path": "/tmp/x", "content": "hi"}, "id": "1"}],
        "node_errors":    {},
    }
    out = nodes.risk_gate_node(state)
    assert out.get("awaiting_confirm") is True
    assert "confirm" in (out.get("response") or "").lower()


def test_risk_gate_no_tool_calls_passes(tmp_db):
    state = {"user_input": "yo", "llm_tool_calls": [], "node_errors": {}}
    out = nodes.risk_gate_node(state)
    assert out.get("awaiting_confirm") is not True
