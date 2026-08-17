---
id: "0003"
title: "Model tier hierarchy"
status: accepted
date: 2026-04-23
invariants:
  tiers:
    - name: haiku
      model: claude-haiku-4-5
      threshold_default: 0.80
      cost: 0.001
    - name: sonnet
      model: claude-sonnet-4-6
      threshold_default: 0.70
      cost: 0.015
    - name: opus
      model: claude-opus-4-6
      threshold_default: 0.60
      cost: 0.075
---

# ADR 0003 — Model tier hierarchy

## Context

Cost and capability scale together. We want cheap models answering
easy questions and expensive models reserved for the tail.

## Decision

Three tiers — `haiku`, `sonnet`, `opus` — with context-specific
overrides for `threshold_default`. `TieredRouter` walks them in this
order.

## Consequences

- Adding a new provider (e.g. open-weights Llama-3) requires a new
  ADR that maps it onto this hierarchy.
- Thresholds are hyperparameters, not constants: each bounded
  context's nightly calibration run may shift them. CI tracks drift.
