# Section 5 — Results (scaffold)

**Status:** skeleton only. `TODO(real-number)` markers indicate cells that MUST be filled from actual Qwen2.5-0.5B benchmark runs before submission. Do NOT submit with TODO markers present.

> **⚠ BLOCKED ON ITEM G — `WHAT_RAFAEL_NEEDS_TO_DO.md` (2026-04-25 audit).** Filling this scaffold from the *current* `scripts/reproduce_release.sh` output will reproduce Acc=0.000 / AUROC=0.500 across every cell — Qwen2.5-0.5B is too small for FinQA-class extractive QA and the canonical results tables under `docs/tech-report/artifacts/` already carry "NOT FIT FOR CITATION" warning banners for the same reason. Do not begin filling Section 5 until item G resolves (see "Three resolution paths" in WHAT_RAFAEL_NEEDS_TO_DO §G — pivot to BR-Regulatory yes/no, hosted-API single-row on Claude Haiku, or full re-run on Qwen2.5-7B / Llama-3-8B). Once at least one (estimator × dataset) combination produces Acc>0.20 and AUROC>0.55, this banner can be removed and the artifacts/README.md "do not cite" rule updated to point at the regenerated table. Section 6 conclusion drafting is **not** blocked on G and may proceed independently.

**How to fill:** run `scripts/reproduce_release.sh --seed 0 --model qwen2.5-0.5b --benchmarks all`, then copy the JSON under `benchmarks/results/` into the tables below. Every number in this section must be a direct copy from a committed JSON file, keyed by seed and SHA.

---

## 5.1 Experimental setup

We evaluate the library on four banking-adjacent benchmarks: FinQA, ConvFinQA, TAT-QA, and the hand-crafted `br_regulatory` set. All runs use Qwen2.5-0.5B-Instruct as the base model (chosen for reproducibility on commodity GPUs — an A100 pass is not required). Larger-model runs (Qwen2.5-7B, Llama-3.1-8B) are reported in Appendix A.

**Hardware:** `TODO(real-number: GPU model, hours of runtime, cost)`.
**Random seeds:** `{0, 1, 2}`. All reported numbers are means across seeds with 95% bootstrap CIs over calibration points (N=`TODO(real-number)` per dataset).
**Calibration split:** 20% of each benchmark, held out before any estimator sees the data.

## 5.2 Estimator comparison — calibration quality

Table 5.1 — Expected Calibration Error (ECE, lower is better) across estimators and benchmarks.

| Estimator | FinQA | ConvFinQA | TAT-QA | br_regulatory |
|---|---|---|---|---|
| Token log-probability | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |
| Semantic entropy (Kuhn 2023) | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |
| Self-consistency (Wang 2022) | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |
| Split conformal | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |
| Perplexity | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |
| P(True) | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |
| Eigenscore | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |
| Verbalized confidence | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |

**Expected pattern (to verify, not assume):** semantic-entropy and self-consistency typically beat token-logprob on ECE in open-ended QA; conformal wins on worst-case guarantees at cost of conservativeness. Report what the data actually shows — including where expectations break.

## 5.3 Brier score

Table 5.2 — Brier score (lower is better).

| Estimator | FinQA | ConvFinQA | TAT-QA | br_regulatory |
|---|---|---|---|---|
| Token log-probability | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |
| Semantic entropy | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |
| Self-consistency | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |
| Split conformal | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` | `TODO(real-number)` |

## 5.4 AUROC for refusal

Table 5.3 — AUROC for the "should-refuse" decision when treating uncertainty as a decision threshold. Higher is better.

`TODO(real-number-table)`

**Interpretation:** AUROC > 0.80 suggests the estimator is a usable refusal signal; < 0.65 suggests it is close to random. Report honestly — low AUROC on br_regulatory would itself be a finding worth publishing.

## 5.5 Risk-coverage curves

Figure 5.1 — Selective prediction: risk (error on predicted subset) vs. coverage (fraction answered) for each estimator on FinQA.
`TODO(figure: plots/risk_coverage_finqa.pdf)`

Figure 5.2 — Same curves, br_regulatory.
`TODO(figure: plots/risk_coverage_br_regulatory.pdf)`

Discussion: at what coverage does each estimator achieve <5% risk? `TODO(real-discussion)`. (5% is a representative high-stakes triage threshold used in regulated decisioning; cite a public source — Basel III or SR 11-7 commentary — in the final draft rather than any single institution's internal value.)

## 5.6 NIST AI RMF sub-category mapping — the key table

Table 5.4 — which calibration metric satisfies which NIST AI RMF 1.0 sub-category. This is the core contribution of the library and the one table a model-risk reviewer will screenshot.

| AI RMF sub-category | Description (abbr.) | Metric in lub | Threshold proposed |
|---|---|---|---|
| MEASURE 2.3 | AI system performance is demonstrated | ECE, Brier | ECE < 0.10 on in-distribution calibration set |
| MEASURE 2.7 | AI system security and resilience demonstrated | AUROC for refusal on adversarial prompts | AUROC > 0.75 |
| MEASURE 2.8 | Risks of adverse impact evaluated and documented | Risk-coverage curve, worst-case coverage | Coverage ≥ 60% at risk ≤ 5% |
| MEASURE 2.9 | AI system evaluated for explainability and interpretability | Conformal prediction-set cardinality | Median cardinality ≤ 3 for multiple-choice |
| MANAGE 4.1 | Post-deployment AI system risk documented | All of the above, re-run monthly | Monthly drift delta < 20% |

**This table is the thesis of the library.** If nothing else is read in Section 5, Table 5.4 is what the reporter emits and what the petition's Section 3.1-3.3 cites.

## 5.7 Ablation — impact of calibration set size

Figure 5.3 — ECE vs. calibration set size for split-conformal on FinQA. `TODO(figure)`. Show that performance saturates around N=`TODO(real-number)` — important because banking deployments rarely have large held-out sets.

## 5.8 Limitations of the reported numbers

1. Qwen2.5-0.5B is a small model; larger-model calibration may differ qualitatively (Appendix A reports 7B / 8B replication).
2. FinQA/ConvFinQA/TAT-QA are English-only; cross-lingual behavior is out of scope for v0.1.
3. `br_regulatory` is 20 items — statistical power is limited. Treat its numbers as indicative, not conclusive.
4. All estimators assume stable inference temperature across calibration and deployment; temperature drift in production would break the guarantees.

---

## Before submitting, verify:

- [ ] Every `TODO(real-number)` is replaced with a number sourced from `benchmarks/results/*.json`.
- [ ] Every table cell references a committed JSON + seed + SHA.
- [ ] Every figure PDF is committed under `docs/tech-report/plots/`.
- [ ] Table 5.4 survives pressure-testing: can you defend, to a model-risk reviewer, why each metric maps to that sub-category?
- [ ] Appendix A (7B / 8B replication) exists and shows numbers in the same format.
- [ ] The "expected pattern" sentences in §5.2 either confirm or deliberately break expectations — no "results align with intuition" hedging.
