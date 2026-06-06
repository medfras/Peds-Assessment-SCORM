#!/usr/bin/env python3
"""
Calibration metrics — Phase 7 (§20).

Queries completed sessions for tier resolution rates, ambiguous rates, override
rates, and score distributions.  Use this to identify items that need Tier 2
expansion, satisfaction rule revision, or instructor calibration review.

Usage:
    python3 scripts/calibration_metrics.py [options]

Options:
    --scenario SCENARIO_ID   Filter to one scenario (default: all)
    --level LEVEL            Filter to one provider level (default: all)
    --min-sessions N         Only include items seen in >= N sessions (default: 2)
    --format json|table      Output format (default: table)
    --top N                  Show top N missed/ambiguous items (default: 10)

Examples:
    python3 scripts/calibration_metrics.py --scenario peds_syncope_01
    python3 scripts/calibration_metrics.py --min-sessions 5 --format json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

# Allow importing app modules from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings


# ── Query ─────────────────────────────────────────────────────────────────────


async def collect_metrics(
    scenario_filter: str | None = None,
    level_filter: str | None = None,
) -> dict:
    """Return raw metrics aggregated across all matching sessions."""
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with async_session() as db:
            query = text("""
                SELECT
                    s.id            AS session_id,
                    s.scenario_id,
                    s.provider_level,
                    s.score,
                    s.assessment_score,
                    s.checklist_states,
                    s.score_snapshot,
                    s.ended_at,
                    (
                        SELECT COUNT(*)
                        FROM adjudications a
                        WHERE a.session_id = s.id
                          AND a.reason_type = 'instructor_override'
                    ) AS override_count
                FROM sessions s
                WHERE s.checklist_states IS NOT NULL
                  AND s.narrative_submitted = TRUE
                  AND s.score IS NOT NULL
                  :scenario_clause
                  :level_clause
                ORDER BY s.ended_at DESC
            """.replace(
                ":scenario_clause",
                f"AND s.scenario_id = :scenario_id" if scenario_filter else "",
            ).replace(
                ":level_clause",
                f"AND s.provider_level = :level" if level_filter else "",
            ))

            bind_params: dict = {}
            if scenario_filter:
                bind_params["scenario_id"] = scenario_filter
            if level_filter:
                bind_params["level"] = level_filter

            result = await db.execute(query, bind_params)
            rows = result.mappings().all()

    finally:
        await engine.dispose()

    # Aggregate per (scenario_id, provider_level)
    by_context: dict = defaultdict(lambda: {
        "sessions": 0,
        "sessions_with_overrides": 0,
        "scores": [],
        "items": defaultdict(lambda: {
            "seen": 0,
            "satisfied": 0,
            "tier1": 0,
            "tier2": 0,
            "tier3": 0,
            "ambiguous": 0,
            "not_satisfied": 0,
        }),
    })

    total_sessions = len(rows)

    for row in rows:
        key = (row["scenario_id"], row["provider_level"] or "unknown")
        m = by_context[key]
        m["sessions"] += 1
        if row["override_count"] and row["override_count"] > 0:
            m["sessions_with_overrides"] += 1
        if row["score"] is not None:
            m["scores"].append(int(row["score"]))

        states_blob = row["checklist_states"]
        if isinstance(states_blob, str):
            states_blob = json.loads(states_blob)
        if not states_blob:
            continue

        for item_state in (states_blob or {}).get("item_states", []):
            item_id = item_state.get("item_id", "unknown")
            state = item_state.get("state", "unknown")
            evs = item_state.get("evidence_references", [])

            if state == "not_applicable":
                continue

            m["items"][item_id]["seen"] += 1

            if state == "satisfied":
                m["items"][item_id]["satisfied"] += 1
                tier = evs[0].get("tier", 1) if evs else 1
                tier_key = f"tier{tier}" if tier in (1, 2, 3) else "tier1"
                m["items"][item_id][tier_key] += 1
            elif state == "ambiguous":
                m["items"][item_id]["ambiguous"] += 1
            elif state in ("not_satisfied", "contradicted", "unsupported_by_run"):
                m["items"][item_id]["not_satisfied"] += 1

    return {
        "total_sessions_scanned": total_sessions,
        "by_context": {
            f"{k[0]} / {k[1]}": v for k, v in by_context.items()
        },
    }


# ── Formatting ────────────────────────────────────────────────────────────────


def _format_table(metrics: dict, min_sessions: int, top_n: int) -> str:
    lines: list[str] = []
    lines.append(f"Sessions scanned: {metrics['total_sessions_scanned']}")
    lines.append("")

    for context_key, m in sorted(metrics["by_context"].items()):
        n = m["sessions"]
        scores = m["scores"]
        score_avg = round(sum(scores) / len(scores), 1) if scores else None
        override_pct = round(100 * m["sessions_with_overrides"] / max(n, 1), 1)

        lines.append(f"{'═' * 70}")
        lines.append(f"Context: {context_key}  ({n} sessions, avg score: {score_avg}, overrides: {override_pct}%)")
        lines.append(f"{'─' * 70}")

        # Sort items by miss rate desc (for calibration: most-missed first)
        item_rows = []
        for item_id, counts in m["items"].items():
            seen = counts["seen"]
            if seen < min_sessions:
                continue
            miss_rate = round(counts["not_satisfied"] / seen, 2)
            ambiguous_rate = round(counts["ambiguous"] / seen, 2)
            t1_rate = round(counts["tier1"] / max(counts["satisfied"], 1), 2)
            t2_rate = round(counts["tier2"] / max(counts["satisfied"], 1), 2)
            item_rows.append((item_id, seen, miss_rate, ambiguous_rate, t1_rate, t2_rate))

        # Most-missed items
        most_missed = sorted(item_rows, key=lambda r: -r[2])[:top_n]
        if most_missed:
            lines.append(f"  Most-missed items (miss_rate ≥ seen × {min_sessions}):")
            lines.append(f"  {'Item ID':<50} {'Seen':>5} {'Miss':>6} {'Ambig':>6} {'T1%':>5} {'T2%':>5}")
            for row in most_missed:
                lines.append(
                    f"  {row[0]:<50} {row[1]:>5} {row[2]:>6.0%} {row[3]:>6.0%} {row[4]:>5.0%} {row[5]:>5.0%}"
                )
        else:
            lines.append(f"  No items with >= {min_sessions} sessions.")

        # High-ambiguous items
        high_ambiguous = sorted(
            [r for r in item_rows if r[3] > 0], key=lambda r: -r[3]
        )[:top_n]
        if high_ambiguous:
            lines.append("")
            lines.append(f"  High-ambiguous items (candidates for Tier 2 expansion or Tier 3 rollout):")
            for row in high_ambiguous:
                lines.append(f"    {row[0]} — {row[3]:.0%} ambiguous ({row[1]} sessions)")

        lines.append("")

    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Calibration metrics for the adjudication engine (Phase 7 §20)"
    )
    parser.add_argument("--scenario", default=None, help="Filter to one scenario ID")
    parser.add_argument("--level", default=None, help="Filter to one provider level (EMT, AEMT, Paramedic)")
    parser.add_argument("--min-sessions", type=int, default=2, metavar="N",
                        help="Minimum session count to include an item (default: 2)")
    parser.add_argument("--format", choices=["json", "table"], default="table",
                        help="Output format (default: table)")
    parser.add_argument("--top", type=int, default=10, metavar="N",
                        help="Number of items to show per section (default: 10)")
    args = parser.parse_args()

    print("Querying sessions…", file=sys.stderr)
    metrics = await collect_metrics(
        scenario_filter=args.scenario,
        level_filter=args.level,
    )
    print(f"Done. {metrics['total_sessions_scanned']} sessions found.", file=sys.stderr)

    if args.format == "json":
        print(json.dumps(metrics, indent=2, default=str))
    else:
        print(_format_table(metrics, min_sessions=args.min_sessions, top_n=args.top))


if __name__ == "__main__":
    asyncio.run(_main())
