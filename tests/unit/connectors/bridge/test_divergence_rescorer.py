# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for :mod:`lub.connectors.bridge.divergence_rescorer`.

The divergence rescorer wires :mod:`answer_scorer` onto Bridge's
``query.answer_divergence`` site. These tests pin the three-branch
behaviour of :meth:`DivergenceRescorer.apply`:

* no upstream guard verdict — declined fabrication, skip flagged in
  the audit payload;
* agent ≈ guard pipeline — cheap short-circuit, no scorer call;
* agent ≠ guard pipeline — scorer invoked, fresh ``GuardResult``
  returned, audit payload carries both pre- and post-rescoring
  verdicts so the BCB 4893 reviewer can confirm the calibration gap
  was closed for that release.

Also exercises threshold inheritance/override semantics, the
:func:`rescore_on_divergence` convenience wrapper, the dataclass
construction-time validation, and the standard pipeline edge cases
(empty input, banking PII, scorer exceptions).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from lub.connectors.bridge.divergence_rescorer import (
    DEFAULT_RESCORED_ABSTAIN_MARKER,
    DivergenceRescorer,
    RescoringOutcome,
    rescore_on_divergence,
)
from lub.guard import GuardResult, PolicyDecision, rmf_subcategory
from lub.policies import PolicyOutcome
from lub.types import UncertaintyResult

# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------


class _StubScorer:
    """Deterministic ``AnswerScorer`` that records calls and returns a fixed score."""

    def __init__(
        self,
        confidence: float,
        *,
        should_refuse: bool = False,
        raw_scores: dict[str, float] | None = None,
    ) -> None:
        self.confidence = confidence
        self.should_refuse = should_refuse
        self.raw_scores = raw_scores or {}
        self.calls: list[tuple[str, str]] = []

    def score(self, prompt: str, answer: str) -> UncertaintyResult:
        self.calls.append((prompt, answer))
        return UncertaintyResult(
            answer=answer,
            confidence=self.confidence,
            raw_scores=dict(self.raw_scores),
            should_refuse=self.should_refuse,
        )


class _ExplodingScorer:
    """Scorer that always raises — verifies error-propagation contract."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def score(self, prompt: str, answer: str) -> UncertaintyResult:
        raise self.exc


def _make_guard_result(
    pipeline_answer: str,
    *,
    confidence: float = 0.9,
    threshold: float = 0.7,
    decision: PolicyDecision = PolicyDecision.PASSTHROUGH,
) -> GuardResult:
    """Build a realistic ``GuardResult`` shaped like what the upstream guard emits."""
    raw = UncertaintyResult(
        answer=pipeline_answer,
        confidence=confidence,
        raw_scores={"entropy": 0.1},
    )
    passed = decision is PolicyDecision.PASSTHROUGH
    outcome = PolicyOutcome(
        decision=decision,
        confidence=confidence,
        threshold=threshold,
        passed=passed,
        answer=pipeline_answer,
        reason="test fixture verdict",
    )
    output = pipeline_answer if passed else "[ABSTAIN]"
    return GuardResult(
        raw=raw,
        outcome=outcome,
        output=output,
        rmf_subcategory=rmf_subcategory(decision),
    )


@pytest.fixture
def banking_prompt() -> str:
    return "Qual a taxa do CDB pré-fixado de 12 meses no Bradesco?"


@pytest.fixture
def agent_answer() -> str:
    return "A taxa atual do CDB pré-fixado de 12 meses é de 11.5% ao ano."


@pytest.fixture
def pipeline_answer() -> str:
    # Structurally different text — drives ``answers_diverge`` to True.
    return "Para um CDB, recomendamos consultar uma agência."


# ---------------------------------------------------------------------------
# Construction-time validation
# ---------------------------------------------------------------------------


class TestConstructionValidation:
    def test_default_threshold_override_is_none(self) -> None:
        rescorer = DivergenceRescorer(scorer=_StubScorer(0.5))
        assert rescorer.threshold_override is None

    def test_default_marker_is_distinct_from_upstream_guard(self) -> None:
        # An audit reader must be able to tell which gate fired.
        assert "answer-attributed" in DEFAULT_RESCORED_ABSTAIN_MARKER

    @pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.0, float("inf")])
    def test_out_of_range_threshold_raises(self, bad: float) -> None:
        with pytest.raises(ValueError, match=r"threshold_override must be in \[0, 1\]"):
            DivergenceRescorer(scorer=_StubScorer(0.5), threshold_override=bad)

    @pytest.mark.parametrize("ok", [0.0, 0.5, 1.0])
    def test_boundary_thresholds_accepted(self, ok: float) -> None:
        rescorer = DivergenceRescorer(scorer=_StubScorer(0.5), threshold_override=ok)
        assert rescorer.threshold_override == ok

    def test_dataclass_is_frozen(self) -> None:
        rescorer = DivergenceRescorer(scorer=_StubScorer(0.5))
        with pytest.raises(FrozenInstanceError):
            rescorer.threshold_override = 0.42  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Skip path: no upstream verdict
# ---------------------------------------------------------------------------


class TestNoUpstreamVerdict:
    def test_no_guard_result_returns_unrescored(
        self, banking_prompt: str, agent_answer: str
    ) -> None:
        scorer = _StubScorer(0.99)
        outcome = DivergenceRescorer(scorer=scorer).apply(
            banking_prompt, agent_answer, None
        )
        assert isinstance(outcome, RescoringOutcome)
        assert outcome.rescored is False
        assert outcome.guard_result is None
        assert outcome.audit_payload == {
            "rescored": False,
            "skip_reason": "no_guard_result",
        }

    def test_no_guard_result_does_not_invoke_scorer(
        self, banking_prompt: str, agent_answer: str
    ) -> None:
        # Cost-sensitive contract: rescorer must not pay scoring cost when
        # there is no upstream verdict to compare against.
        scorer = _StubScorer(0.5)
        DivergenceRescorer(scorer=scorer).apply(banking_prompt, agent_answer, None)
        assert scorer.calls == []


# ---------------------------------------------------------------------------
# Short-circuit: answers already aligned
# ---------------------------------------------------------------------------


class TestAnswersAligned:
    def test_identical_answers_short_circuit(
        self, banking_prompt: str, agent_answer: str
    ) -> None:
        guard = _make_guard_result(agent_answer, confidence=0.88)
        scorer = _StubScorer(0.1)  # would tank confidence if invoked
        outcome = DivergenceRescorer(scorer=scorer).apply(
            banking_prompt, agent_answer, guard
        )
        assert outcome.rescored is False
        assert outcome.guard_result is guard
        assert scorer.calls == []

    def test_whitespace_only_diff_short_circuits(self, banking_prompt: str) -> None:
        # ``answers_diverge`` is whitespace-collapsed; rescorer must inherit.
        guard = _make_guard_result("hello   world")
        scorer = _StubScorer(0.1)
        outcome = DivergenceRescorer(scorer=scorer).apply(
            banking_prompt, "hello world", guard
        )
        assert outcome.rescored is False
        assert scorer.calls == []

    def test_case_only_diff_short_circuits(self, banking_prompt: str) -> None:
        guard = _make_guard_result("BRADESCO PIX")
        scorer = _StubScorer(0.1)
        outcome = DivergenceRescorer(scorer=scorer).apply(
            banking_prompt, "bradesco pix", guard
        )
        assert outcome.rescored is False
        assert scorer.calls == []

    def test_aligned_payload_carries_pipeline_decision(
        self, banking_prompt: str, agent_answer: str
    ) -> None:
        guard = _make_guard_result(
            agent_answer, confidence=0.91, decision=PolicyDecision.PASSTHROUGH
        )
        outcome = DivergenceRescorer(scorer=_StubScorer(0.1)).apply(
            banking_prompt, agent_answer, guard
        )
        assert outcome.audit_payload == {
            "rescored": False,
            "skip_reason": "answers_aligned",
            "pipeline_confidence": pytest.approx(0.91),
            "pipeline_decision": PolicyDecision.PASSTHROUGH.value,
        }


# ---------------------------------------------------------------------------
# Hot path: divergent answers → rescoring
# ---------------------------------------------------------------------------


class TestDivergenceRescoring:
    def test_divergent_answers_invoke_scorer_with_agent_text(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        guard = _make_guard_result(pipeline_answer, confidence=0.95)
        scorer = _StubScorer(0.42)
        DivergenceRescorer(scorer=scorer).apply(banking_prompt, agent_answer, guard)
        # The whole point: the scorer is called with the **agent's** text.
        assert scorer.calls == [(banking_prompt, agent_answer)]

    def test_high_confidence_rescore_passes_through(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        guard = _make_guard_result(pipeline_answer, confidence=0.95, threshold=0.7)
        outcome = DivergenceRescorer(scorer=_StubScorer(0.85)).apply(
            banking_prompt, agent_answer, guard
        )
        assert outcome.rescored is True
        assert outcome.guard_result is not None
        assert outcome.guard_result.outcome.decision is PolicyDecision.PASSTHROUGH
        # The rescored envelope must be attributable to the agent's text.
        assert outcome.guard_result.raw.answer == agent_answer
        assert outcome.guard_result.output == agent_answer

    def test_low_confidence_rescore_abstains(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        # Upstream guard said PASSTHROUGH (its pipeline answer scored high),
        # but the agent's actual text scores below threshold → must abstain.
        # This is the central calibration-gap-closure assertion.
        guard = _make_guard_result(pipeline_answer, confidence=0.95, threshold=0.7)
        outcome = DivergenceRescorer(scorer=_StubScorer(0.40)).apply(
            banking_prompt, agent_answer, guard
        )
        assert outcome.rescored is True
        assert outcome.guard_result is not None
        assert outcome.guard_result.outcome.decision is PolicyDecision.ABSTAIN
        assert outcome.guard_result.output == DEFAULT_RESCORED_ABSTAIN_MARKER

    def test_threshold_inherited_from_upstream_guard(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        # Upstream threshold of 0.5 → agent confidence 0.6 passes.
        guard = _make_guard_result(pipeline_answer, confidence=0.95, threshold=0.5)
        outcome = DivergenceRescorer(scorer=_StubScorer(0.6)).apply(
            banking_prompt, agent_answer, guard
        )
        assert outcome.rescored is True
        assert outcome.guard_result is not None
        assert outcome.guard_result.outcome.threshold == pytest.approx(0.5)
        assert outcome.guard_result.outcome.decision is PolicyDecision.PASSTHROUGH

    def test_threshold_override_supersedes_upstream(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        # Upstream guard threshold is permissive (0.3) but we override to 0.9.
        # Agent confidence 0.6 must now abstain.
        guard = _make_guard_result(pipeline_answer, confidence=0.95, threshold=0.3)
        outcome = DivergenceRescorer(
            scorer=_StubScorer(0.6), threshold_override=0.9
        ).apply(banking_prompt, agent_answer, guard)
        assert outcome.rescored is True
        assert outcome.guard_result is not None
        assert outcome.guard_result.outcome.threshold == pytest.approx(0.9)
        assert outcome.guard_result.outcome.decision is PolicyDecision.ABSTAIN

    def test_custom_abstain_marker_used_in_output(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        guard = _make_guard_result(pipeline_answer, threshold=0.7)
        rescorer = DivergenceRescorer(
            scorer=_StubScorer(0.1),
            abstain_marker="[CUSTOM-ABSTAIN]",
        )
        outcome = rescorer.apply(banking_prompt, agent_answer, guard)
        assert outcome.guard_result is not None
        assert outcome.guard_result.output == "[CUSTOM-ABSTAIN]"

    def test_scorer_should_refuse_forces_abstain_even_above_threshold(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        # Even with high numeric confidence, an explicit refuse signal must
        # collapse to ABSTAIN — refusal is a hard gate, not a soft score.
        guard = _make_guard_result(pipeline_answer, threshold=0.5)
        scorer = _StubScorer(0.95, should_refuse=True)
        outcome = DivergenceRescorer(scorer=scorer).apply(
            banking_prompt, agent_answer, guard
        )
        assert outcome.rescored is True
        assert outcome.guard_result is not None
        assert outcome.guard_result.outcome.decision is PolicyDecision.ABSTAIN
        assert outcome.audit_payload["agent_should_refuse"] is True

    def test_upstream_abstain_does_not_prevent_rescoring(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        # Even if the upstream guard already decided ABSTAIN, the rescorer
        # may yield a different verdict because it scores the agent's text.
        guard = _make_guard_result(
            pipeline_answer,
            confidence=0.30,
            threshold=0.70,
            decision=PolicyDecision.ABSTAIN,
        )
        outcome = DivergenceRescorer(scorer=_StubScorer(0.85)).apply(
            banking_prompt, agent_answer, guard
        )
        assert outcome.rescored is True
        assert outcome.guard_result is not None
        assert outcome.guard_result.outcome.decision is PolicyDecision.PASSTHROUGH

    def test_rescored_envelope_uses_answer_scorer_namespace(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        # The rescored ``GuardResult`` must tag its metadata so a BCB 4893
        # auditor can tell that this verdict came from the post-hoc scorer
        # rather than from the upstream pipeline.
        guard = _make_guard_result(pipeline_answer, threshold=0.7)
        outcome = DivergenceRescorer(scorer=_StubScorer(0.9)).apply(
            banking_prompt, agent_answer, guard
        )
        assert outcome.guard_result is not None
        assert (
            outcome.guard_result.outcome.metadata.get("scorer")
            == "lub.bridge.answer_scorer"
        )


# ---------------------------------------------------------------------------
# Audit payload — BCB 4893 reviewer needs both pre- and post- verdicts
# ---------------------------------------------------------------------------


class TestAuditPayload:
    def test_rescored_payload_carries_both_decisions(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        guard = _make_guard_result(pipeline_answer, confidence=0.92, threshold=0.7)
        outcome = DivergenceRescorer(scorer=_StubScorer(0.50)).apply(
            banking_prompt, agent_answer, guard
        )
        payload = outcome.audit_payload
        assert payload["rescored"] is True
        assert payload["scorer"] == "lub.bridge.answer_scorer"
        assert payload["threshold"] == pytest.approx(0.7)
        assert payload["pipeline_confidence"] == pytest.approx(0.92)
        assert payload["pipeline_decision"] == PolicyDecision.PASSTHROUGH.value
        assert payload["agent_confidence"] == pytest.approx(0.50)
        assert payload["agent_decision"] == PolicyDecision.ABSTAIN.value
        assert payload["agent_should_refuse"] is False

    def test_audit_payload_values_are_serialization_safe(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        # All values must be primitives the audit serializer can dump
        # without custom encoder logic.
        guard = _make_guard_result(pipeline_answer)
        outcome = DivergenceRescorer(scorer=_StubScorer(0.8)).apply(
            banking_prompt, agent_answer, guard
        )
        for key, val in outcome.audit_payload.items():
            assert isinstance(key, str)
            assert isinstance(val, (bool, int, float, str))


# ---------------------------------------------------------------------------
# Edge cases — empty input, banking PII, scorer exceptions
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_prompt_passes_through_to_scorer(self) -> None:
        guard = _make_guard_result("alguma resposta")
        scorer = _StubScorer(0.8)
        DivergenceRescorer(scorer=scorer).apply("", "outra resposta", guard)
        assert scorer.calls == [("", "outra resposta")]

    def test_two_empty_answers_short_circuit(self) -> None:
        # Both empty → not divergent → no rescore.
        guard = _make_guard_result("")
        scorer = _StubScorer(0.1)
        outcome = DivergenceRescorer(scorer=scorer).apply("prompt", "", guard)
        assert outcome.rescored is False
        assert scorer.calls == []

    def test_empty_agent_answer_diverges_from_nonempty_pipeline(self) -> None:
        guard = _make_guard_result("pipeline said something")
        scorer = _StubScorer(0.1)  # empty answer rightly scores low
        outcome = DivergenceRescorer(scorer=scorer).apply("prompt", "", guard)
        assert outcome.rescored is True
        assert scorer.calls == [("prompt", "")]
        assert outcome.guard_result is not None
        assert outcome.guard_result.outcome.decision is PolicyDecision.ABSTAIN

    def test_pii_in_answer_is_not_logged_in_audit_payload(self) -> None:
        # Audit payload must not echo customer text — only decisions and
        # numeric scores. Verifies we don't leak PII through the audit
        # channel even when the agent's answer accidentally contains it.
        pii_answer = "Seu CPF 123.456.789-00 está vinculado à conta 12345-6."
        guard = _make_guard_result("Não posso compartilhar dados pessoais.")
        outcome = DivergenceRescorer(scorer=_StubScorer(0.8)).apply(
            "Qual meu CPF?", pii_answer, guard
        )
        payload_text = repr(outcome.audit_payload)
        assert "123.456.789-00" not in payload_text
        assert "12345-6" not in payload_text

    def test_scorer_exception_propagates(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        # The rescorer does not catch scorer exceptions — that's each
        # scorer implementation's job (e.g. ``PTrueScorer`` returns
        # ``confidence=0`` on verifier failure). A bare exception from a
        # non-conforming scorer must surface so it is not silently
        # swallowed in production.
        guard = _make_guard_result(pipeline_answer)
        scorer = _ExplodingScorer(RuntimeError("backend timeout"))
        with pytest.raises(RuntimeError, match="backend timeout"):
            DivergenceRescorer(scorer=scorer).apply(
                banking_prompt, agent_answer, guard
            )

    def test_rescore_preserves_agent_answer_verbatim(self) -> None:
        # Even for tricky unicode and punctuation, the agent's text must
        # round-trip into the GuardResult unchanged.
        agent = "Não — o IOF é de 0,38% (zero vírgula trinta e oito por cento)."
        guard = _make_guard_result("o IOF varia")
        outcome = DivergenceRescorer(scorer=_StubScorer(0.9)).apply(
            "Qual o IOF?", agent, guard
        )
        assert outcome.guard_result is not None
        assert outcome.guard_result.raw.answer == agent
        assert outcome.guard_result.output == agent


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


class TestRescoreOnDivergenceWrapper:
    def test_wrapper_matches_dataclass_call(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        guard = _make_guard_result(pipeline_answer, threshold=0.6)
        scorer_a = _StubScorer(0.75)
        scorer_b = _StubScorer(0.75)

        direct = DivergenceRescorer(scorer=scorer_a).apply(
            banking_prompt, agent_answer, guard
        )
        wrapped = rescore_on_divergence(
            banking_prompt, agent_answer, guard, scorer_b
        )

        assert direct.rescored == wrapped.rescored
        assert direct.audit_payload == wrapped.audit_payload
        assert direct.guard_result is not None
        assert wrapped.guard_result is not None
        assert (
            direct.guard_result.outcome.decision
            == wrapped.guard_result.outcome.decision
        )

    def test_wrapper_forwards_threshold_override(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        guard = _make_guard_result(pipeline_answer, threshold=0.3)
        outcome = rescore_on_divergence(
            banking_prompt,
            agent_answer,
            guard,
            _StubScorer(0.55),
            threshold_override=0.8,
        )
        assert outcome.guard_result is not None
        assert outcome.guard_result.outcome.threshold == pytest.approx(0.8)
        assert outcome.guard_result.outcome.decision is PolicyDecision.ABSTAIN

    def test_wrapper_forwards_custom_abstain_marker(
        self,
        banking_prompt: str,
        agent_answer: str,
        pipeline_answer: str,
    ) -> None:
        guard = _make_guard_result(pipeline_answer, threshold=0.9)
        outcome = rescore_on_divergence(
            banking_prompt,
            agent_answer,
            guard,
            _StubScorer(0.1),
            abstain_marker="[WRAPPED-ABSTAIN]",
        )
        assert outcome.guard_result is not None
        assert outcome.guard_result.output == "[WRAPPED-ABSTAIN]"

    def test_wrapper_short_circuits_on_no_guard(
        self, banking_prompt: str, agent_answer: str
    ) -> None:
        scorer = _StubScorer(0.5)
        outcome = rescore_on_divergence(banking_prompt, agent_answer, None, scorer)
        assert outcome.rescored is False
        assert outcome.guard_result is None
        assert scorer.calls == []


# ---------------------------------------------------------------------------
# RescoringOutcome dataclass
# ---------------------------------------------------------------------------


class TestRescoringOutcome:
    def test_default_audit_payload_is_empty_dict(self) -> None:
        out = RescoringOutcome(guard_result=None, rescored=False)
        assert out.audit_payload == {}

    def test_is_frozen(self) -> None:
        out = RescoringOutcome(guard_result=None, rescored=False)
        with pytest.raises(FrozenInstanceError):
            out.rescored = True  # type: ignore[misc]

    def test_distinct_instances_do_not_share_default_payload(self) -> None:
        # Regression guard for mutable default — each instance must get
        # its own dict (``field(default_factory=dict)`` not ``= {}``).
        a = RescoringOutcome(guard_result=None, rescored=False)
        b = RescoringOutcome(guard_result=None, rescored=False)
        a.audit_payload["k"] = "v"
        assert "k" not in b.audit_payload
