from truman.brain import tier_router


def test_classify_trivial_greeting():
    d = tier_router.classify_tier("yo")
    assert d["tier"] == "trivial"


def test_classify_trivial_yoo_repeated_chars():
    assert tier_router.classify_tier("yoo")["tier"] == "trivial"
    assert tier_router.classify_tier("yooo")["tier"] == "trivial"
    assert tier_router.classify_tier("heyyy")["tier"] == "trivial"


def test_classify_trivial_greeting_with_whats_up():
    assert tier_router.classify_tier("yo what's up")["tier"] == "trivial"
    assert tier_router.classify_tier("hey sup")["tier"] == "trivial"
    assert tier_router.classify_tier("yo. what's up?")["tier"] == "trivial"


def test_classify_trivial_thanks():
    d = tier_router.classify_tier("thanks man")
    assert d["tier"] == "trivial"


def test_classify_trivial_reactions():
    assert tier_router.classify_tier("lmao")["tier"] == "trivial"
    assert tier_router.classify_tier("facts")["tier"] == "trivial"
    assert tier_router.classify_tier("bet")["tier"] == "trivial"
    assert tier_router.classify_tier("fr fr")["tier"] == "trivial"


def test_classify_trivial_simple_math():
    d = tier_router.classify_tier("what's 2+2")
    assert d["tier"] == "trivial"


def test_classify_complex_code_lookup():
    d = tier_router.classify_tier("look up risk_gate in my codebase")
    assert d["tier"] == "complex"
    assert d["pool"] == "coding"


def test_classify_complex_multistep():
    d = tier_router.classify_tier("first read this file, then summarize it")
    assert d["tier"] == "complex"


def test_classify_normal_chat():
    d = tier_router.classify_tier("what's the weather in NYC")
    assert d["tier"] == "normal"


def test_classify_image_routes_vision_complex():
    d = tier_router.classify_tier("what's in this", image_count=1)
    assert d["pool"] == "vision"
    assert d["tier"] == "complex"


def test_routing_decision_has_required_fields():
    d = tier_router.classify_tier("hi")
    for k in ["tier", "pool", "runtime", "hints", "skip_llm_eval"]:
        assert k in d


def test_trivial_skips_llm_eval():
    d = tier_router.classify_tier("yo")
    assert d["skip_llm_eval"] is True


def test_complex_does_not_skip_llm_eval():
    d = tier_router.classify_tier("look up risk_gate")
    assert d["skip_llm_eval"] is False
