"""Tests for lub.agents.core — scaffold behavior and NotImplementedError stubs."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from lub.agents.core import CalibratedAgent, RunReport


@pytest.fixture
def sample_report() -> RunReport[dict[str, Any], str]:
    return RunReport(
        input={"q": "hello"},
        output="world",
        confidence=0.87,
        refusal_flags={"low_conf": "below 0.9"},
        audit_trail={"model": "claude-opus-4-7", "tokens": 42},
    )


@pytest.fixture
def mocks() -> tuple[MagicMock, MagicMock, MagicMock]:
    return MagicMock(name="backend"), MagicMock(name="uncertainty"), MagicMock(name="policy")


class _ConcreteAgent(CalibratedAgent[dict[str, Any], str]):
    """Minimal concrete subclass used only for testing the base class."""

    prompt_template = "Q: {question}"

    def parse(self, raw: str) -> str:
        return raw.strip()


class _NoTemplateAgent(CalibratedAgent[dict[str, Any], str]):
    """Subclass without a prompt_template, to test the None branch."""

    def parse(self, raw: str) -> str:
        return raw


class TestRunReport:
    def test_stores_all_fields(self, sample_report: RunReport[dict[str, Any], str]) -> None:
        assert sample_report.input == {"q": "hello"}
        assert sample_report.output == "world"
        assert sample_report.confidence == 0.87
        assert sample_report.refusal_flags == {"low_conf": "below 0.9"}
        assert sample_report.audit_trail == {"model": "claude-opus-4-7", "tokens": 42}

    def test_defaults_for_optional_fields(self) -> None:
        report = RunReport(input=1, output=2, confidence=0.5)
        assert report.refusal_flags == {}
        assert report.audit_trail == {}

    def test_default_dicts_are_independent_between_instances(self) -> None:
        a = RunReport(input=1, output=2, confidence=0.5)
        b = RunReport(input=3, output=4, confidence=0.6)
        assert a.refusal_flags is not b.refusal_flags
        assert a.audit_trail is not b.audit_trail

    def test_is_frozen(self, sample_report: RunReport[dict[str, Any], str]) -> None:
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            sample_report.confidence = 0.0  # type: ignore[misc]

    def test_to_json_raises_not_implemented(
        self, sample_report: RunReport[dict[str, Any], str]
    ) -> None:
        with pytest.raises(NotImplementedError, match="to_json"):
            sample_report.to_json()

    def test_to_oscal_raises_not_implemented(
        self, sample_report: RunReport[dict[str, Any], str]
    ) -> None:
        with pytest.raises(NotImplementedError, match="to_oscal"):
            sample_report.to_oscal()

    def test_stub_messages_reference_v0_3(
        self, sample_report: RunReport[dict[str, Any], str]
    ) -> None:
        with pytest.raises(NotImplementedError) as exc:
            sample_report.to_json()
        assert "v0.3" in str(exc.value)

        with pytest.raises(NotImplementedError) as exc:
            sample_report.to_oscal()
        assert "v0.3" in str(exc.value)


class TestCalibratedAgent:
    def test_cannot_instantiate_abstract_base(
        self, mocks: tuple[MagicMock, MagicMock, MagicMock]
    ) -> None:
        backend, uncertainty, policy = mocks
        with pytest.raises(TypeError):
            CalibratedAgent(backend, uncertainty, policy)  # type: ignore[abstract]

    def test_init_stores_dependencies(
        self, mocks: tuple[MagicMock, MagicMock, MagicMock]
    ) -> None:
        backend, uncertainty, policy = mocks
        agent = _ConcreteAgent(backend, uncertainty, policy)
        assert agent.backend is backend
        assert agent.uncertainty is uncertainty
        assert agent.policy is policy

    def test_parse_is_overridable(
        self, mocks: tuple[MagicMock, MagicMock, MagicMock]
    ) -> None:
        agent = _ConcreteAgent(*mocks)
        assert agent.parse("  result  ") == "result"

    def test_render_prompt_formats_dict_input(
        self, mocks: tuple[MagicMock, MagicMock, MagicMock]
    ) -> None:
        agent = _ConcreteAgent(*mocks)
        assert agent.render_prompt({"question": "why?"}) == "Q: why?"

    def test_render_prompt_raises_when_template_is_none(
        self, mocks: tuple[MagicMock, MagicMock, MagicMock]
    ) -> None:
        agent = _NoTemplateAgent(*mocks)
        with pytest.raises(NotImplementedError, match="prompt_template"):
            agent.render_prompt({"question": "why?"})

    def test_render_prompt_raises_on_non_dict_input(
        self, mocks: tuple[MagicMock, MagicMock, MagicMock]
    ) -> None:
        agent = _ConcreteAgent(*mocks)
        with pytest.raises(NotImplementedError, match="dict inputs only"):
            agent.render_prompt("not a dict")  # type: ignore[arg-type]

    def test_run_raises_not_implemented(
        self, mocks: tuple[MagicMock, MagicMock, MagicMock]
    ) -> None:
        agent = _ConcreteAgent(*mocks)
        with pytest.raises(NotImplementedError, match="scaffold"):
            agent.run({"question": "why?"})

    def test_run_stub_message_references_rfc(
        self, mocks: tuple[MagicMock, MagicMock, MagicMock]
    ) -> None:
        agent = _ConcreteAgent(*mocks)
        with pytest.raises(NotImplementedError) as exc:
            agent.run({"question": "why?"})
        assert "RFC_001" in str(exc.value)

    def test_subclass_missing_parse_cannot_instantiate(
        self, mocks: tuple[MagicMock, MagicMock, MagicMock]
    ) -> None:
        class _Broken(CalibratedAgent[dict[str, Any], str]):
            prompt_template = "x"

        with pytest.raises(TypeError, match="parse"):
            _Broken(*mocks)  # type: ignore[abstract]
