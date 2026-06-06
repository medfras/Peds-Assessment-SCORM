import os
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV = os.getenv("ENV", "development")
_IS_PROD = _ENV == "production"


class Settings(BaseSettings):
    groq_api_key: str
    app_secret_key: str = "changeme"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60           # 60-minute access token; refresh via /api/token/refresh
    refresh_token_expire_days: int = 7     # 7-day httpOnly refresh token (S-07)
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    base_url: str = "http://localhost:8000"
    database_url: str = "postgresql+asyncpg://ems_user:changeme@postgres:5432/ems_sim"
    groq_model: str = "openai/gpt-oss-120b"           # sim chat + medical control
    groq_debrief_model: str = "openai/gpt-oss-120b"  # debrief scoring (main coaching call)
    groq_lexi_model: str = "openai/gpt-oss-20b"      # fast Lexi companion + in-scenario hints
    groq_practice_coach_model: str = "openai/gpt-oss-120b"  # richer post-call/dashboard coaching
    groq_extraction_model: str = "openai/gpt-oss-20b"  # Phase 6 focused doc extraction + prof review
    groq_tier3_model: str = "openai/gpt-oss-120b"       # Phase 6 Tier 3 AI adjudication (logprob required)
    tts_provider: str = "browser"                        # "browser" | "google" | "openai"
    tts_cache_dir: str = "/tmp/tts_cache"
    gemini_tts_model: str = "gemini-2.5-flash-tts"
    openai_api_key: str = ""
    openai_tts_model: str = "tts-1"
    openai_tts_format: str = "mp3"
    openai_tts_speed: float = 1.12
    # CORS — JSON array in .env: ALLOWED_ORIGINS=["http://localhost:8000","https://app.example.com"]
    allowed_origins: List[str] = ["http://localhost:8000"]
    # Sentry DSN — leave empty to disable error tracking
    sentry_dsn: str = ""

    default_provider_level: str = "EMT"
    default_mca: str = "mi_base"

    # Global superuser — auto-created on startup when both are set
    superuser_username: str = ""
    superuser_password: str = ""

    # Optional default agency seed — auto-created on startup when all three are set
    seed_agency_name: str = ""
    seed_agency_join_code: str = ""
    seed_agency_file: str = ""

    # Database connection pool — tune via .env without code changes
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # DB-level timeouts — applied per-connection so they survive pool recycling (DB-05)
    db_lock_timeout: str = "10s"
    db_statement_timeout: str = "60s"

    # Logging — "json" for production, "console" for local dev
    log_level: str = "INFO"
    log_format: str = "json"

    # Auth rate limits — IP-based for unauthenticated callers
    rate_limit_auth: int = 10          # login + registration; IP-keyed to prevent brute force

    # Session lifecycle rate limits
    rate_limit_session_start: int = 10 # POST /api/sessions — session creation spam guard
    rate_limit_session_write: int = 60 # interventions and findings during active simulation

    # Per-user AI rate limits (requests per minute)
    rate_limit_chat: int = 20          # reduced from 30 — 70B model is ~5x cost
    rate_limit_med_control: int = 8
    rate_limit_lexi: int = 5
    rate_limit_practice_coach: int = 3
    practice_coach_daily_turn_cap: int = 10
    practice_coach_session_turn_cap: int = 5
    rate_limit_debrief: int = 3        # one per scenario; 3/min prevents retry abuse
    rate_limit_lexi_group_create: int = 5
    rate_limit_lexi_group_join: int = 10
    rate_limit_lexi_group_start: int = 5
    rate_limit_lexi_group_answer: int = 30
    rate_limit_lexi_group_feedback_ready: int = 30
    rate_limit_lexi_group_next_round: int = 10
    rate_limit_team_presence: int = 30
    rate_limit_team_invite: int = 10
    rate_limit_team_accept: int = 10
    rate_limit_team_start: int = 10
    team_challenge_enabled: bool = False

    # ── Corroboration shadow mode (C3) ─────────────────────────────────────────
    # shadow_deterministic_corroboration: run deterministic check alongside LLM
    # prepass and log comparison counts. Observe-only — LLM result used for scoring.
    # Flip use_deterministic_corroboration only after shadow validation criteria are met
    # (see docs/SCORING_IMPROVEMENT_PLAN.md C3 for rollout requirements).
    shadow_deterministic_corroboration: bool = True
    use_deterministic_corroboration: bool = False

    # ── NASEMSO call-type rubric (Group F) ─────────────────────────────────────
    # shadow_call_type_rubric: compose and log call-type rubric items alongside the
    # effective checklist. Observe-only — existing checklist used for scoring.
    # Already active as of F2a (ShadowCompositionReport in checklist_states).
    #
    # use_call_type_rubric: activate scored composition. Call-type rubric items
    # are merged into the effective checklist and contribute to scores.
    # Flip only after shadow runs show clean diffs for all three call types
    # (no unexpected conflicts, suspected_duplicates eyeballed, level_excluded correct).
    # See docs/SCORING_IMPROVEMENT_PLAN.md Group F2b for activation checklist.
    shadow_call_type_rubric: bool = True   # F2a shadow always on
    use_call_type_rubric: bool = True      # F2b scored composition — active 2026-05-14

    # ── SCORM integration ──────────────────────────────────────────────────────
    # scorm_integration_key: non-secret module identifier validated on POST /api/scorm/auth.
    # Not a secret — any value in SCORM JS is visible to the learner. Security relies on
    # CORS/origin checks, tenant binding, rate limits, and short token lifetimes.
    scorm_integration_key: str = "pfd_station1_v1"
    # scorm_agency_file: agency_file stem of the agency used for SCORM provisioning.
    scorm_agency_file: str = "pfd"
    # scorm_module_id: default module identifier used when provisioning SCORM attempts.
    scorm_module_id: str = "pfd_station1"

    @field_validator("app_secret_key")
    @classmethod
    def secret_key_must_be_set(cls, v: str) -> str:
        if _IS_PROD:
            if not v or v == "changeme":
                raise ValueError(
                    "app_secret_key must be set to a strong random value in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            if len(v) < 32:
                raise ValueError(
                    "app_secret_key is too short for production (minimum 32 characters). "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
        elif _ENV in ("staging", "preview"):
            if not v or v == "changeme":
                raise ValueError(
                    f"app_secret_key must be changed from the default in {_ENV} environments. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
        return v

    @field_validator("database_url")
    @classmethod
    def database_url_must_not_use_default_password(cls, v: str) -> str:
        if _IS_PROD and "changeme" in v:
            raise ValueError(
                "database_url contains the default 'changeme' password. "
                "Set a strong database password before deploying to production."
            )
        return v

    @model_validator(mode="after")
    def superuser_credentials_consistent(self) -> "Settings":
        if self.superuser_username and not self.superuser_password:
            raise ValueError(
                "superuser_username is set but superuser_password is empty. "
                "Both must be provided to create the superuser account."
            )
        if _IS_PROD and self.superuser_username and self.superuser_password in ("", "changeme"):
            raise ValueError(
                "superuser_password must not be empty or the default 'changeme' value in production."
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",  # docker-compose .env files include POSTGRES_USER etc. that are not Settings fields
    )


settings = Settings()
