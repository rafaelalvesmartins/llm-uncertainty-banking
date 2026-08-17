# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Compliance endpoints — SR 11-7 three-pillar mapping for the dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

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


@router.get("/compliance/sr-11-7")
def compliance_sr_11_7() -> dict[str, Any]:
    """Return the SR 11-7 three-pillar mapping for the dashboard panel.

    Bridge hub connection: every Bridge response gates through the
    UncertaintyGuard (Stage 7) and lands in the AuditTrail (Stage 9), both
    of which the audit.py docstring declares as SR 11-7 evidence. This
    endpoint exposes which SR 11-7 control each lub metric evidences so the
    dashboard can render the regulator-facing pillar view.
    """
    s = _server()
    return s._SR_11_7_PAYLOAD  # type: ignore[no-any-return]


# Friendly jurisdiction labels for the dashboard (the lub Regime enum values are
# machine keys). Demonstrates multi-jurisdiction coverage at a glance.
_JURISDICTION: dict[str, str] = {
    "BCB": "Brazil — BCB",
    "BCBS": "International — Basel",
    "EU_AI_ACT": "European Union",
    "ISO_23894": "International — ISO",
    "ISO_42001": "International — ISO",
    "NIST_GENAI": "USA — NIST",
    "SR_11_7": "USA — Fed/OCC",
}


@router.get("/compliance/frameworks")
def compliance_frameworks() -> dict[str, Any]:
    """Regulatory coverage — every compliance framework the lub crosswalk maps.

    Surfaces the full ``lub.compliance.frameworks`` suite (BCB 4.893, BCBS 239,
    EU AI Act, ISO 42001/23894, NIST AI RMF, SR 11-7) with their real controls,
    so the dashboard shows multi-jurisdiction governance — not a single regime.
    """
    try:
        from lub.compliance.frameworks import FRAMEWORKS
    except Exception as exc:  # pragma: no cover - lub always present here
        print(f"[compliance] framework load failed: {exc!r}", flush=True)
        return {"frameworks": [], "n_frameworks": 0, "n_controls_total": 0, "error": "internal error"}

    out: list[dict[str, Any]] = []
    for fw in FRAMEWORKS:
        try:
            controls = list(fw.get_controls())
        except Exception:
            controls = []
        key = fw.CROSSWALK_KEY
        out.append(
            {
                "key": key,
                "title": fw.TITLE,
                "jurisdiction": _JURISDICTION.get(key, "—"),
                "n_controls": len(controls),
                "controls": [
                    {
                        "control_id": c["control_id"],
                        "control_title": c["control_title"],
                        "description": c["description"],
                    }
                    for c in controls
                ],
            }
        )
    out.sort(key=lambda f: f["jurisdiction"])
    return {
        "frameworks": out,
        "n_frameworks": len(out),
        "n_jurisdictions": len({f["jurisdiction"] for f in out}),
        "n_controls_total": sum(f["n_controls"] for f in out),
        # Candor: these counts are CROSSWALK MAPPING coverage (which controls a
        # metric maps to), NOT measured pass/fail. Measured evidence for the SR
        # 11-7 pillars is at /compliance/sr-11-7; see docs/evidence-status.md.
        "coverage_kind": "crosswalk_mapping",
        "coverage_note": (
            "Control counts are crosswalk mapping coverage (metric → control), "
            "not measured evidence. Measured metrics: /compliance/sr-11-7."
        ),
    }


__all__ = ["router"]
