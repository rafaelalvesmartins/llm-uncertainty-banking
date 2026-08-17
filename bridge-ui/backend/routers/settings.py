# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Runtime demo controls (Bloco A2).

Exposes the two tunable knobs the dashboard turns into live controls:

  - ``guard_threshold`` — the UncertaintyGuard confidence gate. Lowering it
    pushes more ordinary-intent queries to PASSTHROUGH; raising it pushes them
    to FLAG/REASK/ESCALATE. Safety/fraud intents hard-override to ESCALATE
    regardless, so the control never weakens the safety floor.
  - ``cache_enabled`` — whether the SemanticCache short-circuits repeat
    queries. Off = every query re-runs the full pipeline.

``backend`` is reported read-only: swapping the LLM backend at runtime is out
of scope (it's chosen at startup), so the UI shows it but doesn't pretend to
change it.

State lives in ``server.py`` module globals; this router reads/writes them
lazily via the same ``_server()`` dance the other routers use.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

try:
    from backend.routers.auth import verify_token
except ImportError:  # pragma: no cover
    from routers.auth import verify_token  # type: ignore[no-redef]
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()


def _server() -> ModuleType:
    # Reuse whichever ``server`` module is already loaded so this router's
    # writes and the app's hot-path reads hit the SAME module globals. uvicorn
    # runs ``server:app`` and the tests ``import server`` — both register
    # ``"server"`` in sys.modules. Forcing ``from backend import server`` here
    # would create a divergent second module (runtime state would split).
    import sys
    mod = sys.modules.get("server") or sys.modules.get("backend.server")
    if mod is not None:
        return mod
    try:
        import server  # type: ignore[no-redef]
    except ImportError:
        from backend import server
    return server


def _snapshot(s: ModuleType) -> dict[str, Any]:
    return {
        "guard_threshold": s._RUNTIME_GUARD_THRESHOLD,
        "guard_threshold_default": s.GUARD_THRESHOLD_DEFAULT,
        "guard_threshold_min": s.GUARD_THRESHOLD_MIN,
        "guard_threshold_max": s.GUARD_THRESHOLD_MAX,
        "cache_enabled": s._RUNTIME_CACHE_ENABLED,
        # Read-only: backend is fixed at startup.
        "backend": s._BACKEND.name,
        "backend_is_real": s._BACKEND.is_real,
        "backend_mutable": False,
    }


class SettingsUpdate(BaseModel):
    """Partial update — only the provided fields change."""

    guard_threshold: float | None = Field(default=None)
    cache_enabled: bool | None = Field(default=None)
    operator: str = Field(default="", max_length=128)  # demo identity, for audit attribution


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    """Return the current runtime demo controls."""
    return _snapshot(_server())


def _audit_settings_change(s: ModuleType, field: str, before: Any, after: Any, operator: str) -> None:
    """Record a runtime-control change on the SAME tamper-evident audit hash-chain the
    /query path uses, so an ungoverned knob is at least dated, attributed, and
    reconstructable from history (SR 11-7). Best-effort: a successful control change
    must never fail because the audit sink hiccuped."""
    try:
        s._audit_append(
            {
                "ts": time.time(),
                "event": "settings.change",
                "intent": "settings",
                "decision": "APPLIED",
                "field": field,
                "before": before,
                "after": after,
                "operator": operator or "unknown",
                "channel": "console",
            }
        )
    except Exception as e:  # noqa: BLE001 — audit is best-effort, never block the control
        print(f"[settings] audit append failed ({field}): {e}", flush=True)


@router.put("/settings")
def put_settings(
    update: SettingsUpdate,
    principal: dict[str, Any] | None = Depends(verify_token),
) -> dict[str, Any]:
    """Apply a partial update to the runtime controls and echo the new state.

    Mutating module globals from a router requires setattr on the server
    module — the values are plain floats/bools read on the hot /query path.
    Each *real* change is appended to the audit hash-chain (operator + before/after)
    so these ungoverned knobs remain traceable even without the full governed flow.
    """
    s = _server()
    op = principal["sub"] if principal else update.operator
    if update.guard_threshold is not None:
        lo, hi = s.GUARD_THRESHOLD_MIN, s.GUARD_THRESHOLD_MAX
        if not (lo <= update.guard_threshold <= hi):
            raise HTTPException(
                status_code=422,
                detail=f"guard_threshold must be within [{lo}, {hi}]",
            )
        new_threshold = round(update.guard_threshold, 3)
        before = s._RUNTIME_GUARD_THRESHOLD
        s._RUNTIME_GUARD_THRESHOLD = new_threshold
        if new_threshold != before:
            _audit_settings_change(s, "guard_threshold", before, new_threshold, op)
    if update.cache_enabled is not None:
        before = s._RUNTIME_CACHE_ENABLED
        s._RUNTIME_CACHE_ENABLED = update.cache_enabled
        if update.cache_enabled != before:
            _audit_settings_change(s, "cache_enabled", before, update.cache_enabled, op)
    return _snapshot(s)


__all__ = ["router"]
