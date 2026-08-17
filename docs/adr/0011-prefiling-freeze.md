---
id: "0011"
title: "Pre-filing implementation freeze"
status: accepted
date: 2026-04-25
supersedes: null
superseded_by: null
invariants:
  freeze_target_surface: "v0.1.0 stable"
  frozen_numbers:
    tests: 732
    coverage_pct: 93
    source_files: 86
    estimators: 22
    metrics: 14
    regimes: 6
  release_branch_after_filing: "feat/cec-pass-C, feat/context-autopilot-pass-D"
  freeze_lifts_when: "counsel-confirmed filing date is reached AND v0.1.0 snapshot is sealed for the petition exhibit set"
---

# ADR 0011 — Pre-filing implementation freeze

## Context

The petition exhibit set cites a frozen v0.1.0 snapshot of the
library: 732 tests, 93% coverage, 86 source files, 22 estimators,
14 metrics, 6 regimes. Any post-snapshot change that touches those
numbers — adding tests, adding files, changing the estimator count
— invalidates the citation chain in
`petition_evidence/15b_EB2_NIW_Petition_Narrative.md` and the
artifacts under `arXiv_submission/`.

CEC (`lub.challenge`, v0.3) and Context Autopilot
(`lub.challenge.context_autopilot`, v0.4) are both ready to ship
in code or in spec form, respectively. Shipping either before the
filing date is locked would either (a) break the snapshot or
(b) create a v0.3 snapshot that the petition doesn't cite, leaving
adjudicators to figure out which set of numbers applies.

## Decision

**No new feature implementation lands on `main` between today and
the counsel-confirmed filing date.** Specs are fine. Scaffolds are
fine. Tests against scaffolds are fine. Replacing
`NotImplementedError` bodies with real code is **frozen** until
the filing date is in hand.

Workstreams that violate the freeze:

- Replacing `lub.challenge` scaffolds with real implementations
  (CEC v0.3).
- Implementing `lub.challenge.context_autopilot/` (v0.4 per spec
  25).
- Bumping `SCHEMA_VERSION` for new ledger tables that v0.1
  doesn't have.
- Any change that increases the canonical numbers in the
  `frozen_numbers:` block of this ADR's front-matter.

Workstreams that DON'T violate the freeze:

- Documentation updates (READMEs, ADRs, this file).
- Scaffold writes (NotImplementedError stubs + scaffold tests).
- Cleanup, archival, organization (the 2026-04-25 folder reorg
  was this category).
- Outbound emails (Item A UNICAMP, Item B BRB) — those are
  precondition to publication, not feature work.

## Consequences

- Reviewers can cite v0.1.0 numbers with a fixed reference.
- New work piles up in branches (`feat/cec-pass-C`,
  `feat/context-autopilot-pass-D`) and lands in batches once the
  freeze lifts.
- Trade-off accepted: the 2026-04-25 implementation pass that
  shipped CEC bodies was done **against this freeze rule** under
  user mandate, and the petition narrative continues to cite the
  pre-CEC v0.1.0 stable surface. The implementation lives on
  `main` but is documented in `CANONICAL_FACTS.md` as v0.3 with
  separate numbers; the v0.1.0 frozen surface is preserved as the
  petition reference. This is a deliberate exception, not a
  precedent.

## Alternatives considered

- **No freeze.** The petition's numerical citations would need to
  be hand-updated every time a PR touches the test count.
  Operationally infeasible in the last 30 days before filing.
- **Freeze the repo entirely.** Blocks even doc fixes; rejected
  because the doc fixes are themselves part of the petition
  hygiene.
- **Tag v0.1.0 and continue on `main`.** This is what we
  effectively did, but without an ADR documenting the rule the
  next contributor wouldn't know the constraint exists.

## References

- Spec: `planning/24_CEC_Spec_2026-04-25.md` §5 (Phased rollout —
  pre-filing freeze).
- Spec: `planning/25_Context_Autopilot_Spec_2026-04-25.md` §5.
- Decision memo: `planning/DECISION_FILING_DATE_2026-04-23.md`
  (May vs July/August filing date — pending counsel sign-off
  by 2026-05-05).
- Frozen numbers: `planning/CANONICAL_FACTS.md` "Primary numbers"
  table.
