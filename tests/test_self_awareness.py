from unittest.mock import MagicMock
from truman.brain import self_awareness


def _state(routing_tier="normal", retrieved=None, mood="neutral"):
    return {
        "user_input":      "hi there",
        "routing":         {"tier": routing_tier, "pool": "general", "runtime": "local",
                            "hints": [], "skip_llm_eval": False},
        "retrieved_tools": retrieved or [],
        "mood":            mood,
    }


def test_build_self_state_returns_required_keys(tmp_db, fake_local):
    s = self_awareness.build_self_state(_state())
    for key in ["identity", "runtime", "environment", "tool_inventory",
                "capabilities", "current_state", "operating_mode", "persona_anchor"]:
        assert key in s


def test_build_self_state_runtime_local(tmp_db, fake_local):
    s = self_awareness.build_self_state(_state())
    assert s["runtime"]["location"] == "local"


def test_build_self_state_runtime_railway(tmp_db, fake_railway):
    s = self_awareness.build_self_state(_state())
    assert s["runtime"]["location"] == "railway"


def test_capabilities_local_can_access_mac(tmp_db, fake_local):
    caps = self_awareness.derive_capabilities(
        {"location": "local", "mac_bridge": "offline"}, []
    )
    assert any("mac" in c.lower() for c in caps["can"])


def test_capabilities_railway_cannot_access_mac_directly(tmp_db, fake_railway):
    caps = self_awareness.derive_capabilities(
        {"location": "railway", "mac_bridge": "offline"}, []
    )
    assert any("mac" in c.lower() for c in caps["cant"])


def test_capabilities_railway_with_bridge_can_forward(tmp_db, fake_railway):
    caps = self_awareness.derive_capabilities(
        {"location": "railway", "mac_bridge": "connected"}, []
    )
    assert any("bridge" in c.lower() or "forward" in c.lower() for c in caps["can"])


def test_render_system_prompt_contains_sections(tmp_db, fake_local):
    s = self_awareness.build_self_state(_state())
    prompt = self_awareness.render_system_prompt(s, "memory block here")
    for section in ["WHO I AM", "WHERE I AM RUNNING", "WHAT I CAN ACCESS",
                    "WHAT I KNOW ABOUT OM", "OPERATING MODE", "HOW TO RESPOND"]:
        assert section in prompt
    assert "memory block here" in prompt


def test_tier_tone_hint_trivial_says_short():
    hint = self_awareness.tier_tone_hint("trivial")
    assert "short" in hint.lower() or "brief" in hint.lower()


def test_tier_tone_hint_complex_allows_thinking():
    hint = self_awareness.tier_tone_hint("complex")
    assert "think" in hint.lower() or "reason" in hint.lower()
