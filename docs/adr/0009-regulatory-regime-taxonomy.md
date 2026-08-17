---
id: "0009"
title: "Six canonical regulatory regimes"
status: accepted
date: 2026-04-25
supersedes: null
superseded_by: null
invariants:
  canonical_regime_count: 6
  canonical_regimes:
    - NIST_GENAI       # NIST AI 600-1 (Generative AI Profile of AI RMF 1.0)
    - EU_AI_ACT        # Regulation (EU) 2024/1689
    - BCBS             # BCBS 239 (renamed 2026-04-26 from "BCBS d475")
    - BCB              # BCB Resolução 4.893/2021
    - ISO_23894        # ISO/IEC 23894:2023
    - ISO_42001        # ISO/IEC 42001:2023
  cross_referenced_only:
    - SR_11_7          # Federal Reserve / OCC Bulletin 2011-12
    - NIST_AI_RMF_1_0  # umbrella framework, NIST AI 600-1 is its profile
---

# ADR 0009 — Six canonical regulatory regimes

## Context

The library's selling point is mapping LLM uncertainty controls to
real regulatory regimes. The set of regimes is contested in the
broader literature (some count five, some count seven, some fold
SR 11-7 in as a regime). Without a canonical list, the README, the
petition narrative, and `docs/airmf-mapping.md` will drift apart.

## Decision

Six regimes are canonical:

1. NIST AI 600-1 (Generative AI Profile of AI RMF 1.0)
2. Regulation (EU) 2024/1689 (EU AI Act)
3. BCBS 239 — Principles for effective risk data aggregation and risk reporting (Basel Committee, January 2013). Renamed 2026-04-26: previous label "BCBS d475" was wrong (d475 is the 2019 derivatives-margining paper). Legacy `"BCBS_d475"` strings still resolve via `crosswalk.coerce_legacy_regime`.
4. BCB Resolução 4.893/2021 (Banco Central do Brasil)
5. ISO/IEC 23894:2023 (AI risk management)
6. ISO/IEC 42001:2023 (AI management system)

Two related artifacts are **cross-referenced only**, not counted:

- **SR 11-7** (Federal Reserve / OCC Bulletin 2011-12). US
  model-risk supervisory guidance, not an AI-specific regime. Its
  three pillars (conceptual soundness, ongoing monitoring, outcomes
  analysis) apply across all six canonical regimes via a
  three-pillar mapping table.
- **NIST AI RMF 1.0**. Umbrella framework. NIST AI 600-1 is its
  Generative AI Profile and IS the canonical entry; they are not
  separately counted.

The number 6 appears in the README, in the petition narrative, in
`planning/CANONICAL_FACTS.md`, and in
`src/lub/reports/crosswalk_data.toml`. All four must stay in sync.

## Consequences

- Numerical claims in petition / abstract / outreach use the
  number 6 consistently.
- Adding a regime is a deliberate event: new TOML row, new
  crosswalk entries, README + CANONICAL_FACTS update, new ADR
  superseding this one.
- Trade-off accepted: this taxonomy is current as of 2026-04. New
  AI-specific guidance issued by national regulators (Singapore
  MAS, UK FCA, etc.) will require a fresh ADR; we don't try to
  pre-enumerate them.

## Alternatives considered

- **Five regimes** (older docs). Pre-2026-04-22 the library
  treated BCBS and BCB as "legacy back-compat values"; that
  framing was retracted because both are first-class.
- **Seven regimes** (some `14c_Competitive_Gap_Analysis` drafts).
  Rejected because the seventh entry was always SR 11-7, which
  isn't AI-specific.
- **Eight regimes.** Rejected for the same reason; pre-fix `14c`
  conflated SR 11-7 + NIST AI RMF 1.0 (umbrella) as separate
  entries.

## References

- TOML source of truth: `src/lub/reports/crosswalk_data.toml`
  (32 controls across the 6 regimes).
- Petition narrative: `petition_evidence/15b_EB2_NIW_Petition_Narrative.md`
- Canonical numbers: `planning/CANONICAL_FACTS.md` "Primary numbers"
  table.
- "What NOT to cite" list in `CANONICAL_FACTS.md` enumerates the
  retracted alternative counts.
