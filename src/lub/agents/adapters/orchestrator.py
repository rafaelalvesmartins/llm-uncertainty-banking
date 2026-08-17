"""
lub.agents.adapters.orchestrator -- generic agent-orchestrator bridge.

Bidirectional Protocol-based bridge between LUB CalibratedAgents and any
**agent orchestration framework** that exposes ``.name`` + ``.run(input)``
on its agent objects.

This module is **framework-agnostic by design** -- it does not depend on
any specific orchestrator (no `import ruflo`, no `import langgraph`, etc).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeVar

import structlog

from lub.agents.core import CalibratedAgent, RunReport
from lub.agents.policies import Policy
from lub.agents.protocols import OrchestratorAgentProtocol
from lub.exceptions import ConfidenceParseError
from lub.protocols import (
    AdapterLabel,
    AuditKey,
    UncertaintyEstimatorProtocol,
)

_LOG = structlog.get_logger("lub.agents.adapters.orchestrator")

__all__ = [
    "ConfidenceParseError",
    "OrchestratorAgentProtocol",
    "from_orchestrator_agent",
    "to_orchestrator_agent",
]


TInput = TypeVar("TInput")
TOutput = TypeVar("TOutput")


def _clamp01(x: float) -> float:
    """Clamp to [0, 1] so confidence stays in the documented range."""
    return max(0.0, min(1.0, x))


def _interpret_confidence_result(result: Any) -> float | None:
    """Extract a confidence float in ``[0, 1]`` from any documented shape.

    Returns ``None`` when the result has none of the recognised shapes
    (numeric, ``.confidence`` attribute, or ``dict`` with ``"confidence"``
    key). When a dict carries ``"confidence"`` but the value cannot be
    coerced to ``float``, we log a warning -- this is an upstream-shape
    mismatch worth surfacing -- and still return ``None`` so the caller
    can fall back to the next candidate. Callers that want fail-loud
    semantics (raise :class:`~lub.exceptions.ConfidenceParseError`
    instead of returning ``None``) can wrap this helper.
    """
    if isinstance(result, (int, float)):
        return _clamp01(float(result))
    confidence_attr = getattr(result, "confidence", None)
    if isinstance(confidence_attr, (int, float)):
        return _clamp01(float(confidence_attr))
    if isinstance(result, dict) and "confidence" in result:
        try:
            return _clamp01(float(result["confidence"]))
        except (TypeError, ValueError) as exc:
            _LOG.warning(
                "orchestrator.confidence_parse_failed",
                shape="dict",
                received_type=type(result["confidence"]).__name__,
                error=str(exc),
            )
            return None
    return None


def _score_confidence(estimator: Any, *, prompt: str, output: Any) -> float:
    """Best-effort uncertainty scoring with typed primary path + duck-typed fallbacks."""
    if estimator is None:
        return 1.0

    if isinstance(estimator, UncertaintyEstimatorProtocol):
        try:
            confidence = _interpret_confidence_result(estimator.score(prompt, output))
            if confidence is not None:
                return confidence
        except (TypeError, NotImplementedError):
            pass

    candidates: list[tuple[str, tuple[Any, ...]]] = [
        ("score", (output,)),
        ("estimate", (prompt, output)),
        ("estimate", (output,)),
        ("__call__", (prompt, output)),
        ("__call__", (output,)),
    ]
    for method_name, args in candidates:
        method = getattr(estimator, method_name, None)
        if not callable(method):
            continue
        try:
            confidence = _interpret_confidence_result(method(*args))
        except (TypeError, NotImplementedError):
            continue
        if confidence is not None:
            return confidence

    # No candidate produced an interpretable confidence. Log so the
    # operator can spot a misconfigured estimator (silent 0.0 used to
    # masquerade as "model is unsure", which is a different signal from
    # "we could not extract confidence at all"). Callers that prefer to
    # fail loud can catch this case via the ``"orchestrator.no_confidence"``
    # log event and raise :class:`~lub.exceptions.ConfidenceParseError`.
    _LOG.warning(
        "orchestrator.no_confidence",
        estimator_type=type(estimator).__name__,
        candidates_tried=[name for name, _ in candidates],
    )
    return 0.0


class _CalibratedOrchestratorWrapper(CalibratedAgent[Any, Any]):
    """CalibratedAgent that delegates execution to an orchestrator-shaped agent."""

    prompt_template = "{input}"

    def __init__(
        self,
        orchestrator_agent: OrchestratorAgentProtocol,
        uncertainty: Any,
        policy: Policy | None,
    ) -> None:
        super().__init__(
            backend=orchestrator_agent,
            uncertainty=uncertainty,
            policy=policy,
        )
        self._orchestrator_agent = orchestrator_agent

    def parse(self, raw: str) -> Any:
        """Identity parse: orchestrator agents own their output shape."""
        return raw

    def render_prompt(self, input: Any) -> str:
        """Render input as a string for telemetry."""
        return str(input)

    def run(self, input: Any) -> RunReport[Any, Any]:
        """End-to-end: invoke orchestrator agent, score, gate, build report."""
        agent_name = getattr(
            self._orchestrator_agent,
            "name",
            type(self._orchestrator_agent).__name__,
        )
        prompt_for_audit = self.render_prompt(input)

        try:
            raw_output = self._orchestrator_agent.run(input)
        except Exception as exc:  # noqa: BLE001
            return RunReport(
                input=input,
                output=None,
                confidence=0.0,
                refusal_flags={
                    AuditKey.UPSTREAM_ERROR: type(exc).__name__,
                    AuditKey.UPSTREAM_MESSAGE: str(exc),
                },
                audit_trail={
                    AuditKey.ADAPTER: AdapterLabel.ORCHESTRATOR,
                    AuditKey.ORCHESTRATOR_AGENT: agent_name,
                    AuditKey.STAGE: "orchestrator_agent.run",
                },
            )

        confidence = _score_confidence(
            self.uncertainty,
            prompt=prompt_for_audit,
            output=raw_output,
        )

        flags: dict[str, str] = {}
        output: Any = raw_output
        policy_name: str | None = None
        if self.policy is not None:
            policy_name = type(self.policy).__name__
            decision = self.policy.decide(confidence)
            if not decision.emit:
                output = decision.action
                flags[AuditKey.REFUSED] = decision.action or "REFUSED"
                if decision.rationale:
                    flags[AuditKey.RATIONALE] = decision.rationale

        audit: dict[str, Any] = {
            AuditKey.ADAPTER: AdapterLabel.ORCHESTRATOR,
            AuditKey.ORCHESTRATOR_AGENT: agent_name,
            AuditKey.UNCERTAINTY: (
                type(self.uncertainty).__name__ if self.uncertainty is not None else None
            ),
            AuditKey.POLICY: policy_name,
        }
        description = getattr(self._orchestrator_agent, "description", None)
        if description is not None:
            audit[AuditKey.ORCHESTRATOR_AGENT_DESCRIPTION] = description

        return RunReport(
            input=input,
            output=output,
            confidence=confidence,
            refusal_flags=flags,
            audit_trail=audit,
        )


def from_orchestrator_agent(
    orchestrator_agent: OrchestratorAgentProtocol,
    *,
    uncertainty: Any,
    policy: Policy | None = None,
) -> CalibratedAgent[Any, Any]:
    """Wrap an orchestrator-shaped agent as a :class:`CalibratedAgent`."""
    if not callable(getattr(orchestrator_agent, "run", None)):
        raise TypeError(
            "orchestrator_agent must expose a callable .run() method "
            f"(got {type(orchestrator_agent).__name__})."
        )
    return _CalibratedOrchestratorWrapper(orchestrator_agent, uncertainty, policy)


@dataclass
class _OrchestratorShapedAgent:
    """Orchestrator-compatible Python object produced by ``to_orchestrator_agent``."""

    name: str
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _calibrated: CalibratedAgent[Any, Any] | None = field(default=None, repr=False)

    def run(self, input: Any) -> Any:
        """Invoke the wrapped CalibratedAgent and return its output."""
        if self._calibrated is None:
            return None
        report = self._calibrated.run(input)
        self.metadata[AuditKey.LAST_CONFIDENCE] = report.confidence
        self.metadata[AuditKey.LAST_REFUSAL_FLAGS] = dict(report.refusal_flags)
        return report.output


def to_orchestrator_agent(
    agent: CalibratedAgent[Any, Any],
    *,
    name: str,
    description: str | None = None,
) -> _OrchestratorShapedAgent:
    """Translate a :class:`CalibratedAgent` into an orchestrator-shaped agent."""
    if not name:
        raise ValueError("name must be a non-empty string")

    return _OrchestratorShapedAgent(
        name=name,
        description=description,
        metadata={
            AuditKey.LUB_CALIBRATED: True,
            AuditKey.LUB_AGENT_CLASS: type(agent).__name__,
        },
        _calibrated=agent,
    )
