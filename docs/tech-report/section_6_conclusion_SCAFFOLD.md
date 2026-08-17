# Section 6 — Conclusion and Future Work (scaffold)

**Status:** draft v1 (2026-04-25). Numbers from CANONICAL_FACTS are
filled (22 estimators, 14 metrics, 20 br_regulatory items). Section
6.2's Findings 1-3 stay placeholdered until item G (Qwen rerun)
ships. Sections 6.1, 6.3, 6.4, 6.5, 6.6, 6.8 are review-ready prose;
§6.7 (Acknowledgments) is the explicit fill-by-hand block per
DESIGN_DECISIONS.md rules. Target length: 1,200-1,800 words (arXiv tech-report conclusions commonly overflow 2k — we aim shorter).

---

## 6.1 Summary of contributions

We introduce `llm-uncertainty-banking` (lub), an open-source Python library
for calibrated uncertainty quantification of LLM outputs in regulated
banking contexts. The library contributes three artifacts:

1. **A uniform estimator interface** that wraps HuggingFace, OpenAI,
   Anthropic, vLLM, and a dummy backend behind a common
   `ModelBackend` ABC (Section 3), with 22 estimators
   implementing black-box, grey-box, and white-box uncertainty
   signals from the literature.

2. **A calibration-metric suite** (14 metrics including
   ECE, Brier, AUROC-for-refusal, risk-coverage curves, and prediction-set
   cardinality) that can be applied to any estimator's output and
   compared across benchmarks (Section 4).

3. **A NIST AI RMF-aligned report generator** (Section 4.5, Table 5.4)
   that maps calibration metrics to AI RMF 1.0 sub-categories in
   markdown and HTML, producing an artifact that a model-risk reviewer
   can drop directly into a validation packet. To our knowledge, no
   prior open-source tool produces this artifact. This is the library's
   principal contribution — the estimators and metrics are
   infrastructure that makes the report reproducible, not differentiators.

## 6.2 Empirical findings

> **NOTE (2026-04-25, pre-rerun):** the three findings in this section
> reference Section 5 results that are currently blocked on item G in
> ``06_Projeto_GitHub/WHAT_RAFAEL_NEEDS_TO_DO.md`` -- the canonical
> Qwen2.5-0.5B benchmark sweep currently shows Acc=0.000 / AUROC=0.500
> across all rows in ``docs/tech-report/artifacts/results_table_qwen.md``,
> which is not a citable result. Once item G ships (rerun on a model
> that scores >0% on the eval task), the three ``{Finding N -- fill
> from Section X.Y}`` placeholders below get real numbers and prose.
> Until then, this section is intentionally unfilled.


Our experiments on FinQA, ConvFinQA, TAT-QA, and a hand-crafted
Brazilian-regulatory benchmark (20 items) yielded three
findings worth highlighting:

1. **{Finding 1 — fill from Section 5.2}:** e.g., semantic entropy and
   self-consistency outperform token-logprob on ECE in {X of 4} of the
   benchmarks we tested, at roughly {K×} the compute cost. Practitioners
   selecting an estimator for production should weigh the calibration
   improvement against the inference budget.

2. **{Finding 2 — fill from Section 5.3-5.4}:** the AUROC-for-refusal
   signal is {strong/weak} on {which} benchmark and {unexpectedly
   weak/strong} on {which}, suggesting {hypothesis}.

3. **{Finding 3 — fill from Section 5.5}:** selective prediction risk
   falls below 5% at {X}% coverage on {benchmark}, meaning {implication
   for banking deployments — e.g., ~40% of queries could be automated
   with human review on the rest without breaching a 5%-risk threshold}.

We were {surprised / unsurprised} by {specific result}; this is
discussed in Section 5.2.

## 6.3 The AI RMF-mapping thesis

The core intellectual claim of this work is that **calibration metrics
can serve as first-class compliance evidence** when mapped to regulatory
sub-categories in a structured format. Table 5.4 operationalizes this
claim: it proposes thresholds per sub-category that are achievable
with contemporary LLMs on in-distribution calibration sets, and it
flags where thresholds are aspirational (for instance, MEASURE 2.7
for adversarial robustness, where no open-source estimator currently
meets the proposed threshold across all four benchmarks).

We do not claim Table 5.4 is the final mapping. We claim that
**having a structured mapping is itself a contribution**, because it
converts the otherwise-vague "demonstrate calibration" requirement of
SR 11-7 and BCB Resolution 4.658 into a specific, reproducible,
automatable artifact.

## 6.4 Limitations

1. **Scale.** All primary experiments use Qwen2.5-0.5B-Instruct. Appendix
   A reports 7B/8B replications, but the library's claims should be
   re-validated at the specific scale a deployment uses.

2. **Language and jurisdiction.** Three of four benchmarks are
   English-only. `br_regulatory` covers Brazilian banking regulation;
   the mapping in Table 5.4 is framed against US (SR 11-7) and
   international (Basel) standards but does not exhaustively cover
   EU AI Act annexes or other jurisdictional frameworks.

3. **Single-turn QA focus.** The library's current primitives assume a
   single-turn prompt-response interaction. Multi-turn agent
   pipelines — increasingly common in production — are not yet
   handled end-to-end. Section 6.6 discusses this as the next
   direction.

4. **The hand-crafted `br_regulatory` set is small** ({N=20} items).
   Statistical power is limited. We make no claims of generalizability
   from that set; it functions as a probe, not a benchmark.

5. **Calibration set drift.** All conformal and temperature-scaled
   estimators assume exchangeability between calibration and deployment
   distributions. In banking deployments this assumption is routinely
   violated (new regulations, new products, seasonal load patterns);
   monitoring drift is the deployer's responsibility, not the
   library's.

## 6.5 Reproducibility

All experiments are reproducible via `scripts/reproduce_release.sh`.
Seeds, hashes, and JSON outputs are committed under
`benchmarks/results/`. The library is available on PyPI
(`pip install llm-uncertainty-banking`), source-licensed under
Apache 2.0, and the arXiv version of this report is {arxiv:TBD}.
A Zenodo DOI is minted at each tagged release.

## 6.6 Future work — the agent-layer extension (v0.3)

The direction we intend to pursue next is **attaching calibrated
confidence to every step of a multi-agent LLM pipeline.** Current
agent-orchestration frameworks (LangGraph, CrewAI, AutoGen, ruflo)
route, compose, and delegate, but do not attach a calibrated
probability to each agent's output — leaving the orchestrator with
no principled way to decide when to abstain, escalate to a human, or
re-route to a different agent. We are extending lub with an `agents/`
module that wraps these frameworks and produces per-step
`(answer, calibrated_probability, uq_method, ai_rmf_category)` tuples.
The AI RMF reporter is extended with an "Agent Trail" section.

The motivation is concrete: banking deployments are moving from
single-call LLMs to multi-agent workflows (document triage → rule
lookup → credit-memo summarization → human handoff), and the
per-step uncertainty problem is harder than the single-call case.
We believe this is where the AI RMF mapping has the most to
contribute over the next 12 months.

Beyond the agent layer, three smaller directions:

- **Red-team / jailbreak prompts specific to financial QA**, feeding
  AUROC-for-refusal against adversarial distributions (MEASURE 2.7
  threshold currently not met — improving it is a well-defined
  research direction).
- **Shadow-mode calibration logging** — a deployment mode that logs
  predictions alongside calibration-ready metadata without blocking
  traffic, so banks can calibrate estimators on their own traffic
  distribution without the risks of online calibration.
- **HELM-style agent eval suite** — contributing lub's AI RMF scorers
  upstream to HELM as an optional scoring protocol.

## 6.7 Acknowledgments

{Fill in this section by hand — DESIGN_DECISIONS.md rules apply:
name specific researchers, papers, colleagues, advisors. No
boilerplate.}

## 6.8 Code and data availability

- Code: https://github.com/rafaelmartinsalves/llm-uncertainty-banking
- PyPI: https://pypi.org/project/llm-uncertainty-banking
- Data: `src/lub/benchmarks/data/br_regulatory.jsonl` (hand-crafted,
  public sources); other benchmarks via their respective HuggingFace
  datasets (licenses preserved).
- Tech report LaTeX source: `docs/tech-report/paper.tex`
- Reproduction recipe: `scripts/reproduce_release.sh`

---

## Pre-submit checklist

- [ ] All `{bracketed}` placeholders filled with Rafael's actual numbers and words.
- [ ] Acknowledgments (§6.7) hand-written.
- [ ] Limitations (§6.4) includes *at least one* limitation you are uncomfortable admitting publicly but know is true.
- [ ] Future-work (§6.6) agent-layer paragraph is consistent with RFC-001.
- [ ] Zenodo DOI minted and referenced.
- [ ] arXiv number filled in place of `{arxiv:TBD}` after assignment.
