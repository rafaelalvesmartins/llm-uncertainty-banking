---
id: "0008"
title: "Hashed TF-IDF for k-NN over evidence"
status: accepted
date: 2026-04-25
supersedes: null
superseded_by: null
invariants:
  evidence_embedding: hashed_tf_idf
  embedding_dim_default: 1024
  external_model_dep: false
  deterministic: true
---

# ADR 0008 — Hashed TF-IDF for k-NN over evidence

## Context

`lub.evidence` provides k-NN retrieval over historical
(question, answer, outcome) tuples for memory-augmented selective
prediction. Production-grade vector stores (FAISS, pgvector,
Chroma, RuVector) need either a service, an SDK, or a trained
embedding model. None of those compose with the
"clone-and-reproduce" property the library advertises.

## Decision

Embeddings for the evidence k-NN store are **hashed TF-IDF**:

- Tokenize on `[\w'-]+`, lowercase.
- Hash each token via blake2b into a fixed-dimension vector
  (default 1024).
- L2-normalize.
- Store as `numpy.ndarray[float32]`. Search is cosine-similarity
  via a single matmul.

No trained model. No external service. No GPU. The store is a
plain numpy array on disk (or in memory for tests). The
implementation is ~120 lines in `src/lub/evidence/store.py` and
depends only on numpy + stdlib.

## Consequences

- Reproducibility is byte-exact. The same input produces the same
  vector forever; results don't drift when a model card changes
  upstream.
- Cold-start works. A user with no historical corpus can populate
  a few dozen reference cases and have a usable retrieval baseline
  the same afternoon.
- Trade-off accepted: hashed TF-IDF is weaker than a tuned
  embedding model on semantic-similarity benchmarks. We document
  this and ship a `lub.evidence.protocols.EvidenceStore` Protocol
  so a real vector DB can be swapped in for production where the
  semantic gap matters.

## Alternatives considered

- **Sentence-transformers / OpenAI embeddings.** Adds a model
  dependency, breaks reproducibility on model card updates, and
  costs API budget per evaluation run.
- **FAISS or pgvector.** Adds infra; loses embedability.
- **No retrieval at all (skip the feature).** Removes the
  memory-augmented selective-prediction baseline that the
  petition narrative cites as Phase 2 evidence.

## References

- Code: `src/lub/evidence/store.py` (`_embed`, `_tokenize`,
  `_hash_token`)
- Cross-link: ADR 0004 (SQLite substrate has the same
  no-external-service discipline).
- Upstream pattern: hashing trick (Weinberger et al. 2009),
  scikit-learn's `HashingVectorizer`.
