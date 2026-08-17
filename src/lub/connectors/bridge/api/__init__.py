# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""REST API for the Bridge banking AI platform.

Exposes the Bridge multi-agent orchestrator via FastAPI endpoints.
Every query endpoint returns both the answer and a confidence score
so that downstream consumers can make informed decisions about when
to trust, escalate, or suppress AI-generated responses.

Endpoints:
    POST /query          — Route a customer query with uncertainty scoring
    GET  /health         — Platform health check
    GET  /metrics        — Operational metrics snapshot
    GET  /compliance     — Compliance dashboard data (BCB 4893, BCBS 239)
    GET  /agents         — List registered agents and their status
"""

from __future__ import annotations

__all__ = ["build_app"]


def build_app() -> object:
    """Build and return the FastAPI application.

    Lazy import so that ``lub.api`` can be imported without FastAPI
    installed (e.g., in test environments that only need the models).
    """
    from lub.connectors.bridge.api.routes import create_app

    return create_app()
