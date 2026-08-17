# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Shared skip-logic for real-backend smoke tests."""
from __future__ import annotations

import importlib
import os

import pytest


def skip_unless_opted_in() -> None:
    if os.environ.get("LUB_REAL_BACKEND_TESTS") != "1":
        pytest.skip(
            "Real-backend test: set LUB_REAL_BACKEND_TESTS=1 to enable.",
            allow_module_level=False,
        )


def require_sdk(pkg: str) -> None:
    try:
        importlib.import_module(pkg)
    except ImportError:
        pytest.skip(f"SDK {pkg!r} not installed", allow_module_level=False)


def require_env(var: str) -> None:
    if not os.environ.get(var):
        pytest.skip(f"{var} not set in environment", allow_module_level=False)
