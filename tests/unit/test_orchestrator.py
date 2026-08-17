# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Tests for ``lub.agents.adapters.orchestrator`` -- pipeline + gating + errors.

The orchestrator adapter is the seam through which any agent
framework (ruflo, langgraph, crewai, autogen, ...) plugs into the
LUB calibration / refusal pipeline. These tests exercise that seam
end-to-end with fakes -- no real orchestrator runtime, no real LLM
calls -- focusing on:

* Customer queries flow through ``from_orchestrator_agent(...).run(...)``
  and produce a ``RunReport`` with the underlying agent's output.
* Confidence thresholds gate emission (low confidence -> escalate /
  refuse; high confidence -> emit the agent's raw answer).
* Edge cases: empty input, PII-shaped input, exotic estimator shapes,
  None estimator, unparseable estimator.
* Upstream errors (timeouts, invalid responses, framework exceptions)
  surface as refusal flags without raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from lub.agents.adapters.orchestrator import (
    OrchestratorAgentProtocol,
    from_orchestrator_agent,
    to_orchestrator_agent,
)
from lub.agents.core import CalibratedAgent, RunReport
from lub.agents.policies import RefusalPolicy

# ---------------------------------------------------------------------------
# Fakes -- hermetic stand-ins for an orchestrator-framework agent + estimator.
# ---------------------------------------------------------------------------


@dataclass
class FakeOrchAgent:
    """Minimal orchestrator-shaped agent (name + run + optional description)."""

    name: str
    description: str | None = None
    response: Any = "ok"

    def run(self, input: Any) -> Any:
        return f"{self.response}::{input}"


@dataclass
class _BrokenAgent:
    """Orchestrator agent whose ``.run`` always raises -- simulates upstream
    timeout / invalid-response / framework crash."""

    name: str = "broken"
    exc: BaseException = field(default_factory=lambda: TimeoutError("upstream timeout"))

    def run(self, input: Any) -> Any:
        raise self.exc


@dataclass
class _ConstUQ:
    """Estimator returning a fixed scalar confidence via ``.score``."""

    confidence: float

    def score(self, prompt: str, output: Any) -> float:
        return self.confidence


@dataclass
class _ConstUQEstimate:
    """Estimator that only exposes ``.estimate`` (duck-typed fallback path)."""

    confidence: float

    def estimate(self, prompt: str, output: Any) -> float:
        return self.confidence


@dataclass
class _CallableUQ:
    """Estimator that is itself callable -- ``__call__`` fallback path."""

    confidence: float

    def __call__(self, prompt: str, output: Any) -> float:
        return self.confidence


@dataclass
class _DictResultUQ:
    """Estimator returning ``{"confidence": ...}`` -- dict-shape path."""

    confidence: float

    def score(self, prompt: str, output: Any) -> dict[str, Any]:
        return {"confidence": self.confidence, "raw": "ignored"}


class _UnparseableDictUQ:
    """Estimator returning a dict whose ``"confidence"`` is non-numeric."""

    def score(self, prompt: str, output: Any) -> dict[str, Any]:
        return {"confidence": "not-a-number"}


class _NoShapeUQ:
    """Estimator that returns something with no recognised confidence shape."""

    def score(self, prompt: str, output: Any) -> object:
        return object()


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chatbot_agent() -> FakeOrchAgent:
    """A banking-chatbot-shaped orchestrator agent."""
    return FakeOrchAgent(
        name="chatbot",
        description="general banking Q&A",
        response="resposta",
    )


@pytest.fixture
def payments_agent() -> FakeOrchAgent:
    """A payments-shaped orchestrator agent."""
    return FakeOrchAgent(
        name="smart_payments",
        description="PIX/TED flows",
        response="payment-ack",
    )


@pytest.fixture
def high_conf() -> _ConstUQ:
    return _ConstUQ(confidence=0.95)


@pytest.fixture
def low_conf() -> _ConstUQ:
    return _ConstUQ(confidence=0.10)


@pytest.fixture
def refusal_policy() -> RefusalPolicy:
    """Strict policy: anything below 0.7 is escalated for human review."""
    return RefusalPolicy(
        threshold=0.7,
        below_threshold_action="REQUIRES_HUMAN_REVIEW",
    )


# ---------------------------------------------------------------------------
# Happy path: customer query flows through the wrapper end-to-end.
# ---------------------------------------------------------------------------


def test_customer_query_produces_run_report(chatbot_agent, high_conf):
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=high_conf)
    report = wrapped.run("qual o saldo?")
    assert isinstance(report, RunReport)
    assert report.input == "qual o saldo?"
    assert report.output == "resposta::qual o saldo?"


def test_customer_query_reports_estimator_confidence(chatbot_agent):
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=_ConstUQ(0.42))
    assert wrapped.run("oi").confidence == pytest.approx(0.42)


def test_audit_trail_records_pipeline_metadata(chatbot_agent, refusal_policy):
    wrapped = from_orchestrator_agent(
        chatbot_agent, uncertainty=_ConstUQ(0.9), policy=refusal_policy,
    )
    report = wrapped.run("qual o saldo?")
    audit = report.audit_trail
    assert audit["adapter"] == "orchestrator"
    assert audit["orchestrator_agent"] == "chatbot"
    assert audit["orchestrator_agent_description"] == "general banking Q&A"
    assert audit["uncertainty"] == "_ConstUQ"
    assert audit["policy"] == "RefusalPolicy"


# ---------------------------------------------------------------------------
# Confidence thresholds: low -> escalate, high -> respond.
# ---------------------------------------------------------------------------


def test_low_confidence_escalates_for_human_review(chatbot_agent, refusal_policy):
    wrapped = from_orchestrator_agent(
        chatbot_agent, uncertainty=_ConstUQ(0.10), policy=refusal_policy,
    )
    report = wrapped.run("autorizar transferência R$ 50000")
    assert report.output == "REQUIRES_HUMAN_REVIEW"
    assert report.refusal_flags["refused"] == "REQUIRES_HUMAN_REVIEW"
    assert "rationale" in report.refusal_flags


def test_high_confidence_emits_agent_output(chatbot_agent, refusal_policy):
    wrapped = from_orchestrator_agent(
        chatbot_agent, uncertainty=_ConstUQ(0.95), policy=refusal_policy,
    )
    report = wrapped.run("oi")
    assert report.output == "resposta::oi"
    assert report.refusal_flags == {}


def test_no_policy_means_never_refuses_even_at_zero_confidence(chatbot_agent):
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=_ConstUQ(0.0))
    report = wrapped.run("oi")
    assert report.output == "resposta::oi"
    assert report.refusal_flags == {}


@pytest.mark.parametrize(
    ("score", "should_emit"),
    [
        (0.0, False),
        (0.5, False),
        (0.6999, False),
        (0.7, True),    # threshold is inclusive-from-above in RefusalPolicy
        (0.95, True),
        (1.0, True),
    ],
)
def test_threshold_boundary_behaviour(chatbot_agent, refusal_policy, score, should_emit):
    wrapped = from_orchestrator_agent(
        chatbot_agent, uncertainty=_ConstUQ(score), policy=refusal_policy,
    )
    report = wrapped.run("q")
    if should_emit:
        assert report.output == "resposta::q"
        assert report.refusal_flags == {}
    else:
        assert report.output == "REQUIRES_HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# Estimator shape variety -- protocol, duck-typed, dict, callable, fallbacks.
# ---------------------------------------------------------------------------


def test_estimator_with_only_estimate_method(chatbot_agent):
    wrapped = from_orchestrator_agent(
        chatbot_agent, uncertainty=_ConstUQEstimate(0.66),
    )
    assert wrapped.run("q").confidence == pytest.approx(0.66)


def test_estimator_callable_only(chatbot_agent):
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=_CallableUQ(0.33))
    assert wrapped.run("q").confidence == pytest.approx(0.33)


def test_estimator_dict_result(chatbot_agent):
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=_DictResultUQ(0.55))
    assert wrapped.run("q").confidence == pytest.approx(0.55)


def test_estimator_clamps_above_one(chatbot_agent):
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=_ConstUQ(1.5))
    assert wrapped.run("q").confidence == 1.0


def test_estimator_clamps_below_zero(chatbot_agent):
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=_ConstUQ(-0.3))
    assert wrapped.run("q").confidence == 0.0


def test_estimator_dict_with_non_numeric_confidence_fails_closed(chatbot_agent):
    """Garbage shape -> we fall back to 0.0 (fail-closed) rather than raise."""
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=_UnparseableDictUQ())
    assert wrapped.run("q").confidence == 0.0


def test_estimator_with_unknown_result_shape_fails_closed(chatbot_agent):
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=_NoShapeUQ())
    assert wrapped.run("q").confidence == 0.0


def test_estimator_none_opt_out_returns_full_confidence(chatbot_agent):
    """Explicit ``uncertainty=None`` is an opt-out, NOT an error."""
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=None)
    assert wrapped.run("q").confidence == 1.0


def test_estimator_object_with_nothing_useful_fails_closed(chatbot_agent):
    """A bare ``object()`` -- no score/estimate/__call__ that returns a float."""
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=object())
    assert wrapped.run("q").confidence == 0.0


# ---------------------------------------------------------------------------
# Edge cases for the input itself.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["", " ", "\n", "\t\t"])
def test_empty_or_whitespace_input_is_passed_through(chatbot_agent, high_conf, query):
    """Whitespace-only queries are the agent's concern, not the adapter's."""
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=high_conf)
    report = wrapped.run(query)
    assert report.input == query
    assert report.output == f"resposta::{query}"


def test_pii_input_is_passed_through_unchanged(chatbot_agent, high_conf):
    """The orchestrator adapter does NOT mask PII -- that is a Bridge-layer
    concern (data_governance.py). Verify the adapter is transparent so the
    Bridge pipeline keeps full control of where masking happens."""
    pii_query = "CPF 123.456.789-09 / e-mail rafael@example.com"
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=high_conf)
    report = wrapped.run(pii_query)
    assert pii_query in str(report.output)
    assert report.input == pii_query


def test_nontext_input_is_passed_through(chatbot_agent, high_conf):
    """Bridge intent dicts / structured payloads must reach the agent intact."""
    payload = {"intent": "transfer", "amount": -1, "currency": "BRL"}
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=high_conf)
    report = wrapped.run(payload)
    assert report.input == payload


def test_none_input_does_not_crash_adapter(chatbot_agent, high_conf):
    wrapped = from_orchestrator_agent(chatbot_agent, uncertainty=high_conf)
    report = wrapped.run(None)
    assert report.output == "resposta::None"


# ---------------------------------------------------------------------------
# Upstream error handling -- timeout, invalid response, framework crash.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("upstream timeout"),
        RuntimeError("framework crashed"),
        ValueError("invalid response shape"),
        KeyError("missing field"),
    ],
)
def test_upstream_exception_surfaces_as_refusal_flag(high_conf, exc):
    """Any upstream exception type -> RunReport with confidence=0.0 + flags."""
    broken = _BrokenAgent(exc=exc)
    wrapped = from_orchestrator_agent(broken, uncertainty=high_conf)
    report = wrapped.run("q")
    assert report.output is None
    assert report.confidence == 0.0
    assert report.refusal_flags["upstream_error"] == type(exc).__name__
    assert str(exc) in report.refusal_flags["upstream_message"]


def test_upstream_error_records_orchestrator_agent_name():
    broken = _BrokenAgent(name="payments_v2", exc=TimeoutError("t/o"))
    wrapped = from_orchestrator_agent(broken, uncertainty=_ConstUQ(0.9))
    report = wrapped.run("q")
    audit = report.audit_trail
    assert audit["orchestrator_agent"] == "payments_v2"
    assert audit["stage"] == "orchestrator_agent.run"


def test_upstream_error_does_not_propagate_estimator_call(high_conf):
    """When upstream fails we must NOT call the estimator on a bogus output."""
    class _UQTracker:
        calls = 0

        def score(self, prompt: str, output: Any) -> float:
            type(self).calls += 1
            return 0.99

    broken = _BrokenAgent(exc=TimeoutError("t/o"))
    wrapped = from_orchestrator_agent(broken, uncertainty=_UQTracker())
    wrapped.run("q")
    assert _UQTracker.calls == 0


# ---------------------------------------------------------------------------
# Input validation: from_orchestrator_agent / to_orchestrator_agent.
# ---------------------------------------------------------------------------


def test_from_rejects_object_without_run():
    class _NoRun:
        name = "x"

    with pytest.raises(TypeError, match=r"\.run\(\)"):
        from_orchestrator_agent(_NoRun(), uncertainty=_ConstUQ(0.5))


def test_from_rejects_object_with_non_callable_run():
    class _BadRun:
        name = "x"
        run = "not callable"

    with pytest.raises(TypeError, match=r"\.run\(\)"):
        from_orchestrator_agent(_BadRun(), uncertainty=_ConstUQ(0.5))


def test_to_rejects_empty_name():
    class _EchoAgent(CalibratedAgent[Any, Any]):
        prompt_template = "{x}"

        def parse(self, raw: str) -> Any:
            return raw

        def run(self, input: Any) -> RunReport[Any, Any]:
            return RunReport(input=input, output="ok", confidence=1.0)

    agent = _EchoAgent(backend=object(), uncertainty=object(), policy=None)
    with pytest.raises(ValueError, match="non-empty"):
        to_orchestrator_agent(agent, name="")


# ---------------------------------------------------------------------------
# Outbound: to_orchestrator_agent translates a CalibratedAgent for frameworks.
# ---------------------------------------------------------------------------


class _Echo(CalibratedAgent[Any, Any]):
    """Trivial CalibratedAgent used for outbound + round-trip tests."""

    prompt_template = "{x}"

    def __init__(self, response: Any, confidence: float) -> None:
        super().__init__(backend=object(), uncertainty=object(), policy=None)
        self._response = response
        self._confidence = confidence

    def parse(self, raw: str) -> Any:
        return raw

    def run(self, input: Any) -> RunReport[Any, Any]:
        return RunReport(
            input=input,
            output=self._response,
            confidence=self._confidence,
            refusal_flags={},
            audit_trail={"agent": "_Echo"},
        )


def test_to_orchestrator_agent_satisfies_protocol():
    shaped = to_orchestrator_agent(_Echo("hi", 0.9), name="echo")
    assert isinstance(shaped, OrchestratorAgentProtocol)
    assert shaped.name == "echo"


def test_to_orchestrator_agent_propagates_last_confidence():
    shaped = to_orchestrator_agent(_Echo("answer", 0.88), name="x")
    shaped.run("input")
    assert shaped.metadata["last_confidence"] == pytest.approx(0.88)
    assert shaped.metadata["last_refusal_flags"] == {}


def test_to_orchestrator_agent_marks_calibrated_origin():
    shaped = to_orchestrator_agent(_Echo("x", 0.5), name="x", description="desc")
    assert shaped.description == "desc"
    assert shaped.metadata["lub_calibrated"] is True
    assert shaped.metadata["lub_agent_class"] == "_Echo"


def test_roundtrip_to_then_from(chatbot_agent):
    """Wrap a CalibratedAgent as orchestrator-shaped, then re-wrap as CalibratedAgent."""
    inner = _Echo(response="answer", confidence=0.95)
    shaped = to_orchestrator_agent(inner, name="rt")
    rewrapped = from_orchestrator_agent(shaped, uncertainty=_ConstUQ(0.95))
    report = rewrapped.run("q")
    assert report.output == "answer"
    assert report.confidence == pytest.approx(0.95)
    assert report.audit_trail["adapter"] == "orchestrator"
    assert report.audit_trail["orchestrator_agent"] == "rt"
