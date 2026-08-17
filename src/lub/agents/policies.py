"""
lub.agents.policies — refusal policies for CalibratedAgent.

All policies are dataclasses / pydantic-compatible. They accept a
confidence score (or a mapping of per-field confidences) and return a
gating decision. Concrete behavior is DEFER (v0.3).

.. note::
   This module's :class:`PolicyDecision` is the **agent-side dataclass**
   (``emit`` / ``action`` / ``rationale``). The top-level
   :mod:`lub.policies` exports a same-named **enum** used by the guard
   layer. The two are intentionally distinct -- see the cross-reference
   docstrings in both modules. The planned v0.3 rename is
   ``PolicyDecision`` (here) -> ``AgentDecision`` to remove the
   ambiguity; the alias is documented here rather than exported because
   the project linter strips bare aliases from module bodies. New code
   should import :class:`PolicyDecision` from this module by name today
   and migrate at the v0.3 cut.

.. note::
   ``# TODO`` markers have been retired in favor of ``DEFER (v0.3)``
   to disambiguate scaffold-debt from open bugs (per
   IMPROVEMENT_OPPORTUNITIES_2026-04-25.md §C).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol


class Policy(Protocol):
    """Minimal policy protocol. A policy decides, given a confidence value,
    whether to emit the raw output, redact it, or defer to a human.
    """

    def decide(self, confidence: float) -> PolicyDecision:
        """Decide whether to emit given a confidence score."""
        ...


@dataclass(frozen=True)
class PolicyDecision:
    """Outcome of a policy.

    Attributes:
        emit: True if the output should be emitted as-is.
        action: Token describing the action if not emit (e.g. "REQUIRES_HUMAN_REVIEW",
            "[REDACTED]", "OMIT").
        rationale: Short machine-readable rationale for audit trails.
    """

    emit: bool
    action: str | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class RefusalPolicy:
    """Single-threshold refusal policy.

    If confidence < threshold, emit the `below_threshold_action` string in
    the output's place.

    Attributes:
        threshold: Confidence threshold in [0, 1].
        below_threshold_action: Token emitted in place of the output when
            confidence falls below threshold. Defaults to
            "REQUIRES_HUMAN_REVIEW".
        method_name: Optional descriptive tag for audit trails (e.g.
            "semantic_entropy").
    """

    threshold: float = 0.5
    below_threshold_action: str = "REQUIRES_HUMAN_REVIEW"
    method_name: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError(f"threshold must be in [0, 1], got {self.threshold}")

    def decide(self, confidence: float) -> PolicyDecision:
        """Decide whether to emit given a confidence score."""
        if confidence >= self.threshold:
            return PolicyDecision(
                emit=True,
                rationale=f"confidence {confidence:.3f} >= threshold {self.threshold:.3f}",
            )
        return PolicyDecision(
            emit=False,
            action=self.below_threshold_action,
            rationale=f"confidence {confidence:.3f} < threshold {self.threshold:.3f}",
        )

    def apply(self, raw: Any, confidence: float) -> Any:
        """Apply the policy. DEFER (v0.3) — needs full per-field logic."""
        raise NotImplementedError(
            "RefusalPolicy.apply (structured-output gating) lands in v0.3. "
            "RefusalPolicy.decide works today for scalar-confidence use."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )


@dataclass(frozen=True)
class PerFieldPolicy:
    """Apply different thresholds to different output fields.

    Example::

        PerFieldPolicy(
            field_policies={
                "numeric_fields": RefusalPolicy(threshold=0.7, ...),
                "citation_fields": RefusalPolicy(threshold=0.5, ...),
            },
            default=RefusalPolicy(threshold=0.35),
        )
    """

    field_policies: dict[str, RefusalPolicy]
    default: RefusalPolicy

    def decide(self, confidence: float) -> PolicyDecision:
        """Reject scalar confidence; PerFieldPolicy requires per-field input."""
        raise NotImplementedError(
            "PerFieldPolicy needs field-level confidence. Use .decide_field(field, confidence)."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )

    def decide_field(self, field: str, confidence: float) -> PolicyDecision:
        """Decide for a specific named field. DEFER (v0.3)."""
        raise NotImplementedError(
            "PerFieldPolicy.decide_field is not yet implemented."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )


class PolicyCombinator(ABC):
    """Base for combining policies (And / Or / Conditional)."""

    @abstractmethod
    def decide(self, confidence: float) -> PolicyDecision:
        """Decide whether to emit given a confidence score."""
        raise NotImplementedError


@dataclass(frozen=True)
class AndPolicy(PolicyCombinator):
    """Emits only if all sub-policies emit."""

    policies: tuple[RefusalPolicy, ...]

    def decide(self, confidence: float) -> PolicyDecision:
        """Emit only if every sub-policy emits. DEFER (v0.3)."""
        raise NotImplementedError(
            "AndPolicy.decide is not yet implemented. Lands in v0.3."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )


@dataclass(frozen=True)
class OrPolicy(PolicyCombinator):
    """Emits if any sub-policy emits."""

    policies: tuple[RefusalPolicy, ...]

    def decide(self, confidence: float) -> PolicyDecision:
        """Emit if any sub-policy emits. DEFER (v0.3)."""
        raise NotImplementedError(
            "OrPolicy.decide is not yet implemented. Lands in v0.3."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )


@dataclass(frozen=True)
class ConditionalPolicy(PolicyCombinator):
    """Applies different policies depending on a predicate on the input.

    Useful when the right refusal threshold depends on the question type
    (e.g., numeric questions need tighter gating than summarization).
    """

    predicate: Any  # callable; typed Any to avoid premature constraint
    if_true: RefusalPolicy
    if_false: RefusalPolicy

    def decide(self, confidence: float) -> PolicyDecision:
        """Reject scalar confidence; ConditionalPolicy requires the input context."""
        raise NotImplementedError(
            "ConditionalPolicy.decide requires the input context; "
            "use .decide_for_input(input, confidence) instead. Not yet implemented."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )


__all__ = [
    "AndPolicy",
    "ConditionalPolicy",
    "OrPolicy",
    "PerFieldPolicy",
    "Policy",
    "PolicyCombinator",
    "PolicyDecision",
    "RefusalPolicy",
]
