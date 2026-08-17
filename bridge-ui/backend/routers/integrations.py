# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Integrations — declarative provider inventory (product v3).

Phoenix/Langfuse/NeMo all expose a provider list configured by **server-side env
vars, never an API key pasted into the UI**. This endpoint does the same for the
Bridge: it inventories the LLM backends (FakeBackend, Ollama, and future
OpenAI/Anthropic adapters), checks Ollama's live reachability + loaded models, and
reports which backend is active and how to switch (BRIDGE_USE_REAL_LLM on the
server). Read-only by design — switching is an env+restart operation, not a UI
form, so no credential ever touches the browser.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()

_OLLAMA_URL = "http://localhost:11434"
_CACHE: dict[str, Any] | None = None
# Short TTL so the auto-poll path (no ?refresh) still re-probes Ollama instead of
# serving a frozen snapshot — a killed Ollama would otherwise read "reachable"
# forever until a manual recheck. The frontend polls every 15s.
_CACHE_TS: float = 0.0
_CACHE_TTL_S: float = 10.0


def _server() -> ModuleType:
    import sys

    mod = sys.modules.get("server") or sys.modules.get("backend.server")
    if mod is not None:
        return mod
    try:
        import server  # type: ignore[no-redef]
    except ImportError:
        from backend import server
    return server


def _ollama_status() -> dict[str, Any]:
    try:
        with urllib.request.urlopen(_OLLAMA_URL + "/api/tags", timeout=2.5) as r:  # noqa: S310
            data = json.loads(r.read())
        return {"reachable": True, "models": [m["name"] for m in data.get("models", [])]}
    except Exception as exc:  # noqa: BLE001 — any failure = unreachable
        return {"reachable": False, "models": [], "error": str(exc)[:100]}


def build_integrations(refresh: bool = False) -> dict[str, Any]:
    global _CACHE, _CACHE_TS
    now = time.monotonic()
    if _CACHE is not None and not refresh and (now - _CACHE_TS) < _CACHE_TTL_S:
        return _CACHE
    s = _server()
    active = getattr(s._BACKEND, "name", "fake")
    is_fake = active == "fake"
    configured_model = getattr(s, "_OLLAMA_MODEL", None)
    oll = _ollama_status()
    model_loaded = (configured_model in oll["models"]) if configured_model else None

    # Honest Ollama status: "active" ONLY when it is the serving backend AND can
    # actually serve. If Ollama is selected but unreachable or its configured model
    # isn't loaded, every turn silently falls back to canned — so show "degraded"
    # (not a green "active"), and it won't be counted as available below.
    if is_fake:
        ollama_status = "reachable" if oll["reachable"] else "unreachable"
    elif not oll["reachable"] or model_loaded is False:
        ollama_status = "degraded"
    else:
        ollama_status = "active"

    providers = [
        {
            "id": "fake",
            "name": "FakeBackend",
            "kind": "LLM backend",
            "status": "active" if is_fake else "available",
            "live": is_fake,
            "note": "Deterministic responses, no network — demo / CI mode.",
        },
        {
            "id": "ollama",
            "name": "Ollama (local)",
            "kind": "LLM backend",
            "status": ollama_status,
            "live": not is_fake,
            "reachable": oll["reachable"],
            "models": oll["models"],
            "configured_model": configured_model,
            "model_loaded": model_loaded,
            "endpoint": _OLLAMA_URL,
            "note": "Real local LLM. Enable with BRIDGE_USE_REAL_LLM=on on the server (requires restart).",
        },
        {
            "id": "openai",
            "name": "OpenAI",
            "kind": "LLM backend",
            "status": "not_configured",
            "live": False,
            "note": "Future adapter — key via server-side environment variable, never in the UI.",
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "kind": "LLM backend",
            "status": "not_configured",
            "live": False,
            "note": "Future adapter — key via server-side environment variable, never in the UI.",
        },
    ]

    _CACHE = {
        "active_backend": active,
        "n_providers": len(providers),
        "n_available": sum(1 for p in providers if p["status"] in ("active", "available", "reachable")),
        "providers": providers,
        "switch_note": (
            "Backend switching is done via BRIDGE_USE_REAL_LLM (off / on / required) on the "
            "server and requires a restart — never via a key pasted into the UI (NeMo/Guardrails AI pattern)."
        ),
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _CACHE_TS = now
    return _CACHE


@router.get("/integrations")
def integrations(refresh: bool = False) -> dict[str, Any]:
    """Provider inventory with live Ollama reachability (cached; ?refresh=1 re-checks)."""
    return build_integrations(refresh=refresh)


__all__ = ["router"]
