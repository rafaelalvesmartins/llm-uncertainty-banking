# Regulatory Triggers by Region — a champion-to-CRO briefing sheet

> **What this page is:** a one-page-per-region "buying trigger" sheet a `lub`/Bridge
> champion can forward to their Chief Risk Officer, Head of Model Risk Management
> (MRM), or Head of AI Governance. For each region it names **one lead regulatory
> anchor**, **what the examiner actually expects**, **the deadline or cadence that
> creates urgency**, and **the exact `lub` artifact** that answers it.
>
> **What this page is NOT:** legal advice, a compliance certification, or a claim
> that `lub` makes you compliant. `lub` supplies *quantitative calibration,
> performance, and provenance evidence that plugs into a validation report* — it is
> evidence **for** a program, not compliance **with** a regime. See
> [`docs/sr-11-7.md`](./sr-11-7.md) for the full scope-limit statement, which
> applies to every row below.

---

## Read this first — honesty & posture (a bank does diligence)

Before you forward this internally, four things a diligent MRM reviewer will (and
should) check, stated plainly so nobody is surprised:

1. **Two coded regimes vs. principles we evidence.** `lub` ships **six machine-coded
   regulatory regimes** with real, article-level control mappings in
   `src/lub/reports/crosswalk_data.toml`: **NIST AI 600-1** (GenAI Profile of AI RMF
   1.0), **EU AI Act (2024/1689)**, **BCBS 239**, **BCB Res. 4.893/2021**, **ISO/IEC
   23894:2023**, and **ISO/IEC 42001:2023**. Of the regions in this sheet, only the
   **US** (via the SR 11-7 cross-map) and **EU** and **Brazil** anchors are backed by
   coded article/pillar mappings. **UK (PRA) and APAC (MAS/HKMA) are principles that
   `lub` evidences through the *same underlying artifacts* — they are NOT coded
   regime enums.** Where a row says "principles `lub` evidences," read it as "the
   same metrics/OSCAL/ledger that answer a coded regime also speak to these
   principles," not "a supervisor has blessed a mapping."

2. **SR 11-7 is cross-referenced, not a 7th coded regime.** Its three validation
   "pillars" are cross-mapped via a table in `crosswalk_data.toml`. The internal
   control-id lettering (`SR-11-7-V.A/-V.B/-VI.*`) is **`lub`'s own crosswalk
   convention, not verbatim OCC 2011-12 subsection citations**. A reconciliation of
   that internal numbering against the primary guidance is a tracked **v0.2 item**
   (see `planning/32_SR117_Audit_Findings_2026-07-05.md`). Cite the *evidence*, not
   the letter labels.

3. **Every date and citation below: verify against the primary source before
   external use.** Regulatory clocks move, and several dates here are directional.
   Treat them as "confirm with your legal/compliance function," not as settled fact.

4. **What `lub` is, technically.** Single-tenant, single-org deployment. The
   evidence core (`lub.calibration`, `lub.evidence`) is **numpy + Python stdlib
   only — no sklearn, no torch — and air-gap-runnable**. With local model backends
   there is **no data egress** — and as of the air-gapped profile
   (`LUB_LOCAL_ONLY=1`, `lub.governance.local_only`) that is *enforced* rather than
   merely configured: hosted-API backends refuse to construct, so the objects that
   could carry a prompt off-premises cannot be built. Read that module's docstring
   for the exact scope — it covers customer prompts, not HuggingFace weight
   downloads on a cold cache. Evidence is **process-verifiable and reproducible
   (seed + dataset hash), not externally time-bound** — an auditor re-runs it and
   verifies every number; it is not a third-party-attested point-in-time snapshot.
   The demo console is **auth-gated**. There is **no SOC 2, no independent
   penetration test, no SLA, no hosted SaaS, no legal entity, and no reference
   customer today** — those are roadmap, not fact. Integration, hosting, and
   security review remain the institution's responsibility (see
   [`docs/integration_tiers.md`](./integration_tiers.md)).

---

## United States — SR 11-7 / OCC Bulletin 2011-12

| | |
|---|---|
| **Lead anchor** | **SR 11-7 / OCC Bulletin 2011-12** — "Supervisory Guidance on Model Risk Management" (Federal Reserve & OCC, April 2011). Supervisory **guidance** (examiner expectations), *not* a statute. |
| **What the examiner expects** | A model validation with three elements: **conceptual soundness** (predicted confidence is meaningful — predicted ≈ observed), **ongoing monitoring** (performance stays stable, drift is detected, the record is auditable over time), and **outcomes analysis** (outputs are back-tested against realized outcomes; failures are detected). Plus **effective challenge** — critical review by parties *independent of the model developers*. |
| **The clock / cadence** | No single statutory deadline — the trigger is your **next model-validation cycle** (typically annual, or on material model change) and the periodic exam. That is when the evidence must be on the table. |
| **The exact `lub` artifact** | **Conceptual soundness:** calibration metrics — `ece`, `rmsce`, `ence`, `brier`, `miscalibration_area`, `sharpness`, `spearman`, `kendall_tau`, `adversarial_group_calibration`. **Ongoing monitoring:** `lub.calibration.drift`, adaptive-conformal coverage, `missing_ratio`, and the append-only, tamper-evident `lub.ledger`. **Outcomes analysis:** `accuracy`, `matthews_correlation`, `refusal_auroc`, `prr`, `reversed_pairs_proportion`, `aurc`, `auucc`. All surface as machine-readable **OSCAL Assessment Results** a GRC platform can ingest. |
| **Honest limit** | `lub` **produces the evidence a challenger uses; it does not perform the independent review**, supply the validator, or substitute for the enterprise model inventory or board oversight. The internal `SR-11-7-*` control-id lettering is `lub`'s crosswalk convention (v0.2 reconciliation pending — `planning/32`). *Verify SR 11-7 structure against federalreserve.gov `sr1107` / occ.gov `bulletin-2011-12` before external use (repo verified 2026-07-05).* |

> **Note for institution sizing.** Adoption pattern differs by tier (systemically
> important → regional → community/credit-union); see
> [`docs/integration_tiers.md`](./integration_tiers.md). The tailoring references
> there (e.g., OCC Bulletin 2025-26, News Release 2025-89) should be
> **verified against the primary source**.

---

## European Union — AI Act (Regulation 2024/1689), high-risk Arts. 9/10/13/14/15

| | |
|---|---|
| **Lead anchor** | **EU AI Act, Regulation (EU) 2024/1689** — the **high-risk** obligations. Credit scoring / creditworthiness assessment and certain insurance uses fall in Annex III high-risk categories. This is **the sharpest clock in this sheet.** |
| **What the examiner expects (article-level, as coded in `lub`)** | **Art. 9** — a documented **risk-management system** across the lifecycle; `lub`'s `ece`/`aurc`/`prr` supply the quantitative risk evidence for Art. 9(2)(a). **Art. 10** — **data governance**: relevant, representative, bias-examined data; dataset provenance/hashing + `adversarial_group_calibration` address Art. 10(2)(f). **Art. 13** — **transparency** for deployers; uncertainty reporting, confidence bounds, reliability diagrams for Art. 13(3)(b)(ii). **Art. 14** — **human oversight**; `refusal_auroc`, abstention rates, and gated tool-call policies implement Art. 14(4)(a) real-time intervention. **Art. 15** — **accuracy & robustness**; task accuracy/Brier/proper scores for 15(1), and adaptive-conformal coverage / `miscalibration_area` / `aurc`-under-shift for 15(4). |
| **The clock / cadence** | High-risk conformity obligations are widely tracked to **~August 2026** (24 months after the Act's August 2024 entry into force), with phased milestones before and after. **This directional date MUST be verified against the primary Official Journal text and your legal function** — phasing by Annex/use-case and any adjustments materially change what applies to *you*, *when*. |
| **The exact `lub` artifact** | The **six EU-AI-Act controls are coded article-by-article** in `crosswalk_data.toml` (`EU_ART_9`, `_10`, `_13`, `_14`, `_15_ACC`, `_15_ROB`) and mapped to specific metrics — so the crosswalk output shows, per metric, which Article it evidences. Delivered as **OSCAL Assessment Results** for your technical-documentation package. |
| **Honest limit** | `lub` evidences *specific technical-documentation and risk-management elements* of these Articles — it is **not** a conformity assessment, a notified-body function, CE marking, or a full Annex IV technical file. Bias/robustness metrics are **evidence inputs** to Art. 10/15, not a legal determination of "free of errors." *Verify all dates and Article scoping against Regulation (EU) 2024/1689 primary text.* |

---

## United Kingdom — PRA SS1/23 (principles `lub` evidences, **not** a coded regime)

| | |
|---|---|
| **Lead anchor** | **PRA Supervisory Statement SS1/23** — "Model risk management principles for banks" (Prudential Regulation Authority). |
| **What the supervisor expects** | Principles-based model-risk expectations closely paralleling SR 11-7: model **identification & inventory**, robust **development/validation**, **independent validation**, and **ongoing monitoring**, under board-level governance. |
| **The clock / cadence** | Aligned to your **internal model-risk review cadence and PRA supervisory engagement**, not a fixed external filing date. |
| **The exact `lub` artifact** | **The same artifacts that answer SR 11-7 §V** — calibration metrics (conceptual soundness), `lub.calibration.drift` + `lub.ledger` (ongoing monitoring), and back-testing metrics (outcomes analysis), emitted as OSCAL. These **principles are evidenced through `lub`'s existing artifacts; SS1/23 is NOT a coded regime enum** in `crosswalk_data.toml`. |
| **Honest limit** | There is **no PRA-specific coded crosswalk** in `lub` today. `lub` speaks to SS1/23 *by analogy to its SR 11-7 evidence*, and the independence/governance principles remain **organizational responsibilities `lub` cannot discharge**. A dedicated SS1/23 mapping is candidate roadmap, not built. *Verify SS1/23 content against the PRA primary source.* |

---

## Brazil — BCB Res. 4.893/2021 + LGPD Art. 20

| | |
|---|---|
| **Lead anchor** | **BCB Resolução CMN/BCB 4.893/2021** (política de gestão de riscos e continuidade de negócios de tecnologia) — **coded in `lub`** — **plus LGPD (Lei 13.709/2018) Art. 20**, the data-subject right to **review of decisions taken solely on automated processing**. |
| **What the examiner/regulator expects** | **BCB 4.893:** a technology-risk management policy proportional to the institution's size/complexity (Art. 5) and **continuous risk monitoring with timely corrective action** (Art. 7); plus data quality/traceability (aligned with Circular 3.978 Art. 3). **LGPD Art. 20:** the ability to **explain and, on request, support review of an automated decision** affecting a data subject. |
| **The clock / cadence** | **BCB:** continuous monitoring cadence + the customary **5-year audit-record retention** the console's audit export is built around. **LGPD:** trigger is **on data-subject request** (per-decision), not a calendar deadline. |
| **The exact `lub` artifact** | **BCB 4.893** is coded article-level (`BCB_RES4893_ART5`, `_ART7`, `BCB_CIRC3978_ART3`) mapping to `ece`/`refusal_auroc`/`prr`/adaptive-conformal coverage + dataset provenance. **LGPD Art. 20** is served by the **append-only `lub.ledger` / Bridge audit trail** — every customer-facing AI output is recorded, and the console's **per-entry explanation drill-in** ("explicação por decisão") plus a **JSON audit export** provide the per-decision reviewability record. |
| **Honest limit** | `lub` provides the **technical/evidentiary substrate** for BCB 4.893 monitoring and for satisfying an Art. 20 review request — it does **not** constitute the institution's risk *policy*, nor is it a legal opinion that a given automated decision is LGPD-compliant. The ledger records *what the system did*; the review process Art. 20 contemplates remains a process the institution runs. *Verify BCB 4.893 articles and LGPD Art. 20 against primary Brazilian sources.* |

---

## APAC — MAS / HKMA GenAI guidance (principles `lub` evidences, **not** a coded regime)

| | |
|---|---|
| **Lead anchor** | **MAS** (Monetary Authority of Singapore) and **HKMA** (Hong Kong Monetary Authority) generative-AI / model-risk expectations — e.g., MAS's FEAT principles and information papers on GenAI risk, and HKMA guidance on GenAI in banking. |
| **What the supervisor expects** | Sound **governance, validation, monitoring, and human accountability** for AI/GenAI, with fairness, transparency, and explainability emphasized — principles-based, closely echoing SR 11-7 / SS1/23. |
| **The clock / cadence** | Supervisory-dialogue and internal-review driven; **no single fixed external deadline** attaches to `lub`'s evidence role. |
| **The exact `lub` artifact** | **The same evidence surface** — calibration + back-testing metrics, `adversarial_group_calibration` for fairness, uncertainty/reliability reporting for transparency, `refusal_auroc`/abstention for human-oversight, and the audit ledger — emitted as OSCAL. As with the UK, **these are principles `lub` evidences via its existing artifacts; MAS/HKMA are NOT coded regime enums.** |
| **Honest limit** | **No MAS/HKMA-specific coded crosswalk exists in `lub` today.** The mapping is by analogy, and jurisdiction-specific expectations (and any binding instruments) **must be confirmed with local counsel**. A dedicated APAC mapping is candidate roadmap, not built. *Verify all MAS/HKMA references against the respective primary sources.* |

---

## Cross-cutting — civil liability for AI-generated statements

Every row above is *supervisory*: an examiner asks, the bank answers. This one is
different in kind, and it is worth a separate line in a CRO briefing because it
does not wait for an exam cycle — a plaintiff sets the clock.

| | |
|---|---|
| **Lead anchor** | **Regional Court of Munich (Landgericht München)** — injunction holding Google liable for defamatory statements produced by its AI Overview, on the reasoning that AI-generated summaries are the platform's **own speech**, not third-party content it merely displays. |
| **Why it is different** | The traditional intermediary shield (a search engine *shows* content, it does not *make* it) was rejected because the system **combined and rewrote** source material into new assertions. Cited sources did not support the generated claims. |
| **What it implies operationally** | A confidently-wrong generated statement is not only a quality defect; it is a potential liability event. The defence is not "the model said it" — it is being able to show that low-confidence outputs were **withheld, deferred, or escalated**, and that the decision was **recorded**. |
| **The exact `lub` artifact** | The guard decision vocabulary (`ABSTAIN` / `FLAG` / `ESCALATE`) plus the per-decision audit ledger: for any given customer-facing statement, evidence of what the confidence was, which threshold applied, and what the system did about it. |
| **Honest limit** | ⚠️ **NOT PRIMARY-SOURCE VERIFIED.** Sourced from secondary reporting (*The Batch*, 2026-07-17); the judgment text, docket number, and exact date have **not** been checked against the court record, and Google was reported to be appealing to the Federal Court of Justice (BGH). It is a **German** decision — persuasive context for a risk conversation, **not** a US or Brazilian legal authority, and **not** an anchor to cite externally until verified. Do not carry this row into any external or evidentiary document in its current state. |

---

## One-glance summary

| Region | Lead anchor | Coded in `lub`? | Primary urgency | Headline `lub` artifact |
|---|---|---|---|---|
| **US** | SR 11-7 / OCC 2011-12 | Cross-mapped (3-pillar table); not a 7th enum | Next model-validation cycle / exam | Calibration + back-testing metrics → OSCAL |
| **EU** | AI Act Arts. 9/10/13/14/15 (high-risk) | **Yes — article-level coded** | **~Aug 2026** (verify) — sharpest clock | Article-by-article crosswalk → OSCAL |
| **UK** | PRA SS1/23 | **No — principles evidenced via same artifacts** | Internal review / PRA engagement | Same SR 11-7 evidence surface, by analogy |
| **Brazil** | BCB 4.893/2021 + LGPD Art. 20 | **Yes (BCB coded)** + audit ledger for Art. 20 | Continuous monitoring; ~5-yr retention; on-request review | Coded BCB metrics + per-decision audit drill-in |
| **APAC** | MAS / HKMA GenAI | **No — principles evidenced via same artifacts** | Supervisory dialogue | Same evidence surface, by analogy |

---

## For your CRO — the three questions to ask us

1. **"Show me the reproduction."** `lub`'s evidence is open-source and reproducible
   (seed + dataset hash); an auditor can re-run it and verify every number. Ask us
   to reproduce a metric live.
2. **"Where does our data go?"** With local model backends, **nowhere** — the
   evidence core is numpy + stdlib and air-gap-runnable, single-tenant. Confirm this
   against your data-residency requirements.
3. **"What do you explicitly NOT do?"** We do not perform your independent
   validation, hold your model inventory, or assert legal/conformity determinations;
   and we do **not** yet hold SOC 2, an independent pen-test, an SLA, a hosted
   offering, or a reference customer. Those are roadmap. See
   [`docs/sr-11-7.md`](./sr-11-7.md) and
   [`docs/integration_tiers.md`](./integration_tiers.md).

---

*Every regulatory citation, article number, deadline, and cadence on this page is
directional and **must be verified against the primary source and your own legal /
compliance function before any external or filing use.** Coded regimes:
`src/lub/reports/crosswalk_data.toml`. SR 11-7 internal-citation reconciliation is a
tracked v0.2 item (`planning/32_SR117_Audit_Findings_2026-07-05.md`). Repo
SR 11-7 structure verified against federalreserve.gov `sr1107` / occ.gov
`bulletin-2011-12` on 2026-07-05.*