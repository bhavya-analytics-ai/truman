"""run_verify.py — End-to-end verification of smart routing.

Run from project root:
  python tests/verify/run_verify.py

Outputs a markdown report to docs/superpowers/verify/<date>-phase1-verify.md
"""
import json
import os
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from truman.storage import db
from truman.brain.tier_router import classify_tier
from truman.brain.tool_retrieval import retrieve, init_tool_embeddings, _TOOL_VECTORS
from truman.tools.all_tools import TOOLS


def main():
    db.init()

    # Only embed if not already populated (skip if NVIDIA_API_KEY not set)
    if not _TOOL_VECTORS:
        try:
            init_tool_embeddings(TOOLS, [])
        except Exception as e:
            print(f"[verify] embedding skipped (no API key?): {e}")

    cases = json.load(open("tests/verify/tool_selection.json"))

    # ── Test Set 1: Tier + Tool Selection Accuracy ────────────────────────────
    correct = 0
    failures = []
    for case in cases:
        d = classify_tier(case["msg"])
        tier = d["tier"]
        tier_ok = tier == case["tier"]

        if tier == "trivial":
            tools = retrieve(case["msg"], tier, d["pool"])
            tool_ok = (tools == [])
        else:
            tools = retrieve(case["msg"], tier, d["pool"])
            names = [t.name for t in tools]
            expected = case["expected_in_topK"]
            if expected:
                tool_ok = any(e in names for e in expected)
            else:
                tool_ok = True

        if tier_ok and tool_ok:
            correct += 1
        else:
            failures.append({
                "msg":            case["msg"],
                "expected_tier":  case["tier"],
                "got_tier":       tier,
                "expected_tools": case["expected_in_topK"],
                "got_tools":      [t.name for t in tools] if tier != "trivial" else [],
                "tier_ok":        tier_ok,
                "tool_ok":        tool_ok,
            })

    accuracy = correct / len(cases) * 100

    # ── Test Set 2: Latency Benchmarks (3 runs each, take median) ────────────
    from truman.brain.loop import get_graph
    g = get_graph()
    latencies = {"trivial": [], "normal": [], "complex": []}
    bench = {
        "trivial": ["yo", "thanks"],
        "normal":  ["what's on my desktop", "remind me to ship tomorrow"],
        "complex": ["look up risk_gate in my codebase", "find all .py files modified last week"],
    }
    print("\n[verify] running latency benchmarks (6 messages × 2 = ~12 LLM calls, takes a few min)...")
    for tier, msgs in bench.items():
        for msg in msgs:
            for _ in range(2):
                t0 = time.time()
                g.invoke({"user_input": msg, "session_id": f"verify_{tier}", "attach_ids": []})
                lat = time.time() - t0
                latencies[tier].append(lat)
                print(f"  [{tier}] {msg[:30]!r}: {lat:.1f}s")

    medians = {tier: sorted(v)[len(v) // 2] for tier, v in latencies.items()}
    targets = {"trivial": 3.0, "normal": 10.0, "complex": 18.0}

    # ── Report ────────────────────────────────────────────────────────────────
    out_dir = "docs/superpowers/verify"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/{date.today()}-phase1-verify.md"

    with open(out_path, "w") as f:
        f.write(f"# Phase 1 Verification Report — {date.today()}\n\n")

        f.write("## Tool Selection + Tier Accuracy\n")
        f.write(f"- **{correct}/{len(cases)} = {accuracy:.1f}%**\n")
        f.write(f"- PASS criteria: ≥93%\n")
        f.write(f"- Status: {'✅ PASS' if accuracy >= 93 else '❌ FAIL'}\n\n")
        if failures:
            f.write("### Failures\n```json\n")
            f.write(json.dumps(failures, indent=2))
            f.write("\n```\n\n")

        f.write("## Latency Benchmarks (median)\n")
        f.write("| Tier | Median | Target | Status |\n|---|---|---|---|\n")
        for tier, med in medians.items():
            ok = med < targets[tier]
            f.write(f"| {tier} | {med:.2f}s | <{targets[tier]}s | {'✅' if ok else '❌'} |\n")

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"Report: {out_path}")
    print(f"Accuracy: {accuracy:.1f}% ({'PASS' if accuracy >= 93 else 'FAIL'})")
    for tier, med in medians.items():
        status = "✅" if med < targets[tier] else "❌"
        print(f"  {tier} median: {med:.2f}s (target <{targets[tier]}s) {status}")
    print(f"{'='*50}\n")

    all_lat_ok = all(medians[t] < targets[t] for t in targets)
    return 0 if (accuracy >= 93 and all_lat_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
