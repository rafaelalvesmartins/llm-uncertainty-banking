---
id: "0002"
title: "Abstention rules"
status: accepted
date: 2026-04-23
invariants:
  default_on_fail: ABSTAIN
  max_reask_retries: 1
  require_citation_for_domains:
    - regulatory-qa
    - investor-advisory
---

# ADR 0002 — Abstention rules

## Context

When the runtime is uncertain, silence beats noise. Regulatory-QA and
investor-advisory also demand a citation when they do answer.

## Decision

- The default `PolicyDecision.on_fail` is `ABSTAIN`.
- `REASK` is allowed once (`max_reask_retries = 1`) before falling
  back to `ABSTAIN`.
- For `regulatory-qa` and `investor-advisory` the post-hook must
  reject any answer that does not contain a retrieved citation.

## Consequences

Callers explicitly opt in to `FLAG` or `PASSTHROUGH` — the runtime
will never silently return a low-confidence answer.
