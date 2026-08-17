# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.connectors.bridge.rag``."""

from __future__ import annotations

import pytest

from lub.connectors.bridge.rag import (
    Document,
    DocumentStore,
    InMemoryDocumentStore,
    RAGPipeline,
    Retriever,
    TFIDFRetriever,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store_with_banking_docs() -> InMemoryDocumentStore:
    store = InMemoryDocumentStore()
    store.add(
        Document(
            id="pix-001",
            text=(
                "PIX é o sistema de pagamentos instantâneos do Banco Central. "
                "Funciona 24 horas por dia, 7 dias por semana. Para PJ, há "
                "tarifas a partir de janeiro de 2024."
            ),
            source="BCB Manual PIX",
        )
    )
    store.add(
        Document(
            id="ted-001",
            text=(
                "TED (Transferência Eletrônica Disponível) opera em dias úteis "
                "até as 17:00. Valor mínimo R$ 0,01. Tarifa varia por banco."
            ),
            source="Manual Bradesco TED",
        )
    )
    store.add(
        Document(
            id="iof-001",
            text=(
                "IOF não incide sobre transferências PIX. Operações de câmbio "
                "têm IOF de 1,1% conforme decreto 6.306."
            ),
            source="Receita Federal",
        )
    )
    return store


# ---------------------------------------------------------------------------
# Document + Store
# ---------------------------------------------------------------------------


class TestDocumentStore:
    def test_implements_protocol(self) -> None:
        assert isinstance(InMemoryDocumentStore(), DocumentStore)

    def test_add_and_get(self) -> None:
        store = InMemoryDocumentStore()
        doc = Document(id="x", text="hello", source="src")
        store.add(doc)
        assert store.get("x") is doc

    def test_get_missing_returns_none(self) -> None:
        assert InMemoryDocumentStore().get("nope") is None

    def test_add_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            InMemoryDocumentStore().add(Document(id="", text="x", source="s"))

    def test_size_reflects_count(self) -> None:
        store = InMemoryDocumentStore()
        assert store.size == 0
        store.add(Document(id="a", text="x", source="s"))
        store.add(Document(id="b", text="y", source="s"))
        assert store.size == 2

    def test_add_replaces_existing_id(self) -> None:
        store = InMemoryDocumentStore()
        store.add(Document(id="x", text="v1", source="s"))
        store.add(Document(id="x", text="v2", source="s"))
        assert store.size == 1
        assert store.get("x").text == "v2"


# ---------------------------------------------------------------------------
# TFIDFRetriever
# ---------------------------------------------------------------------------


class TestTFIDFRetriever:
    def test_protocol_compliance(self, store_with_banking_docs: InMemoryDocumentStore) -> None:
        r = TFIDFRetriever(store=store_with_banking_docs)
        assert isinstance(r, Retriever)

    def test_invalid_store_raises(self) -> None:
        class NotAStore:
            pass

        with pytest.raises(TypeError, match="DocumentStore"):
            TFIDFRetriever(store=NotAStore())  # type: ignore[arg-type]

    def test_empty_store_returns_empty(self) -> None:
        r = TFIDFRetriever(store=InMemoryDocumentStore())
        assert r.retrieve("anything") == []

    def test_retrieves_relevant_doc_first(
        self, store_with_banking_docs: InMemoryDocumentStore
    ) -> None:
        r = TFIDFRetriever(store=store_with_banking_docs)
        results = r.retrieve("Como funciona o PIX?")
        assert len(results) > 0
        assert results[0].document.id == "pix-001"

    def test_top_k_respects_limit(
        self, store_with_banking_docs: InMemoryDocumentStore
    ) -> None:
        r = TFIDFRetriever(store=store_with_banking_docs)
        results = r.retrieve("transferencia", k=2)
        assert len(results) == 2

    def test_results_sorted_by_score_desc(
        self, store_with_banking_docs: InMemoryDocumentStore
    ) -> None:
        r = TFIDFRetriever(store=store_with_banking_docs)
        results = r.retrieve("PIX TED IOF", k=3)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_reindex_when_corpus_grows(self) -> None:
        store = InMemoryDocumentStore()
        r = TFIDFRetriever(store=store)
        # First retrieve on empty
        assert r.retrieve("x") == []
        # Add a doc
        store.add(Document(id="d1", text="alpha bravo charlie", source="s"))
        # Should now find it
        results = r.retrieve("alpha")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# RAGPipeline
# ---------------------------------------------------------------------------


class TestRAGPipelineConstruction:
    def test_invalid_retriever_raises(self) -> None:
        class NotARetriever:
            pass

        with pytest.raises(TypeError, match="Retriever"):
            RAGPipeline(retriever=NotARetriever())  # type: ignore[arg-type]

    def test_invalid_top_k_raises(
        self, store_with_banking_docs: InMemoryDocumentStore
    ) -> None:
        r = TFIDFRetriever(store=store_with_banking_docs)
        with pytest.raises(ValueError, match="top_k"):
            RAGPipeline(retriever=r, top_k=0)

    def test_invalid_min_score_raises(
        self, store_with_banking_docs: InMemoryDocumentStore
    ) -> None:
        r = TFIDFRetriever(store=store_with_banking_docs)
        with pytest.raises(ValueError, match="min_score"):
            RAGPipeline(retriever=r, min_score=2.0)


class TestRAGPipelineRun:
    def setup_method(self) -> None:
        self.store = InMemoryDocumentStore()
        self.store.add(
            Document(
                id="pix",
                text="PIX e o sistema instantaneo do BCB. Sem tarifa para PF.",
                source="Manual PIX",
            )
        )
        self.store.add(
            Document(
                id="ted",
                text="TED e transferencia em dias uteis ate 17h.",
                source="Manual TED",
            )
        )
        self.retriever = TFIDFRetriever(store=self.store)
        self.pipeline = RAGPipeline(retriever=self.retriever)

    def test_grounded_prompt_includes_documents(self) -> None:
        result = self.pipeline.run("Como funciona o PIX?")
        assert "PIX" in result.grounded_prompt
        assert "Manual PIX" in result.grounded_prompt

    def test_grounded_prompt_includes_query(self) -> None:
        result = self.pipeline.run("Como funciona o PIX?")
        assert "Como funciona o PIX?" in result.grounded_prompt

    def test_prompt_includes_citation_instruction(self) -> None:
        result = self.pipeline.run("PIX")
        assert "cite a fonte" in result.grounded_prompt.lower()

    def test_citations_extracted_from_retrieval(self) -> None:
        result = self.pipeline.run("transferencia PIX TED")
        assert "Manual PIX" in result.citations or "Manual TED" in result.citations

    def test_no_relevant_docs_returns_empty_retrieved(self) -> None:
        # Aggressive min_score filters everything out
        pipeline = RAGPipeline(retriever=self.retriever, min_score=0.99)
        result = pipeline.run("Como funciona o PIX?")
        assert result.retrieved == ()
        assert not result.has_grounding

    def test_unrelated_query_still_returns_prompt(self) -> None:
        result = self.pipeline.run("xyz totally unrelated abcdef")
        # Prompt is always built, even if no docs are relevant.
        assert "xyz totally unrelated abcdef" in result.grounded_prompt

    def test_duration_ms_recorded(self) -> None:
        result = self.pipeline.run("PIX")
        assert result.duration_ms >= 0

    def test_top_k_caps_retrieved_documents(self) -> None:
        pipeline = RAGPipeline(retriever=self.retriever, top_k=1)
        result = pipeline.run("transferencia")
        assert len(result.retrieved) <= 1
