from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta

from app.minigame_results import sanitize_minigame_hint_count, summarize_phase13_readiness
from app.models import MinigameResult


def test_minigame_result_request_declares_optional_hint_count():
    source = Path("app/main.py").read_text()

    assert "hint_count: Optional[int] = None" in source


def test_peds_gateway_progress_is_not_frontend_authoritative():
    source = Path("app/main.py").read_text()

    assert "/api/me/peds/gateway-complete" not in source
    assert "class PedsGatewayRequest" not in source
    assert 'body.game_id == "rule_of_nines"' in source
    assert 'PedsMapProgress(user_id=ctx.user_id, map_id="pt1")' in source


def test_minigame_hint_count_sanitization_defaults_and_clamps():
    assert sanitize_minigame_hint_count(None) == 0
    assert sanitize_minigame_hint_count(-4) == 0
    assert sanitize_minigame_hint_count(3) == 3
    assert sanitize_minigame_hint_count(999) == 200


def test_minigame_result_model_has_hint_count_column():
    assert "hint_count" in MinigameResult.__table__.columns


def test_minigame_result_model_has_sequence_data_column():
    assert "sequence_data" in MinigameResult.__table__.columns


def test_generic_minigames_use_station_drill_xp_caps():
    source = Path("app/main.py").read_text()

    assert "_MINIGAME_PER_RUN_MAX_XP = 30" in source
    assert "_MINIGAME_DAILY_CAP_XP = 90" in source


def test_minigame_results_migration_adds_hint_count_idempotently():
    source = Path("app/database.py").read_text()

    assert "ADD COLUMN IF NOT EXISTS hint_count INTEGER NOT NULL DEFAULT 0" in source


def test_minigame_results_migration_adds_sequence_data_idempotently():
    source = Path("app/database.py").read_text()

    assert "ADD COLUMN IF NOT EXISTS sequence_data JSONB" in source


def test_phase13_readiness_summary_counts_dmist_window_and_tags():
    now = datetime(2026, 5, 6, 12, 0, 0)
    rows = [
        SimpleNamespace(
            game_id="dmist_builder",
            score=80,
            mistake_tags=["handoff_omission", "handoff_omission_priority"],
            created_at=now - timedelta(days=31),
        ),
        SimpleNamespace(
            game_id="dmist_builder",
            score=90,
            mistake_tags=["handoff_omission"],
            created_at=now - timedelta(days=2),
        ),
        SimpleNamespace(
            game_id="peds_gcs_calculator",
            score=70,
            mistake_tags=["motor_localization"],
            created_at=now - timedelta(days=1),
        ),
    ]

    summary = summarize_phase13_readiness(rows, now=now)
    dmist = summary["games"]["dmist_builder"]

    assert dmist["runs_total"] == 2
    assert dmist["runs_30d"] == 1
    assert dmist["avg_score_30d"] == 90
    assert dmist["has_30_days_data"] is True
    assert dmist["sequence_scoring_data_gate_ready"] is True
    assert dmist["mistake_tag_counts_30d"] == {"handoff_omission": 1}
    assert dmist["handoff_omission_count_30d"] == 1
    assert dmist["handoff_sequence_count_30d"] == 0
