# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Prometheus scrape endpoint — Track D (scale), ADDITIVE + INERT.

Standalone ``APIRouter`` that exposes a Prometheus text-format scrape endpoint.
It is NOT mounted in ``server.py``; to activate it, add it after the existing
router includes using the same flat/package dual-import the rest of the backend
uses (server.py runs flat as ``uvicorn server:app``)::

    try:
        from routers.observability import router as observability_router
    except ImportError:
        from backend.routers.observability import router as observability_router
    app.include_router(observability_router)

NOTE: the existing ``GET /metrics`` (routers/metrics.py, a JSON dashboard) is
already mounted, so this router's ``/metrics`` would COLLIDE — mount this at a
distinct path (e.g. ``/metrics/prometheus``) and point deploy/prometheus.yml's
``metrics_path`` at it before wiring the monitoring stack.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

# Flat-layout import with a package-mode fallback (backend/ has no __init__.py;
# the demo runs flat as `uvicorn server:app`, where `from backend.X` fails).
try:
    from scale.metrics_prometheus import metrics_text
except ImportError:  # package-mode (backend.scale.*)
    from backend.scale.metrics_prometheus import metrics_text

router = APIRouter()


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
def prometheus_metrics() -> PlainTextResponse:
    """Prometheus text scrape endpoint.

    Returns all Bridge Prometheus instruments (latency histogram, query
    counter, resolution/escalation rate gauges) in the standard text
    exposition format that Prometheus and compatible scrapers understand.

    Mount this router and point your Prometheus ``scrape_configs`` at
    ``<host>/metrics`` to start collecting.
    """
    body, content_type = metrics_text()
    return PlainTextResponse(content=body, media_type=content_type)


__all__ = ["router"]
