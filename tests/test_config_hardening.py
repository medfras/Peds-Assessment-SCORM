"""Tests for Settings validators in app/config.py.

Settings instances are constructed with _env_file=None to avoid loading the
local .env. The module-level _IS_PROD flag is monkeypatched to simulate
production vs. development environments.
"""
import sys
import pytest
from pydantic import ValidationError

# Remove any stale monkeypatched app.config before importing the real module.
# Other test files (test_evidence_packet, test_gamification_regressions) patch
# sys.modules["app.config"] at module level. Targeted test runs can collect those
# files before this one, leaving a fake in sys.modules. Pop it so we always
# import the real Settings class regardless of collection order.
sys.modules.pop("app.config", None)

import app.config as _cfg_module
from app.config import Settings

# Minimal kwargs common to all Settings constructions
_BASE = dict(_env_file=None, groq_api_key="k")
_STRONG_SECRET = "a" * 32
_STRONG_DB = "postgresql+asyncpg://u:strongpassword@h:5432/db"


# ── app_secret_key validator ──────────────────────────────────────────────────

def test_secret_key_accepts_strong_key_in_production(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", True)
    s = Settings(**_BASE, app_secret_key=_STRONG_SECRET, database_url=_STRONG_DB)
    assert s.app_secret_key == _STRONG_SECRET


def test_secret_key_rejects_changeme_in_production(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", True)
    with pytest.raises(ValidationError, match="app_secret_key"):
        Settings(**_BASE, app_secret_key="changeme", database_url=_STRONG_DB)


def test_secret_key_rejects_short_key_in_production(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", True)
    with pytest.raises(ValidationError, match="too short"):
        Settings(**_BASE, app_secret_key="short", database_url=_STRONG_DB)


def test_secret_key_allows_changeme_in_dev(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", False)
    s = Settings(**_BASE, app_secret_key="changeme")
    assert s.app_secret_key == "changeme"


def test_secret_key_requires_minimum_32_chars_in_production(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", True)
    # Exactly 32 chars should pass
    s = Settings(**_BASE, app_secret_key="a" * 32, database_url=_STRONG_DB)
    assert len(s.app_secret_key) == 32
    # 31 chars should fail
    with pytest.raises(ValidationError, match="too short"):
        Settings(**_BASE, app_secret_key="a" * 31, database_url=_STRONG_DB)


# ── database_url validator ────────────────────────────────────────────────────

def test_database_url_rejects_changeme_password_in_production(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", True)
    with pytest.raises(ValidationError, match="changeme"):
        Settings(
            **_BASE,
            app_secret_key=_STRONG_SECRET,
            database_url="postgresql+asyncpg://ems_user:changeme@postgres:5432/ems_sim",
        )


def test_database_url_accepts_strong_password_in_production(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", True)
    s = Settings(**_BASE, app_secret_key=_STRONG_SECRET, database_url=_STRONG_DB)
    assert "strongpassword" in s.database_url


def test_database_url_allows_changeme_in_dev(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", False)
    s = Settings(**_BASE, database_url="postgresql+asyncpg://u:changeme@h:5432/db")
    assert "changeme" in s.database_url


# ── superuser credentials cross-validator ────────────────────────────────────

def test_superuser_requires_password_when_username_set(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", False)
    with pytest.raises(ValidationError, match="superuser_password is empty"):
        Settings(**_BASE, superuser_username="admin", superuser_password="")


def test_superuser_accepts_both_fields_set(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", False)
    s = Settings(**_BASE, superuser_username="admin", superuser_password="secret")
    assert s.superuser_username == "admin"


def test_superuser_accepts_neither_field_set(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", False)
    s = Settings(**_BASE, superuser_username="", superuser_password="")
    assert s.superuser_username == ""


def test_superuser_password_changeme_blocked_in_production(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", True)
    with pytest.raises(ValidationError, match="superuser_password"):
        Settings(
            **_BASE,
            app_secret_key=_STRONG_SECRET,
            database_url=_STRONG_DB,
            superuser_username="admin",
            superuser_password="changeme",
        )


def test_superuser_empty_password_blocked_in_production_when_username_set(monkeypatch):
    monkeypatch.setattr(_cfg_module, "_IS_PROD", True)
    with pytest.raises(ValidationError):
        Settings(
            **_BASE,
            app_secret_key=_STRONG_SECRET,
            database_url=_STRONG_DB,
            superuser_username="admin",
            superuser_password="",
        )
