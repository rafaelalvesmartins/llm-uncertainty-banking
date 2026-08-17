# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Uncertainty-gated answer guard.

Holds only the **executor** part of the uncertainty-gating subsystem:

* :class:`UncertaintyGuard` — a thin adapter over
  :class:`~lub.pipeline.UncertaintyPipeline` that returns a structured
  :class:`GuardResult` per prompt. Each guard call produces a
  :class:`~lub.policies.PolicyOutcome` that the L5 AI RMF reporter can
  aggregate into a MANAGE-section "actions taken" table.
* :class:`GuardResult` — the per-prompt result envelope (raw estimator
  result + policy outcome + post-policy answer).

Policy *definitions* (:class:`~lub.policies.PolicyDecision`,
:class:`~lub.policies.PolicyOutcome`, :func:`~lub.policies.rmf_subcategory`)
moved to :mod:`lub.policies` in the 2026-04-25 refactor (ADR-005).
This module re-exports them for backwards compatibility, so
``from lub.guard import PolicyDecision`` continues to work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog

from lub.types import UncertaintyResult

# ---------------------------------------------------------------------------
# Policy types (previously in lub.policies, now defined here to avoid
# circular imports — lub.policies re-exports these for backwards compat)
# ---------------------------------------------------------------------------


class PolicyDecision(StrEnum):
    """Action taken when an estimator's confidence falls below threshold."""

    ABSTAIN = "abstain"
    ESCALATE = "escalate"
    FLAG = "flag"
    PASSTHROUGH = "passthrough"
    RAISE = "raise"
    REASK = "reask"


@dataclass(frozen=True)
class PolicyOutcome:
    """The structured record of one policy evaluation."""

    decision: PolicyDecision
    confidence: float
    threshold: float
    passed: bool
    answer: str | None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the guard decision to a JSON-compatible dict."""
        return {
            "decision": self.decision.value,
            "confidence": float(self.confidence),
            "threshold": float(self.threshold),
            "passed": bool(self.passed),
            "answer": self.answer,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


_RMF_SUBCATEGORY: dict[PolicyDecision, str] = {
    PolicyDecision.ABSTAIN: "MANAGE 2.3",
    # Escalation supersedes the model's own output with a stronger system
    # (or a human), which is the MANAGE 2.4 "supersede / disengage"
    # mechanism rather than the MANAGE 2.3 recovery procedure.
    PolicyDecision.ESCALATE: "MANAGE 2.4",
    PolicyDecision.FLAG: "MANAGE 2.4",
    PolicyDecision.PASSTHROUGH: "GOVERN 3.2",
    PolicyDecision.RAISE: "MANAGE 2.3",
    PolicyDecision.REASK: "MANAGE 2.4",
}


def rmf_subcategory(decision: PolicyDecision) -> str:
    """Return the NIST AI RMF 1.0 sub-category id for *decision*."""
    return _RMF_SUBCATEGORY[decision]


# ---------------------------------------------------------------------------
# Guard implementation
# ---------------------------------------------------------------------------

_LOG = structlog.get_logger("lub.guard")

if TYPE_CHECKING:
    from lub.protocols import PipelineProto


DEFAULT_ABSTAIN_MARKER = "[ABSTAIN: confidence below threshold]"

ToolFn = Callable[[str], str]
"""Signature for a retrieval / tool callable gated by UQ-gated dispatch."""


@dataclass(frozen=True)
class GuardResult:
    """Outcome of a single guarded call.

    Attributes
    ----------
    raw:
        The underlying :class:`~lub.types.UncertaintyResult` as
        produced by the estimator, untouched by policy logic.
    outcome:
        The :class:`~lub.policies.PolicyOutcome` describing what the
        guard decided and why.
    output:
        The post-policy answer. Equal to ``raw.answer`` for
        PASSTHROUGH and FLAG; equal to the abstain marker for
        ABSTAIN; undefined for RAISE (the call raised).
    rmf_subcategory:
        The NIST AI RMF 1.0 sub-category attributed to this call,
        derived from ``outcome.decision``.
    """

    raw: UncertaintyResult
    outcome: PolicyOutcome
    output: str
    rmf_subcategory: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the uncertainty result to a JSON-compatible dict."""
        return {
            "raw": {
                "answer": self.raw.answer,
                "confidence": float(self.raw.confidence),
                "should_refuse": bool(self.raw.should_refuse),
                "raw_scores": dict(self.raw.raw_scores),
            },
            "outcome": self.outcome.to_dict(),
            "output": self.output,
            "rmf_subcategory": self.rmf_subcategory,
        }

    def to_otel_attributes(self) -> dict[str, str | float | bool]:
        """Return OpenTelemetry-compatible span attributes.

        Follows the OpenLLMetry / OpenInference semantic convention
        (``gen_ai.*`` namespace) so LUB guard results can travel through
        any existing OTEL collector (Datadog, Grafana, Honeycomb) without
        a bespoke sink. Add these to an OTEL span via
        ``span.set_attributes(guard_result.to_otel_attributes())``.

        See: https://github.com/traceloop/openllmetry
        """
        attrs: dict[str, str | float | bool] = {
            "gen_ai.system": "lub",
            "lub.guard.decision": str(self.outcome.decision),
            "lub.guard.passed": bool(self.outcome.passed),
            "lub.guard.confidence": float(self.raw.confidence),
            "lub.guard.threshold": float(self.outcome.threshold),
            "lub.guard.should_refuse": bool(self.raw.should_refuse),
            "lub.guard.rmf_subcategory": self.rmf_subcategory,
        }
        if self.outcome.metadata.get("tool_invoked") is not None:
            attrs["lub.guard.tool_invoked"] = bool(self.outcome.metadata["tool_invoked"])
        if self.outcome.metadata.get("uala_gate") is not None:
            attrs["lub.guard.uala_gate"] = float(self.outcome.metadata["uala_gate"])
        return attrs


class UncertaintyGuard:
    """Wrap an :class:`UncertaintyPipeline` with an explicit policy.

    Parameters
    ----------
    pipeline:
        Any pipeline object exposing ``answer(prompt) -> UncertaintyResult``.
    threshold:
        Confidence threshold in ``[0, 1]``. Calls with confidence
        strictly below this value fail the guard.
    on_fail:
        :class:`PolicyDecision` applied when the guard fails. Defaults
        to ABSTAIN, the safe choice in regulated settings.
    abstain_marker:
        String returned as the answer when the guard abstains.
        Override for custom abstention routing — e.g., return a JSON
        structure that triggers a human-review queue downstream.
    max_reask_retries:
        Maximum number of retry attempts when ``on_fail`` is
        :attr:`PolicyDecision.REASK`. Defaults to ``1``. Set to ``0``
        to skip the reask entirely and fall through to ABSTAIN
        immediately.
    escalate_to:
        Stronger pipeline used when ``on_fail`` is
        :attr:`PolicyDecision.ESCALATE`. Required for that policy and
        ignored by every other one — a target configured alongside a
        non-ESCALATE policy never routes, so escalation can never
        happen by accident. For a cascade of three or more tiers use
        :class:`~lub.orchestration.router.TieredRouter` instead; this
        parameter covers the two-tier case without pulling in the
        router's cost-accounting machinery.
    escalate_to_name:
        Audit label for the escalation target, recorded as
        ``escalated_to`` in the outcome metadata.
    """

    def __init__(
        self,
        pipeline: PipelineProto,
        threshold: float = 0.5,
        on_fail: PolicyDecision = PolicyDecision.ABSTAIN,
        abstain_marker: str = DEFAULT_ABSTAIN_MARKER,
        max_reask_retries: int = 1,
        escalate_to: PipelineProto | None = None,
        escalate_to_name: str = "escalation",
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be in [0, 1], got {threshold}")
        if not isinstance(on_fail, PolicyDecision):
            raise TypeError(f"on_fail must be a PolicyDecision, got {type(on_fail).__name__}")
        if on_fail is PolicyDecision.ESCALATE and escalate_to is None:
            # Fail closed: silently degrading to ABSTAIN would hide a
            # misconfigured deployment behind a plausible-looking refusal.
            raise ValueError(
                "on_fail=PolicyDecision.ESCALATE requires an escalate_to pipeline; "
                "pass the stronger tier explicitly, or use PolicyDecision.ABSTAIN."
            )
        self.pipeline = pipeline
        self.threshold = float(threshold)
        self.on_fail = on_fail
        self.abstain_marker = abstain_marker
        self.max_reask_retries = max_reask_retries
        self.escalate_to = escalate_to
        self.escalate_to_name = escalate_to_name

    def __call__(self, prompt: str, **kwargs: Any) -> GuardResult:
        _LOG.debug("guard.call.start", threshold=self.threshold, on_fail=str(self.on_fail))
        raw = self.pipeline.answer(prompt, **kwargs)
        passed = raw.confidence >= self.threshold

        if passed:
            decision = PolicyDecision.PASSTHROUGH
            output: str = raw.answer
            reason = "confidence >= threshold"
        else:
            decision = self.on_fail
            if decision is PolicyDecision.RAISE:
                _LOG.warning(
                    "guard.raise",
                    confidence=f"{raw.confidence:.4f}",
                    threshold=f"{self.threshold:.4f}",
                )
                raise RuntimeError(
                    f"UncertaintyGuard raised: confidence {raw.confidence:.4f} "
                    f"< threshold {self.threshold:.4f}"
                )
            if decision is PolicyDecision.REASK:
                return self._handle_reask(prompt, raw, **kwargs)
            if decision is PolicyDecision.ESCALATE:
                return self._handle_escalate(prompt, raw, **kwargs)
            output = self.abstain_marker if decision is PolicyDecision.ABSTAIN else raw.answer
            reason = f"confidence {raw.confidence:.4f} < threshold {self.threshold:.4f}"

        _LOG.debug(
            "guard.call.done",
            decision=str(decision),
            passed=passed,
            confidence=f"{raw.confidence:.4f}",
        )
        outcome = PolicyOutcome(
            decision=decision,
            confidence=float(raw.confidence),
            threshold=self.threshold,
            passed=bool(passed),
            answer=raw.answer,
            reason=reason,
            metadata=dict(raw.raw_scores),
        )
        return GuardResult(
            raw=raw,
            outcome=outcome,
            output=output,
            rmf_subcategory=rmf_subcategory(decision),
        )

    _REASK_PREFIX = (
        "Your previous answer had low confidence. Please reconsider carefully "
        "and provide your best answer. If you are unsure, say so explicitly.\n\n"
    )

    def _handle_reask(
        self,
        prompt: str,
        first_raw: UncertaintyResult,
        **kwargs: Any,
    ) -> GuardResult:
        """Retry the prompt with a corrective instruction.

        If ``max_reask_retries`` is ``0``, skip the retry entirely and
        fall through to ABSTAIN.  Otherwise, retry up to
        ``max_reask_retries`` times.  If any retry meets the threshold,
        return REASK with the new answer.  If all retries fail, fall
        through to ABSTAIN.  Inspired by Guardrails AI
        ``OnFailAction.REASK``.
        """
        _LOG.info(
            "guard.reask",
            first_confidence=f"{first_raw.confidence:.4f}",
            threshold=f"{self.threshold:.4f}",
            max_retries=self.max_reask_retries,
        )
        if self.max_reask_retries <= 0:
            _LOG.debug("guard.reask.skipped", reason="max_reask_retries=0")
            metadata = {
                **dict(first_raw.raw_scores),
                "first_pass_confidence": float(first_raw.confidence),
                "reask_attempted": False,
                "reask_succeeded": False,
            }
            outcome = PolicyOutcome(
                decision=PolicyDecision.ABSTAIN,
                confidence=float(first_raw.confidence),
                threshold=self.threshold,
                passed=False,
                answer=first_raw.answer,
                reason=(
                    f"reask skipped (max_reask_retries=0): confidence "
                    f"{first_raw.confidence:.4f} < threshold {self.threshold:.4f}; "
                    f"fell through to ABSTAIN"
                ),
                metadata=metadata,
            )
            return GuardResult(
                raw=first_raw,
                outcome=outcome,
                output=self.abstain_marker,
                rmf_subcategory=rmf_subcategory(PolicyDecision.ABSTAIN),
            )

        reask_prompt = self._REASK_PREFIX + prompt
        retry = self.pipeline.answer(reask_prompt, **kwargs)
        retry_passed = retry.confidence >= self.threshold

        if retry_passed:
            decision = PolicyDecision.REASK
            output = retry.answer
            reason = (
                f"reask succeeded: first confidence {first_raw.confidence:.4f} "
                f"< threshold {self.threshold:.4f}, retry confidence "
                f"{retry.confidence:.4f} >= threshold"
            )
            raw_for_result = retry
        else:
            # Retry also failed — fall through to ABSTAIN.
            decision = PolicyDecision.ABSTAIN
            output = self.abstain_marker
            reason = (
                f"reask failed: first confidence {first_raw.confidence:.4f}, "
                f"retry confidence {retry.confidence:.4f}, both "
                f"< threshold {self.threshold:.4f}; fell through to ABSTAIN"
            )
            raw_for_result = retry

        _LOG.debug(
            "guard.reask.done",
            decision=str(decision),
            retry_passed=retry_passed,
            first_confidence=f"{first_raw.confidence:.4f}",
            retry_confidence=f"{retry.confidence:.4f}",
        )
        metadata = {
            **dict(retry.raw_scores),
            "first_pass_confidence": float(first_raw.confidence),
            "reask_attempted": True,
            "reask_succeeded": retry_passed,
        }
        outcome = PolicyOutcome(
            decision=decision,
            confidence=float(retry.confidence),
            threshold=self.threshold,
            passed=retry_passed,
            answer=retry.answer,
            reason=reason,
            metadata=metadata,
        )
        return GuardResult(
            raw=raw_for_result,
            outcome=outcome,
            output=output,
            rmf_subcategory=rmf_subcategory(decision),
        )

    def _handle_escalate(
        self,
        prompt: str,
        first_raw: UncertaintyResult,
        **kwargs: Any,
    ) -> GuardResult:
        """Re-run the *verbatim* prompt against the stronger tier.

        This is the deferral half of selective prediction: rather than
        refusing outright, hand the question to a system more likely to
        answer it. Unlike :meth:`_handle_reask`, the prompt is passed
        through unchanged — the customer's question was never the
        problem, the cheap tier's competence was.

        If the stronger tier clears the threshold its answer is
        returned with an ESCALATE decision. If it does not, the guard
        falls through to ABSTAIN and attaches a human-review package
        (both drafts plus both confidences) so the reviewer picking the
        case up does not have to re-derive what the models already said.
        """
        assert self.escalate_to is not None  # noqa: S101 — enforced in __init__.
        _LOG.info(
            "guard.escalate",
            first_confidence=f"{first_raw.confidence:.4f}",
            threshold=f"{self.threshold:.4f}",
            target=self.escalate_to_name,
        )
        escalated = self.escalate_to.answer(prompt, **kwargs)
        escalated_passed = escalated.confidence >= self.threshold

        metadata: dict[str, Any] = {
            **dict(escalated.raw_scores),
            "first_pass_confidence": float(first_raw.confidence),
            "escalation_attempted": True,
            "escalation_succeeded": bool(escalated_passed),
            "escalated_to": self.escalate_to_name,
        }

        if escalated_passed:
            decision = PolicyDecision.ESCALATE
            output = escalated.answer
            reason = (
                f"escalated to {self.escalate_to_name}: first confidence "
                f"{first_raw.confidence:.4f} < threshold {self.threshold:.4f}, "
                f"escalated confidence {escalated.confidence:.4f} >= threshold"
            )
        else:
            decision = PolicyDecision.ABSTAIN
            output = self.abstain_marker
            reason = (
                f"escalation to {self.escalate_to_name} failed: first confidence "
                f"{first_raw.confidence:.4f}, escalated confidence "
                f"{escalated.confidence:.4f}, both < threshold "
                f"{self.threshold:.4f}; fell through to ABSTAIN"
            )
            metadata["human_review_required"] = True
            metadata["primary_answer"] = first_raw.answer
            metadata["escalation_answer"] = escalated.answer

        _LOG.debug(
            "guard.escalate.done",
            decision=str(decision),
            escalation_succeeded=escalated_passed,
            escalated_confidence=f"{escalated.confidence:.4f}",
        )
        outcome = PolicyOutcome(
            decision=decision,
            confidence=float(escalated.confidence),
            threshold=self.threshold,
            passed=bool(escalated_passed),
            answer=escalated.answer,
            reason=reason,
            metadata=metadata,
        )
        return GuardResult(
            raw=escalated,
            outcome=outcome,
            output=output,
            rmf_subcategory=rmf_subcategory(decision),
        )

    def gated_tool_call(
        self,
        prompt: str,
        tool: ToolFn,
        *,
        uncertainty_threshold: float | None = None,
        **kwargs: Any,
    ) -> GuardResult:
        """UQ-gated tool dispatch (Han, Buntine, Shareghi, ACL 2024).

        Answers ``prompt`` through the pipeline. If the model is confident
        (``confidence >= uncertainty_threshold``), returns the parametric
        answer directly and never invokes ``tool`` — a banking agent can
        skip RAG or document-retrieval calls that the LLM already knows.
        If the model is uncertain, invokes ``tool(prompt)`` to fetch
        external context, then re-runs the pipeline with the tool output
        prepended and returns the guarded result.

        Defaults ``uncertainty_threshold`` to :attr:`threshold` (the
        same level the abstain/flag policy uses) so callers can share
        one confidence bar for both refusal and tool gating.

        Reference: *Towards Uncertainty-Aware Language Agent (UALA)*,
        arXiv:2401.14016.
        """
        gate = self.threshold if uncertainty_threshold is None else float(uncertainty_threshold)
        if not 0.0 <= gate <= 1.0:
            raise ValueError(f"uncertainty_threshold must be in [0, 1], got {gate}")

        first_pass = self(prompt, **kwargs)
        if first_pass.raw.confidence >= gate:
            # Tool skipped — record the decision in metadata for audit.
            outcome = first_pass.outcome
            augmented_metadata = {**outcome.metadata, "tool_invoked": False, "uala_gate": gate}
            return GuardResult(
                raw=first_pass.raw,
                outcome=PolicyOutcome(
                    decision=outcome.decision,
                    confidence=outcome.confidence,
                    threshold=outcome.threshold,
                    passed=outcome.passed,
                    answer=outcome.answer,
                    reason=f"{outcome.reason} (UALA gate: confidence >= {gate:.3f}, tool skipped)",
                    metadata=augmented_metadata,
                ),
                output=first_pass.output,
                rmf_subcategory=first_pass.rmf_subcategory,
            )

        # Uncertain — invoke the tool and re-prompt with the context.
        try:
            tool_output = tool(prompt)
        except Exception as exc:
            _LOG.warning(
                "guard.gated_tool_call.tool_failed",
                error=str(exc),
                confidence=f"{first_pass.raw.confidence:.4f}",
            )
            # Tool failure → fall back to first-pass result with ABSTAIN.
            return GuardResult(
                raw=first_pass.raw,
                outcome=PolicyOutcome(
                    decision=PolicyDecision.ABSTAIN,
                    confidence=float(first_pass.raw.confidence),
                    threshold=self.threshold,
                    passed=False,
                    answer=first_pass.raw.answer,
                    reason=f"tool raised {type(exc).__name__}: {exc}",
                    metadata={
                        **first_pass.outcome.metadata,
                        "tool_invoked": True,
                        "tool_error": str(exc),
                        "uala_gate": gate,
                    },
                ),
                output=self.abstain_marker,
                rmf_subcategory=rmf_subcategory(PolicyDecision.ABSTAIN),
            )
        augmented_prompt = f"Context from tool:\n{tool_output}\n\n{prompt}"
        second_pass = self(augmented_prompt, **kwargs)
        augmented_metadata = {
            **second_pass.outcome.metadata,
            "tool_invoked": True,
            "uala_gate": gate,
            "first_pass_confidence": float(first_pass.raw.confidence),
        }
        return GuardResult(
            raw=second_pass.raw,
            outcome=PolicyOutcome(
                decision=second_pass.outcome.decision,
                confidence=second_pass.outcome.confidence,
                threshold=second_pass.outcome.threshold,
                passed=second_pass.outcome.passed,
                answer=second_pass.outcome.answer,
                reason=f"{second_pass.outcome.reason} (UALA gate: first-pass confidence {first_pass.raw.confidence:.3f} < {gate:.3f}, tool invoked)",
                metadata=augmented_metadata,
            ),
            output=second_pass.output,
            rmf_subcategory=second_pass.rmf_subcategory,
        )

    def batch(self, prompts: list[str], **kwargs: Any) -> list[GuardResult]:
        """Guard a list of prompts; never raises, even with RAISE policy.

        RAISE is converted to an aborting return for batch use so one
        bad prompt does not kill the whole run. Use ``__call__`` per
        prompt if hard-fail semantics are required.
        """
        results: list[GuardResult] = []
        for p in prompts:
            try:
                results.append(self(p, **kwargs))
            except RuntimeError as exc:
                raw = UncertaintyResult(answer="", confidence=0.0)
                outcome = PolicyOutcome(
                    decision=PolicyDecision.ABSTAIN,
                    confidence=0.0,
                    threshold=self.threshold,
                    passed=False,
                    answer=None,
                    reason=f"raised: {exc}",
                    metadata={},
                )
                results.append(
                    GuardResult(
                        raw=raw,
                        outcome=outcome,
                        output=self.abstain_marker,
                        rmf_subcategory=rmf_subcategory(PolicyDecision.ABSTAIN),
                    )
                )
        return results


__all__ = [
    "DEFAULT_ABSTAIN_MARKER",
    "GuardResult",
    "PolicyDecision",
    "PolicyOutcome",
    "ToolFn",
    "UncertaintyGuard",
    "rmf_subcategory",
]
