# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.grounded_query``.

Exercises the four-stage chain (RAG -> Agent -> Guard -> Grounding)
that :class:`GroundedQuery` wires on top of an existing
:class:`BridgePlatform`. The tests confirm the *contract* documented in
the module:

* the agent sees the grounded prompt, but the audit envelope restores
  the customer's original prompt;
* a low-grounding signal downgrades the guard verdict (FLAG / ABSTAIN)
  without ever substituting the agent's answer text;
* failures in RAG or the evaluator never propagate -- they fall back to
  the existing platform path or skip grounding, and always leave a
  structured audit event behind;
* ``require_grounding=True`` short-circuits with ABSTAIN before the
  agent is called, matching the regulated-channel behaviour.

LLM and pipeline calls are mocked: the tests never touch a network or
load a model. Real :class:`BridgePlatform` and :class:`UncertaintyGuard`
instances are constructed because :class:`GroundedQuery` enforces the
type at construction time, but every collaborator below them is a
deterministic fake.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from lub.connectors.bridge import (
    AgentRole,
    BridgeResult,
    EscalationReason,
)
from lub.connectors.bridge.grounded_query import (
    GroundedQuery,
    GroundedQueryConfig,
)
from lub.connectors.bridge.grounding import (
    GroundingScore,
    LexicalGroundingEvaluator,
)
from lub.connectors.bridge.platform import BridgePlatform
from lub.connectors.bridge.rag import (
    Document,
    RAGPipeline,
    RAGResult,
    RetrievedDocument,
)
from lub.guard import PolicyDecision, UncertaintyGuard
from lub.types import UncertaintyResult

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakePipeline:
    """Minimal pipeline that satisfies UncertaintyGuard's protocol."""

    answer_text: str = "PIX opera 24/7. [Fonte: BCB Manual PIX]"
    confidence: float = 0.92
    raise_on_call: bool = False
    last_prompt: str | None = None

    def answer(self, prompt: str, **_kwargs: Any) -> UncertaintyResult:
        self.last_prompt = prompt
        if self.raise_on_call:
            raise RuntimeError("pipeline failure")
        return UncertaintyResult(
            answer=self.answer_text,
            confidence=self.confidence,
            raw_scores={"entropy": 0.1},
        )


@dataclass
class _RecordingAgent:
    """Records what prompt the platform handed to the agent."""

    response: str = "PIX opera 24/7. [Fonte: BCB Manual PIX]"
    last_prompt: str | None = None
    call_count: int = 0
    raise_on_call: bool = False

    def __call__(self, prompt: str) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        if self.raise_on_call:
            raise RuntimeError("agent failure")
        return self.response


@dataclass
class _FakeRetriever:
    """Deterministic retriever that satisfies the Retriever protocol."""

    results: list[RetrievedDocument] = field(default_factory=list)
    raise_on_call: bool = False
    last_query: str | None = None

    def retrieve(self, query: str, k: int = 3) -> list[RetrievedDocument]:
        self.last_query = query
        if self.raise_on_call:
            raise RuntimeError("retriever failure")
        return list(self.results[:k])


@dataclass
class _StubEvaluator:
    """Evaluator that returns a predetermined GroundingScore."""

    score_to_return: GroundingScore | None = None
    raise_on_call: bool = False
    last_answer: str | None = None
    last_rag: RAGResult | None = None

    def score(self, answer: str, rag: RAGResult) -> GroundingScore:
        self.last_answer = answer
        self.last_rag = rag
        if self.raise_on_call:
            raise RuntimeError("evaluator failure")
        if self.score_to_return is not None:
            return self.score_to_return
        return _perfect_score()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _doc(doc_id: str, text: str, source: str) -> Document:
    return Document(id=doc_id, text=text, source=source)


def _retrieved(doc: Document, score: float) -> RetrievedDocument:
    return RetrievedDocument(document=doc, score=score)


def _perfect_score() -> GroundingScore:
    return GroundingScore(
        citation_score=1.0,
        support_score=1.0,
        coverage_score=1.0,
        cited_sources=("BCB Manual PIX",),
        missing_sources=(),
        unsupported_token_ratio=0.0,
    )


def _weak_score(*, citation: float = 0.5, support: float = 0.5, coverage: float = 0.5) -> GroundingScore:
    return GroundingScore(
        citation_score=citation,
        support_score=support,
        coverage_score=coverage,
        cited_sources=("BCB Manual PIX",),
        missing_sources=("Manual Bradesco TED",),
        unsupported_token_ratio=1.0 - support,
    )


def _build_platform(
    agent: _RecordingAgent | None = None,
    *,
    pipeline: _FakePipeline | None = None,
    threshold: float = 0.5,
    role: AgentRole = AgentRole.CHATBOT,
) -> tuple[BridgePlatform, _RecordingAgent, _FakePipeline]:
    agent = agent or _RecordingAgent()
    pipeline = pipeline or _FakePipeline()
    guard = UncertaintyGuard(pipeline=pipeline, threshold=threshold)
    platform = BridgePlatform(guard=guard, default_role=role)
    platform.register_agent(role, agent)
    return platform, agent, pipeline


def _build_rag(
    *,
    retrieved: list[RetrievedDocument] | None = None,
    raise_on_call: bool = False,
    top_k: int = 3,
    min_score: float = 0.05,
) -> tuple[RAGPipeline, _FakeRetriever]:
    retriever = _FakeRetriever(results=retrieved or [], raise_on_call=raise_on_call)
    pipeline = RAGPipeline(retriever=retriever, top_k=top_k, min_score=min_score)
    return pipeline, retriever


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pix_doc() -> Document:
    return _doc(
        "pix-001",
        "PIX e o sistema de pagamentos instantaneos do Banco Central. Opera 24 horas todos os dias.",
        "BCB Manual PIX",
    )


@pytest.fixture
def populated_rag(pix_doc: Document) -> tuple[RAGPipeline, _FakeRetriever]:
    return _build_rag(retrieved=[_retrieved(pix_doc, score=0.62)])


@pytest.fixture
def empty_rag() -> tuple[RAGPipeline, _FakeRetriever]:
    return _build_rag(retrieved=[])


@pytest.fixture
def passthrough_platform() -> tuple[BridgePlatform, _RecordingAgent, _FakePipeline]:
    return _build_platform()


# ---------------------------------------------------------------------------
# GroundedQueryConfig
# ---------------------------------------------------------------------------


class TestGroundedQueryConfig:
    def test_defaults_pass_validation(self) -> None:
        cfg = GroundedQueryConfig()
        assert cfg.require_grounding is False
        assert 0.0 <= cfg.hard_floor <= cfg.soft_floor <= 1.0

    @pytest.mark.parametrize("hard_floor", [-0.01, 1.01, -1.0, 2.0])
    def test_hard_floor_out_of_range_rejected(self, hard_floor: float) -> None:
        with pytest.raises(ValueError, match="hard_floor"):
            GroundedQueryConfig(hard_floor=hard_floor, soft_floor=0.99)

    @pytest.mark.parametrize("soft_floor", [-0.01, 1.01, -1.0, 2.0])
    def test_soft_floor_out_of_range_rejected(self, soft_floor: float) -> None:
        with pytest.raises(ValueError, match="soft_floor"):
            GroundedQueryConfig(hard_floor=0.0, soft_floor=soft_floor)

    def test_hard_above_soft_rejected(self) -> None:
        with pytest.raises(ValueError, match="hard_floor.*soft_floor"):
            GroundedQueryConfig(hard_floor=0.7, soft_floor=0.3)

    def test_hard_equal_soft_accepted(self) -> None:
        cfg = GroundedQueryConfig(hard_floor=0.5, soft_floor=0.5)
        assert cfg.hard_floor == cfg.soft_floor == 0.5

    def test_config_is_frozen(self) -> None:
        cfg = GroundedQueryConfig()
        with pytest.raises(Exception):  # FrozenInstanceError subclasses AttributeError
            cfg.hard_floor = 0.99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Construction-time type checks
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_rejects_non_platform(self, populated_rag: tuple[RAGPipeline, _FakeRetriever]) -> None:
        rag, _ = populated_rag
        with pytest.raises(TypeError, match="platform must be a BridgePlatform"):
            GroundedQuery(platform="not a platform", rag=rag)  # type: ignore[arg-type]

    def test_rejects_non_rag(
        self, passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline]
    ) -> None:
        platform, _, _ = passthrough_platform
        with pytest.raises(TypeError, match="rag must be a RAGPipeline"):
            GroundedQuery(platform=platform, rag="not a rag")  # type: ignore[arg-type]

    def test_rejects_non_evaluator(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        with pytest.raises(TypeError, match="evaluator must implement GroundingEvaluator"):
            GroundedQuery(platform=platform, rag=rag, evaluator="nope")  # type: ignore[arg-type]

    def test_default_evaluator_is_lexical(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag)
        assert isinstance(gq.evaluator, LexicalGroundingEvaluator)

    def test_default_config_does_not_require_grounding(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag)
        assert gq.config.require_grounding is False


# ---------------------------------------------------------------------------
# Convenience query() wrapper
# ---------------------------------------------------------------------------


class TestQueryConvenience:
    def test_query_returns_post_policy_string_only(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, agent, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        out = gq.query("Como funciona o PIX?")
        assert out == agent.response


# ---------------------------------------------------------------------------
# End-to-end pipeline wiring (the missing connection)
# ---------------------------------------------------------------------------


class TestPipelineWiring:
    def test_agent_receives_grounded_prompt_when_evidence_present(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, agent, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        original = "Como funciona o PIX?"
        gq.query_with_confidence(original)
        # Agent must have been called with the grounded prompt, not the raw one.
        assert agent.last_prompt is not None
        assert original in agent.last_prompt
        assert "BCB Manual PIX" in agent.last_prompt
        assert agent.last_prompt != original

    def test_agent_receives_raw_prompt_when_rag_returns_nothing(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        empty_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, agent, _ = passthrough_platform
        rag, _ = empty_rag
        # require_grounding=False (default) -> fall back, do not refuse.
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        original = "saldo conta corrente"
        gq.query_with_confidence(original)
        assert agent.last_prompt == original

    def test_original_prompt_is_restored_on_response_envelope(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        original = "Como funciona o PIX?"
        result = gq.query_with_confidence(original)
        # Audit consumers expect the customer's text, not the grounded template.
        assert result.primary.prompt == original

    def test_default_role_used_when_none_supplied(
        self,
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, agent, _ = _build_platform(role=AgentRole.SMART_PAYMENTS)
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        result = gq.query_with_confidence("autorizar transferencia 500")
        assert result.primary.role == AgentRole.SMART_PAYMENTS
        assert agent.call_count == 1

    def test_explicit_role_overrides_default(
        self,
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, agent, _ = _build_platform(role=AgentRole.CHATBOT)
        # Register a second role so we can dispatch to it.
        payments = _RecordingAgent(response="autorizado [Fonte: BCB Manual PIX]")
        platform.register_agent(AgentRole.SMART_PAYMENTS, payments)
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        result = gq.query_with_confidence("transferir", role=AgentRole.SMART_PAYMENTS)
        assert result.primary.role == AgentRole.SMART_PAYMENTS
        assert payments.call_count == 1
        assert agent.call_count == 0


# ---------------------------------------------------------------------------
# Grounding-driven verdict downgrade
# ---------------------------------------------------------------------------


class TestGroundingDowngrade:
    def test_high_grounding_preserves_passthrough(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(score_to_return=_perfect_score()),
        )
        result = gq.query_with_confidence("Como funciona o PIX?")
        assert result.primary.guard_result is not None
        assert result.primary.guard_result.outcome.decision is PolicyDecision.PASSTHROUGH
        assert result.escalated is False
        assert result.escalation_reason is None

    def test_mid_grounding_downgrades_to_flag(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, agent, _ = passthrough_platform
        rag, _ = populated_rag
        # Geometric mean of (0.4, 0.4, 0.4) ~= 0.4 -> between hard_floor (0.20)
        # and soft_floor (0.50) -> FLAG.
        mid = _weak_score(citation=0.4, support=0.4, coverage=0.4)
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(score_to_return=mid),
        )
        result = gq.query_with_confidence("Como funciona o PIX?")
        assert result.primary.guard_result is not None
        assert result.primary.guard_result.outcome.decision is PolicyDecision.FLAG
        assert result.escalated is True
        assert result.escalation_reason is EscalationReason.POLICY_FLAG
        # Contract: FLAG releases the agent's text unchanged.
        assert result.primary.answer == agent.response

    def test_low_grounding_downgrades_to_abstain(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, agent, _ = passthrough_platform
        rag, _ = populated_rag
        # Geometric mean of (0.1, 0.1, 0.1) ~= 0.1 < hard_floor (0.20) -> ABSTAIN.
        very_low = _weak_score(citation=0.1, support=0.1, coverage=0.1)
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(score_to_return=very_low),
        )
        result = gq.query_with_confidence("Como funciona o PIX?")
        assert result.primary.guard_result is not None
        assert result.primary.guard_result.outcome.decision is PolicyDecision.ABSTAIN
        assert result.escalated is True
        assert result.escalation_reason is EscalationReason.POLICY_ABSTAIN
        # Contract: ABSTAIN suppresses the answer with the abstain marker;
        # the agent's text is *never* substituted -- it is hidden.
        assert result.primary.answer != agent.response
        assert "ABSTAIN" in result.primary.answer.upper()

    def test_zero_grounding_collapses_to_abstain(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        zero = GroundingScore(
            citation_score=0.0,
            support_score=1.0,
            coverage_score=1.0,
            cited_sources=(),
            missing_sources=("BCB Manual PIX",),
            unsupported_token_ratio=0.0,
        )
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(score_to_return=zero),
        )
        result = gq.query_with_confidence("Como funciona o PIX?")
        assert result.primary.guard_result is not None
        assert result.primary.guard_result.outcome.decision is PolicyDecision.ABSTAIN

    def test_custom_floor_thresholds_take_effect(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        # With soft_floor=0.95, even a fairly strong score gets downgraded.
        cfg = GroundedQueryConfig(hard_floor=0.05, soft_floor=0.95)
        score = _weak_score(citation=0.7, support=0.7, coverage=0.7)  # ~0.7 confidence
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(score_to_return=score),
            config=cfg,
        )
        result = gq.query_with_confidence("Como funciona o PIX?")
        assert result.primary.guard_result is not None
        assert result.primary.guard_result.outcome.decision is PolicyDecision.FLAG


# ---------------------------------------------------------------------------
# require_grounding short-circuit
# ---------------------------------------------------------------------------


class TestRequireGrounding:
    def test_refuses_without_calling_agent_when_rag_empty(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        empty_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, agent, pipeline = passthrough_platform
        rag, _ = empty_rag
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(),
            config=GroundedQueryConfig(require_grounding=True),
        )
        result = gq.query_with_confidence("autorizar transferencia 5000")
        # Agent and guard pipeline must NOT have been touched.
        assert agent.call_count == 0
        assert pipeline.last_prompt is None
        # Result is an ABSTAIN-style escalation.
        assert result.escalated is True
        assert result.escalation_reason is EscalationReason.POLICY_ABSTAIN
        assert "ABSTAIN" in result.primary.answer.upper()
        assert result.primary.prompt == "autorizar transferencia 5000"

    def test_refusal_audit_trail_explains_why(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        empty_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = empty_rag
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(),
            config=GroundedQueryConfig(require_grounding=True),
        )
        result = gq.query_with_confidence("transferir")
        events = [e["event"] for e in result.audit_trail]
        assert "grounded_query.start" in events
        assert "grounded_query.rag_empty" in events
        assert "grounded_query.refused_ungrounded" in events

    def test_proceeds_normally_when_grounding_present(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, agent, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(),
            config=GroundedQueryConfig(require_grounding=True),
        )
        result = gq.query_with_confidence("Como funciona o PIX?")
        assert agent.call_count == 1
        assert result.escalated is False


# ---------------------------------------------------------------------------
# Defensive error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_rag_exception_falls_through_with_raw_prompt(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
    ) -> None:
        platform, agent, _ = passthrough_platform
        rag, _ = _build_rag(raise_on_call=True)
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        original = "Qual o saldo?"
        result = gq.query_with_confidence(original)
        # Pipeline still ran with the raw prompt.
        assert agent.last_prompt == original
        # Audit must record that grounding was skipped because of no evidence.
        events = [e["event"] for e in result.audit_trail]
        assert "grounded_query.grounding_skipped" in events

    def test_rag_exception_with_require_grounding_refuses(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
    ) -> None:
        platform, agent, pipeline = passthrough_platform
        rag, _ = _build_rag(raise_on_call=True)
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(),
            config=GroundedQueryConfig(require_grounding=True),
        )
        result = gq.query_with_confidence("autorizar PIX 10000")
        assert agent.call_count == 0
        assert pipeline.last_prompt is None
        assert result.escalation_reason is EscalationReason.POLICY_ABSTAIN

    def test_evaluator_exception_skips_downgrade_but_keeps_audit(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(raise_on_call=True),
        )
        result = gq.query_with_confidence("Como funciona o PIX?")
        # Original verdict must be preserved (no downgrade applied).
        assert result.primary.guard_result is not None
        assert result.primary.guard_result.outcome.decision is PolicyDecision.PASSTHROUGH
        events = [e["event"] for e in result.audit_trail]
        assert "grounded_query.grounding_error" in events

    def test_grounding_skipped_when_no_guard_verdict(
        self,
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        # Make the guard pipeline raise so the platform records a None verdict.
        pipeline = _FakePipeline(raise_on_call=True)
        platform, _, _ = _build_platform(pipeline=pipeline)
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        result = gq.query_with_confidence("Como funciona o PIX?")
        assert result.primary.guard_result is None
        events = [e["event"] for e in result.audit_trail]
        assert "grounded_query.grounding_skipped" in events
        # An evaluator failure should NOT be recorded -- we never called it.
        assert "grounded_query.grounding_error" not in events

    def test_agent_failure_propagates_as_escalation(
        self,
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        agent = _RecordingAgent(raise_on_call=True)
        platform, _, _ = _build_platform(agent=agent)
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        result = gq.query_with_confidence("Como funciona o PIX?")
        assert result.escalated is True
        assert result.escalation_reason is EscalationReason.AGENT_ERROR


# ---------------------------------------------------------------------------
# Audit trail assembly
# ---------------------------------------------------------------------------


class TestAuditTrail:
    def test_start_and_end_events_present_on_normal_path(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        result = gq.query_with_confidence("Como funciona o PIX?")
        events = [e["event"] for e in result.audit_trail]
        assert events[0] == "grounded_query.start"
        assert events[-1] == "grounded_query.end"
        assert "grounded_query.grounding_scored" in events

    def test_start_event_records_retrieval_metadata(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        original = "Como funciona o PIX?"
        result = gq.query_with_confidence(original)
        head = result.audit_trail[0]
        assert head["event"] == "grounded_query.start"
        assert head["prompt_chars"] == len(original)
        assert head["retrieved"] == 1
        assert head["rag_citations"] == ["BCB Manual PIX"]

    def test_grounding_scored_event_carries_decisions(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        weak = _weak_score(citation=0.1, support=0.1, coverage=0.1)  # -> ABSTAIN
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(score_to_return=weak),
        )
        result = gq.query_with_confidence("Como funciona o PIX?")
        scored: Mapping[str, Any] | None = next(
            (e for e in result.audit_trail if e["event"] == "grounded_query.grounding_scored"),
            None,
        )
        assert scored is not None
        assert scored["prior_decision"] == PolicyDecision.PASSTHROUGH.value
        assert scored["post_decision"] == PolicyDecision.ABSTAIN.value
        # The grounding payload is JSON-serializable for the BCB envelope.
        assert "confidence" in scored["grounding"]

    def test_audit_trail_immutable_after_return(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        result = gq.query_with_confidence("Como funciona o PIX?")
        # BridgeResult holds audit_trail as a tuple -- structurally immutable.
        assert isinstance(result.audit_trail, tuple)


# ---------------------------------------------------------------------------
# Integration with the real lexical evaluator (no stub)
# ---------------------------------------------------------------------------


class TestLexicalEvaluatorIntegration:
    def test_well_grounded_answer_passes_through(
        self, pix_doc: Document
    ) -> None:
        # Agent returns an answer that is grounded in the doc and cites it.
        agent = _RecordingAgent(
            response=(
                "PIX e o sistema de pagamentos instantaneos do Banco Central. "
                "Opera 24 horas todos os dias. [Fonte: BCB Manual PIX]"
            )
        )
        platform, _, _ = _build_platform(agent=agent)
        rag, _ = _build_rag(retrieved=[_retrieved(pix_doc, score=0.65)])
        gq = GroundedQuery(platform=platform, rag=rag)  # default LexicalGroundingEvaluator
        result = gq.query_with_confidence("Como funciona o PIX?")
        assert result.primary.guard_result is not None
        assert result.primary.guard_result.outcome.decision is PolicyDecision.PASSTHROUGH

    def test_uncited_answer_is_downgraded(self, pix_doc: Document) -> None:
        # Agent omits the [Fonte: ...] marker -> citation_score=0 -> ABSTAIN.
        agent = _RecordingAgent(response="Sim, o PIX opera 24 horas.")
        platform, _, _ = _build_platform(agent=agent)
        rag, _ = _build_rag(retrieved=[_retrieved(pix_doc, score=0.65)])
        gq = GroundedQuery(platform=platform, rag=rag)
        result = gq.query_with_confidence("Como funciona o PIX?")
        assert result.primary.guard_result is not None
        assert result.primary.guard_result.outcome.decision is PolicyDecision.ABSTAIN
        assert result.escalation_reason is EscalationReason.POLICY_ABSTAIN


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_prompt_does_not_raise(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        empty_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = empty_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        result = gq.query_with_confidence("")
        assert isinstance(result, BridgeResult)
        assert result.primary.prompt == ""

    def test_pii_in_prompt_passes_through_unchanged(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        # Grounded query layer is not a PII redactor -- it must transmit the
        # exact customer text so an upstream redactor can act on it.
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        cpf_prompt = "meu CPF e 123.456.789-00, qual meu saldo PIX?"
        result = gq.query_with_confidence(cpf_prompt)
        assert result.primary.prompt == cpf_prompt

    def test_very_long_prompt_is_handled(
        self,
        passthrough_platform: tuple[BridgePlatform, _RecordingAgent, _FakePipeline],
        populated_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        platform, _, _ = passthrough_platform
        rag, _ = populated_rag
        gq = GroundedQuery(platform=platform, rag=rag, evaluator=_StubEvaluator())
        long_prompt = "PIX " * 5000
        result = gq.query_with_confidence(long_prompt)
        assert result.primary.prompt == long_prompt
        assert result.audit_trail[0]["prompt_chars"] == len(long_prompt)


# ---------------------------------------------------------------------------
# BridgePlatform shim
# ---------------------------------------------------------------------------


class TestGuardAbstainMarkerShim:
    def test_method_attached_to_bridge_platform(self) -> None:
        # The grounded_query module patches BridgePlatform on import.
        assert hasattr(BridgePlatform, "guard_abstain_marker")

    def test_returns_configured_marker(self) -> None:
        custom = "[CUSTOM ABSTAIN MARKER]"
        guard = UncertaintyGuard(pipeline=_FakePipeline(), abstain_marker=custom)
        platform = BridgePlatform(guard=guard)
        assert platform.guard_abstain_marker() == custom

    def test_refusal_uses_platform_abstain_marker(
        self,
        empty_rag: tuple[RAGPipeline, _FakeRetriever],
    ) -> None:
        custom = "[ESCALATING TO HUMAN]"
        guard = UncertaintyGuard(pipeline=_FakePipeline(), abstain_marker=custom)
        platform = BridgePlatform(guard=guard)
        platform.register_agent(AgentRole.CHATBOT, _RecordingAgent())
        rag, _ = empty_rag
        gq = GroundedQuery(
            platform=platform,
            rag=rag,
            evaluator=_StubEvaluator(),
            config=GroundedQueryConfig(require_grounding=True),
        )
        result = gq.query_with_confidence("autorizar PIX 10k")
        assert result.primary.answer == custom
