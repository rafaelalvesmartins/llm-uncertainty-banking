---
id: "0006"
title: "Layer enforcement via importlinter contracts"
status: accepted
date: 2026-04-25
supersedes: null
superseded_by: null
invariants:
  enforcement_tool: import-linter
  enforcement_runtime: ci_only
  fail_open: false
  layered_packages:
    - lub.wrappers
    - lub.uncertainty
    - lub.calibration
    - lub.benchmarks
    - lub.reports
  composition_packages:
    - lub.ledger
    - lub.evidence
    - lub.mcp
    - lub.governance
    - lub.agents
    - lub.challenge
---

# ADR 0006 — Layer enforcement via importlinter contracts

## Context

The library is layered: wrappers → uncertainty → calibration →
benchmarks → reports. Composition modules (ledger, evidence, mcp,
governance, agents, challenge) sit on top. Without enforcement, an
"oh just import it from there" patch turns the layered architecture
into a graph in three sprints. Once the cycles exist, they are
expensive to remove.

## Decision

Layer dependencies are enforced by `import-linter` contracts in
`pyproject.toml`. CI runs `import-linter` on every PR. A contract
violation fails the build with a clear rule citation. The
contracts are the source of truth — diagrams in
`docs/architecture.md` are derived from them, not the other way
around.

Specific contracts:

- L1–L5 are a strict layered chain. L_n may import from L_{<n}; the
  reverse is forbidden.
- Composition modules each declare their dependency set explicitly
  (e.g., `lub.challenge` may import from
  `{uncertainty, calibration, reports, ledger, evidence, mcp}` and
  nothing in that set may import from `lub.challenge`).

## Consequences

- A PR that introduces a circular import or a wrong-direction
  import fails CI before reviewer time is spent.
- Refactoring is safe: the contracts catch accidental coupling
  during a rename or a move.
- Trade-off accepted: every new package adds one contract entry.
  This is a minor authoring cost paid once per package.

## Alternatives considered

- **Lint rules / runtime asserts.** Lint rules don't catch
  transitive cycles; runtime asserts pay the cost on every import
  and don't run in tests that mock the dependency.
- **Manual review.** Doesn't scale; reviewers don't reliably catch
  layer violations in a 200-file diff.
- **Single big package, no enforcement.** Loses the testability and
  swappability that layers buy.

## References

- Config: `pyproject.toml` `[tool.importlinter]`
- Tool: https://import-linter.readthedocs.io
- Cross-link: ADR 0007 (Protocol adapters use the same
  no-hard-dep discipline at the framework boundary).
