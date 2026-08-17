# Integration Tiers

This document describes three institutional adoption pathways for the `lub`
framework across U.S. federally supervised depository institutions. Tiers
are distinguished by validation profile, regulatory examination cadence,
and model-inventory depth. Each pathway is an **implementation pattern**
intended to guide configuration of the technical workstreams (uncertainty
quantification, calibration, refusal/abstention, regulatory crosswalk,
continuous monitoring), not a guaranteed adoption outcome.

The three pathways correspond to the Federal Reserve's prudential
tailoring framework codified at 12 CFR 252.5 and the community-bank
threshold articulated in OCC News Release 2025-89 of September 18, 2025
(up to $30 billion in total assets), with tailored expectations in OCC
Bulletin 2025-26 of October 6, 2025.

---

## Tier 1 — Systemically Important Institutions

**Population.** Banking organizations subject to enhanced prudential
standards under Federal Reserve Regulation YY (12 CFR 252) — typically
Categories I and II.

**Validation profile.** Dedicated model-risk-management (MRM) teams; deep
model inventories; continuous supervisory monitoring; quantitative-finance
talent pipeline.

**Adoption pattern.** The framework integrates with existing MRM
infrastructure rather than displacing it. The OSCAL Assessment Results
records (see `lub.reports.oscal`) surface as additional validation
packets within established review cycles. The calibration metrics in
`lub.calibration` supplement existing performance assessments. The
regulatory crosswalk in `lub.reports.crosswalk` supplies documentation
alignment that supervisory examination already presupposes.

**Key resource.** In-house ML engineering capacity is the gating factor.

**Configuration notes.**
- Run estimator ensemble at corpus scale; use `lub.orchestration.UQSwarm`
  for parallel estimator execution.
- Bind OSCAL output to GRC platforms via the machine-readable Assessment
  Results schema.
- Continuous-monitoring layer integrates with existing model-performance
  dashboards through `lub.ledger.metrics` (stdlib-only Prometheus
  textfile + Grafana exporters).

---

## Tier 2 — Regional and Mid-Sized Institutions

**Population.** Banking organizations under Federal Reserve Regulation YY
Categories III and IV, operating proportionally scaled MRM functions
calibrated to intermediate inventory depth.

**Validation profile.** Formal MRM programs with smaller validation
teams and more focused model inventories.

**Adoption pattern.** Adoption is configured for a defined set of
priority workflows rather than across an institution-wide model
inventory. Initial use cases are regulatory and compliance document
summarization, entity extraction, and related documentation tasks.
Hybrid configuration: the framework deploys alongside existing
validation workflows under the second-pillar effective-challenge
expectation. Knowledge transfer to internal MRM teams is a built-in
component.

**Key resource.** Partner-enabled second-line review — RegTech
providers, model-risk boutiques, or specialized advisory firms acting
as integration partners.

**Configuration notes.**
- This is the **beachhead tier** of the initial 24-month focus.
- Use the readiness assessment (see §6.3.2 of the petition framing) to
  identify priority workflows.
- Configure calibration thresholds per use case rather than fixed.
- OSCAL records flow into the institution's existing GRC tooling.

---

## Tier 3 — Community Banks and Credit Unions

**Population.** OCC-supervised community banks (up to $30 billion in
total assets per OCC News Release 2025-89) and federally insured credit
unions supervised by the NCUA.

**Validation profile.** Smaller MRM teams; focused model inventories
often centered on credit scoring and fraud detection; validation
processes still evolving. Institutions in this tier typically do not
carry in-house generative-AI validation staffing at the scale an
independent validation function would require.

**Adoption pattern.** The framework reaches this tier through
**vendor-mediated adoption** — core service providers, vendor-licensed
platforms, and AI-governance platforms acting as intermediaries — under
the tailored expectations articulated in OCC Bulletin 2025-26 of
October 6, 2025. The open-source distribution removes proprietary
software-license cost for the framework itself; integration, security
review, hosting, and staffing decisions remain with the institution.

**Key resource.** Third-party perimeter coverage. The June 2023
*Interagency Guidance on Third-Party Relationships: Risk Management*
(Federal Reserve, OCC, FDIC) applies — the institution's use of third
parties does not diminish its responsibility under applicable laws and
safe-and-sound practices.

**Configuration notes.**
- Most institutions in this tier approach generative AI incrementally,
  often beginning with internal-documentation summarization or a single
  use case.
- The NCUA does not currently possess statutory authority to examine
  technology service providers directly (per GAO-25-107197), so the
  framework's audit trail is particularly load-bearing here.
- Default refusal thresholds should be configured conservatively.

---

## Cross-Tier Summary

| Tier | Validation profile | Adoption pattern | Key resource |
|------|--------------------|------------------|--------------|
| 1 — Systemically Important | Dedicated MRM; deep inventories | Integration with existing MRM | In-house ML engineering |
| 2 — Regional | Formal MRM; focused use cases | Hybrid via RegTech/MRM partner | Partner-enabled second-line review |
| 3 — Community + Credit Unions | Vendor-mediated; OCC 2025-26 tailoring | Vendor-routed via core service providers | Third-party perimeter coverage |

---

## References

- *Interagency Guidance on Third-Party Relationships: Risk Management*
  (Federal Reserve, OCC, FDIC, June 2023)
- OCC Bulletin 2025-26 (October 6, 2025) — tailored expectations for
  community institutions
- OCC News Release 2025-89 (September 18, 2025) — community-bank
  threshold
- GAO-25-107197 (May 2025) — *Artificial Intelligence: Use and Oversight
  in Financial Services*
- 12 CFR 252.5 — Federal Reserve tailoring framework (Regulation YY)
- Revised Interagency Supervisory Guidance on Model Risk Management
  (OCC / Federal Reserve / FDIC, April 17, 2026) — carries forward the
  *SR 11-7* principles-based posture; states that generative AI and
  agentic AI are outside its declared scope
