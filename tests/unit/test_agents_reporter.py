"""
Tests for lub.agents.reporter — ReportingAgent and AuditTrail.
"""

from __future__ import annotations

import pytest


def test_imports():
    from lub.agents import AuditTrail, ReportingAgent

    assert AuditTrail is not None
    assert ReportingAgent is not None


def test_audit_trail_direct_construction():
    from lub.agents import AuditTrail

    trail = AuditTrail(
        run_id="01J...",
        agent_class="tests.FakeAgent",
        agent_version=None,
        lub_version="0.0.1",
        backend_id="HFBackend/Qwen2.5-0.5B-Instruct",
        uncertainty_method="semantic_entropy",
        prompt_version="sha256:abc123",
        input_hash="sha256:def456",
        raw_output="raw",
        parsed_output_repr="'raw'",
        confidence=0.75,
        refusal_decisions={},
        timestamp_utc="2026-04-23T12:00:00+00:00",
    )
    assert trail.run_id == "01J..."
    assert trail.confidence == 0.75


def test_audit_trail_new_factory_is_scaffold():
    from lub.agents import AuditTrail

    with pytest.raises(NotImplementedError, match="scaffold"):
        AuditTrail.new(
            agent_class="tests.FakeAgent",
            backend_id="HFBackend/x",
            uncertainty_method="semantic_entropy",
        )


def test_audit_trail_to_markdown_is_scaffold():
    from lub.agents import AuditTrail

    trail = AuditTrail(
        run_id="r",
        agent_class="a",
        agent_version=None,
        lub_version="0.0.1",
        backend_id="b",
        uncertainty_method="m",
        prompt_version="p",
        input_hash="i",
        raw_output="",
        parsed_output_repr="",
        confidence=0.5,
        refusal_decisions={},
        timestamp_utc="2026-04-23T12:00:00+00:00",
    )
    with pytest.raises(NotImplementedError):
        trail.to_markdown()


def test_audit_trail_to_oscal_is_scaffold():
    from lub.agents import AuditTrail

    trail = AuditTrail(
        run_id="r",
        agent_class="a",
        agent_version=None,
        lub_version="0.0.1",
        backend_id="b",
        uncertainty_method="m",
        prompt_version="p",
        input_hash="i",
        raw_output="",
        parsed_output_repr="",
        confidence=0.5,
        refusal_decisions={},
        timestamp_utc="2026-04-23T12:00:00+00:00",
    )
    with pytest.raises(NotImplementedError):
        trail.to_oscal()


def test_reporting_agent_run_is_scaffold():
    from lub.agents import ReportingAgent

    class MyAgent(ReportingAgent):
        prompt_template = "x"

        def parse(self, raw: str) -> str:
            return raw

    agent = MyAgent(backend=object(), uncertainty=object(), policy=object())
    with pytest.raises(NotImplementedError, match="scaffold"):
        agent.run({"x": "y"})


def test_reporting_agent_now_iso_returns_iso_string():
    from lub.agents import ReportingAgent

    ts = ReportingAgent._now_iso()
    # ISO-8601-with-timezone must contain "T" and "+00:00" or similar.
    assert "T" in ts
    assert any(marker in ts for marker in ("+00:00", "Z"))
