# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Platform-level endpoints: /health and /version.

Both endpoints are pure projections of module-level singletons living in
``server.py`` (``_BACKEND``, ``_METRICS``, ``_AUDIT``, etc.). To avoid a
circular import between ``server`` and this router, the singletons are
fetched lazily inside each handler via :func:`_get_state`. This keeps the
import graph ``server -> routers.platform`` one-directional even though
the handlers read mutable state defined by ``server``.

Once ``server.py`` is refactored to publish its state through a separate
``backend.state`` module, ``_get_state`` collapses into a normal import
at the top of this file.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter()


def _get_state() -> dict[str, Any]:
    """Return a dict of references to ``server.py`` module-level state.

    Lazy import to break the circular dependency between ``server.py``
    (which calls ``app.include_router(platform.router)``) and this
    module. Tries the ``backend.server`` path first (pytest from repo
    root), falls back to a top-level ``server`` import (uvicorn launched
    from ``backend/``).
    """
    import sys
    server = sys.modules.get("server") or sys.modules.get("backend.server")
    if server is None:
        try:
            import server  # type: ignore[no-redef]
        except ImportError:
            from backend import server

    return {
        "BACKEND": server._BACKEND,
        "METRICS": server._METRICS,
        "AUDIT": server._AUDIT,
        "DOC_STORE": server._DOC_STORE,
        "DQ_INPUT": server._DQ_INPUT,
        "DQ_OUTPUT": server._DQ_OUTPUT,
        "PROMPT_FINGERPRINT": server._PROMPT_FINGERPRINT,
        "CORPUS_FINGERPRINT": server._CORPUS_FINGERPRINT,
    }


def _local_only_enabled() -> bool:
    """Report whether the library's air-gapped profile is in force.

    Read from :class:`lub.config.LubConfig` rather than from a local flag, so
    the console cannot claim a perimeter the library is not actually
    enforcing. Under the profile, hosted-API backends refuse to construct —
    see :mod:`lub.governance.local_only` for the exact scope of the guarantee
    (customer prompts; not a network firewall).
    """
    from lub.config import LubConfig

    return bool(LubConfig().local_only)


@router.get("/health")
def health() -> dict[str, Any]:
    """Report liveness of the Bridge UI BFF and basic hub state.

    Bridge hub connection: lightweight probe the Next.js dashboard (and any
    uptime monitor) hits to confirm the Bridge platform process is alive
    and which backend it is currently wired to.

    Returns:
        Dict with ``status``, ``platform``, active ``backend`` name, and the
        running queries-processed counter from the in-memory Metrics hub.
    """
    s = _get_state()
    return {
        "status": "ok",
        "platform": "bridge",
        "backend": getattr(s["BACKEND"], "name", "fake"),
        "backend_is_real": getattr(s["BACKEND"], "is_real", False),
        # Which side of the data perimeter this deployment runs on.
        "local_only": _local_only_enabled(),
        "queries_processed_total": s["METRICS"].queries_total,
        "audit_entries_current": len(s["AUDIT"]),
        # Back-compat field (deprecated, matches queries_processed_total).
        "queries_processed": s["METRICS"].queries_total,
    }


@router.get("/version")
def version() -> dict[str, Any]:
    """Versioning surface required by SR 11-7 Ongoing Monitoring.

    Exposes the fingerprint of every artifact that materially affects a
    response: model identity, prompt template, RAG corpus version. A
    compliance reviewer asking "which version of the prompt produced
    customer X's answer on date Y?" can resolve it through this endpoint
    cross-referenced with the audit trail's timestamps.
    """
    s = _get_state()
    return {
        "api_version": "0.2.0",
        "model": getattr(s["BACKEND"], "name", "fake-demo-v1"),
        "backend_is_real": getattr(s["BACKEND"], "is_real", False),
        "prompt_template_hash": s["PROMPT_FINGERPRINT"],
        "corpus_version": s["CORPUS_FINGERPRINT"],
        "corpus_doc_count": s["DOC_STORE"].size,
        "dq_input_rules": len(s["DQ_INPUT"].rules),
        "dq_output_rules": len(s["DQ_OUTPUT"].rules),
        "rate_limit_per_minute": None,
        "deployed_at": "static-demo",
    }


__all__ = ["router"]
