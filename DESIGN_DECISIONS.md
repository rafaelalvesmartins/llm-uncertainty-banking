# Design Decisions Behind `llm-uncertainty-banking`

This document captures the non-obvious trade-offs in the library's
design. It is a companion to `README.md` (what the library does) and
`docs/architecture.md` (how the parts fit together).

The target reader is someone evaluating `lub` for production use —
typically a model risk officer or a senior engineer on a model-risk
platform team — who wants to know *why* the design looks the way it
does before committing to the dependency.

---

> ## Repositioning (ADR-002, 2026-04-25, post-counsel-warning)
>
> The five-layer architecture described in section 1 below is **still
> the foundation** of `lub` and is still enforced by `import-linter`.
> What changed in pass 24 is the **public positioning**: `lub` is now
> framed as a library of calibrated workers running inside a
> [ruflo](https://github.com/ruvnet/ruflo) swarm, not as a top-level
> Python application. The recommended entry point for new users is
> `lub.runtime.build_swarm_pack`, not `lub.pipeline`.
>
> Decision log:
> `planning/ADRs/ADR-002_ruflo_as_orchestration_core_2026-04-25.md`
> (records 5 explicit warnings raised by Cowork before the change was
> accepted: EB2-NIW originality, counsel-gating, RFC-001 inversion,
> upstream dependency risk, petition narrative impact).

## 1. Architecture rationale

A strict five-layer architecture — `wrappers` < `uncertainty` <
`calibration` < `benchmarks` < `reports` — enforced at CI time by two
import-linter contracts defined in `pyproject.toml` (lines 140–180).
The first contract is a `layers` type that encodes the dependency
direction explicitly:

```
layers = [
    "lub.reports",
    "lub.benchmarks",
    "lub.calibration",
    "lub.uncertainty",
    "lub.wrappers",
]
```

The ordering is not arbitrary: each layer depends only on the layers
below it, never sideways or upward. A backend wrapper knows nothing
about calibration metrics; a report generator can reach down to any
layer but never touches the guard or policy system.

The reason tooling enforces this — rather than convention — is that
convention does not survive a team. Import-linter fails the CI build
if any module violates the layer contract, so the architecture is a
tested property of the codebase, not a diagram that drifts.

Cross-cutting concerns — `UncertaintyGuard`, the CLI, the
`UncertaintyPipeline` facade, and the telemetry module — live outside
the five layers. They are explicitly exempted in the import-linter
`ignore_imports` rules (`lub.pipeline -> lub.*`, `lub.cli -> lub.*`,
`lub.guard -> lub.*`, `lub.telemetry -> lub.*`,
`lub.protocols -> lub.*`) because their job is to *orchestrate* the
layers, not to sit inside one. A second `forbidden` contract prevents
the core five layers from importing `guard`, `rails`, `policies`, or
`telemetry`, so the trust/policy boundary cannot leak into the
estimation or reporting logic. The `forbidden` contract uses
`allow_indirect_imports = "true"` because some indirect paths are
legitimate — for example, `benchmarks.runner` imports `pipeline` under
`TYPE_CHECKING` only, which is safe at runtime.

Decoupling at the interfaces uses Protocol-based structural typing
(`protocols.py`). Three protocols define the behavioural contracts:

- **`BackendProto`** — requires `generate()`, plus optional whitebox
  extensions `logprobs()` and `embed()` that raise `NotImplementedError`
  when unsupported. Estimators catch that exception and fall back to a
  blackbox path.
- **`WhiteboxBackendProto`** — extends `BackendProto` with a `model_id`
  attribute and a `_load() -> (model, tokenizer, config)` method for
  estimators like MC dropout and LM-Polygraph that need direct access
  to `nn.Module` internals.
- **`PipelineProto`** — requires `answer()`, `batch_answer()`, and
  `to_dict()`. Any object with these three methods satisfies the
  contract without inheriting from anything.

These are `typing.Protocol` contracts — not abstract base classes —
so a three-line mock with an `answer()` method satisfies
`PipelineProto` without subclassing. That matters for testing (every
test in the guard suite uses a `FakePipeline` dataclass, not a real
`UncertaintyPipeline`) and for extensibility (a third-party backend
works without subclassing `ModelBackend`).

---

## 2. Estimator selection

`lub` ships 22 estimators organised into 8 families:

- **Token-level:** `TokenLogprobEstimator`, `PerplexityEstimator` —
  cheapest to compute, single-pass, work on any backend exposing
  log-probabilities.
- **Sampling-based:** `SelfConsistencyEstimator`,
  `SemanticEntropyEstimator`, `EnsembleEstimator` — require multiple
  generations, measure answer-level disagreement.
- **SAR (Shifted Attention Ratio):** `TokenSAREstimator`,
  `SentenceSAREstimator` — attention-based uncertainty from
  Duan et al. (2024).
- **Conformal:** `ConformalEstimator`, `AdaptiveConformalEstimator`,
  `MondrianConformalEstimator`, `ConformalSamplingEstimator`,
  `CCPEstimator` — distribution-free coverage guarantees.
- **Density / embedding:** `MahalanobisEstimator`,
  `EigenScoreEstimator`, `GraphLaplacianEstimator` — detect
  out-of-distribution inputs via embedding geometry.
- **Verbalized:** `VerbalizedOneShot`, `VerbalizedTwoShot` — prompt
  the model to self-report confidence; zero extra cost, works on any
  blackbox API.
- **Whitebox:** `MCDropoutEstimator`, `EpistemicAleatoricEstimator`,
  `LMPolygraphEstimator` — require access to model internals (dropout
  masks, hidden states).
- **Hybrid:** `PTrueEstimator`, `SelfCertaintyEstimator`,
  `ClaimLevelEstimator` — combine generation with secondary
  verification passes.

The reason for 22 rather than 3 is coverage across the backend
spectrum. A bank using OpenAI's API cannot run MC dropout — they only
get blackbox methods (`VerbalizedOneShot`, `VerbalizedTwoShot`,
`SelfConsistencyEstimator`, `SemanticEntropyEstimator`). A bank
running an on-premise Llama-3 via HuggingFace or vLLM gets whitebox
methods too (`MCDropoutEstimator`, `EpistemicAleatoricEstimator`,
`LMPolygraphEstimator`) plus the full token-level family. No single
estimator works everywhere, and no single family captures all
dimensions of uncertainty. Token-level methods catch fluency
uncertainty but miss factual uncertainty; sampling methods catch
factual disagreement but cost 5–10× more compute; density/embedding
methods detect out-of-distribution inputs that the other families miss
entirely. The lazy-loading design in `uncertainty/__init__.py` (see
Section 5, Mistake 3) means a bank only pays the import cost for the
estimators it actually uses.

The conformal family deserves special attention. Conformal prediction
provides a mathematical guarantee — "the true answer is in this set
with probability ≥ 1 − α" — without distributional assumptions about
the model. For a regulator asking "how do you know the model is
calibrated?", conformal prediction is the only answer that does not
start with "we assume the model's output distribution is…". The five
conformal variants serve different needs:

- `ConformalEstimator` — the basic split-conformal guarantee.
- `AdaptiveConformalEstimator` — handles distribution shift over time.
- `MondrianConformalEstimator` — group-conditional coverage (critical
  for fair-lending compliance, where you need coverage guarantees
  *per subgroup*, not just on average).
- `ConformalSamplingEstimator` — works with sampled generations
  rather than point predictions.
- `CCPEstimator` — class-conditional conformal with exchangeability
  relaxation.

---

## 3. Regulatory framework mapping

`lub` maps to six regulatory regimes, defined as a `Regime` StrEnum in
`reports/crosswalk.py`:

| Regime enum value | Framework | Jurisdiction |
|---|---|---|
| `NIST_GENAI` | NIST AI 600-1 (GenAI Profile, July 2024) | US |
| `EU_AI_ACT` | Regulation 2024/1689 (binding August 2026) | EU |
| `BCBS` | BCBS d475 + 2024 GenAI extension | International (Basel) |
| `BCB` | Resolução 4.893 + Circular 3.978 | Brazil |
| `ISO_23894` | ISO/IEC 23894:2023 (AI risk management) | International |
| `ISO_42001` | ISO/IEC 42001:2023 (AI management systems) | International |

The crosswalk itself lives in `reports/crosswalk_data.toml` — a TOML
file, not Python — so auditors can review the regulatory mapping
without reading code. The file defines 32 controls across all six
regimes and maps 23 `lub` metrics (19 quantitative + 4 provenance) to
those controls. The Python module `reports/crosswalk.py` loads and
validates the TOML at import time using `tomllib`, exposing
`get_crosswalk()`, `get_crosswalk_for_regime()`, and
`get_all_controls_for_regime()`. The catalogs in `reports/catalog.py`
render these controls as machine-readable OSCAL 1.1.2 Catalog JSON —
the foundational layer of the OSCAL stack.

The 23 mapped metrics span four trust dimensions: **Efficacy**
(accuracy, Spearman, Kendall tau, Matthews correlation, sharpness),
**Robustness** (ECE, Brier, RMSCE, ENCE, miscalibration area,
refusal AUROC, PRR, AURC, AUUCC, missing ratio, reversed pairs
proportion, CRPS, NLL), **Bias** (adversarial group calibration), and
**Explainability/Security** (dataset hash, dataset version, git SHA,
package versions). Every metric maps to at least two regimes; most
map to all six.

The OSCAL output (`reports/oscal.py`) makes the mapping
machine-actionable. Each benchmark run produces an OSCAL Component
Definition (schema version 1.1.2) with one `component` per benchmark
run naming the `backend:model/estimator` combination, one
`control-implementation` per control catalog, and one
`implemented-requirement` per metric — keyed by the RMF sub-category
from `reports/mapping.py`. The `by-component.description` field
carries the metric name, numeric value, and severity label from the
`FindingClassifier`. GRC tools like NIST Trestle or Regscale ingest
these directly — no manual re-keying of metric values into a
spreadsheet. No other open-source LLM library publishes OSCAL output
as of April 2026; the closest is Venturalítica (arXiv:2604.13767v1),
which explicitly excludes LLMs ("LLM remain future work").

`lub` also generates OSCAL Catalogs for the EU AI Act and BCBS d475 —
controls that no one has published in OSCAL format before. The EU AI
Act catalog covers Articles 9, 10, 13, 14, and 15 (accuracy and
robustness); the BCBS d475 catalog covers Principles 1, 3, and 5
(including the 2024 GenAI extension). Even if no one uses `lub`
itself, those catalogs are independently useful to the GRC community.

---

## 4. Benchmark and calibration design

The calibration layer (`lub.calibration.metrics`) computes 14 metrics
plus 5 scoring rules. The core trio is **ECE** (Expected Calibration
Error, Guo et al. 2017), **Brier score**, and **AUROC** of confidence
as a correctness predictor. These three capture orthogonal properties:
ECE measures whether stated confidence matches empirical accuracy
(calibration), Brier measures the mean squared error of probabilistic
predictions (sharpness + calibration combined), and AUROC measures
whether the confidence ranking is useful for triage (discrimination).
A model can have good AUROC but terrible ECE — it ranks well but the
probabilities are wrong. A bank that reports only one metric gets a
dangerously incomplete picture.

Beyond the core trio, the library computes RMSCE (root mean squared
calibration error — the L2 analogue of ECE that penalises large
single-bin gaps), ENCE (expected normalised calibration error),
miscalibration area (a bin-free CDF-based alternative to ECE),
adversarial group calibration (worst-case ECE over random subgroups),
and several others. Adversarial group calibration is particularly
important for banking: it catches cases where the model is
well-calibrated on average but badly miscalibrated on a subpopulation,
exactly the pattern that triggers fair-lending scrutiny under ECOA
and Regulation B.

Conformal prediction enters the calibration design as a coverage
guarantee. The `ConformalEstimator` and its variants produce
prediction sets with a user-specified coverage level (e.g. 90%). The
calibration metrics then verify empirically that the coverage holds on
held-out data. This two-step — conformal set construction, then
empirical coverage verification — is what "calibration" means in a
regulatory context: not just "the model is confident" but "the model's
confidence means what it claims to mean."

The benchmarks use public financial QA datasets (FinQA, ConvFinQA,
TAT-QA) plus 20 hand-curated banking questions drawn from BCB and
Basel III source documents. The 20 questions cover capital adequacy
(Basel III Pillar 1), liquidity coverage ratio, BCB Resolução 4.893
technology risk, and LGPD data governance. They are hand-written
because generated questions are generic — they do not test whether a
model knows the difference between CET1 and Tier 2 capital, or can
cite the correct BCB circular number. A banking audience would
immediately spot synthetic filler.

---

## 5. Mistakes and lessons learned

**Mistake 1: Splitting policies into a separate module (commit
`dda9add`).** The first version of the code created a `policies.py`
module with `PolicyDecision` and `PolicyOutcome`, on the theory that
separation of concerns required a separate file. In practice, the
policy definitions and the guard that enforces them are a single
cohesive concept — you never use one without the other. Worse, having
them separate created a circular import risk: `guard.py` imported
from `policies.py`, but both needed types from `types.py`, and any
growth would tighten the cycle. Commit `dda9add` consolidated
everything into `guard.py`. The module docstring on line 8 still
reads "Combines two concerns that are logically one" — a deliberate
record of the original split. The code is organised with a section
header comment on line 37:
`# Policy definitions (formerly lub.policies)` to make the provenance
explicit. The import-linter `forbidden` contract in `pyproject.toml`
(line 172) still lists `lub.policies` as a banned import target — a
fossil from the original design that now serves as a guard against
anyone recreating the mistake.

**Mistake 2: REASK with no metadata tracking.** The first version of
the REASK policy was fire-and-forget: the guard retried the prompt,
and if the retry passed, it returned the new answer with no record
that a retry had happened. That made it impossible to audit retry
decisions in the AI RMF report. MANAGE 2.4 needs to show "actions
taken in response to measured risks," and a silent retry is an
invisible action. `_handle_reask` (guard.py, lines 281–381) now
produces a `PolicyOutcome` with explicit metadata. The metadata dict
carries three audit fields: `first_pass_confidence` (the original
score that triggered the retry), `reask_attempted` (boolean — `False`
when `max_reask_retries=0` skips the retry entirely), and
`reask_succeeded` (boolean — whether the retry met the threshold).
The `reason` string is also fully descriptive, e.g.
`"reask failed: first confidence 0.3200, retry confidence 0.4100,
both < threshold 0.5000; fell through to ABSTAIN"`. Every retry is
a first-class auditable event. The `max_reask_retries` parameter
(defaulting to 1) was added after a run where unbounded retries could
mask a fundamentally uncertain answer — retrying ten times until one
passes is not risk management, it is p-hacking. The zero-retry path
(`max_reask_retries=0`, lines 302–328) also records full metadata so
the audit trail shows *why* no retry was attempted.

**Mistake 3: Eager loading of all 22 estimator modules.** The first
release loaded every estimator at import time via conventional
`from .token_logprob import TokenLogprobEstimator` lines in
`uncertainty/__init__.py`. With 22 modules and transitive dependencies
on torch, sentence-transformers, and lm-polygraph, CLI startup took
4–6 seconds even for `lub --help`. `uncertainty/__init__.py` now uses
`__getattr__`-based lazy loading with a `_LAZY_MAP` dict — a
dictionary mapping 23 class names (22 estimators + `VerbalizedOneShot`
and `VerbalizedTwoShot` sharing one module) to their
`(module_path, class_name)` tuples. The module-level `__getattr__`
function on line 47 checks the map, calls `importlib.import_module()`
only on first access, and raises `AttributeError` for anything not in
the map. The base class `Estimator` is still eagerly imported
(`from lub.uncertainty.base import Estimator`) because downstream code
(`pipeline`, `guard`) needs the ABC and registry helpers at import
time. This cut CLI startup by 30–50%. The module docstring
explicitly documents the rationale: "This avoids importing all 22
estimator modules (and their transitive dependencies) when only one
is needed." The lesson: in a library with heavyweight optional
dependencies, lazy loading is not premature optimisation — it is a
usability requirement.

---

## 6. What `lub` deliberately does NOT do

**`lub` does not fine-tune models.** It quantifies uncertainty on
models as-given. Fine-tuning changes the model's behaviour, which
invalidates any pre-fine-tuning calibration. Mixing estimation and
training in one library would create a misleading "calibrate then
fine-tune" workflow that gives banks false confidence. The correct
order is: fine-tune first, then run `lub` on the result.

**`lub` does not host or serve models.** It wraps existing backends
(HuggingFace, OpenAI, Anthropic, vLLM) but never runs an inference
server. Model serving is an infrastructure concern with its own
security, scaling, and SLA requirements. Bundling a server would
expand `lub`'s regulatory surface from NIST AI RMF MEASURE (where it
belongs) into GOVERN and MANAGE territory (availability, access
control, incident response) — concerns that belong to the platform
team, not the measurement library.

**`lub` does not handle PII.** Prompts and answers flow through the
library in memory and are never persisted by `lub` itself. Benchmark
datasets are public (FinQA, ConvFinQA, TAT-QA) or synthetic. The 20
hand-curated banking questions contain no customer data. This boundary
is deliberate: the moment a library stores PII, it inherits GDPR
Article 30, LGPD Article 37, and GLBA 501(b) record-of-processing
obligations. `lub` stays outside that perimeter entirely.

**`lub` does not provide real-time serving guarantees.** The
`UncertaintyGuard` is a synchronous Python call (the `__call__`
method on line 228 of `guard.py`), not an async endpoint with latency
SLAs. The `gated_tool_call` method (lines 383–482) implements the
UALA pattern (Han, Buntine, Shareghi, ACL 2024) — it makes *two*
sequential pipeline calls when the model is uncertain, which doubles
latency. Banks needing sub-100ms guard decisions should run the
estimator offline, cache the thresholds, and use a lightweight runtime
check. `lub` is a measurement and reporting tool, not a serving layer.

**`lub` does not ship Docker images, IaC, or database storage.** These
are infrastructure concerns that vary per bank and per cloud provider.
Bundling a Dockerfile would create a false impression that `lub` is a
deployable service; it is a pip-installable library. Database storage
for benchmark results would require schema management, migration
tooling, and data retention policies that differ across jurisdictions
(LGPD vs. GDPR vs. GLBA). `lub` writes JSON files; the bank's
platform team decides where those files go. The one exception is the
optional SQLite **uncertainty ledger** (`lub.ledger`), which is
process-local and explicitly scoped to selective-prediction audit
— it is not a general-purpose benchmark store.
