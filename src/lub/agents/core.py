"""
lub.agents.core — CalibratedAgent and RunReport.

All concrete behavior is DEFER (v0.3). This module intentionally ships
as a scaffold with ``NotImplementedError`` stubs so tests and downstream
consumers can type-check against the shape before the implementation
lands. See RFC-001 for the full design.

.. note::
   ``# TODO`` markers in this subpackage have been retired in favor of
   ``DEFER (v0.3)`` so reviewers can tell scaffold-debt from open bugs
   at a glance (per IMPROVEMENT_OPPORTUNITIES_2026-04-25.md §C). The
   ``Backend`` / ``UncertaintyEstimator`` / ``Policy`` aliases below
   already use this convention; method docstrings now match.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

__all__ = [
    "Backend",
    "CalibratedAgent",
    "Policy",
    "RunReport",
    "UncertaintyEstimator",
]

try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    BaseModel = object  # type: ignore[misc,assignment]

# Re-exported lazily to avoid forcing a hard import cycle with lub.wrappers
# and lub.uncertainty during scaffolding.
Backend = Any  # DEFER (v0.3): replace with lub.wrappers.LLMBackend once interface stabilizes
UncertaintyEstimator = Any  # DEFER (v0.3): replace with lub.uncertainty.base.UncertaintyEstimator
Policy = Any  # DEFER (v0.3): replace with lub.agents.policies.RefusalPolicy protocol

TInput = TypeVar("TInput")
TOutput = TypeVar("TOutput")


@dataclass(frozen=True)
class RunReport(Generic[TInput, TOutput]):
    """Structured result of one agent.run() call.

    Contains the raw LLM output, the parsed output after refusal-policy
    gating, the uncertainty numbers that drove the decision, and enough
    metadata for a compliance reviewer to reconstruct what happened.
    """

    input: TInput
    output: TOutput
    confidence: float
    refusal_flags: dict[str, str] = field(default_factory=dict)
    audit_trail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize the report to JSON. DEFER (v0.3)."""
        raise NotImplementedError(
            "RunReport.to_json is not yet implemented. Tracked in RFC-001."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )

    def to_oscal(self) -> dict[str, Any]:
        """Emit an OSCAL-compatible representation. DEFER (v0.3)."""
        raise NotImplementedError(
            "RunReport.to_oscal is not yet implemented. Requires lub.reports.oscal."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )


class CalibratedAgent(ABC, Generic[TInput, TOutput]):
    """Abstract base class for agents whose outputs are gated by calibrated
    uncertainty.

    Subclasses must implement:

    - ``prompt_template``: a string (optionally with ``{placeholders}``) or a
      callable producing the prompt from the input.
    - ``parse(raw: str) -> TOutput``: transform the raw LLM string into the
      structured output type.

    The base class implements ``run()`` which:

    1. Renders the prompt.
    2. Calls the backend.
    3. Computes per-output-field uncertainty via the estimator.
    4. Applies the refusal policy.
    5. Returns a RunReport.
    """

    prompt_template: str | None = None

    def __init__(
        self,
        backend: Backend,
        uncertainty: UncertaintyEstimator,
        policy: Policy,
    ) -> None:
        self.backend = backend
        self.uncertainty = uncertainty
        self.policy = policy

    @abstractmethod
    def parse(self, raw: str) -> TOutput:
        """Parse the raw LLM output into the structured output type.

        Subclasses MUST override.
        """
        raise NotImplementedError(
            "v0.3 scaffold."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )

    def render_prompt(self, input: TInput) -> str:
        """Render the prompt from the input. Default: simple .format() on
        prompt_template if it's a string and input is a mapping.

        Subclasses may override.
        """
        if self.prompt_template is None:
            raise NotImplementedError(
                f"{type(self).__name__} must set `prompt_template` or override render_prompt()."
            )
        if isinstance(input, dict):
            return self.prompt_template.format(**input)
        raise NotImplementedError(
            "Default render_prompt supports dict inputs only. Override for custom types."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )

    def run(self, input: TInput) -> RunReport[TInput, TOutput]:
        """Run the agent end-to-end. DEFER (v0.3) — full implementation lands in v0.3."""
        raise NotImplementedError(
            "CalibratedAgent.run is a scaffold. Full wiring lands in lub v0.3. "
            "See planning/RFC_001_calibrated_agents_2026-04-23.md in the repo."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )
