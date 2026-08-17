# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Continuous effective challenge — the governance panel's verdict.

Bridge hub connection: SR 11-7 calls for *ongoing monitoring* and *effective
challenge*, and the console has always described them as processes. This
endpoint makes them a measurement an operator can read: it runs the same rule
the scheduled ``lub challenge-nightly`` job runs
(:func:`lub.challenge.nightly.run_nightly_challenge`), over this deployment's
own labelled intent samples, and returns the tri-state verdict.

Honesty, stated up front: the evidence is the intent catalog's labelled
example queries — the same single source of truth behind ``/calibration`` and
the SR 11-7 Outcome Analysis pillar — and the demo classifier's confidence is
a keyword heuristic. So a FAIL here is the gate working on a deliberately
simple classifier, not a defect being hidden. That is the point of showing it.

The verdict is deliberately tri-state; ``INCONCLUSIVE`` means the evidence was
insufficient to judge, which is not a pass. See the module docstring of
:mod:`lub.challenge.nightly`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()


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


def _ledger_from_labelled_samples(samples: list[dict[str, Any]]) -> Any:
    """Materialise an in-memory lub ledger from labelled classifier samples.

    The console does not persist a lub ledger — it keeps its own audit trail —
    so the evidence is replayed into an ephemeral one for the duration of the
    request. Nothing is written to disk and nothing outlives the call.
    """
    from lub.ledger import Ledger

    led = Ledger(":memory:")
    for smp in samples:
        qid = led.log_query(prompt=str(smp["query"]), domain="regulatory")
        aid = led.log_answer(
            query_id=qid,
            model="intent-classifier",
            backend="bridge-demo",
            answer=str(smp["predicted"]),
            cost=0.0,
        )
        led.log_score(answer_id=aid, method="confidence", value=float(smp["confidence"]))
        led.update_outcome(
            answer_id=aid,
            correct=bool(smp["correct"]),
            ground_truth=str(smp["expected"]),
        )
    return led


@router.get("/challenge/nightly")
def challenge_nightly(
    context: str = Query(
        "regulatory-qa",
        description="Bounded context whose calibration target applies. Defaults to the "
        "strictest one — defaulting to the loosest would be grading on a curve.",
    ),
    min_samples: int = Query(10, ge=1, description="Labelled answers required to judge."),
) -> dict[str, Any]:
    """Run continuous effective challenge over this deployment's labelled samples.

    Returns the same :class:`~lub.challenge.nightly.ChallengeVerdict` payload
    the scheduled job produces, so the screen and the nightly build cannot
    disagree about what PASS means.
    """
    from lub.challenge.nightly import run_nightly_challenge
    from lub.governance.contexts import default_registry

    try:
        ctx = default_registry().get(context)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"unknown bounded context: {context}") from exc

    s = _server()
    samples = s._intent_calibration_samples()
    led = _ledger_from_labelled_samples(samples)
    try:
        verdict = run_nightly_challenge(led, ctx, min_samples=min_samples)
    finally:
        led.close()

    payload = verdict.to_dict()
    payload["evidence_source"] = (
        "intent catalog labelled example queries (same source as /calibration and the "
        "SR 11-7 Outcome Analysis pillar)"
    )
    return payload
