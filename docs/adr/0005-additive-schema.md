---
id: "0005"
title: "Additive-only schema migrations"
status: accepted
date: 2026-04-25
supersedes: null
superseded_by: null
invariants:
  schema_version_current: 2
  schema_evolution_rule: "additive only"
  forbidden_operations:
    - DROP TABLE
    - DROP COLUMN
    - ALTER COLUMN TYPE
    - RENAME TABLE
    - RENAME COLUMN
---

# ADR 0005 — Additive-only schema migrations

## Context

The ledger is the audit trail. If a schema migration could destroy
a column or change its type, a re-run of an old benchmark would
produce different numbers — and the petition / SR 11-7 evidence
chain would lose its reproducibility property.

## Decision

Schema migrations are **additive only**. New tables and new columns
are allowed. Renames, drops, and type changes are forbidden. The
library never modifies an existing column or table. If a column
becomes obsolete, it stays in the schema with a comment marking it
deprecated; new writers stop populating it but old data remains
readable.

`SCHEMA_VERSION` is monotonically increasing. The bootstrap path in
`Ledger.__init__` runs all migrations from the file's recorded
version up to the current `SCHEMA_VERSION` in order. A migration
that violates the additive rule fails CI via a schema-diff check.

## Consequences

- Old ledgers open in new library versions without losing data or
  changing the meaning of historical rows.
- Reproducibility holds across versions: a calibration replay run
  six months from now over a ledger written today produces the same
  numbers, because no column was redefined in between.
- Trade-off accepted: the schema accumulates dead columns over
  time. Periodic cleanup happens at major version boundaries
  (v1.0, v2.0) via a documented one-shot migration tool that lives
  outside the runtime path.

## Alternatives considered

- **Free schema evolution.** Cheaper short-term but breaks the
  audit-trail invariant. Disqualifying for SR 11-7 evidence.
- **External migration tool (Alembic).** Heavyweight for a library
  whose primary value is being embeddable.
- **Versioned table names** (e.g., `answers_v2`, `answers_v3`).
  Equivalent in practice but harder to query across versions.

## References

- Code: `src/lub/ledger/schema.py` (`SCHEMA_VERSION`, `SCHEMA_SQL`)
- Recent migration: v1 → v2 added `cec_meta_predictions` and
  `cec_meta_outcomes` for the CEC module (planning/24_CEC_Spec).
- Cross-link: ADR 0004 (SQLite as substrate).
