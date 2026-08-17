"""
Tests for lub.agents.core — CalibratedAgent and RunReport.

These tests target the scaffold contract: the classes import cleanly,
have the expected attribute shape, and raise NotImplementedError on
unimplemented methods rather than surfacing import errors or attribute
errors. Behavioral tests land with the v0.3 implementation.
"""

from __future__ import annotations

import pytest


def test_imports():
    from lub.agents import CalibratedAgent, RunReport

    assert CalibratedAgent is not None
    assert RunReport is not None


def test_run_report_has_expected_fields():
    from lub.agents import RunReport

    report = RunReport(
        input={"q": "test"},
        output="test_output",
        confidence=0.75,
    )
    assert report.input == {"q": "test"}
    assert report.output == "test_output"
    assert report.confidence == 0.75
    assert report.refusal_flags == {}
    assert report.audit_trail == {}


def test_run_report_to_json_is_scaffold():
    from lub.agents import RunReport

    report = RunReport(input={}, output="", confidence=0.5)
    with pytest.raises(NotImplementedError, match="to_json"):
        report.to_json()


def test_run_report_to_oscal_is_scaffold():
    from lub.agents import RunReport

    report = RunReport(input={}, output="", confidence=0.5)
    with pytest.raises(NotImplementedError, match="to_oscal"):
        report.to_oscal()


def test_calibrated_agent_run_is_scaffold():
    from lub.agents import CalibratedAgent

    class MyAgent(CalibratedAgent):
        prompt_template = "Answer: {q}"

        def parse(self, raw: str) -> str:
            return raw.strip()

    agent = MyAgent(backend=object(), uncertainty=object(), policy=object())
    with pytest.raises(NotImplementedError, match="scaffold"):
        agent.run({"q": "test"})


def test_calibrated_agent_parse_is_abstract():
    from lub.agents import CalibratedAgent

    # Instantiating an ABC without implementing parse should fail at class
    # instantiation time due to ABC contract.
    with pytest.raises(TypeError):
        CalibratedAgent(  # type: ignore[abstract]
            backend=object(),
            uncertainty=object(),
            policy=object(),
        )


def test_calibrated_agent_render_prompt_with_dict_input():
    from lub.agents import CalibratedAgent

    class MyAgent(CalibratedAgent):
        prompt_template = "Q: {q}"

        def parse(self, raw: str) -> str:
            return raw

    agent = MyAgent(backend=object(), uncertainty=object(), policy=object())
    rendered = agent.render_prompt({"q": "ping"})
    assert rendered == "Q: ping"


def test_calibrated_agent_render_prompt_with_non_dict_input_is_scaffold():
    from lub.agents import CalibratedAgent

    class MyAgent(CalibratedAgent):
        prompt_template = "Q: {q}"

        def parse(self, raw: str) -> str:
            return raw

    agent = MyAgent(backend=object(), uncertainty=object(), policy=object())
    with pytest.raises(NotImplementedError, match="dict inputs"):
        agent.render_prompt("not a dict")


def test_calibrated_agent_missing_prompt_template():
    from lub.agents import CalibratedAgent

    class MyAgent(CalibratedAgent):
        def parse(self, raw: str) -> str:
            return raw

    agent = MyAgent(backend=object(), uncertainty=object(), policy=object())
    with pytest.raises(NotImplementedError, match="prompt_template"):
        agent.render_prompt({"q": "ping"})
