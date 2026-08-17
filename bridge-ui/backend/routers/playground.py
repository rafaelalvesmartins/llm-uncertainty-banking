# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Playground — compare the guard decision across thresholds (product v4).

"See a bad result, jump to the playground, iterate" (Langfuse). Here the lever is
the uncertainty-guard threshold: classify the query ONCE, then show how the
decision flips across a spread of thresholds — side by side. Side-effect-free
(no audit / metrics / cache writes), so it is safe to run repeatedly while tuning.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()

_DEFAULT_THRESHOLDS = [0.10, 0.40, 0.70, 0.95]


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


class CompareRequest(BaseModel):
    query: str
    thresholds: list[float] = Field(default_factory=lambda: list(_DEFAULT_THRESHOLDS))


@router.post("/playground/compare")
def playground_compare(req: CompareRequest) -> dict[str, Any]:
    """Classify the query once, then derive the guard decision per threshold."""
    s = _server()
    intent, conf = s.classify_intent(req.query)
    thresholds = sorted({round(max(0.0, min(1.0, t)), 2) for t in (req.thresholds or _DEFAULT_THRESHOLDS)})
    comparisons = []
    for t in thresholds:
        decision, reason = s.apply_guard(conf, threshold=t, intent=intent)
        comparisons.append(
            {
                "threshold": t,
                "decision": decision,
                "released": decision in ("PASSTHROUGH", "FLAG"),
                "reason": reason,
            }
        )
    distinct = sorted({c["decision"] for c in comparisons})
    return {
        "query": req.query,
        "intent": intent,
        "confidence": round(conf, 3),
        "comparisons": comparisons,
        "n_distinct_decisions": len(distinct),
        "note": (
            "Classification done once; the decision is re-derived per threshold (apply_guard). "
            "High-risk intents (fraud/crisis) escalate at any threshold — control "
            "proportional to risk. No side effects (does not write audit/metrics)."
        ),
    }


__all__ = ["router"]
