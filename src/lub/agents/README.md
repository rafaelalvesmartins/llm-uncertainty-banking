# `lub.agents` — three agent concepts, one folder

This subpackage carries three things that all have "agent" in the name
but mean different things. Read this first before adding code.

## The trinity

```
┌─────────────────────────────┐
│ CalibratedAgent             │  ← inherit from this when you write a
│   (lub.agents.core, ABC)    │    new lub-native agent. Provides the
│                             │    full RunReport + policy + uncertainty
│                             │    plumbing.
└─────────────────────────────┘

┌─────────────────────────────┐
│ OrchestratorAgentProtocol   │  ← duck-type against this when you
│   (lub.agents.protocols,    │    integrate an EXTERNAL framework
│    typing.Protocol)         │    (ruflo, langgraph, crewai, autogen).
│                             │    No inheritance. Just .name + .run().
└─────────────────────────────┘

┌─────────────────────────────┐
│ OrchestratedAgentSpec       │  ← declarative METADATA for swarm
│   (lub.runtime.engine,      │    orchestration: domain, priority,
│    frozen dataclass)        │    parallel_safe. NOT a runnable thing —
│                             │    it carries an agent_factory callable.
└─────────────────────────────┘
```

## When to use which

| Need | Use |
|---|---|
| Build a brand-new lub agent from scratch | inherit `CalibratedAgent` |
| Wrap an existing ruflo / langgraph / crewai / autogen agent | duck-type against `OrchestratorAgentProtocol`; pass to `from_orchestrator_agent` |
| Register an agent in the swarm config (domain tags, priority) | construct an `OrchestratedAgentSpec` |
| Expose a lub agent to an external framework | call `to_orchestrator_agent(my_calibrated_agent)` |

## Why three? Why not one big base class?

Three forces are at play and they don't compose into one shape:

1. **Inheritance** (`CalibratedAgent`, ABC) gives you free behavior:
   the base class wires uncertainty scoring + policy + audit trail, so
   subclasses just implement `parse()` and `render_prompt()`.

2. **Structural typing** (`OrchestratorAgentProtocol`, `typing.Protocol`)
   is what we need at the framework boundary. A real `ruflo.Agent`
   shouldn't have to inherit from a lub class — that's a hard import
   we explicitly avoid (see ADR 0007 — Cross-framework adapters via
   `typing.Protocol`).

3. **Configuration** (`OrchestratedAgentSpec`, frozen dataclass) is
   metadata for the swarm scheduler: which domain partition this agent
   serves, what priority it has, whether it can run in parallel with
   peers. Pure data.

Trying to fold these into one class loses one of the three properties
(usually #2: you can't structurally type-check inheritance from
`runtime_checkable` Protocols cleanly when the class also carries
runtime state).

## Adapter family

The adapters under `lub.agents.adapters/` translate between
`CalibratedAgent` (lub-native) and `OrchestratorAgentProtocol` (any
external framework):

- `orchestrator.py` — generic Protocol + `from_orchestrator_agent` /
  `to_orchestrator_agent` round-trip. **The other adapters use this.**
- `ruflo.py` — alias re-exports for backwards-compat with the
  pre-2026-04 ruflo-specific naming (`from_ruflo_agent`,
  `RufloAgentProtocol`).
- `langgraph.py`, `crewai.py`, `autogen.py` — framework-specific
  adapters that satisfy the same Protocol.

When integrating a new framework: add `lub.agents.adapters.<name>` and
duck-type against `OrchestratorAgentProtocol` from
`lub.agents.protocols`. Do NOT import from sibling adapters.

## Why the Protocol now lives in `lub.agents.protocols` (not in `adapters/orchestrator`)

Pre-pass-30: the Protocol lived inside `adapters/orchestrator.py`, and
`adapters/ruflo.py` imported it sibling-to-sibling. Adapters depending
on adapters is a smell — if you delete or move `orchestrator.py` the
others break by surprise.

Pass-30 refactor (this folder): the Protocol moved to
`lub.agents.protocols`. All adapters import from there. The old
location keeps a re-export shim for one minor version, so external
code doesn't break.

If you're new to this codebase: just import from `lub.agents` directly
— `OrchestratorAgentProtocol`, `CalibratedAgent`, and
`OrchestratedAgentSpec` are all re-exported at the top level.
