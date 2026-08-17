---
id: "0007"
title: "Cross-framework adapters via typing.Protocol"
status: accepted
date: 2026-04-25
supersedes: null
superseded_by: null
invariants:
  adapter_pattern: structural_typing
  adapter_module: lub.agents.adapters
  hard_framework_deps: 0
  supported_frameworks:
    - ruflo
    - langgraph
    - crewai
    - autogen
---

# ADR 0007 — Cross-framework adapters via `typing.Protocol`

## Context

`lub.agents` integrates with at least four upstream agent
frameworks: ruflo, LangGraph, CrewAI, AutoGen. Each ships its own
abstract base class for "an agent." Importing all four would (a)
explode the install footprint, (b) couple lub's release cadence to
upstream API churn, and (c) force a hard dependency on packages
that may not be in the user's environment.

## Decision

Cross-framework integration goes through `typing.Protocol`s defined
locally inside `lub.agents.adapters.<framework>`. Each adapter
module declares the minimum structural interface lub depends on
(typically `name: str` + `run(input) -> Any` + a few optional
fields) and uses `runtime_checkable` for `isinstance` use sites.

Concrete agents from upstream frameworks satisfy the Protocol by
**duck typing** — they never need to inherit from a lub class.
Conversely, lub's `CalibratedAgent` is wrapped into a
"framework-shaped" Python dataclass that satisfies the upstream's
expected interface without taking a hard import on the upstream.

No upstream framework is in `pyproject.toml`'s `dependencies`;
`langgraph`, `crewai`, etc. live in optional `[project.optional-dependencies]`
extras for users who already have them.

## Consequences

- The library installs cleanly with zero framework dependencies.
- Tests for the adapters use minimal pytest fakes that satisfy the
  Protocol — no need to install ruflo / langgraph / crewai to run
  the test suite.
- A new framework integration is one new file under
  `lub.agents.adapters/` plus a new optional extra; no edits to
  core lub code.
- Trade-off accepted: loose coupling is inherently a shape contract,
  not a type contract. If an upstream changes a method's signature,
  the adapter breaks at call time, not at import time. Mitigated by
  per-adapter integration tests.

## Alternatives considered

- **Hard imports of each framework.** Defeats the
  embed-without-deps property and bloats the install.
- **A single generic abstract base class.** Forces every framework
  to fit one shape; in practice they don't (LangGraph nodes vs
  CrewAI tasks vs ruflo agents have non-overlapping semantics).
- **Optional `try/except` imports inside core code.** Spreads
  framework knowledge across the codebase; harder to audit.

## References

- Code: `src/lub/agents/adapters/{ruflo,langgraph,crewai,autogen}.py`
- Protocol use sites: `RufloAgentProtocol`, `LangGraphNodeProtocol`,
  etc.
- Cross-link: ADR 0006 (layer enforcement) keeps adapters from
  reaching back into core lub.
