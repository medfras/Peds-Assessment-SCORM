"""Pytest configuration — shared fixtures and early module stubs.

The app.config stub must be installed before any app module is imported.
conftest.py is processed by pytest before any test file is collected, so this
runs first.  Individual test files that also call sys.modules["app.config"] = ...
become effectively no-ops because the module is already cached and the app imports
have already resolved.
"""

import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── Complete app.config stub ──────────────────────────────────────────────────
# Explicit values for fields used at import time by ai_client, database, etc.
# Unknown attributes fall back to "" so new settings added to config.py never
# break the test suite — whichever module reads them at import time gets a
# falsy default.

class _PermissiveSettings:
    """Returns "" for any attribute not explicitly defined below."""

    groq_api_key = "test"
    app_secret_key = "test-secret"
    jwt_algorithm = "HS256"
    jwt_expire_minutes = 60
    refresh_token_expire_days = 7
    app_host = "0.0.0.0"
    app_port = 8000
    base_url = "http://localhost:8000"
    database_url = "postgresql+asyncpg://test:test@localhost:5432/test"
    groq_model = "test-model"
    groq_debrief_model = "test-model"
    groq_lexi_model = "test-lexi-model"
    groq_practice_coach_model = "test-model"
    groq_extraction_model = "test-model"
    allowed_origins = ["http://localhost:8000"]
    sentry_dsn = ""
    default_provider_level = "EMT"
    default_mca = "mi_wmrmcc_kent"
    superuser_username = ""
    superuser_password = ""
    seed_agency_name = ""
    seed_agency_join_code = ""
    seed_agency_file = ""
    db_pool_size = 1
    db_max_overflow = 1
    db_lock_timeout = "10s"
    db_statement_timeout = "60s"
    log_level = "INFO"
    log_format = "json"
    rate_limit_auth = 10
    rate_limit_session_start = 10
    rate_limit_session_write = 60
    rate_limit_chat = 30
    rate_limit_med_control = 10
    rate_limit_lexi = 5
    rate_limit_practice_coach = 3
    practice_coach_daily_turn_cap = 10
    practice_coach_session_turn_cap = 5
    rate_limit_debrief = 3
    rate_limit_lexi_group_create = 5
    rate_limit_lexi_group_join = 10
    rate_limit_lexi_group_start = 5
    rate_limit_lexi_group_answer = 30
    rate_limit_lexi_group_feedback_ready = 30
    rate_limit_lexi_group_next_round = 10
    rate_limit_team_presence = 30
    rate_limit_team_invite = 10
    rate_limit_team_accept = 10
    rate_limit_team_start = 10
    team_challenge_enabled = False
    shadow_deterministic_corroboration = False
    use_deterministic_corroboration = False

    def __getattr__(self, name: str):
        return ""


_fake_config = types.ModuleType("app.config")
_fake_config._IS_PROD = False
_fake_config.settings = _PermissiveSettings()

sys.modules["app.config"] = _fake_config

# Stub sentry_sdk — not installed in the CI/test environment.
# Only sentry_sdk.init() is called in main.py (guarded by settings.sentry_dsn which
# is empty in tests), so a minimal no-op stub is sufficient.
if "sentry_sdk" not in sys.modules:
    _sentry_stub = types.ModuleType("sentry_sdk")
    _sentry_stub.init = lambda *args, **kwargs: None
    sys.modules["sentry_sdk"] = _sentry_stub

# Import app.ai_client now so the full import chain (models, database, protocol_engine)
# is cached in sys.modules.  Individual test files that later override
# sys.modules["app.config"] with their own (possibly stale) stub don't re-trigger
# those imports — Python's import cache short-circuits them.
import app.ai_client  # noqa: E402, F401
