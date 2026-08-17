# Architecture Decision Records

Index of accepted ADRs for `llm-uncertainty-banking`. ADRs document
the *why* behind a decision in 50–100 lines so future maintainers
(and adversarial reviewers) can audit the reasoning without
reverse-engineering the codebase.

## How to use this folder

- **Read order:** numerical. Lower numbers are older / more
  foundational. New ADRs append; existing ones never get rewritten
  in place — supersede instead.
- **Authoring:** copy `_template.md` to `NNNN-<short-title>.md` with
  the next free number. Fill the four sections. Open a PR. Merge
  flips `status: proposed` → `status: accepted`.
- **Machine-checkable invariants:** put numeric constraints,
  library pins, schema versions, etc. in the front-matter
  `invariants:` block. `lub.governance.adr` parses these and asserts
  them in CI.

## Index

| ID | Title | Status | Date |
|---|---|---|---|
| [0001](0001-calibration-targets.md) | Calibration targets per bounded context | accepted | 2026-04-23 |
| [0002](0002-abstention-rules.md) | Abstention rules | accepted | 2026-04-23 |
| [0003](0003-tier-hierarchy.md) | Tier hierarchy for the uncertainty-gated router | accepted | 2026-04-23 |
| [0004](0004-storage-substrate.md) | Storage substrate: SQLite for the uncertainty ledger | accepted | 2026-04-25 |
| [0005](0005-additive-schema.md) | Additive-only schema migrations | accepted | 2026-04-25 |
| [0006](0006-layer-enforcement.md) | Layer enforcement via importlinter contracts | accepted | 2026-04-25 |
| [0007](0007-protocol-adapters.md) | Cross-framework adapters via `typing.Protocol` | accepted | 2026-04-25 |
| [0008](0008-hashed-tfidf.md) | Hashed TF-IDF for k-NN over evidence | accepted | 2026-04-25 |
| [0009](0009-regulatory-regime-taxonomy.md) | Six canonical regulatory regimes | accepted | 2026-04-25 |
| [0010](0010-method-vs-key-count.md) | Method count vs registry-key count duality | accepted | 2026-04-25 |
| [0011](0011-prefiling-freeze.md) | Pre-filing implementation freeze | accepted | 2026-04-25 |

## Conventions

- **One decision per ADR.** Split if it grows.
- **Don't rewrite history.** Supersede with a new ADR instead.
- **Cross-link related ADRs** in the References section.
- **Numeric facts** that drive CI (calibration targets, schema
  version, layer contracts) live in front-matter `invariants:`.
- **Status transitions** are auditable: `proposed` → `accepted` →
  (optional) `superseded` / `deprecated`. `lub.governance.adr` reads
  the front-matter and asserts the transitions are valid.
