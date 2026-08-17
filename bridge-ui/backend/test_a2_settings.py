# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Bloco A2 — runtime controls (guard threshold + cache toggle).

Verifies that PUT /settings mutates the server's runtime knobs AND that the
knobs actually change pipeline behavior, while never weakening the safety
floor. Calls the router functions directly (no TestClient) so the suite stays
fast and doesn't contend with a live demo's SQLite audit store.

Run from the project root::

    pytest bridge-ui/backend/test_a2_settings.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

try:
    from backend.routers import settings as settings_router  # noqa: E402
except ImportError:
    from routers import settings as settings_router  # type: ignore[no-redef]  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_runtime_settings():
    """Save/restore the mutated globals so tests don't bleed into each other
    (or into a running process / other test modules)."""
    saved_thr = server._RUNTIME_GUARD_THRESHOLD
    saved_cache = server._RUNTIME_CACHE_ENABLED
    yield
    server._RUNTIME_GUARD_THRESHOLD = saved_thr
    server._RUNTIME_CACHE_ENABLED = saved_cache


def test_get_settings_reports_defaults() -> None:
    s = settings_router.get_settings()
    assert s["guard_threshold"] == server.GUARD_THRESHOLD_DEFAULT
    assert s["cache_enabled"] is True
    assert s["backend_mutable"] is False
    assert s["backend"] == server._BACKEND.name


def test_put_threshold_mutates_global() -> None:
    out = settings_router.put_settings(settings_router.SettingsUpdate(guard_threshold=0.3), principal=None)
    assert out["guard_threshold"] == 0.3
    assert server._RUNTIME_GUARD_THRESHOLD == 0.3


def test_threshold_change_flips_ordinary_intent_decision() -> None:
    # The /query path calls apply_guard(conf, threshold=_RUNTIME_GUARD_THRESHOLD,
    # ...). At conf=0.6: threshold 0.7 → REASK; threshold 0.3 → PASSTHROUGH.
    settings_router.put_settings(settings_router.SettingsUpdate(guard_threshold=0.7), principal=None)
    decision_high, _ = server.apply_guard(
        0.6, threshold=server._RUNTIME_GUARD_THRESHOLD, intent="balance"
    )
    settings_router.put_settings(settings_router.SettingsUpdate(guard_threshold=0.3), principal=None)
    decision_low, _ = server.apply_guard(
        0.6, threshold=server._RUNTIME_GUARD_THRESHOLD, intent="balance"
    )
    assert decision_high == "REASK", f"expected REASK at 0.7, got {decision_high}"
    assert decision_low == "PASSTHROUGH", f"expected PASSTHROUGH at 0.3, got {decision_low}"


def test_lowering_threshold_never_weakens_safety_floor() -> None:
    settings_router.put_settings(settings_router.SettingsUpdate(guard_threshold=0.1), principal=None)
    for intent in ("crisis", "card_fraud", "illegal_activity"):
        decision, _ = server.apply_guard(
            0.99, threshold=server._RUNTIME_GUARD_THRESHOLD, intent=intent
        )
        assert decision == "ESCALATE", (
            f"safety/fraud intent {intent!r} must ESCALATE even at threshold 0.1; got {decision}"
        )


def test_cache_toggle_mutates_global() -> None:
    settings_router.put_settings(settings_router.SettingsUpdate(cache_enabled=False), principal=None)
    assert server._RUNTIME_CACHE_ENABLED is False
    settings_router.put_settings(settings_router.SettingsUpdate(cache_enabled=True), principal=None)
    assert server._RUNTIME_CACHE_ENABLED is True


@pytest.mark.parametrize("bad", [2.0, -0.5, 1.5, 0.0])
def test_out_of_range_threshold_rejected(bad: float) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        settings_router.put_settings(settings_router.SettingsUpdate(guard_threshold=bad), principal=None)
    assert exc.value.status_code == 422
    # Rejected update must not have mutated the global.
    assert server._RUNTIME_GUARD_THRESHOLD == server.GUARD_THRESHOLD_DEFAULT


def test_partial_update_leaves_other_field_untouched() -> None:
    settings_router.put_settings(settings_router.SettingsUpdate(guard_threshold=0.5), principal=None)
    before_cache = server._RUNTIME_CACHE_ENABLED
    settings_router.put_settings(settings_router.SettingsUpdate(cache_enabled=not before_cache), principal=None)
    # threshold unchanged by the cache-only update
    assert server._RUNTIME_GUARD_THRESHOLD == 0.5
