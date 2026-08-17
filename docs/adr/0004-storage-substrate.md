---
id: "0004"
title: "Storage substrate: SQLite for the uncertainty ledger"
status: accepted
date: 2026-04-25
supersedes: null
superseded_by: null
invariants:
  ledger_engine: sqlite
  ledger_filename_default: "uq_ledger.db"
  zero_external_services: true
---

# ADR 0004 — Storage substrate: SQLite for the uncertainty ledger

## Context

The uncertainty ledger has to record every (prompt, response, UQ
score, policy decision, outcome) tuple so that calibration can be
audited, replayed, and re-derived nightly. Banking deployments
typically default to Postgres or a managed warehouse; either would
add an external service the library can't assume exists.

## Decision

The ledger is SQLite. One file (`uq_ledger.db` by default; `:memory:`
in tests). No server. No connection pool. No external dependency
beyond the Python stdlib `sqlite3` module.

Concurrency is handled by SQLite's WAL mode for readers; writes
serialize through a single per-process connection. Multi-tenant or
multi-process deployments wrap the library in their own
write-coordinating layer rather than asking the library to do it.

## Consequences

- Zero infrastructure cost to run a calibration benchmark, replay,
  or audit. A reviewer can clone the repo and reproduce results
  without provisioning anything.
- The library stays embeddable: a Jupyter notebook, a CI job, or a
  containerized runtime can each open its own ledger file.
- Trade-off accepted: SQLite is not the right substrate for a bank
  with millions of decisions per day. Such deployments swap the
  storage adapter (`lub.ledger.store.Ledger` is open for subclassing
  / replacement) but the *interface* — the schema and the query
  surface — stays the same.

## Alternatives considered

- **Postgres / cloud warehouse.** Adds a hard infra dep; loses the
  "clone-and-run" property that makes the library credible as
  reproducible evidence.
- **JSONL append-only files.** Simpler, but no query layer for the
  nightly calibration jobs. Re-deriving rolling reliability curves
  becomes O(N) every night.
- **Parquet on disk.** Good for analytics, weak for transactional
  writes during a live run.

## References

- Code: `src/lub/ledger/store.py`, `src/lub/ledger/schema.py`
- Schema: ADR 0005 (additive migrations)
- Petition exhibit: `planning/CANONICAL_FACTS.md` "732 tests / 93%
  coverage / 86 source files" snapshot is reproducible without any
  external service.
