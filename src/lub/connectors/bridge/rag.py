# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Retrieval-Augmented Generation (RAG) for the Bridge platform.

Inspired by ``deepset-ai/haystack`` (Apache-2.0): for banking, model
knowledge alone is unsafe — answers must be **grounded in real source
material** (manuais Bradesco, regras BCB, FAQ interno). Otherwise the
chatbot hallucinates "PIX gratuito para PJ até R$ 50k" and the bank
gets sued.

This module gives Bridge a 3-stage RAG pipeline:

1. :class:`DocumentStore` — holds the corpus. Documents have ``id``,
   ``text``, ``source``, ``metadata``.
2. :class:`Retriever` — given a query, returns the top-K most similar
   documents using the same hashing-trick embedding as
   :mod:`lub.connectors.bridge.memory` (no extra deps).
3. :class:`RAGPipeline` — orchestrates retrieval + builds a prompt
   that includes the retrieved documents plus a citation requirement,
   so the agent's answer comes back with explicit source attribution.

For larger corpora (>10k docs), swap the in-memory retriever for FAISS
or a real vector DB. The Protocol-based interfaces keep that drop-in.

Banking notes
-------------

* Every retrieval is logged with the chosen doc IDs and similarity
  scores: BCB 4893 reviewers can reconstruct *why* a customer received
  answer X (which document grounded it).
* Citation is enforced at the prompt level: the answer template
  includes "Cite a fonte" so a downstream evaluator can fail responses
  that lack citations.
* Fallback semantics: if no document is above the relevance threshold,
  the pipeline returns ``None`` (caller decides: reject vs. let the
  unconstrained agent answer with low confidence).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Final, Protocol, runtime_checkable

import structlog

from lub.connectors.bridge.embeddings import cosine, embed, tokenize

__all__ = [
    "Document",
    "DocumentStore",
    "InMemoryDocumentStore",
    "RAGPipeline",
    "RAGResult",
    "Retriever",
    "RetrievedDocument",
    "TFIDFRetriever",
]

_LOG = structlog.get_logger("lub.bridge.rag")


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Document:
    """A single corpus document."""

    id: str
    text: str
    source: str
    """Citation label: 'BCB Resolução 4893', 'Manual Bradesco PIX v3', etc."""

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedDocument:
    """A document plus its retrieval score for a specific query."""

    document: Document
    score: float


@dataclass(frozen=True)
class RAGResult:
    """Output of :meth:`RAGPipeline.run`."""

    grounded_prompt: str
    retrieved: tuple[RetrievedDocument, ...]
    citations: tuple[str, ...]
    """Distinct source labels in the same order they appear in the prompt."""

    duration_ms: float

    @property
    def has_grounding(self) -> bool:
        """Report whether Bridge's RAG stage produced any usable evidence.

        Bridge's stage-7 ``UncertaintyGuard`` reads this flag: a False
        means the agent answered without source backing and should be
        treated as low-confidence (FLAG/REASK/ESCALATE candidate).
        """
        return len(self.retrieved) > 0


# ---------------------------------------------------------------------------
# Storage protocol + impl
# ---------------------------------------------------------------------------


@runtime_checkable
class DocumentStore(Protocol):
    """Pluggable corpus storage. Default impl is in-memory."""

    def add(self, doc: Document) -> None:
        """Insert (or overwrite) a document in Bridge's grounding corpus.

        Called during Bridge bootstrap (loading manuais Bradesco / BCB
        rules) and by ingestion pipelines that refresh the knowledge
        base. ``doc.id`` is the upsert key.
        """
        ...

    def get(self, doc_id: str) -> Document | None:
        """Fetch a single document by id, or ``None`` if absent.

        Used by Bridge audit replays (stage 9) to re-materialize the
        exact document that grounded a past answer for BCB 4893
        traceability.
        """
        ...

    def all(self) -> list[Document]:
        """Return every document in the corpus.

        Bridge's :class:`TFIDFRetriever` calls this each time it
        rebuilds its IDF table; downstream analytics also use it to
        snapshot the active knowledge base.
        """
        ...

    @property
    def size(self) -> int:
        """Current document count.

        Bridge's retriever watches this value to trigger lazy reindex
        when the corpus changes between queries.
        """
        ...


@dataclass
class InMemoryDocumentStore:
    """Reference impl. Stable across process lifetime."""

    _docs: dict[str, Document] = field(default_factory=dict)

    def add(self, doc: Document) -> None:
        """Upsert ``doc`` into the in-memory corpus used by Bridge stage 4.

        Raises ``ValueError`` if ``doc.id`` is empty — Bridge requires
        stable ids so audit logs can cite documents unambiguously.
        """
        if not doc.id:
            raise ValueError("document id must be non-empty")
        self._docs[doc.id] = doc

    def get(self, doc_id: str) -> Document | None:
        """Return the stored ``Document`` for ``doc_id`` or ``None``.

        Used by Bridge's audit trail (stage 9) when reconstructing the
        evidence chain of an earlier customer interaction.
        """
        return self._docs.get(doc_id)

    def all(self) -> list[Document]:
        """Snapshot every document so Bridge's retriever can reindex.

        Returns a fresh list (mutations by the caller do not leak back
        into the store), which is what :class:`TFIDFRetriever` relies
        on when recomputing IDF.
        """
        return list(self._docs.values())

    @property
    def size(self) -> int:
        """Number of documents currently held — Bridge's reindex trigger."""
        return len(self._docs)


# ---------------------------------------------------------------------------
# Retriever protocol + TF-IDF-ish impl
# ---------------------------------------------------------------------------


@runtime_checkable
class Retriever(Protocol):
    """Given a query and top-k, return the K most relevant documents."""

    def retrieve(self, query: str, k: int = 3) -> list[RetrievedDocument]:
        """Return the top-``k`` documents matching ``query`` for Bridge stage 4.

        Bridge's :class:`RAGPipeline` calls this between intent
        classification (stage 5) and the agent (stage 6) to produce
        grounding evidence; results are later cited in the audit log.
        """
        ...


def _tokenize(text: str) -> list[str]:
    return tokenize(text)


def _embed(tokens: list[str], idf: dict[str, float] | None = None) -> tuple[float, ...]:
    return embed(tokens, idf)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return cosine(a, b)


@dataclass
class TFIDFRetriever:
    """In-memory TF-IDF retriever over a :class:`DocumentStore`.

    Recomputes the IDF table lazily on first ``retrieve`` after the
    store changes. For corpus sizes up to ~5000 documents, queries
    return in <10ms; larger corpora should use FAISS or a vector DB.
    """

    store: DocumentStore
    _idf: dict[str, float] = field(default_factory=dict)
    _doc_vectors: dict[str, tuple[float, ...]] = field(default_factory=dict)
    _last_indexed_size: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.store, DocumentStore):
            raise TypeError("store must implement DocumentStore protocol")

    def _maybe_reindex(self) -> None:
        if self.store.size == self._last_indexed_size:
            return
        docs = self.store.all()
        n = len(docs)
        # Document frequency.
        df: dict[str, int] = {}
        doc_tokens: dict[str, list[str]] = {}
        for doc in docs:
            tokens = _tokenize(doc.text)
            doc_tokens[doc.id] = tokens
            for tok in set(tokens):
                df[tok] = df.get(tok, 0) + 1
        # IDF: log((N+1)/(df+1)) + 1  (smoothed)
        self._idf = {tok: math.log((n + 1) / (count + 1)) + 1 for tok, count in df.items()}
        # Pre-embed all docs.
        self._doc_vectors = {doc.id: _embed(doc_tokens[doc.id], self._idf) for doc in docs}
        self._last_indexed_size = n
        _LOG.info("bridge.rag.reindexed", docs=n, vocab=len(df))

    def retrieve(self, query: str, k: int = 3) -> list[RetrievedDocument]:
        """Score every doc against ``query`` and return the top ``k``.

        Reindexes lazily if the underlying store changed. Called by
        Bridge's :class:`RAGPipeline` (stage 4); the returned scores
        feed the ``min_score`` gate that decides whether the agent
        gets grounding or must fall back.
        """
        self._maybe_reindex()
        if self._last_indexed_size == 0:
            return []
        q_tokens = _tokenize(query)
        q_vec = _embed(q_tokens, self._idf)
        scored: list[RetrievedDocument] = []
        for doc in self.store.all():
            sim = _cosine(q_vec, self._doc_vectors[doc.id])
            scored.append(RetrievedDocument(document=doc, score=sim))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]


# ---------------------------------------------------------------------------
# RAG pipeline
# ---------------------------------------------------------------------------


_PROMPT_TEMPLATE: Final = """\
Voce e um assistente bancario do Bridge. Responda a pergunta do cliente
usando APENAS as informacoes nos documentos abaixo. Se a informacao nao
estiver nos documentos, diga 'Nao encontrei essa informacao na base
oficial; vou transferir para um especialista.'

SEMPRE cite a fonte ao final da resposta no formato: [Fonte: <source>]

Documentos disponiveis:
{docs_block}

Pergunta do cliente: {query}

Resposta:"""


@dataclass
class RAGPipeline:
    """End-to-end retrieval + grounded prompt construction.

    ``min_score`` filters out weak matches: if the top doc scores below
    this, the pipeline returns an empty result and the caller decides
    what to do (reject, escalate, or fall back to ungrounded LLM).
    """

    retriever: Retriever
    top_k: int = 3
    min_score: float = 0.05
    prompt_template: str = _PROMPT_TEMPLATE

    def __post_init__(self) -> None:
        if not isinstance(self.retriever, Retriever):
            raise TypeError("retriever must implement Retriever protocol")
        if self.top_k < 1:
            raise ValueError(f"top_k must be >= 1 (got {self.top_k})")
        if not (0 <= self.min_score <= 1):
            raise ValueError(f"min_score must be in [0, 1] (got {self.min_score})")

    def run(self, query: str) -> RAGResult:
        start = time.perf_counter()
        candidates = self.retriever.retrieve(query, k=self.top_k)
        retrieved = tuple(c for c in candidates if c.score >= self.min_score)

        # Build the docs block + collect citations preserving order, dedupe.
        seen_sources: list[str] = []
        doc_lines: list[str] = []
        for i, r in enumerate(retrieved, start=1):
            doc_lines.append(
                f"[{i}] (Fonte: {r.document.source}, score={r.score:.2f})\n{r.document.text}"
            )
            if r.document.source not in seen_sources:
                seen_sources.append(r.document.source)

        docs_block = "\n\n".join(doc_lines) if doc_lines else "(nenhum documento relevante)"
        grounded_prompt = self.prompt_template.format(docs_block=docs_block, query=query)

        duration_ms = (time.perf_counter() - start) * 1000
        _LOG.info(
            "bridge.rag.complete",
            query_len=len(query),
            retrieved=len(retrieved),
            top_score=retrieved[0].score if retrieved else 0.0,
            sources=seen_sources,
            duration_ms=round(duration_ms, 2),
        )

        return RAGResult(
            grounded_prompt=grounded_prompt,
            retrieved=retrieved,
            citations=tuple(seen_sources),
            duration_ms=duration_ms,
        )
