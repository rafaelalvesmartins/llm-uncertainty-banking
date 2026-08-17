# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Tests for ``lub.agents.adapters.ruflo``.

Hermetic: no real ruflo runtime; we use a ``FakeRufloAgent`` that
satisfies :class:`RufloAgentProtocol` plus a deterministic estimator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from lub.agents.adapters.ruflo import (
    RufloAgentProtocol,
    from_ruflo_agent,
    to_ruflo_agent,
)
from lub.agents.core import CalibratedAgent, RunReport
from lub.agents.policies import RefusalPolicy

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@dataclass
class FakeRufloAgent:
    """Minimal ruflo-shaped agent for tests; satisfies RufloAgentProtocol."""

    name: str
    description: str | None = None
    response: str = "fake-output"

    def run(self, input: Any) -> str:
        return f"{self.response}::{input}"


@dataclass
class ConstantUncertainty:
    """Estimator that returns a fixed confidence."""

    confidence: float

    def score(self, prompt: str, output: Any) -> float:
        return self.confidence


@dataclass
class DataclassResultUncertainty:
    """Estimator that returns an object with a ``.confidence`` attribute."""

    confidence_value: float

    def score(self, prompt: str, output: Any):
        @dataclass
        class _Result:
            confidence: float

        return _Result(confidence=self.confidence_value)


@dataclass
class DictResultUncertainty:
    """Estimator that returns a dict with a confidence key."""

    confidence_value: float

    def score(self, prompt: str, output: Any) -> dict:
        return {"confidence": self.confidence_value, "raw": "ignored"}


class _ParseEcho(CalibratedAgent[Any, Any]):
    """A trivial CalibratedAgent for round-trip testing.

    We override ``run`` directly because the base CalibratedAgent.run is
    a v0.3 scaffold; the adapter contract only requires ``.run(input) ->
    RunReport`` so a subclass that supplies ``run`` is enough.
    """

    prompt_template = "{q}"

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
            audit_trail={"agent": "_ParseEcho"},
        )


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


def test_fake_satisfies_ruflo_protocol():
    fake = FakeRufloAgent(name="basel_reporter")
    assert isinstance(fake, RufloAgentProtocol)


def test_calibrated_agent_does_not_satisfy_ruflo_protocol():
    """Sanity check — without to_ruflo_agent, a CalibratedAgent is not ruflo-shaped."""
    agent = _ParseEcho("x", 0.9)
    # CalibratedAgent has .run but no public .name attribute
    assert not hasattr(agent, "name")


# ---------------------------------------------------------------------------
# from_ruflo_agent — happy path
# ---------------------------------------------------------------------------


def test_from_ruflo_agent_returns_calibrated_agent():
    fake = FakeRufloAgent(name="basel_reporter")
    estimator = ConstantUncertainty(confidence=0.8)
    wrapped = from_ruflo_agent(fake, uncertainty=estimator)
    assert isinstance(wrapped, CalibratedAgent)


def test_from_ruflo_agent_runs_underlying_agent():
    fake = FakeRufloAgent(name="basel_reporter", response="answer")
    wrapped = from_ruflo_agent(fake, uncertainty=ConstantUncertainty(0.9))
    report = wrapped.run("query-1")
    assert report.output == "answer::query-1"


def test_from_ruflo_agent_reports_estimator_confidence():
    fake = FakeRufloAgent(name="basel_reporter")
    wrapped = from_ruflo_agent(fake, uncertainty=ConstantUncertainty(0.42))
    report = wrapped.run("q")
    assert report.confidence == pytest.approx(0.42)


def test_from_ruflo_agent_clamps_confidence_to_unit_interval():
    fake = FakeRufloAgent(name="basel_reporter")
    wrapped = from_ruflo_agent(fake, uncertainty=ConstantUncertainty(1.5))
    assert wrapped.run("q").confidence == 1.0
    wrapped2 = from_ruflo_agent(fake, uncertainty=ConstantUncertainty(-0.2))
    assert wrapped2.run("q").confidence == 0.0


def test_from_ruflo_agent_accepts_dataclass_result_estimator():
    fake = FakeRufloAgent(name="x")
    wrapped = from_ruflo_agent(fake, uncertainty=DataclassResultUncertainty(0.65))
    assert wrapped.run("q").confidence == pytest.approx(0.65)


def test_from_ruflo_agent_accepts_dict_result_estimator():
    fake = FakeRufloAgent(name="x")
    wrapped = from_ruflo_agent(fake, uncertainty=DictResultUncertainty(0.55))
    assert wrapped.run("q").confidence == pytest.approx(0.55)


def test_from_ruflo_agent_with_none_estimator_returns_full_confidence():
    """Explicit opt-out: caller passes None to skip UQ."""
    fake = FakeRufloAgent(name="x")
    wrapped = from_ruflo_agent(fake, uncertainty=None)
    assert wrapped.run("q").confidence == 1.0


def test_from_ruflo_agent_with_unparseable_estimator_returns_zero():
    """Unknown estimator shape → fail-closed (confidence=0)."""
    fake = FakeRufloAgent(name="x")
    wrapped = from_ruflo_agent(fake, uncertainty=object())  # no .score / .estimate / __call__ for floats
    assert wrapped.run("q").confidence == 0.0


# ---------------------------------------------------------------------------
# from_ruflo_agent — refusal policy gating
# ---------------------------------------------------------------------------


def test_no_policy_means_never_refuses():
    fake = FakeRufloAgent(name="x", response="raw")
    wrapped = from_ruflo_agent(fake, uncertainty=ConstantUncertainty(0.0))
    report = wrapped.run("q")
    assert report.output == "raw::q"
    assert report.refusal_flags == {}


def test_below_threshold_refuses():
    fake = FakeRufloAgent(name="x", response="raw")
    policy = RefusalPolicy(threshold=0.7, below_threshold_action="REQUIRES_HUMAN_REVIEW")
    wrapped = from_ruflo_agent(fake, uncertainty=ConstantUncertainty(0.5), policy=policy)
    report = wrapped.run("q")
    assert report.output == "REQUIRES_HUMAN_REVIEW"
    assert report.refusal_flags["refused"] == "REQUIRES_HUMAN_REVIEW"
    assert "rationale" in report.refusal_flags


def test_above_threshold_emits():
    fake = FakeRufloAgent(name="x", response="raw")
    policy = RefusalPolicy(threshold=0.5)
    wrapped = from_ruflo_agent(fake, uncertainty=ConstantUncertainty(0.9), policy=policy)
    report = wrapped.run("q")
    assert report.output == "raw::q"
    assert report.refusal_flags == {}


# ---------------------------------------------------------------------------
# from_ruflo_agent — audit trail
# ---------------------------------------------------------------------------


def test_audit_trail_records_adapter_and_agent_name():
    fake = FakeRufloAgent(name="basel_reporter", description="Basel III Pillar 3")
    wrapped = from_ruflo_agent(fake, uncertainty=ConstantUncertainty(0.9))
    report = wrapped.run("q")
    assert report.audit_trail["adapter"] == "orchestrator"
    assert report.audit_trail["orchestrator_agent"] == "basel_reporter"
    assert report.audit_trail["orchestrator_agent_description"] == "Basel III Pillar 3"


def test_audit_trail_records_uncertainty_and_policy_class_names():
    fake = FakeRufloAgent(name="x")
    policy = RefusalPolicy(threshold=0.5)
    wrapped = from_ruflo_agent(
        fake, uncertainty=ConstantUncertainty(0.9), policy=policy,
    )
    report = wrapped.run("q")
    assert report.audit_trail["uncertainty"] == "ConstantUncertainty"
    assert report.audit_trail["policy"] == "RefusalPolicy"


# ---------------------------------------------------------------------------
# from_ruflo_agent — error handling
# ---------------------------------------------------------------------------


def test_upstream_error_surfaces_as_refusal_flag():
    class BrokenAgent:
        name = "broken"

        def run(self, input):
            raise RuntimeError("upstream failure")

    wrapped = from_ruflo_agent(BrokenAgent(), uncertainty=ConstantUncertainty(0.9))
    report = wrapped.run("q")
    assert report.output is None
    assert report.confidence == 0.0
    assert report.refusal_flags["upstream_error"] == "RuntimeError"
    assert "upstream failure" in report.refusal_flags["upstream_message"]


def test_rejects_object_without_run():
    class NotARufloAgent:
        name = "fake"

    with pytest.raises(TypeError, match=r"\.run\(\)"):
        from_ruflo_agent(NotARufloAgent(), uncertainty=ConstantUncertainty(0.5))


# ---------------------------------------------------------------------------
# to_ruflo_agent — outbound translation
# ---------------------------------------------------------------------------


def test_to_ruflo_agent_returns_ruflo_shaped_object():
    agent = _ParseEcho(response="hello", confidence=0.95)
    shaped = to_ruflo_agent(agent, name="test_agent")
    assert shaped.name == "test_agent"
    assert callable(shaped.run)
    assert isinstance(shaped, RufloAgentProtocol)


def test_to_ruflo_agent_records_description_and_metadata():
    agent = _ParseEcho("x", 0.5)
    shaped = to_ruflo_agent(
        agent, name="basel_reporter", description="Basel III Pillar 3 reporter",
    )
    assert shaped.description == "Basel III Pillar 3 reporter"
    assert shaped.metadata["lub_calibrated"] is True
    assert shaped.metadata["lub_agent_class"] == "_ParseEcho"


def test_to_ruflo_agent_run_returns_calibrated_output():
    agent = _ParseEcho(response="emitted-output", confidence=0.95)
    shaped = to_ruflo_agent(agent, name="x")
    out = shaped.run("any-input")
    assert out == "emitted-output"


def test_to_ruflo_agent_propagates_metadata_after_each_run():
    agent = _ParseEcho(response="emit", confidence=0.88)
    shaped = to_ruflo_agent(agent, name="x")
    shaped.run("input")
    assert shaped.metadata["last_confidence"] == pytest.approx(0.88)
    assert shaped.metadata["last_refusal_flags"] == {}


def test_to_ruflo_agent_rejects_empty_name():
    agent = _ParseEcho("x", 0.5)
    with pytest.raises(ValueError, match="non-empty"):
        to_ruflo_agent(agent, name="")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_roundtrip_to_then_from_preserves_output():
    """Wrap a CalibratedAgent as ruflo-shaped, then wrap that back as CalibratedAgent.

    The round-tripped agent must run end-to-end and match the original output
    when no policy gates it.
    """
    inner = _ParseEcho(response="answer", confidence=0.95)
    shaped = to_ruflo_agent(inner, name="rt")
    rewrapped = from_ruflo_agent(shaped, uncertainty=ConstantUncertainty(0.95))
    report = rewrapped.run("q")
    assert report.output == "answer"
    assert report.confidence == pytest.approx(0.95)
    assert report.audit_trail["adapter"] == "orchestrator"
    assert report.audit_trail["orchestrator_agent"] == "rt"
