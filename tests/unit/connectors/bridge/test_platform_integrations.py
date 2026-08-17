# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``BridgePlatform`` integration with the new optional collaborators.

Covers the four keyword-only constructor params added in 2026-05:
``complexity``, ``cache``, ``customer_memory``, ``rag``.

Each is tested in isolation (other collaborators left as None) so a
regression in one cannot mask another.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lub.connectors.bridge import AgentRole
from lub.connectors.bridge.complexity import ComplexityRouter, ComplexityTier
from lub.connectors.bridge.customer_memory import CustomerMemory, InMemoryMemoryStore
from lub.connectors.bridge.memory import SemanticCache
from lub.connectors.bridge.platform import BridgePlatform
from lub.connectors.bridge.rag import (
    Document,
    InMemoryDocumentStore,
    RAGPipeline,
    TFIDFRetriever,
)
from lub.guard import PolicyDecision

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_guard() -> MagicMock:
    """A guard mock that lets every agent answer through unchanged.

    The platform calls ``self._guard(prompt)`` (callable). We return a
    minimal fake GuardResult that the platform's _select_answer logic
    treats as a successful passthrough so tests can focus on the
    pre-agent pipeline stages we care about here.
    """
    g = MagicMock()
    g.threshold = 0.5
    g.abstain_marker = "[ABSTAIN]"
    g.on_fail = MagicMock(value="abstain")
    fake_result = MagicMock()
    fake_result.answer = "guard-passthrough"
    fake_result.raw.confidence = 0.9
    fake_result.raw.answer = "guard-passthrough"
    fake_result.outcome.decision = PolicyDecision.PASSTHROUGH
    fake_result.outcome.passed = True
    fake_result.outcome.reason = "ok"
    g.return_value = fake_result
    return g


@pytest.fixture
def fake_agent() -> MagicMock:
    agent = MagicMock(side_effect=lambda prompt: f"answer-to: {prompt}")
    return agent


@pytest.fixture
def populated_doc_store() -> InMemoryDocumentStore:
    s = InMemoryDocumentStore()
    s.add(Document(id="d1", text="PIX e o sistema do BCB", source="Manual PIX"))
    s.add(Document(id="d2", text="TED em dias uteis", source="Manual TED"))
    return s


# ---------------------------------------------------------------------------
# Constructor: optional params default to None and don't change behavior
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_defaults_keep_old_behavior(self, fake_guard: MagicMock) -> None:
        platform = BridgePlatform(guard=fake_guard)
        # All four attrs are None when not supplied
        assert platform._cache is None
        assert platform._complexity is None
        assert platform._customer_memory is None
        assert platform._rag is None

    def test_accepts_all_collaborators(self, fake_guard: MagicMock) -> None:
        platform = BridgePlatform(
            guard=fake_guard,
            complexity=ComplexityRouter(),
            cache=SemanticCache(),
            customer_memory=CustomerMemory(store=InMemoryMemoryStore()),
            rag=RAGPipeline(retriever=TFIDFRetriever(store=InMemoryDocumentStore())),
        )
        assert platform._complexity is not None
        assert platform._cache is not None
        assert platform._customer_memory is not None
        assert platform._rag is not None


# ---------------------------------------------------------------------------
# Cache: short-circuits when there's a hit
# ---------------------------------------------------------------------------


class TestCacheIntegration:
    def test_cache_hit_short_circuits_agent(
        self, fake_guard: MagicMock, fake_agent: MagicMock
    ) -> None:
        cache = SemanticCache()
        cache.store("qual meu saldo?", "R$ 100", intent="chatbot", confidence=0.9)

        platform = BridgePlatform(guard=fake_guard, cache=cache)
        platform.register_agent(AgentRole.CHATBOT, fake_agent)

        result = platform.query_with_confidence("qual meu saldo?")

        # Agent never called because cache served the answer
        assert fake_agent.call_count == 0
        assert result.primary.answer == "R$ 100"
        # Cache hit recorded in audit
        events = [e["event"] for e in result.audit_trail]
        assert "query.cache_hit" in events

    def test_cache_miss_stores_after_successful_answer(
        self, fake_guard: MagicMock, fake_agent: MagicMock
    ) -> None:
        cache = SemanticCache()
        platform = BridgePlatform(guard=fake_guard, cache=cache)
        platform.register_agent(AgentRole.CHATBOT, fake_agent)

        assert cache.size == 0
        platform.query_with_confidence("qual meu saldo?")
        assert cache.size == 1

    def test_no_cache_means_no_storage(
        self, fake_guard: MagicMock, fake_agent: MagicMock
    ) -> None:
        platform = BridgePlatform(guard=fake_guard)  # no cache
        platform.register_agent(AgentRole.CHATBOT, fake_agent)
        # Should not raise
        result = platform.query_with_confidence("anything")
        assert result.primary.answer  # got some answer


# ---------------------------------------------------------------------------
# Complexity: scored and recorded in audit
# ---------------------------------------------------------------------------


class TestComplexityIntegration:
    def test_complexity_recorded_in_audit(
        self, fake_guard: MagicMock, fake_agent: MagicMock
    ) -> None:
        platform = BridgePlatform(
            guard=fake_guard,
            complexity=ComplexityRouter(),
        )
        platform.register_agent(AgentRole.CHATBOT, fake_agent)

        result = platform.query_with_confidence(
            "Qual a posicao do BACEN sobre tributacao de PIX para PJ?"
        )
        events = [e for e in result.audit_trail if e["event"] == "query.complexity_scored"]
        assert len(events) == 1
        assert events[0]["tier"] == ComplexityTier.COMPLEX.value

    def test_no_complexity_means_no_scoring_event(
        self, fake_guard: MagicMock, fake_agent: MagicMock
    ) -> None:
        platform = BridgePlatform(guard=fake_guard)
        platform.register_agent(AgentRole.CHATBOT, fake_agent)

        result = platform.query_with_confidence("test")
        events = [e["event"] for e in result.audit_trail]
        assert "query.complexity_scored" not in events


# ---------------------------------------------------------------------------
# Customer memory: loaded when customer_id provided
# ---------------------------------------------------------------------------


class TestCustomerMemoryIntegration:
    def test_memory_loaded_when_customer_id_supplied(
        self, fake_guard: MagicMock, fake_agent: MagicMock
    ) -> None:
        memory = CustomerMemory(store=InMemoryMemoryStore())
        memory.update_block("c-123", "persona", "PF conservador")

        platform = BridgePlatform(guard=fake_guard, customer_memory=memory)
        platform.register_agent(AgentRole.CHATBOT, fake_agent)

        result = platform.query_with_confidence("test", customer_id="c-123")
        events = [e for e in result.audit_trail if e["event"] == "query.customer_memory_loaded"]
        assert len(events) == 1
        assert events[0]["customer_id"] == "c-123"
        assert "persona" in events[0]["block_names"]

    def test_no_event_when_no_customer_id(
        self, fake_guard: MagicMock, fake_agent: MagicMock
    ) -> None:
        memory = CustomerMemory(store=InMemoryMemoryStore())
        memory.update_block("c-123", "persona", "PF")

        platform = BridgePlatform(guard=fake_guard, customer_memory=memory)
        platform.register_agent(AgentRole.CHATBOT, fake_agent)

        result = platform.query_with_confidence("test")  # no customer_id
        events = [e["event"] for e in result.audit_trail]
        assert "query.customer_memory_loaded" not in events

    def test_unknown_customer_id_no_event(
        self, fake_guard: MagicMock, fake_agent: MagicMock
    ) -> None:
        memory = CustomerMemory(store=InMemoryMemoryStore())  # empty
        platform = BridgePlatform(guard=fake_guard, customer_memory=memory)
        platform.register_agent(AgentRole.CHATBOT, fake_agent)

        result = platform.query_with_confidence("test", customer_id="ghost")
        events = [e["event"] for e in result.audit_trail]
        # Empty blocks ⇒ no load event
        assert "query.customer_memory_loaded" not in events


# ---------------------------------------------------------------------------
# RAG: retrieval recorded in audit, citations propagated
# ---------------------------------------------------------------------------


class TestRAGIntegration:
    def test_rag_retrieval_recorded(
        self,
        fake_guard: MagicMock,
        fake_agent: MagicMock,
        populated_doc_store: InMemoryDocumentStore,
    ) -> None:
        rag = RAGPipeline(retriever=TFIDFRetriever(store=populated_doc_store))
        platform = BridgePlatform(guard=fake_guard, rag=rag)
        platform.register_agent(AgentRole.CHATBOT, fake_agent)

        result = platform.query_with_confidence("Como funciona o PIX?")
        events = [e for e in result.audit_trail if e["event"] == "query.rag_retrieved"]
        assert len(events) == 1
        assert events[0]["has_grounding"] is True
        assert "Manual PIX" in events[0]["citations"]

    def test_rag_records_no_grounding_when_corpus_empty(
        self, fake_guard: MagicMock, fake_agent: MagicMock
    ) -> None:
        empty_rag = RAGPipeline(retriever=TFIDFRetriever(store=InMemoryDocumentStore()))
        platform = BridgePlatform(guard=fake_guard, rag=empty_rag)
        platform.register_agent(AgentRole.CHATBOT, fake_agent)

        result = platform.query_with_confidence("test")
        events = [e for e in result.audit_trail if e["event"] == "query.rag_retrieved"]
        assert len(events) == 1
        assert events[0]["has_grounding"] is False
        assert events[0]["citations"] == []


# ---------------------------------------------------------------------------
# All together
# ---------------------------------------------------------------------------


class TestAllCollaboratorsTogether:
    def test_full_pipeline_runs_without_error(
        self,
        fake_guard: MagicMock,
        fake_agent: MagicMock,
        populated_doc_store: InMemoryDocumentStore,
    ) -> None:
        memory = CustomerMemory(store=InMemoryMemoryStore())
        memory.update_block("c-1", "persona", "PF")

        platform = BridgePlatform(
            guard=fake_guard,
            complexity=ComplexityRouter(),
            cache=SemanticCache(),
            customer_memory=memory,
            rag=RAGPipeline(retriever=TFIDFRetriever(store=populated_doc_store)),
        )
        platform.register_agent(AgentRole.CHATBOT, fake_agent)

        result = platform.query_with_confidence("Qual meu saldo?", customer_id="c-1")

        # All four optional stages should appear in the audit
        events = {e["event"] for e in result.audit_trail}
        assert "query.complexity_scored" in events
        assert "query.customer_memory_loaded" in events
        assert "query.rag_retrieved" in events
        # Cache miss → no cache_hit event, but stored after
        assert "query.cache_hit" not in events
