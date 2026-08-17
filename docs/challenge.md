# `lub.challenge` — Continuous Effective Challenge (CEC)

**Status:** shipped (v0.3). Real implementation backed by 50+ unit and integration tests. Canonical spec: [`planning/24_CEC_Spec_2026-04-25.md`](https://github.com/rafaelmartinsalves/llm-uncertainty-banking/blob/main/planning/24_CEC_Spec_2026-04-25.md).

## What it is

SR 11-7 requires *"effective challenge"* — validation that actively questions a model's behavior — but every bank treats it as a point-in-time event (annual or semi-annual review, sign-off, repeat). LUB's `lub.ledger` already records every (prompt, response, UQ scores, policy decision, outcome) tuple. CEC turns that log into a **continuous, calibrated, executable** effective-challenge process.

CEC composes already-shipped lub modules:

- `lub.ledger` — substrate
- `lub.calibration.drift` — drift event source
- `lub.evidence` — k-NN historical lookup
- `lub.mcp` — exposes CEC outputs as MCP tools
- `lub.reports.mapping` — OSCAL emission for AIRMF MANAGE 4.1 + MEASURE 2.7 evidence

## Four functions

### 1. Replay (counterfactual model risk)

Take a window of the ledger and re-execute each decision through one of:

- An alternative estimator (`AlternativeEstimator("adaptive_conformal")`)
- A different model tier (`AlternativeTier("claude-sonnet-4-6")`)
- A different calibration threshold (`AlternativeThreshold(0.85)`)

Produces a `ReplayReport` with counterfactual abstention rate, correctness rate, cost delta per 1k calls, and an audit trail. Hermetic — for `AlternativeEstimator` we synthesise a deterministic-by-hash counterfactual confidence rather than spinning up a real backend, so replay never spends external-API budget.

### 2. Drift reasoning

For each `lub.calibration.drift` event in the window, generate a one-paragraph hypothesis about what changed, scored against k-NN retrieval from `lub.evidence` over historical drift events. Pure rule-based for v0.3 — LLM-backed reasoning is gated to v0.4 (see spec §6 for the staging rationale).

### 3. Meta-calibration

`MetaCalibrator.add_prediction(claim_id, predicted_confidence, horizon_days)` records a CEC claim. After the horizon expires, `record_outcome(claim_id, held_up: bool)` closes the loop. `reliability_curve()` returns a binned `CalibrationCurve` (default 10 bins / deciles) plus an ECE figure. Persistence is via two new ledger tables — `cec_meta_predictions` and `cec_meta_outcomes` — added through an additive schema-v2 migration; existing v1 ledgers gain the tables on next open without data loss.

### 4. MCP tool surface

Four read-only MCP tools delegate computation to `lub.challenge`:

- `lub.challenge.replay(window, alternative)`
- `lub.challenge.explain_drift(event_id)`
- `lub.challenge.report(period)`
- `lub.challenge.meta_calibration_curve()` — returns a path to a written PNG (or JSON fallback when matplotlib is unavailable)

## Worked example: replay last month, compare adaptive_conformal vs split_conformal on BR-Regulatory

```python
from datetime import datetime
from lub.challenge import (
    ReplayEngine, AlternativeEstimator, assemble_cec_report,
)
from lub.ledger import Ledger
from lub.evidence import EvidenceStore

ledger = Ledger("./uq_ledger.db")
engine = ReplayEngine(ledger=ledger)

# Counterfactual 1: adaptive conformal
adaptive = engine.replay_window(
    start=datetime(2026, 4, 1),
    end=datetime(2026, 5, 1),
    alternative=AlternativeEstimator("adaptive_conformal"),
)

# Counterfactual 2: split conformal
split = engine.replay_window(
    start=datetime(2026, 4, 1),
    end=datetime(2026, 5, 1),
    alternative=AlternativeEstimator("conformal"),  # split conformal registry key
)

print(f"Baseline abstention: {adaptive.baseline_abstention_rate:.1%}")
print(f"adaptive_conformal: {adaptive.counterfactual_abstention_rate:.1%}")
print(f"split_conformal:    {split.counterfactual_abstention_rate:.1%}")
print(f"Δ cost / 1k calls (adaptive): ${adaptive.cost_delta_estimate:.4f}")

# Wrap into a CEC report (also runs drift + meta-calibration).
store = EvidenceStore()  # or load a domain-tuned store
report = assemble_cec_report(
    period_start=datetime(2026, 4, 1),
    period_end=datetime(2026, 5, 1),
    ledger=ledger,
    evidence_store=store,
    replay_alternatives=[
        AlternativeEstimator("adaptive_conformal"),
        AlternativeEstimator("conformal"),
    ],
)
for rec in report.recommendations:
    print("-", rec)
```

The same data renders to OSCAL Assessment-Results JSON via `to_oscal_assessment_results(report)` — observations are tagged as AIRMF MANAGE 4.1 + MEASURE 2.7 evidence so a GRC tool consuming OSCAL routes them to the right control catalog without manual remapping.

## Why CEC matters for petition / publication

CEC is the basis for the proposed *fourth* "first and only" claim in the lub petition narrative: **first OSS library to operationalize SR 11-7 effective challenge as a continuous, calibrated process** — not a point-in-time review. Maps directly to AIRMF MANAGE 4.1 (continuous monitoring) and MEASURE 2.7 (re-assessment over time), which today are mostly aspirational at most banks.

The publishable angle is the meta-calibration piece. *"Calibrated meta-prediction in continuous model risk monitoring"* has no published baseline. Target venues: FAccT, NeurIPS Trustworthy ML, AIES.

## See also

- Spec: [`planning/24_CEC_Spec_2026-04-25.md`](https://github.com/rafaelmartinsalves/llm-uncertainty-banking/blob/main/planning/24_CEC_Spec_2026-04-25.md)
- [`governance.md`](governance.md) — the governance layer CEC reports against.
