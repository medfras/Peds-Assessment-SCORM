#!/usr/bin/env python3
"""
Shadow corroboration log reviewer — C3 validation.

Reads structured JSON log lines from stdin (or a log file) and summarizes
ai.corroboration.shadow_comparison events. Use this to validate the
deterministic corroboration path before flipping use_deterministic_corroboration.

Usage:
    # From a log file (structlog JSON format, one JSON object per line):
    grep ai.corroboration.shadow_comparison app.log | python3 scripts/review_shadow_corroboration.py

    # Or pipe all log output:
    python3 scripts/review_shadow_corroboration.py < app.log

Flip criteria (see SCORING_IMPROVEMENT_PLAN.md C3):
  1. All 15 calibration fixtures pass (tests/test_corroboration.py)
  2. 20+ real/staging sessions reviewed here
  3. Deterministic false-positive rate is acceptably low (det flags > 0 when LLM flagged 0)
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import Any


def main() -> None:
    events: list[dict[str, Any]] = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("event") == "ai.corroboration.shadow_comparison":
            events.append(obj)

    if not events:
        print("No ai.corroboration.shadow_comparison events found.")
        print("Check that shadow_deterministic_corroboration=True in config and the app has run debriefs.")
        sys.exit(0)

    n = len(events)
    print(f"\n{'='*60}")
    print(f"Shadow Corroboration Review — {n} session(s)")
    print(f"{'='*60}\n")

    # Availability
    llm_available = sum(1 for e in events if e.get("llm_available"))
    det_available = sum(1 for e in events if e.get("det_available"))
    print(f"LLM prepass available:          {llm_available}/{n} ({llm_available/n*100:.0f}%)")
    print(f"Deterministic available:        {det_available}/{n} ({det_available/n*100:.0f}%)")

    # Flag counts
    llm_dmist_total = sum(e.get("llm_dmist_flags", 0) for e in events)
    det_dmist_total = sum(e.get("det_dmist_flags", 0) for e in events)
    llm_narr_total = sum(e.get("llm_narrative_flags", 0) for e in events)
    det_narr_total = sum(e.get("det_narrative_flags", 0) for e in events)
    ambiguous_total = sum(e.get("det_ambiguous_count", 0) for e in events)

    print(f"\nTotal flags across {n} sessions:")
    print(f"  DMIST   — LLM: {llm_dmist_total}   Det: {det_dmist_total}")
    print(f"  Narr    — LLM: {llm_narr_total}   Det: {det_narr_total}")
    print(f"  Det ambiguous (not counted as flags): {ambiguous_total}")

    # Agreement
    dmist_agree = sum(1 for e in events if e.get("dmist_count_match"))
    narr_agree = sum(1 for e in events if e.get("narrative_count_match"))
    print(f"\nFlag-count agreement:")
    print(f"  DMIST match:     {dmist_agree}/{n} ({dmist_agree/n*100:.0f}%)")
    print(f"  Narrative match: {narr_agree}/{n} ({narr_agree/n*100:.0f}%)")

    # False positive analysis (det flags when LLM found none — most concerning)
    det_only_dmist = [
        e for e in events
        if e.get("det_dmist_flags", 0) > 0 and e.get("llm_dmist_flags", 0) == 0
    ]
    det_only_narr = [
        e for e in events
        if e.get("det_narrative_flags", 0) > 0 and e.get("llm_narrative_flags", 0) == 0
    ]
    llm_only_dmist = [
        e for e in events
        if e.get("llm_dmist_flags", 0) > 0 and e.get("det_dmist_flags", 0) == 0
    ]
    llm_only_narr = [
        e for e in events
        if e.get("llm_narrative_flags", 0) > 0 and e.get("det_narrative_flags", 0) == 0
    ]

    print(f"\nDisagreement breakdown:")
    print(f"  Det flags DMIST, LLM found none (potential false positives): {len(det_only_dmist)}")
    print(f"  Det flags Narr,  LLM found none (potential false positives): {len(det_only_narr)}")
    print(f"  LLM flags DMIST, Det found none (potential LLM over-flagging): {len(llm_only_dmist)}")
    print(f"  LLM flags Narr,  Det found none (potential LLM over-flagging): {len(llm_only_narr)}")

    if det_only_dmist or det_only_narr:
        print("\n  ⚠ Sessions where Det flagged but LLM did not (review before flip):")
        for e in det_only_dmist + det_only_narr:
            sid = e.get("session_id", "?")
            scid = e.get("scenario_id", "?")
            print(f"    session={sid} scenario={scid} "
                  f"det_dmist={e.get('det_dmist_flags',0)} det_narr={e.get('det_narrative_flags',0)}")

    # Scoring method used
    method_counts: dict[str, int] = defaultdict(int)
    for e in events:
        method_counts[e.get("scoring_method", "unknown")] += 1
    print(f"\nScoring method used (active path — shadow only observes):")
    for method, count in sorted(method_counts.items()):
        print(f"  {method}: {count}")

    # Per-scenario breakdown
    scenario_counts: dict[str, int] = defaultdict(int)
    for e in events:
        scenario_counts[e.get("scenario_id", "unknown")] += 1
    print(f"\nSessions per scenario:")
    for scid, count in sorted(scenario_counts.items(), key=lambda x: -x[1]):
        print(f"  {scid}: {count}")

    print(f"\n{'='*60}")
    print(f"Flip readiness:")
    print(f"  Sessions reviewed: {n}/20 required")
    if n < 20:
        print(f"  ⏳ Need {20 - n} more sessions before flip is permitted.")
    else:
        fp_rate = (len(det_only_dmist) + len(det_only_narr)) / n
        print(f"  ✓ Session count met.")
        if fp_rate > 0.15:
            print(f"  ⚠ Det false-positive rate {fp_rate:.0%} is high — review before flipping.")
        else:
            print(f"  ✓ Det false-positive rate {fp_rate:.0%} is acceptable.")
        print(f"  Final decision: manual review required — see SCORING_IMPROVEMENT_PLAN.md C3.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
