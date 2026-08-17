# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""FastAPI routers for the Bridge UI BFF.

Each router groups endpoints by domain (platform, audit, drift, etc.) to
keep ``server.py`` focused on application wiring rather than per-endpoint
handler bodies. The pattern is incremental: routers can be added one at
a time without disturbing the existing module-level state in
``server.py``. Each router declares its dependencies as accessor
functions imported lazily from ``server.py`` to avoid circular imports.
"""

try:
    from backend.routers import audit, compliance, discovery, drift, metrics, platform
except ImportError:
    from routers import (  # type: ignore[no-redef]
        audit,
        compliance,
        discovery,
        drift,
        metrics,
        platform,
    )

__all__ = ["audit", "compliance", "discovery", "drift", "metrics", "platform"]
