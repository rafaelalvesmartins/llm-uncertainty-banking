# Tech Report Draft

Working draft of the arXiv tech report that accompanies the `llm-uncertainty-banking`
v0.1.0 release. Target venue: arXiv (cs.CL primary, cs.LG secondary), with a
concurrent 4-page version submitted to a FinML workshop.

See [draft.md](draft.md) for the current skeleton.

**Status:** v0.1 skeleton — sections filled with `TODO` markers where real
results, citations, or figures are still pending the first real-model benchmark
run.

## Addendum — governance runtime framing (2026-04-23)

The v0.2 cut reframes `lub` from *a calibration toolkit* to *a
governance runtime for LLMs in banking*. Two research claims flow from
the new modules and will be validated against `br_regulatory.jsonl`
and FinQA:

1. **Tiered abstention with per-tier calibration** (via `TieredRouter`)
   dominates single-model selective prediction on the cost-vs-risk
   Pareto frontier. Cascaded Haiku → Sonnet with
   context-specific thresholds should at matched cost achieve lower
   risk at fixed coverage than either model alone.

2. **Method-disagreement between UQ scorers** (via `UQSwarm`) is an
   additional, cheap predictor of correctness. Preliminary internal
   runs suggest disagreement adds information beyond any single
   method's confidence; we will report correlation with accuracy and
   AUROC uplift over the best single estimator.

Both claims are directly relevant to AIRMF MEASURE 2.3 / 2.7 / 2.9,
SR 11-7 validation pillars, and BACEN Resolução 4.893. The
accompanying runtime (ledger, evidence store, ADRs, MCP surface) is
described in the main README under *Governance runtime*.

A nightly GitHub Actions workflow (`nightly-calibration.yml`) replays
reliability buckets from the ledger via `lub.governance.drift.enforce_drift`
and fails the job when the measured ECE exceeds the
`regulatory-qa` bounded context's ADR target — turning the two
research claims above into continuously-verified invariants, rather
than one-shot benchmark results. Prometheus textfile export from
`lub.ledger.metrics` makes the same signal observable from any
standard banking SRE stack.
