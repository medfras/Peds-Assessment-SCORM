"""Shared helpers for mini-game result contracts."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any


def sanitize_minigame_hint_count(value: int | None) -> int:
    """Normalize learner-requested hint counts for analytics storage."""

    return max(0, min(200, int(value or 0)))


_PHASE13_GAME_IDS = ("vitals_trend_spotter", "peds_gcs_calculator", "dmist_builder")


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def summarize_phase13_readiness(
    rows: list[Any],
    *,
    now: datetime | None = None,
    window_days: int = 30,
) -> dict[str, Any]:
    """Summarize learner-scoped mini-game evidence for Phase 13 readiness.

    This helper intentionally does not decide that Phase 13 V2 work is ready.
    It only packages deterministic run data so the readiness log can be filled
    without hand-counting result rows.
    """

    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=window_days)
    by_game: dict[str, list[Any]] = {game_id: [] for game_id in _PHASE13_GAME_IDS}
    for row in rows:
        game_id = _row_value(row, "game_id")
        if game_id in by_game:
            by_game[game_id].append(row)

    games: dict[str, dict[str, Any]] = {}
    for game_id, game_rows in by_game.items():
        sorted_rows = sorted(
            game_rows,
            key=lambda row: _row_value(row, "created_at") or datetime.min,
        )
        window_rows = [
            row for row in sorted_rows
            if (_row_value(row, "created_at") or datetime.min) >= cutoff
        ]
        scores = [
            int(_row_value(row, "score", 0) or 0)
            for row in window_rows
        ]
        tag_counts: Counter[str] = Counter()
        for row in window_rows:
            tags = _row_value(row, "mistake_tags") or []
            if isinstance(tags, list):
                tag_counts.update(tag for tag in tags if isinstance(tag, str) and tag)

        first_run_at = _row_value(sorted_rows[0], "created_at") if sorted_rows else None
        latest_run_at = _row_value(sorted_rows[-1], "created_at") if sorted_rows else None
        days_observed = (now - first_run_at).days if first_run_at else 0

        entry = {
            "runs_total": len(sorted_rows),
            "runs_30d": len(window_rows),
            "avg_score_30d": round(sum(scores) / len(scores)) if scores else None,
            "first_run_at": first_run_at.isoformat() if first_run_at else None,
            "latest_run_at": latest_run_at.isoformat() if latest_run_at else None,
            "days_observed": max(0, days_observed),
            "has_30_days_data": bool(first_run_at and first_run_at <= cutoff and window_rows),
            "mistake_tag_counts_30d": dict(sorted(tag_counts.items())),
        }

        if game_id == "dmist_builder":
            entry["handoff_omission_count_30d"] = sum(
                count for tag, count in tag_counts.items()
                if tag == "handoff_omission" or tag.startswith("handoff_omission")
            )
            entry["handoff_sequence_count_30d"] = sum(
                count for tag, count in tag_counts.items()
                if tag == "handoff_sequence" or tag.startswith("handoff_sequence")
            )
            entry["sequence_scoring_data_gate_ready"] = bool(entry["has_30_days_data"])

        games[game_id] = entry

    return {
        "window_days": window_days,
        "generated_at": now.isoformat(),
        "games": games,
    }
