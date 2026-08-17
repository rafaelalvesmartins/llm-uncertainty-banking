"""
lub.agents.reporter — ReportingAgent and AuditTrail.

ReportingAgent extends CalibratedAgent with a structured audit trail
suitable for compliance review. AuditTrail is the pydantic-compatible
shape of that trail. Serialization to JSON / OSCAL / Markdown is
DEFER (v0.3).

.. note::
   ``# TODO`` markers in this module have been retired in favor of
   ``DEFER (v0.3)`` so reviewers can tell scaffold-debt from open bugs
   at a glance (per IMPROVEMENT_OPPORTUNITIES_2026-04-25.md §C).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from lub.agents.core import CalibratedAgent, RunReport

__all__ = ["AuditTrail", "ReportingAgent"]

TInput = TypeVar("TInput")
TOutput = TypeVar("TOutput")


@dataclass(frozen=True)
class AuditTrail:
    """Structured audit trail for a single agent run.

    Fields map to what a model-risk reviewer would want to reconstruct:
    inputs given, prompt rendered, model used, uncertainty computed,
    refusal decisions applied, final output.

    Attributes:
        run_id: ULID-formatted identifier.
        agent_class: Fully qualified class name of the agent.
        agent_version: Optional agent-package version tag.
        lub_version: lub library version.
        backend_id: Identifier for the backend/model (e.g. "HFBackend/Qwen2.5-0.5B-Instruct").
        uncertainty_method: Name of the uncertainty estimator used.
        prompt_version: Hash or tag of the rendered prompt template.
        input_hash: Hash of the agent input (for reproducibility).
        raw_output: The LLM's raw string output.
        parsed_output_repr: Repr of the structured parsed output.
        confidence: Scalar or per-field confidence numbers.
        refusal_decisions: Map of field -> policy decision rationale.
        timestamp_utc: ISO-formatted UTC time of the run.
        extra: Free-form metadata dict for extension.
    """

    run_id: str
    agent_class: str
    agent_version: str | None
    lub_version: str
    backend_id: str
    uncertainty_method: str
    prompt_version: str
    input_hash: str
    raw_output: str
    parsed_output_repr: str
    confidence: float | dict[str, float]
    refusal_decisions: dict[str, str]
    timestamp_utc: str
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        agent_class: str,
        backend_id: str,
        uncertainty_method: str,
    ) -> AuditTrail:
        """Factory. DEFER (v0.3) — needs run_id generation, version pickup, input hashing."""
        raise NotImplementedError(
            "AuditTrail.new is a scaffold. Lands in v0.3 alongside ReportingAgent.run."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )

    def to_markdown(self) -> str:
        """Render audit trail as a human-readable Markdown report. DEFER (v0.3)."""
        raise NotImplementedError(
            "AuditTrail.to_markdown is not yet implemented."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )

    def to_oscal(self) -> dict[str, Any]:
        """Render audit trail as an OSCAL-compatible dict. DEFER (v0.3)."""
        raise NotImplementedError(
            "AuditTrail.to_oscal is not yet implemented. Requires lub.reports.oscal."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )


class ReportingAgent(CalibratedAgent[TInput, TOutput]):
    """CalibratedAgent that emits a full AuditTrail on every run.

    Thin wrapper around CalibratedAgent. Override for agents that need
    compliance-level audit trails by default.
    """

    def run(self, input: TInput) -> RunReport[TInput, TOutput]:
        """Run and attach a full AuditTrail in the RunReport.audit_trail dict.

        DEFER (v0.3) — full wiring lands in v0.3.
        """
        raise NotImplementedError(
            "ReportingAgent.run is a scaffold. Lands in v0.3."
            " Full implementation lands in lub v0.3."
            " Install the agents-beta extra now to get the wired surface:"
            " pip install 'llm-uncertainty-banking[agents-beta]'."
        )

    @staticmethod
    def _now_iso() -> str:
        """Helper: current UTC timestamp in ISO 8601."""
        return datetime.now(UTC).isoformat()
