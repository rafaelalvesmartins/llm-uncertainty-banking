---
id: "0001"
title: "Calibration targets per bounded context"
status: accepted
date: 2026-04-23
supersedes: null
superseded_by: null
invariants:
  regulatory-qa:
    calibration_target_ece: 0.03
    coverage_target: 0.70
    risk_ceiling: 0.01
  retail-credit:
    calibration_target_ece: 0.05
    coverage_target: 0.85
    risk_ceiling: 0.03
  fraud-alerts:
    calibration_target_ece: 0.07
    coverage_target: 0.95
    risk_ceiling: 0.05
  investor-advisory:
    calibration_target_ece: 0.04
    coverage_target: 0.75
    risk_ceiling: 0.02
---

# ADR 0001 — Calibration targets per bounded context

## Context

LLM outputs in banking must be calibrated *per use case*. A single
global ECE target is meaningless when a regulatory-QA bot and a
marketing-copy generator have radically different risk surfaces.

## Decision

Each bounded context declares three numbers:

- `calibration_target_ece` — upper bound on Expected Calibration Error.
- `coverage_target` — fraction of queries the runtime will answer
  without abstaining.
- `risk_ceiling` — maximum acceptable error rate on answered queries.

Nightly calibration replay (`Ledger.replay_calibration`) feeds these
back into CI via `lub.governance.assert_policy`.

## Consequences

- A breach fails CI; the offending estimator or tier must be retrained
  or the context's numbers renegotiated with the risk team.
- New contexts inherit the least-permissive defaults (0.03 / 0.70 /
  0.01) until explicitly relaxed.
