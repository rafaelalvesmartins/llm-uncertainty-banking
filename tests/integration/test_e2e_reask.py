# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""End-to-end: pipeline → guard(REASK) → benchmark-style batch.

Covers gap #5 from the integration audit: :class:`PolicyDecision.REASK`
has unit coverage in ``test_guard_reask.py`` for single calls, but no
test runs REASK end-to-end across a benchmark-sized batch and checks:

* every low-confidence answer records ``reask_attempted=True``,
* at least one outcome falls through to :attr:`PolicyDecision.ABSTAIN`
  when the retry also fails,
* the aggregate decision distribution matches what a governance
  reviewer expects to see in an AI RMF MANAGE 2.4 report.
"""

from __future__ import annotations

from lub.guard import PolicyDecision, UncertaintyGuard
from lub.pipeline import UncertaintyPipeline


def _pipeline(refusal_threshold: float = 0.0) -> UncertaintyPipeline:
    return UncertaintyPipeline.from_pretrained(
        model="dummy-reask",
        backend="dummy",
        estimator="token_logprob",
        refusal_threshold=refusal_threshold,
    )


def test_reask_batch_emits_every_expected_decision() -> None:
    """Threshold 0.99 forces every first-pass answer to fail; max_retries=1
    makes the retry also fail (DummyBackend is deterministic), so every
    outcome must fall through to ABSTAIN with reask metadata populated.
    """
    pipe = _pipeline()
    guard = UncertaintyGuard(
        pipe,
        threshold=0.99,  # impossibly high — forces all to fail
        on_fail=PolicyDecision.REASK,
        max_reask_retries=1,
    )

    prompts = [f"What is banking concept #{i}?" for i in range(10)]
    outcomes = guard.batch(prompts)

    assert len(outcomes) == 10
    # Since the retry also fails, every call should fall through to ABSTAIN.
    decisions = {o.outcome.decision for o in outcomes}
    assert decisions == {PolicyDecision.ABSTAIN}

    # Each outcome must carry the reask audit trail (reask was attempted).
    for o in outcomes:
        meta = o.outcome.metadata
        assert meta["reask_attempted"] is True
        assert meta["reask_succeeded"] is False
        assert "first_pass_confidence" in meta
        assert o.rmf_subcategory == "MANAGE 2.3"  # ABSTAIN maps here


def test_reask_with_zero_retries_skips_retry_path() -> None:
    """``max_reask_retries=0`` short-circuits to ABSTAIN without calling
    the pipeline a second time, and records ``reask_attempted=False``.
    Verifies the documented fast path used when reask is too expensive
    to retry (e.g., paid API models).
    """
    pipe = _pipeline()
    guard = UncertaintyGuard(
        pipe,
        threshold=0.99,
        on_fail=PolicyDecision.REASK,
        max_reask_retries=0,
    )
    out = guard("Any prompt")

    assert out.outcome.decision == PolicyDecision.ABSTAIN
    assert out.outcome.metadata["reask_attempted"] is False
    assert out.outcome.metadata["reask_succeeded"] is False
    assert out.rmf_subcategory == "MANAGE 2.3"


def test_reask_passes_through_when_first_pass_succeeds() -> None:
    """If the first-pass confidence clears the threshold, the guard must
    take the PASSTHROUGH branch and never invoke the reask logic — so
    no ``reask_*`` metadata should be present.
    """
    pipe = _pipeline()
    # threshold 0.0 → every answer passes
    guard = UncertaintyGuard(
        pipe,
        threshold=0.0,
        on_fail=PolicyDecision.REASK,
    )
    out = guard("What is CET1?")
    assert out.outcome.decision == PolicyDecision.PASSTHROUGH
    assert out.outcome.passed is True
    # Passthrough path should not populate reask metadata.
    assert "reask_attempted" not in out.outcome.metadata
    assert out.output == out.raw.answer


def test_reask_batch_decision_distribution_matches_reporter_expectations() -> None:
    """Aggregate decision counts drive the AI RMF MANAGE 2.4 section of
    the report. Verifies that an all-low-confidence batch produces the
    exact counts governance expects to see: n_pass=0, n_abstain=n, no
    PASSTHROUGH/FLAG/RAISE leakage.
    """
    pipe = _pipeline()
    guard = UncertaintyGuard(
        pipe, threshold=0.99, on_fail=PolicyDecision.REASK, max_reask_retries=1,
    )
    outcomes = guard.batch([f"Q{i}" for i in range(5)])

    counts = {d: 0 for d in PolicyDecision}
    for o in outcomes:
        counts[o.outcome.decision] += 1

    assert counts[PolicyDecision.ABSTAIN] == 5
    assert counts[PolicyDecision.PASSTHROUGH] == 0
    assert counts[PolicyDecision.FLAG] == 0
    assert counts[PolicyDecision.RAISE] == 0
    # REASK itself should be zero here because every retry also failed
    # and the guard fell through — the ABSTAIN bucket absorbs them.
    assert counts[PolicyDecision.REASK] == 0
