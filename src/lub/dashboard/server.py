# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.dashboard.server -- tiny FastAPI server for the dashboard.

Post pass-33 refactor: the server is **generic over any SnapshotSource**.
The two public entry points are:

* :func:`build_app`       -- factory; takes a ``source_factory`` callable
  that returns a fresh :class:`SnapshotSource` per request (so sqlite
  handles don't outlive the response).

* :func:`build_app_from_ledger_path` -- thin convenience wrapper for the
  common case: open an :class:`~lub.ledger.Ledger` per request from a
  file path. This is what the CLI / console-script use.

Both raise :class:`ImportError` (with install hint) if ``fastapi`` is not
installed; declare ``llm-uncertainty-banking[dashboard]`` to enable.

Spec: planning/29_Dashboard_Spec_2026-04-25.md section 4.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lub.dashboard.protocols import SnapshotSource

__all__ = [
    "build_app",
    "build_app_from_ledger_path",
    "run_uvicorn",
]


_FASTAPI_HINT = (
    "fastapi is required for the dashboard server. Install with: "
    "pip install fastapi uvicorn  # or: pip install 'llm-uncertainty-banking[dashboard]'"
)


def _require_fastapi() -> tuple[Any, Any]:
    try:
        import fastapi
        from fastapi.responses import HTMLResponse, JSONResponse
    except ImportError as exc:
        raise ImportError(_FASTAPI_HINT) from exc
    return fastapi, (HTMLResponse, JSONResponse)


def build_app(
    source_factory: Callable[[], SnapshotSource],
    *,
    tenant: str = "default",
    default_days: int = 30,
    title: str | None = None,
) -> Any:
    """Build the FastAPI app over any :class:`SnapshotSource` factory.

    The ``source_factory`` is called per request so resource handles (e.g.
    sqlite connections) do not outlive the response. For the common
    ledger-file case prefer :func:`build_app_from_ledger_path`.

    Args:
        source_factory: Zero-arg callable returning a fresh
            :class:`SnapshotSource` per request.
        tenant: Tenant identifier passed through to the snapshot.
        default_days: Default window when ``?days=...`` is omitted.
        title: Optional FastAPI title; defaults to ``f"LUB Dashboard ({tenant})"``.

    Returns:
        A ``fastapi.FastAPI`` instance.

    Raises:
        ImportError: If ``fastapi`` is not installed.
    """
    fastapi, (HTMLResponse, JSONResponse) = _require_fastapi()

    from lub.dashboard.query import build_snapshot
    from lub.dashboard.render import render_html, render_json

    app = fastapi.FastAPI(
        title=title or f"LUB Dashboard ({tenant})",
        description="Read-only observability over any SnapshotSource.",
        version="0.1.0",
    )

    def _snapshot(days: int) -> Any:
        period_end = datetime.now(UTC)
        period_start = period_end - timedelta(days=max(1, days))
        source = source_factory()
        try:
            return build_snapshot(
                source=source,
                evidence_store=None,
                period_start=period_start,
                period_end=period_end,
                tenant=tenant,
                git_sha="server",
            )
        finally:
            close = getattr(source, "close", None)
            if callable(close):
                close()
            inner_close = getattr(getattr(source, "_ledger", None), "close", None)
            if callable(inner_close):
                inner_close()

    @app.get("/healthz")  # type: ignore[misc]
    def healthz() -> dict[str, str]:
        """Liveness probe: returns ``{"status": "ok"}`` if the app is running.

        Intentionally cheap — does not touch the ledger, so it stays
        green even when the data source is paused.
        """
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)  # type: ignore[misc]
    def root(days: int = default_days) -> str:
        """Render the HTML dashboard for the trailing ``days`` window.

        ``days`` defaults to ``default_days`` (30 unless overridden at
        app construction). Pass ``?days=N`` to override per-request.
        """
        return render_html(_snapshot(days))

    @app.get("/api/snapshot", response_class=JSONResponse)  # type: ignore[misc]
    def api_snapshot(days: int = default_days) -> Any:
        """Return the raw snapshot JSON for the trailing ``days`` window.

        Mirrors the data the HTML view consumes; useful for programmatic
        scrapers (Grafana JSON datasource, Prometheus textfile exporter).
        """
        import json as _json

        return _json.loads(render_json(_snapshot(days)))

    return app


def build_app_from_ledger_path(
    ledger_path: Path | str,
    *,
    tenant: str = "default",
    default_days: int = 30,
) -> Any:
    """Convenience wrapper: bind the FastAPI app to a sqlite ledger file.

    Each request opens a fresh :class:`~lub.ledger.Ledger` handle and
    closes it after the response is built (sqlite locking stays
    predictable under concurrent reads).

    Args:
        ledger_path: Path to the sqlite ledger file.
        tenant: Tenant identifier.
        default_days: Default window in days.

    Returns:
        A ``fastapi.FastAPI`` instance.

    Raises:
        ImportError: If ``fastapi`` is not installed.
    """
    ledger_path = Path(ledger_path)

    def _factory() -> SnapshotSource:
        from lub.dashboard.ledger_source import LedgerSnapshotSource
        from lub.ledger import Ledger

        return LedgerSnapshotSource(Ledger(ledger_path))

    return build_app(_factory, tenant=tenant, default_days=default_days)


def run_uvicorn(
    ledger_path: Path | str,
    *,
    host: str = "127.0.0.1",
    port: int = 8081,
    tenant: str = "default",
) -> None:
    """Convenience launcher: build the app from a ledger path and serve via uvicorn.

    Hot-reload is disabled (the dashboard is read-only).

    Raises:
        ImportError: If ``fastapi`` or ``uvicorn`` is not installed.
    """
    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError("uvicorn is required for run_uvicorn. " + _FASTAPI_HINT) from exc

    app = build_app_from_ledger_path(ledger_path, tenant=tenant)
    uvicorn.run(app, host=host, port=port, log_level="info")
