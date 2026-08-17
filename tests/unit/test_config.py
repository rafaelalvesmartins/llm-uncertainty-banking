# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for lub.config.LubConfig.

Hermetic. Uses monkeypatch substitutes (manual env manipulation) so the
plain runner can execute these without pytest fixtures.

Covers:
  - default values when no env vars set
  - LUB_-prefixed env vars override defaults
  - cache_dir defaults to a sensible path under the user's home
  - ensure_cache_dir creates a missing directory
  - request_timeout_s and retry_attempts respect type coercion
  - non-LUB-prefixed env vars are ignored
"""

from __future__ import annotations

import os
from pathlib import Path

from lub.config import LubConfig


def _clear_lub_env() -> dict[str, str | None]:
    """Snapshot and clear all LUB_-prefixed env vars; return a restore map."""
    saved = {}
    for k in list(os.environ.keys()):
        if k.startswith("LUB_"):
            saved[k] = os.environ.pop(k)
    return saved


def _restore_env(saved: dict[str, str | None]) -> None:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


def test_defaults_when_no_env_set() -> None:
    saved = _clear_lub_env()
    try:
        cfg = LubConfig()
        assert cfg.log_level == "INFO"
        assert cfg.openai_api_key is None
        assert cfg.anthropic_api_key is None
        assert cfg.request_timeout_s == 60.0
        assert cfg.retry_attempts == 3
    finally:
        _restore_env(saved)


def test_default_cache_dir_is_under_home() -> None:
    saved = _clear_lub_env()
    try:
        cfg = LubConfig()
        # default factory returns ~/.cache/lub; the actual path will start with
        # the user's home.
        assert ".cache" in str(cfg.cache_dir)
        assert "lub" in str(cfg.cache_dir)
    finally:
        _restore_env(saved)


# ---------------------------------------------------------------------------
# Env var loading (LUB_ prefix)
# ---------------------------------------------------------------------------


def test_log_level_from_env() -> None:
    saved = _clear_lub_env()
    try:
        os.environ["LUB_LOG_LEVEL"] = "DEBUG"
        cfg = LubConfig()
        assert cfg.log_level == "DEBUG"
    finally:
        _restore_env(saved)


def test_openai_api_key_from_env() -> None:
    saved = _clear_lub_env()
    try:
        os.environ["LUB_OPENAI_API_KEY"] = "sk-test-1234"
        cfg = LubConfig()
        assert cfg.openai_api_key == "sk-test-1234"
    finally:
        _restore_env(saved)


def test_anthropic_api_key_from_env() -> None:
    saved = _clear_lub_env()
    try:
        os.environ["LUB_ANTHROPIC_API_KEY"] = "sk-ant-test"
        cfg = LubConfig()
        assert cfg.anthropic_api_key == "sk-ant-test"
    finally:
        _restore_env(saved)


def test_request_timeout_coerced_from_env_string() -> None:
    saved = _clear_lub_env()
    try:
        os.environ["LUB_REQUEST_TIMEOUT_S"] = "120.5"
        cfg = LubConfig()
        assert isinstance(cfg.request_timeout_s, float)
        assert cfg.request_timeout_s == 120.5
    finally:
        _restore_env(saved)


def test_retry_attempts_coerced_from_env_string() -> None:
    saved = _clear_lub_env()
    try:
        os.environ["LUB_RETRY_ATTEMPTS"] = "7"
        cfg = LubConfig()
        assert isinstance(cfg.retry_attempts, int)
        assert cfg.retry_attempts == 7
    finally:
        _restore_env(saved)


def test_cache_dir_overridden_from_env(tmp_path: Path) -> None:
    saved = _clear_lub_env()
    try:
        custom = tmp_path / "my-lub-cache"
        os.environ["LUB_CACHE_DIR"] = str(custom)
        cfg = LubConfig()
        assert cfg.cache_dir == custom
    finally:
        _restore_env(saved)


# ---------------------------------------------------------------------------
# extra="ignore" — non-LUB env vars do not pollute
# ---------------------------------------------------------------------------


def test_non_lub_env_vars_ignored() -> None:
    """A surprise env var like SOME_OTHER_KEY should not become a config field."""
    saved = _clear_lub_env()
    try:
        os.environ["SOME_OTHER_KEY"] = "should-not-leak"
        cfg = LubConfig()
        assert not hasattr(cfg, "some_other_key")
    finally:
        os.environ.pop("SOME_OTHER_KEY", None)
        _restore_env(saved)


# ---------------------------------------------------------------------------
# ensure_cache_dir
# ---------------------------------------------------------------------------


def test_ensure_cache_dir_creates_missing_dir(tmp_path: Path) -> None:
    saved = _clear_lub_env()
    try:
        target = tmp_path / "deep" / "nested" / "cache"
        os.environ["LUB_CACHE_DIR"] = str(target)
        cfg = LubConfig()
        assert not target.exists()
        returned = cfg.ensure_cache_dir()
        assert target.exists()
        assert target.is_dir()
        assert returned == target
    finally:
        _restore_env(saved)


def test_ensure_cache_dir_idempotent(tmp_path: Path) -> None:
    """Calling ensure_cache_dir twice must not raise."""
    saved = _clear_lub_env()
    try:
        target = tmp_path / "cache"
        os.environ["LUB_CACHE_DIR"] = str(target)
        cfg = LubConfig()
        cfg.ensure_cache_dir()
        cfg.ensure_cache_dir()  # should not raise
        assert target.is_dir()
    finally:
        _restore_env(saved)


def test_ensure_cache_dir_returns_path(tmp_path: Path) -> None:
    saved = _clear_lub_env()
    try:
        target = tmp_path / "cache"
        os.environ["LUB_CACHE_DIR"] = str(target)
        cfg = LubConfig()
        returned = cfg.ensure_cache_dir()
        assert isinstance(returned, Path)
    finally:
        _restore_env(saved)


# ---------------------------------------------------------------------------
# Multiple env vars at once
# ---------------------------------------------------------------------------


def test_multiple_env_vars_combined() -> None:
    saved = _clear_lub_env()
    try:
        os.environ["LUB_LOG_LEVEL"] = "WARNING"
        os.environ["LUB_RETRY_ATTEMPTS"] = "5"
        os.environ["LUB_REQUEST_TIMEOUT_S"] = "30"
        cfg = LubConfig()
        assert cfg.log_level == "WARNING"
        assert cfg.retry_attempts == 5
        assert cfg.request_timeout_s == 30.0
    finally:
        _restore_env(saved)
