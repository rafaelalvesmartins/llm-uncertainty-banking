# Evidence dashboard

**Note.** This page is for **private** maintenance use. It lives in the gated
`09_Projeto_GitHub/planning/` tree (moved here 2026-07-11 from `docs/` after it
was accidentally added to the public mkdocs nav) and must never ship in the
built docs. If it ever appears on the public docs site again, treat as a breach
of petition hygiene and remove immediately.

**Purpose.** A single page Rafael can open each month to see the state of petition-relevant evidence without digging through three dozen files. Updated monthly as part of the `EVIDENCE_MONTHLY.md` ritual.

---

## Top-level status

_Last refreshed: 2026-05-02 (covering window 2026-04-01 → 2026-05-01). Section A repo metrics: original snapshot `repo_metrics_2026-04.md` was held at `UNKNOWN — verify manually` due to a session-scoped git-access failure; supplemental capture `repo_metrics_2026-04_supplement.md` added 2026-05-02T22:12Z after eb2niw monorepo git access cleared in-session, populating the rows below. Lub `.git` standalone is still absent from the sandbox mount, so lub-only metrics are computed by path-filter on the monorepo log rather than from a fresh clone; `gh` remains unavailable so star/issue/PR counts still need a host re-run. All non-git rows refreshed from source trackers._

| Dimension | Current | Target | Status |
|---|---|---|---|
| GitHub stars | UNKNOWN — verify manually (`gh` still not available this run) | 20-40 by filing | ⏳ |
| External non-star interactions | 0 in 2026-04 (no issues / PRs / mentions captured) | ≥ 1 | 🔴 |
| Commits/week avg | ~44/wk monorepo (248 commits over 2026-04-14 → 2026-04-30 active span); ~30/wk lub path-filter (177 commits over the same span). Window starts 2026-04-14 = monorepo init, so 2026-04-01 → 04-13 had no commits in this repo. | ≥ 2 sustained | 🟢 (in window) |
| Dormant weeks YTD | UNKNOWN — verify manually (only 2026-04-14 onward exists in this monorepo; pre-init weeks would belong to a different repo) | 0 | ⏳ |
| arXiv tech report status | Drafting | Indexed w/ DOI | ⏳ |
| v0.1 release | Pending (only `v0.0.1` tagged 2026-04-21 confirmed via `refs/tags`, SHA `593690295…`; v0.1 not yet cut) | Tag + PyPI | 🔴 |
| v0.2 beta release (agents) | Not started | By month 3 post-launch | 🔴 |
| Adapter working end-to-end | Scaffold only | ≥ 1 by month 6 | 🔴 |
| Accepted talks (US venue) | 0 (CFP SUBMISSION_LOG still empty; ICML UDL / KDD Fintech / MLOps World deadlines fall in May 2026) | ≥ 1 | 🔴 |
| Citations in academic papers | 0 | ≥ 1 (stretch) | 🔴 |
| Merged PR to US-maintained OSS project | 0 (all 5 tracker rows still "Scoped") | ≥ 1 (stretch) | 🔴 |

Legend: 🟢 on track, ⏳ in progress, 🔴 not yet / at risk.

Replace the `—` values and statuses at each monthly review.

---

## Petition-section evidence map

| Section | What it needs | Current artifacts | Gap |
|---|---|---|---|
| 3.1 Rare Intersection | Public artifact at the banking + UQ + AI governance intersection | Repo (private pre-launch); Flagship Spec; arXiv draft | Launch the repo; index arXiv |
| 3.2 Mathematical Rigor | Conformal coverage derivations; calibration-metric grounding; tech report | tech-report scaffolds Sections 5/6; 22 estimators in code | Populate Section 5 with real numbers; ship tech report |
| 3.3 Banking Execution | Evidence of banking-domain competence | `br_regulatory.jsonl`; Flagship Spec problem framing | Add more benchmark examples; keep BRB-internal language out |
| 3.4 American Engagement | Interaction with US researchers and US OSS maintainers | 7 drafted outreach emails; 5 scoped OSS PRs; community post schedule | Ship the launch → trigger replies |
| Prong 1 (national importance) | AI RMF / EO 14110 relevance evidence | L5 reporter (code); OSCAL rendering | Cite real deployments in a blog post (without naming specific banks); add NIST AI RMF appendix to tech report |
| Prong 2 (well-positioned) | Tangible evidence of capability | Repo + arXiv + agents scaffold + plugin pack spec + adapters | Ship v0.2; publish first community adoption notice |

---

## Upcoming milestones (rolling 90 days)

| Date | Milestone | Source document |
|---|---|---|
| TBD | arXiv submission | `docs/tech-report/SUBMISSION_CHECKLIST.md` |
| TBD D0 | Launch HN / LinkedIn / Reddit | `planning/launch_posts/SCHEDULE.md` |
| TBD D+7 | Community post wave begins | `planning/COMMUNITY_POST_SCHEDULE.md` |
| TBD D+7 | Early-adopter DM wave begins | `planning/launch_posts/DM_TEMPLATE.md` |
| TBD D+14 | First retrospective post | `planning/launch_posts/SCHEDULE.md` |
| TBD month+3 | v0.2 beta (`lub.agents`) | `planning/RFC_001_calibrated_agents_2026-04-23.md` |
| TBD month+6 | lub-ruflo-banking-pack public | `planning/oss_prs/ruflo_banking_compliance/` |
| TBD | First accepted talk | `planning/conferences/CFP_TRACKER.md` |

Replace `TBD` values on each monthly refresh.

---

## Outreach pipeline

| Week | Recipient | Status | Reply type | Follow-up due |
|---|---|---|---|---|
| 1 | Kolter | Not sent | — | — |
| 2 | Raghunathan | Not sent | — | — |
| 3 | Hashimoto | Not sent | — | — |
| 4 | Steinhardt | Not sent | — | — |
| 5 | Koyejo | Not sent | — | — |
| 6 | Liang | Not sent | — | — |
| 7 | Belinkov (conditional) | Not sent | — | — |

Update from `12_Outreach_Emails/REPLY_TRACKER.md` at each monthly refresh.

---

## OSS PR pipeline

| Project | Issue | PR | Status |
|---|---|---|---|
| guardrails-ai | Not opened | — | Pending |
| ruflo | Not opened | — | Pending |
| lm-eval-harness | Not opened | — | Pending |
| giskard | Not opened | — | Pending |
| langchain | Not opened | — | Pending |

Update from `planning/oss_prs/PR_TRACKER.md` at each monthly refresh.

---

## Conferences / talks pipeline

| Event | Deadline | Status |
|---|---|---|
| ICML UDL 2026 workshop | ~2026-05-20 | Not submitted |
| KDD Fintech 2026 workshop | ~2026-05-30 | Not submitted |
| PyData NYC 2026 | ~2026-07 | Not submitted |
| MLOps World Austin 2026 | ~2026-05 | Not submitted |
| NeurIPS Trustworthy ML 2026 | ~2026-09 | Not submitted |

Update from `planning/conferences/CFP_TRACKER.md` at each monthly refresh.

---

## Top-3 risks right now

(Rotate monthly; pick the three worst out of `08_Risks_and_Pitfalls.md`.)

1. **Dormancy risk.** Sustained commit cadence is the single most-checkable
   evidence item; a 3+ week dormant period weakens Section 3.3 visibly.
   *Mitigation:* calendar-blocked commit windows; trivial but real
   maintenance commits count.
2. **Question-line / outreach quality.** Emails with vague questions get
   ignored; emails with specific questions get answered. Current drafts
   are mostly OK (see `QUESTION_LINE_AUDIT_2026-04-23.md`), but two
   drafts need revision before send.
3. **Agent-layer scope drift.** "Build an agent framework" would
   destroy the petition timeline. RFC-001 draws a hard line; monitor
   backlog items against it monthly.

## Bottom-of-page note

This dashboard is a **mirror**, not a source of truth. Sources of truth:

- `12_Outreach_Emails/REPLY_TRACKER.md` for outreach.
- `planning/oss_prs/PR_TRACKER.md` for OSS PRs.
- `planning/conferences/CFP_TRACKER.md` for conferences.
- `02_Evidencias_Profissionais/monthly/*/INDEX_*.md` for monthly snapshots.
- `02_Evidencias_Profissionais/quarterly/*/QUARTERLY_SUMMARY_*.md` for quarterlies.

When a value on this dashboard disagrees with a source of truth, the
source is correct; update this page.
