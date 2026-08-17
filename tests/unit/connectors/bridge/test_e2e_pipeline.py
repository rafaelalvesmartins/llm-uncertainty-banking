# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""End-to-end integration test for the full Bridge pipeline.

Unit tests cover each module in isolation. This file proves the *whole
pipeline* — cache → complexity → memory → RAG → intent → agent →
guard → cache_store → audit — works together with realistic banking
inputs.

If any of the 5 new modules silently breaks its contract with platform.py,
this test fails before unit tests do.
"""

from __future__ import annotations

from typing import Any
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
# A fully wired BridgePlatform fixture — banking corpus + customer history
# ---------------------------------------------------------------------------


@pytest.fixture
def production_like_platform() -> tuple[BridgePlatform, dict[str, Any]]:
    """Build a BridgePlatform with all 5 new modules wired and seeded.

    Returns the platform + a dict of references to the live collaborators
    so individual tests can poke at them (cache size, memory blocks, etc.).
    """
    # Seeded RAG corpus — Bradesco product + BCB regulatory docs.
    docs = InMemoryDocumentStore()
    docs.add(
        Document(
            id="pix-001",
            text="PIX e o sistema instantaneo do BCB. Para PF nao ha tarifa.",
            source="BCB Manual PIX",
        )
    )
    docs.add(
        Document(
            id="ted-001",
            text="TED opera em dias uteis ate 17h. Tarifa Bradesco PF: R$9,90.",
            source="Manual Bradesco TED",
        )
    )

    # Customer with a known persona.
    memory = CustomerMemory(store=InMemoryMemoryStore())
    memory.update_block("c-001", "persona", "PF conservador, 8 anos de Bradesco")
    memory.update_block("c-001", "preferences", "Prefere TED para grandes valores")

    # Mock guard that always passes (fixture for testing the wiring).
    guard = MagicMock()
    guard.threshold = 0.5
    guard.abstain_marker = "[ABSTAIN]"
    guard.on_fail = MagicMock(value="abstain")
    fake_result = MagicMock()
    fake_result.answer = "guard answer"
    fake_result.raw.confidence = 0.92
    fake_result.raw.answer = "guard answer"
    fake_result.outcome.decision = PolicyDecision.PASSTHROUGH
    fake_result.outcome.passed = True
    fake_result.outcome.reason = "passthrough"
    guard.return_value = fake_result

    platform = BridgePlatform(
        guard=guard,
        complexity=ComplexityRouter(),
        cache=SemanticCache(similarity_threshold=0.85),
        customer_memory=memory,
        rag=RAGPipeline(retriever=TFIDFRetriever(store=docs), top_k=2),
    )

    # Register a chatbot that returns a deterministic banking answer.
    platform.register_agent(AgentRole.CHATBOT, lambda p: f"Resposta para: {p}")

    refs = {"docs": docs, "memory": memory, "cache": platform._cache}
    return platform, refs


# ---------------------------------------------------------------------------
# E2E: the audit trail tells the full story
# ---------------------------------------------------------------------------


class TestEndToEndPipeline:
    def test_first_query_runs_full_pipeline(
        self, production_like_platform
    ) -> None:
        platform, refs = production_like_platform
        result = platform.query_with_confidence(
            "Como funciona o PIX para pessoa fisica?",
            customer_id="c-001",
        )

        events = [e["event"] for e in result.audit_trail]
        # Every collaborator left a footprint.
        assert "query.start" in events
        assert "query.complexity_scored" in events
        assert "query.customer_memory_loaded" in events
        assert "query.rag_retrieved" in events
        assert "query.cache_hit" not in events  # first query

    def test_repeated_query_short_circuits_via_cache(
        self, production_like_platform
    ) -> None:
        platform, refs = production_like_platform

        # First call populates the cache.
        first = platform.query_with_confidence(
            "Qual a tarifa TED no Bradesco?", customer_id="c-001"
        )
        assert refs["cache"].size == 1

        # Second call hits the cache and skips agent/RAG.
        second = platform.query_with_confidence(
            "Qual a tarifa TED no Bradesco?", customer_id="c-001"
        )
        events = [e["event"] for e in second.audit_trail]
        assert "query.cache_hit" in events
        # Cache hit returns same answer
        assert second.primary.answer == first.primary.answer

    def test_complexity_tier_recorded(self, production_like_platform) -> None:
        platform, _ = production_like_platform
        result = platform.query_with_confidence(
            "Qual a posicao do BACEN sobre tributacao de PIX para PJ?",
            customer_id="c-001",
        )
        complexity_event = next(
            e for e in result.audit_trail if e["event"] == "query.complexity_scored"
        )
        # Regulatory query routes to COMPLEX tier.
        assert complexity_event["tier"] == ComplexityTier.COMPLEX.value

    def test_rag_retrieves_and_cites(self, production_like_platform) -> None:
        platform, _ = production_like_platform
        result = platform.query_with_confidence(
            "Como funciona o PIX?", customer_id="c-001"
        )
        rag_event = next(
            e for e in result.audit_trail if e["event"] == "query.rag_retrieved"
        )
        assert rag_event["has_grounding"] is True
        assert "BCB Manual PIX" in rag_event["citations"]

    def test_customer_memory_appears_in_audit(
        self, production_like_platform
    ) -> None:
        platform, _ = production_like_platform
        result = platform.query_with_confidence("test", customer_id="c-001")
        mem_event = next(
            e for e in result.audit_trail if e["event"] == "query.customer_memory_loaded"
        )
        assert "persona" in mem_event["block_names"]
        assert "preferences" in mem_event["block_names"]

    def test_unknown_customer_skips_memory(self, production_like_platform) -> None:
        platform, _ = production_like_platform
        result = platform.query_with_confidence("test", customer_id="ghost-999")
        events = [e["event"] for e in result.audit_trail]
        assert "query.customer_memory_loaded" not in events

    def test_query_without_customer_id_works(
        self, production_like_platform
    ) -> None:
        platform, _ = production_like_platform
        # No customer_id — memory step is skipped, everything else runs.
        result = platform.query_with_confidence("PIX info?")
        events = [e["event"] for e in result.audit_trail]
        assert "query.customer_memory_loaded" not in events
        assert "query.rag_retrieved" in events
        assert "query.complexity_scored" in events

    def test_pipeline_with_no_collaborators_still_works(self) -> None:
        """Backward compat: BridgePlatform with no new collaborators behaves
        like the pre-2026-05 version (no extra audit events)."""
        guard = MagicMock()
        guard.threshold = 0.5
        guard.abstain_marker = "[ABSTAIN]"
        guard.on_fail = MagicMock(value="abstain")
        fake_result = MagicMock()
        fake_result.answer = "ok"
        fake_result.raw.confidence = 0.9
        fake_result.raw.answer = "ok"
        fake_result.outcome.decision = PolicyDecision.PASSTHROUGH
        fake_result.outcome.passed = True
        fake_result.outcome.reason = "ok"
        guard.return_value = fake_result

        platform = BridgePlatform(guard=guard)
        platform.register_agent(AgentRole.CHATBOT, lambda p: "answer")

        result = platform.query_with_confidence("test")
        events = [e["event"] for e in result.audit_trail]
        # Neither cache nor complexity nor memory nor rag fired.
        assert "query.cache_hit" not in events
        assert "query.complexity_scored" not in events
        assert "query.customer_memory_loaded" not in events
        assert "query.rag_retrieved" not in events
        # But the agent did run.
        assert result.primary.answer == "answer"

    def test_audit_events_are_chronologically_ordered(
        self, production_like_platform
    ) -> None:
        platform, _ = production_like_platform
        result = platform.query_with_confidence("PIX", customer_id="c-001")
        timestamps = [e["timestamp"] for e in result.audit_trail if "timestamp" in e]
        # Should be monotonically non-decreasing.
        assert timestamps == sorted(timestamps)
