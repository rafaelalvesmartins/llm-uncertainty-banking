# Architecture

!!! note "Scope of this page"
    User-facing summary. The authoritative internal doc -- data flows,
    full directory tree, deferred work -- lives at
    `planning/09_Project_Architecture.md`. The architecture-decision
    record that repositioned ruflo as the orchestration core is at
    `planning/ADRs/ADR-002_ruflo_as_orchestration_core_2026-04-25.md`.

!!! warning "Repositioning (ADR-002, 2026-04-25)"
    As of pass 24, `llm-uncertainty-banking` is **not** a top-level
    application -- it provides **calibrated workers** that run inside a
    [ruflo](https://github.com/ruvnet/ruflo) swarm (npm `claude-flow`,
    MIT). The strictly layered library described below is still the
    foundation, but the recommended user-facing entry point is
    `lub.runtime.build_swarm_pack`, not `lub.pipeline`.


!!! tip "Canonical visual"
    The SVG diagram at `docs/diagrams/architecture.svg` is the single
    source of truth for the post-ADR-002 architecture rendering. The
    ASCII diagrams below are a text-friendly summary; if they drift,
    the SVG wins.

## Two ways to use the library

```
                +-------------------------------------+
                |   ruflo swarm (orchestration core)  |   <- recommended
                |   ruvnet/ruflo - MIT - external Node|      entry point
                +------------------+------------------+
                                   |
                  Protocol-based bridge (lub.agents.adapters.ruflo)
                                   |
                +------------------v------------------+
                |  Calibrated workers built from      |
                |  lub.runtime.SwarmMemberSpec        |
                +------------------+------------------+
                                   |
                +------------------v------------------+
                |  src/lub/  -- strictly-layered lib  |   <- low-level API
                |  (still importable directly via     |      (lub.pipeline)
                |  UncertaintyPipeline for adv. use)  |
                +-------------------------------------+
```

## The layered library underneath

`lub` itself is a small, strictly layered library. Every import flows
downward; no module in a lower layer may import from a higher one. The
contract is enforced at CI time by
[import-linter](https://import-linter.readthedocs.io/).

```
L5 Reports       lub.reports       (AI RMF Jinja template + renderer)
L4 Benchmarks    lub.benchmarks    (FinQA, ConvFinQA, TAT-QA, br_regulatory, runner)
L3 Calibration   lub.calibration   (ECE, Brier, AUROC, reliability diagrams)
L2 Uncertainty   lub.uncertainty   (22 estimators across 7 families;
                                    see `docs/estimators.md` for the
                                    full list and family taxonomy)
L1 Wrappers      lub.wrappers      (ModelBackend ABC + HF / OpenAI /
                                    Anthropic / vLLM / Dummy)
```

The `lub.runtime` and `lub.agents.adapters.ruflo` modules sit above L5;
they orchestrate workers built from the lower layers. `lub.pipeline`
and `lub.cli` remain user-facing entry points for the low-level API and
are allowed to reach into any layer.

## Why strict layering?

Regulated model-risk reviewers need to locate evidence fast. When the
graph of allowed imports is a straight line, every metric on an AI RMF
report has a single upstream path:

- accuracy / ECE / AUROC values <- calibration metrics
- calibration metrics <- benchmark runner
- benchmark runner <- dataset + pipeline
- pipeline <- backend + estimator

There are no cycles, no hidden monkey-patches, and no shared global
state. Swapping a backend or estimator never requires editing layers
above it.

## Capability declarations (2026-04-26)

Each backend declares which optional methods it supports via a
`BackendCapability` flag enum on `ModelBackend.CAPABILITIES`. Each
estimator declares its hard requirements via
`Estimator.REQUIRES_CAPABILITIES`. The pair lets the pipeline reject
incompatible combinations at construction time, before any network
call, instead of catching `NotImplementedError` mid-run:

```python
from lub.wrappers.base import BackendCapability
from lub.wrappers.openai import OpenAIBackend       # GENERATE | EMBED
from lub.wrappers.anthropic import AnthropicBackend # GENERATE only
from lub.wrappers.hf import HFBackend               # GENERATE | LOGPROBS | EMBED

OpenAIBackend.CAPABILITIES & BackendCapability.LOGPROBS  # -> 0 (false)
HFBackend.CAPABILITIES & BackendCapability.EMBED         # -> EMBED (true)
```

Estimators with hard requirements:

| Estimator group                                                          | Requires             |
| ------------------------------------------------------------------------ | -------------------- |
| `conformal`, `adaptive_conformal`, `conformal_sampling`, `mondrian_conformal` | `LOGPROBS`           |
| `mahalanobis`, `graph_laplacian`                                         | `EMBED`              |
| `token_logprob`, `perplexity`, `semantic_entropy`                        | `LOGPROBS` (via `Generation.logprobs`; soft) |
| `self_consistency`, `epistemic_aleatoric`, `claim_level`, `verbalized`   | `GENERATE` only      |
| `p_true`, `eigenscore`                                                   | `GENERATE` (with documented LOGPROBS / EMBED fallback path) |

Estimators that want fail-loud semantics call
`self._assert_backend_capabilities(backend)` at the top of `score()`;
that raises `lub.exceptions.CapabilityError` (a `BackendError`
subtype) with a structured `context` dict that lists the missing
capabilities.

## Domain exception hierarchy (2026-04-26)

`lub.exceptions` ships a hierarchy of domain-specific exceptions so
callers can `except` on something more specific than bare `Exception`:

```
LubError                       # abstract base; never raised directly
+- BackendError                # transport / rate-limit / malformed response
|   +- CapabilityError         # backend lacks an optional method
+- EstimatorError              # estimator could not produce a valid score
+- BenchmarkError              # dataset loader exhausted HF + local fallback
+- CalibrationError            # calibrator state inconsistent (predict-before-fit)
+- OrchestrationError          # router / swarm / phase pipeline failed
+- ConfidenceParseError        # adapter could not interpret upstream confidence
```

All exceptions carry an optional `context: dict` for structured-log
diagnostics and an optional `cause` argument that records the wrapped
exception's class name into `context["cause_type"]` so an OSCAL audit
trail keeps the chain even after the traceback is dropped.

These exceptions are reexported from the top-level package:

```python
from lub import LubError, BackendError, CapabilityError, ConfidenceParseError
```

`ValueError` and `TypeError` are still raised for bad arguments
(idiomatic Python); the new hierarchy covers domain errors at runtime,
not argument validation at function boundaries.

## Data types

The library shares a tiny set of dataclasses across layers
([src/lub/types.py](https://github.com/rafaelmartinsalves/llm-uncertainty-banking/blob/main/src/lub/types.py)):

- `Generation` -- one model completion with optional per-token logprobs.
- `TokenLogProbs` -- token-level logprobs for a (prompt, completion) pair.
- `UncertaintyResult` -- the output of any estimator: answer + confidence
  in `[0, 1]` + diagnostic `raw_scores` + optional samples +
  `should_refuse` flag.
- `BenchmarkResult` -- persisted, frozen Pydantic record of one benchmark
  run. This is the unit of evidence that gets rendered into AI RMF
  reports.
- `LedgerSummary` (`lub.ledger.protocol`) -- aggregate counts derived
  from a `LedgerProtocol` snapshot. Used by `lub.ledger.metrics` to
  render Prometheus / Grafana payloads from any ledger backend, not
  just the sqlite-backed one.

## Pluggable extension points

Three namespaces sit alongside the layered core to make the architecture's
pluggability legible from the source tree, even when no third-party
extensions are installed yet:

- `lub.orchestration.FailoverChain` -- chain of `TieredRouter` instances
  with automatic failover on backend errors. Pattern adapted with
  attribution from `ruvnet/ruflo` (MIT). The lub twist is that
  calibration-monotonicity is enforced at `__init__`: a failover cannot
  silently relax the safety guarantee of an earlier tier.
- `lub.ledger.LedgerProtocol` -- structural interface for any durable
  audit log. The bundled sqlite-backed `Ledger` and the test-double
  `InMemoryLedger` both satisfy it. Includes a `summary() -> LedgerSummary`
  method so first-party metric exporters do not need direct cursor
  access; future plug-in backends (Postgres, DuckDB, Parquet-on-S3)
  drop in without modifying `lub.ledger.metrics`.
- `lub.evidence.EvidenceStoreProtocol` -- structural interface for k-NN
  evidence stores. Bundled implementation: hashed TF-IDF
  (`lub.evidence.store.EvidenceStore`); production-grade vector DBs
  (FAISS, pgvector, RuVector) can plug in via the same protocol.
- `lub.domains` -- empty namespace package reserved for domain-specific
  extension points (banking, healthcare, legal, ...). Each domain
  contributes a regime-mapping module + benchmark dataset + agent pack
  without modifying the core layers. See
  `planning/30_Generic_Architecture_Spec_2026-04-25.md` for the
  contribution contract.
- `lub.compliance` -- empty namespace package reserved for compliance-
  framework adapters that map a `BenchmarkResult` onto regulatory
  controls beyond the six canonical regimes already in
  `lub.reports.crosswalk_data.toml`. Lets a deployment add e.g. a
  jurisdiction-specific audit framework without forking the core.

## What this library is not

- **Not a serving framework.** No server, no live web UI, no database.
  (`lub.reports.dashboard` ships a *static* offline HTML evidence viewer
  -- see below.)
- **Not a training library.** No fine-tuning, no RLHF, no dataset curation.
- **Not a RAG system.** Retrieval is out of scope; BYO retriever if you
  need one.

Staying small is the point: the library is meant to be read end-to-end
by a model-risk team in an afternoon.

## `lub.runtime.engine` vs `lub.orchestration` -- what goes where

Two subpackages have orchestration-flavored names and a new contributor
can be confused about which one to extend. The boundary, codified in
pass 30:

* **`lub.orchestration`** carries the *runtime mechanics*: routing
  (`router.py`, `topology.py`), swarm consensus (`swarm.py`), pipeline
  hooks (`hooks.py` -- `PipelineHookRegistry`), phased rollout
  (`phases.py`). Things that decide **who runs** and **when**, given a
  pre-built set of agents.

* **`lub.runtime.engine`** carries the *agent metadata*:
  `OrchestratedAgentSpec` (id, name, domain, priority, parallel_safe,
  agent_factory) and the dispatch helpers (`dispatch_by_domain`).
  Things that describe **what an agent is** for the orchestrator to
  schedule.

In short: `lub.runtime.engine` declares the inventory;
`lub.orchestration` runs it. The two are intentionally separate so an
external runtime (a custom Ruflo deployment, a hand-rolled scheduler,
a future streamed pipeline) can consume the inventory without taking
the bundled orchestration machinery, and vice versa: a different
declarative format (TOML, plugin manifest) can feed the bundled
orchestration without going through the engine dataclass.

If a future feature is unsure where to land, ask: *does this describe
an agent, or does it decide which agent runs?* The first goes in
`runtime.engine`; the second in `orchestration`.

## On naming: `protocol.py` vs `protocols.py`

Both names appear in the source tree (`benchmarks/protocol.py`,
`evidence/protocol.py`, `ledger/protocol.py`, `reports/protocol.py`
alongside `agents/protocols.py`, `dashboard/protocols.py`,
`evidence/protocols.py`, `runtime/protocols.py`, and the top-level
`lub/protocols.py`). Both forms work today; the canonical form per
file is whichever the bulk of internal callers already import. The
convergence target is the **plural** (`protocols.py`) -- the v0.1
singular files keep working because each ships a paired `protocols.py`
shim that re-exports the singular surface, and the singular files keep
their `# DEFER (v0.3)` deprecation header. The full rename happens at
v0.3 with a deprecation cycle. See
``CODE_ORGANIZATION_REVIEW_2026-04-25.md`` §A.2 for the rationale.

## Deliberately not adopted from ruflo

ADR-002 puts ruflo at the orchestration core, but several Ruflo features
are **deliberately not adopted** into `lub` because they conflict with the
banking-MRM domain or with the audit-defensibility requirements that
shape every other design choice in this library:

- **Q-Learning self-learning router.** Ruflo's router learns over time
  which agent to dispatch to for which prompt class. `lub` uses
  `TieredRouter` with calibrated UQ thresholds (`P(True)` / token-SAR)
  that an auditor can read off as a fixed decision rule. Learned routing
  without a calibration audit trail is a model-risk problem.
- **314 auto-generated MCP tools.** Ruflo exposes its full surface as
  MCP tools. `lub` ships a narrower 5-tool workflow surface
  (`score_with_p_true`, `score_with_token_sar`, `reliability_diagram`,
  `airmf_report`, `cascaded_answer`) plus a per-estimator / per-metric
  auto-generator. Banking auditors prefer fewer named tools they can
  enumerate.
- **WASM kernels (Rust) for hot paths.** `lub.evidence` and `lub.calibration`
  stay numpy + stdlib only -- hermetic-test friendly, easy to ship in an
  air-gapped environment, and LLM-API latency dominates anyway.
- **Byzantine fault tolerance (BFT 2/3 majority).** `lub.orchestration.UQSwarm`
  fuses scores via weighted vote. BFT consensus is overkill for a
  single-tenant single-org banking deployment with no adversarial agents.
- **SPARC dev-workflow agents** (Specification -> Pseudocode -> Architecture
  -> Refinement). `lub` is a model-risk evidence library, not an
  end-to-end software-engineering agent framework; the SPARC pattern
  belongs upstream in ruflo, where it originated.

## Disk-integrity check (2026-04-26)

`scripts/check_integrity.py` scans `src/lub` and `tests` for null
bytes, AST `SyntaxError`, and heuristic truncation cues (last line
ending in an open delimiter). It is a defensive tool for the
Windows-on-bash-mount workflow used during development; CI does not
need it because CI compiles every file. Run before every commit:

```bash
python scripts/check_integrity.py     # exit 0 means clean
python scripts/check_integrity.py --strict   # also flag missing trailing newline
```
