"""Tests for AiProviderError classification and streaming route error handling."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.ai_client import AiProviderError, _classify_provider_error, _is_retryable_groq_error


class _FakeRateLimitError(Exception):
    status_code = 429


class _FakeTimeoutError(Exception):
    __name__ = "APITimeoutError"

    def __init__(self):
        super().__init__("timeout")
        self.__class__.__name__ = "APITimeoutError"


class _FakeServerError(Exception):
    status_code = 503


class _FakeConnectionError(Exception):
    def __init__(self):
        super().__init__("connection failed")
        self.__class__.__name__ = "APIConnectionError"


# ── _classify_provider_error ──────────────────────────────────────────────────

def test_classify_rate_limit_by_status():
    exc = _FakeRateLimitError()
    assert _classify_provider_error(exc) == "rate_limit"


def test_classify_rate_limit_by_class_name():
    class RateLimitError(Exception):
        pass
    assert _classify_provider_error(RateLimitError()) == "rate_limit"


def test_classify_asyncio_timeout():
    assert _classify_provider_error(asyncio.TimeoutError()) == "timeout"


def test_classify_stdlib_timeout():
    assert _classify_provider_error(TimeoutError()) == "timeout"


def test_classify_api_timeout_by_name():
    exc = _FakeConnectionError()
    assert _classify_provider_error(exc) == "timeout"


def test_classify_server_error():
    exc = _FakeServerError()
    assert _classify_provider_error(exc) == "unavailable"


# ── AiProviderError ───────────────────────────────────────────────────────────

def test_provider_error_stores_kind():
    err = AiProviderError("rate_limit")
    assert err.kind == "rate_limit"


def test_provider_error_is_exception():
    assert isinstance(AiProviderError("timeout"), Exception)


def test_provider_error_str_contains_kind():
    assert "unavailable" in str(AiProviderError("unavailable"))


# ── _is_retryable_groq_error ──────────────────────────────────────────────────

def test_rate_limit_is_retryable():
    assert _is_retryable_groq_error(_FakeRateLimitError())


def test_server_error_is_retryable():
    assert _is_retryable_groq_error(_FakeServerError())


def test_asyncio_timeout_is_retryable():
    assert _is_retryable_groq_error(asyncio.TimeoutError())


def test_value_error_is_not_retryable():
    assert not _is_retryable_groq_error(ValueError("bad prompt"))


def test_key_error_is_not_retryable():
    assert not _is_retryable_groq_error(KeyError("missing"))
