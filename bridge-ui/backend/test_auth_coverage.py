# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Regression guard: every mutating/operator endpoint wires ``verify_token``.

Before this pass only ``PUT /settings`` and ``DELETE /audit`` were protected;
drift rebaseline, cache flush, the visibility write endpoints, and the audit
tamper-test were reachable unauthenticated even with ``BRIDGE_AUTH=on``. This
test introspects the assembled app so a future router that forgets the
dependency fails here instead of silently shipping an open control.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

try:
    from backend.routers.auth import verify_token  # noqa: E402
except ImportError:
    from routers.auth import verify_token  # type: ignore[no-redef]  # noqa: E402

# (method, path) pairs that mutate server state or perform an operator action.
# Each MUST depend on verify_token so BRIDGE_AUTH=on can gate it.
PROTECTED = {
    ("PUT", "/settings"),
    ("DELETE", "/audit"),
    ("POST", "/audit/tamper-test"),
    ("DELETE", "/cache"),
    ("POST", "/drift/baseline"),
    ("POST", "/drift/auto-rebaseline"),
    ("PUT", "/visibility/config"),
    ("POST", "/visibility/run"),
    ("POST", "/visibility/content/draft"),
    ("POST", "/visibility/content/{draft_id}/approve"),
    ("POST", "/visibility/schedule"),
}


def _wires_verify_token(route) -> bool:
    """True if verify_token appears anywhere in the route's dependency tree."""
    seen = list(route.dependant.dependencies)
    while seen:
        dep = seen.pop()
        if dep.call is verify_token:
            return True
        seen.extend(dep.dependencies)
    return False


def test_all_mutating_endpoints_require_auth() -> None:
    by_key = {}
    for route in server.app.routes:
        methods = getattr(route, "methods", None) or set()
        for m in methods:
            by_key[(m, getattr(route, "path", ""))] = route

    missing = []
    for method, path in sorted(PROTECTED):
        route = by_key.get((method, path))
        assert route is not None, f"{method} {path} is not registered — test is stale"
        if not _wires_verify_token(route):
            missing.append(f"{method} {path}")

    assert not missing, "mutating endpoints missing verify_token: " + ", ".join(missing)
