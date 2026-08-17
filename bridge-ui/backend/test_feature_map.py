# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Bloco A5 guard: the UI Feature Map must not drift from the real API.

`frontend/lib/featureMap.ts` is the single source of truth for the dashboard's
LIVE/MOCK/STATIC honesty layer (state badges + Feature Map). Every endpoint it
declares is rendered with a ✓/✗ cross-check against the live /openapi.json so a
renamed or removed backend route shows up visually. This test pins the same
invariant at CI time: every "METHOD /path" string in the registry must resolve
to a path the FastAPI app actually exposes.

It caught a real bug during development (the RAG Corpus panel was listed as
`/corpus` but the backend serves `/docs/corpus`).

Run from the project root::

    pytest bridge-ui/backend/test_feature_map.py -v
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402  — must follow sys.path setup

_FEATURE_MAP_TS = _HERE.parent / "frontend" / "lib" / "featureMap.ts"

# "GET /metrics", "POST /audit/replay/{seq}", etc. The registry only ever puts
# these inside `endpoints:` arrays, so a quoted METHOD-path string is
# unambiguous.
_ENDPOINT_RE = re.compile(r'"(GET|POST|PUT|PATCH|DELETE)\s+(/[^"]*)"')


def _normalize(path: str) -> str:
    """Match the frontend's normalizePath: collapse {param} and trailing /."""
    return re.sub(r"\{[^}]+\}", "{}", path).rstrip("/")


def _declared_endpoints() -> list[tuple[str, str]]:
    text = _FEATURE_MAP_TS.read_text(encoding="utf-8")
    return [(m.group(1), m.group(2)) for m in _ENDPOINT_RE.finditer(text)]


def test_feature_map_file_exists() -> None:
    assert _FEATURE_MAP_TS.is_file(), f"missing {_FEATURE_MAP_TS}"


def test_registry_has_endpoints() -> None:
    # Guards against the regex silently matching nothing (which would make the
    # cross-check below vacuously pass).
    assert len(_declared_endpoints()) >= 14


@pytest.mark.parametrize(
    "method,path",
    _declared_endpoints(),
    ids=[f"{m} {p}" for m, p in _declared_endpoints()],
)
def test_declared_endpoint_exists_in_openapi(method: str, path: str) -> None:
    spec = server.app.openapi()
    available = {_normalize(p): set(ops) for p, ops in spec["paths"].items()}
    norm = _normalize(path)
    assert norm in available, (
        f"featureMap.ts declares {method} {path}, but {norm} is not a path in "
        f"the FastAPI app. The Feature Map would render a ✗ for it — fix the "
        f"registry or the route."
    )
    assert method.lower() in available[norm], (
        f"featureMap.ts declares {method} {path}, but the app exposes only "
        f"{sorted(available[norm])} on that path."
    )


# Infra/diagnostic paths intentionally excluded from the Feature Map. MUST stay
# in sync with INFRA_ALLOWLIST in frontend/components/HowThisWorks.tsx.
# /metrics/prometheus is the Prometheus text-scrape endpoint (routers/observability.py),
# mounted for the scale/monitoring stack — infra, not a user-facing feature.
_INFRA_ALLOWLIST = {"/health", "/version", "/metrics/prometheus"}


def test_every_openapi_path_is_covered_or_allowlisted() -> None:
    """Reverse cross-check (A5): every path the server exposes must be declared
    in featureMap.ts OR be an infra/diagnostic path on the allowlist. Catches
    NEW endpoints that would silently escape the honesty layer — the forward
    test only checks declared->exists, this checks exists->declared."""
    spec = server.app.openapi()
    declared = {_normalize(p) for _m, p in _declared_endpoints()}
    allowed = {_normalize(p) for p in _INFRA_ALLOWLIST}
    uncovered = sorted(
        p for p in spec["paths"] if _normalize(p) not in declared and _normalize(p) not in allowed
    )
    assert not uncovered, (
        f"Live /openapi.json exposes paths absent from featureMap.ts and the "
        f"infra allowlist: {uncovered}. Add them to FEATURE_MAP (so the Feature "
        f"Map surfaces them) or to _INFRA_ALLOWLIST (+ HowThisWorks.tsx) if they "
        f"are intentionally non-feature infra."
    )
