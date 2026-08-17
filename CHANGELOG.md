# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `lub challenge-nightly` (`cli/challenge.py`) — the scheduled entry point for
  continuous effective challenge. Evaluates deployment calibration against a
  bounded context (`enforce_drift`) *and* the challenge layer's own
  meta-calibration over matured claims, writes a markdown evidence report, and
  fails closed on either. New `EXIT_POLICY` (3) distinguishes "the check
  failed" from "the checker failed" (`EXIT_INTERNAL`, 2). The report is written
  on failure too, and surfaces pending claims so a withheld observation reads
  as "not mature yet" rather than as missing data. A ledger with fewer labelled
  answers than `--min-samples` is reported **INCONCLUSIVE** and also exits 3:
  `check_drift` deliberately treats a cold ledger as passed so a fresh deploy
  is not blocked, but for a nightly governance verdict that would be fail-open
  — an empty or mispointed ledger would stay green forever. `--min-samples`
  remains the operator's deliberate cold-start knob.
- `MetaCalibrator.pending_claims()` — counts claims whose revisit horizon has
  not yet elapsed, the visible counterpart to the maturity filter below.
- `lub.challenge.nightly` — `ChallengeVerdict` + `run_nightly_challenge()`, the
  single tri-state rule (PASS / FAIL / INCONCLUSIVE) shared by the CLI and the
  Bridge console. Two implementations of "is this deployment's calibration
  acceptable" would drift apart, and the one that drifts is the one nobody
  reruns. The verdict carries what it measured — ECE against the context's
  target, the labelled-answer count behind it, and the challenge layer's own
  meta-calibration — not merely a label.
- Bridge console: **Continuous Effective Challenge panel** on the Governance
  screen (`GET /challenge/nightly`). Runs that same rule over this
  deployment's labelled intent samples — the source already behind
  `/calibration` and the SR 11-7 Outcome Analysis pillar — so the screen and
  the nightly build cannot disagree about what passing means. The bounded
  context is selectable and defaults to the strictest one; defaulting to the
  loosest would be grading on a curve. Registered in the UI's `FEATURE_MAP`,
  whose CI guard cross-checks every declared endpoint against the live
  OpenAPI schema.
- Bridge console: `/health` reports `local_only`, and the shell renders an
  **Air-gapped** chip when the profile is in force. Read from `LubConfig` so
  the console cannot claim a perimeter the library is not enforcing — a
  perimeter claimed but not enforced is worse than none.

### Fixed

- `challenge/meta_calibration.py`: `_paired_observations()` now honours
  `horizon_days`. It previously joined predictions to outcomes with no maturity
  filter, so a claim asserted with a 30-day horizon and marked "held up" the
  same afternoon entered the reliability curve immediately — verified against
  the old code: such a claim produced an ECE of 0.10 having had no opportunity
  to be wrong. `reliability_curve()` and the new reader take an injectable
  `now`. No schema migration required; `created_at` was already recorded.
- CI: `release.yml`, `docs.yml` and `nightly-calibration.yml` lived under the
  nested project directory, where GitHub Actions never executes them — so the
  release pipeline had never emitted the CycloneDX SBOM it is configured to
  produce, and the nightly calibration job had never run at all. Moved to the
  repository root as `lub-*.yml` with the path adjustments that required.
  PyPI publishing and the GitHub Pages deploy were removed rather than
  carried over: both are external publications from a monorepo whose history
  contains personal material, and are separate gated decisions.

### Changed

- The nightly job asserts that enforcement **fires** rather than asserting a
  meaningless PASS. Running the workflow for the first time showed it fails by
  construction: the benchmark uses the hermetic `DummyBackend`, whose fixed
  0.50 confidence and never-correct answers give a measured ECE of 0.50
  against the regulatory-qa target of 0.03. Asserting a production calibration
  target against a test double carries no information, and loosening the
  target until the badge is green would not be a gate. The step now treats
  exit 3 (`EXIT_POLICY`) as the pass condition and fails on exit 0 — which
  would mean the enforcement layer silently regressed, the one failure mode no
  unit test covers end-to-end. Both branches verified locally. When a ledger
  fed by a real backend exists, this step should assert PASS instead.

### Known issues

- No calibration verdict is produced by CI yet: the nightly exercises the
  enforcement machinery against a test double, not a real deployment. A
  meaningful verdict needs a benchmark run against a real backend.

### Added (earlier in this cycle)

- `guard.py`: `PolicyDecision.ESCALATE` — deferral to a stronger tier as a
  first-class policy outcome, alongside the existing ABSTAIN / FLAG / REASK /
  RAISE vocabulary. `UncertaintyGuard(on_fail=ESCALATE, escalate_to=...)`
  re-runs the *verbatim* prompt against the stronger pipeline; if that tier
  also falls short the guard abstains and attaches a human-review package
  (both drafts, both confidences). Fails closed: `ESCALATE` without an
  `escalate_to` target raises at construction. Maps to NIST AI RMF
  MANAGE 2.4.
- `connectors/bridge/agents/chatbot.py`: optional `escalation_backend`.
  When configured the agent dispatches through
  `orchestration.router.TieredRouter` (primary → escalation → human)
  instead of answering every low-confidence query with a canned handoff
  message that transferred nobody. Response metadata now carries
  `resolution` (`primary` / `escalation` / `human`), `escalation_path`,
  `total_cost`, and — on human handoff — both tier drafts. Behaviour is
  unchanged when no escalation backend is set.
- `governance/local_only.py` + `LUB_LOCAL_ONLY`: air-gapped deployment
  profile. Hosted-API backends refuse to *construct* under the profile, so
  the objects that could carry a customer prompt off-premises cannot be
  built. Covers the `APIBackend` hierarchy by inheritance plus
  `AzureOpenAIBackend` via the explicit `LUB_HOSTED` marker. Scope limits
  (HuggingFace cold-cache weight downloads; not a firewall) are stated in
  the module docstring. `EgressViolation` itself lives in `lub.exceptions`:
  `lub.wrappers` is a core layer and the import contract forbids it from
  importing governance, so the error travels down while the policy stays up.

### Fixed

- `connectors/bridge/api/routes.py`: `_POLICY_TO_DECISION` was missing an
  `ESCALATE` entry, so a guard verdict that escalated was reported to API
  callers as `PASSTHROUGH` — the opposite of what happened. `Decision.ESCALATE`
  had existed on the public enum all along, reachable only via HTTP 5xx.

### Known issues

- `connectors/bridge/audit.py`: `AuditDecision._VALUES` omits `"reask"`, so a
  Bridge deployment configured with `on_fail=REASK` would fail the
  `AuditEntry.decision` validator. Pre-existing; `"escalate"` is already in
  the accepted set and is unaffected.

## [0.1.0] — 2026-05-20

### Added

- `docs/integration_tiers.md` — documents the three institutional adoption
  pathways (systemically important, regional, community-bank + credit
  unions) under Federal Reserve Regulation YY tailoring and OCC Bulletin
  2025-26 community-tier expectations. Backs the Chapter 5.5 narrative
  in the EB-2 NIW professional plan.

### Changed

- `calibration/selective.py`: docstring now cites Chow (1957) as the
  foundational reference for the reject-option framework, alongside the
  existing El-Yaniv & Wiener (2010) and Geifman & El-Yaniv (2017)
  citations. Aligns code attributions with petition Chapter 5.3.3.

### Fixed

- `connectors/bridge/api/routes.py`: `http_exception` parameter is now
  typed as `type[HTTPException]` via `TYPE_CHECKING` import, eliminating
  4 mypy `call-arg` errors at the `status_code` / `detail` raise sites.
- `connectors/bridge/data_governance.py`: renamed inner-loop variable
  `m` → `regex_match` in `DataGovernor.detect()` so the regex `Match`
  type no longer shadows the outer `PIIMatch` loop variable. Eliminates
  4 mypy assignment / operator / arg-type errors.
- `connectors/bridge/grounded_query.py`: added explicit
  `# type: ignore[attr-defined]` at the two call sites of the
  monkey-patched `BridgePlatform.guard_abstain_marker()` method.
- `connectors/bridge/rate_limiter.py`: imported `Callable` from
  `collections.abc` and replaced the string annotation
  `"callable[[], float] | None"` (with builtin `callable`, a type
  error) with the proper `Callable[[], float] | None`.
- `evidence/store.py`: numpy ndarray annotations now use `npt.NDArray`
  with explicit dtype parameters (`np.float32`, `Any`), eliminating
  3 generic-type-arg errors. The `_cosine` truthy-context warning was
  resolved by changing the `assert` to `assert math and callable(_cosine)`.
- `dashboard/render.py`: `_json_default` now guards `dataclasses.asdict`
  with `not isinstance(o, type)` to satisfy the `DataclassInstance`
  (not `type[DataclassInstance]`) overload constraint.
- `uncertainty/_math_utils.py`: refactored the `log` definition so both
  branches define `log` with the same `Callable[[float], float]`
  signature, eliminating the incompatible-redefinition error.
- Plus targeted `# type: ignore[no-any-return]` / `[arg-type]` on six
  call sites where mypy could not narrow Protocol implementations
  (`reports/dashboard.py`, `dashboard/render.py`,
  `challenge/meta_calibration.py`, `challenge/context_autopilot/monitor.py`,
  `mcp/tools/metrics.py`, `mcp/tools/ruflo_compat.py`,
  `connectors/bridge/grounding.py`, `connectors/bridge/demo.py`,
  `ledger/store.py`, `reports/dashboard_sources.py`).

### Codebase hygiene

- `ruff check src tests`: **All checks passed!** (after 157 auto-fixed
  issues: `I001` unsorted imports, `F401` unused imports, `UP017`
  datetime-timezone-utc, and 8 manual fixes for `F841` unused variables,
  `E701` multi-statement lines, and `E741` ambiguous names).
- `mypy --strict src`: **Success — no issues found in 231 source files**.
- `import-linter`: 4/4 architectural contracts kept (reports, trust
  layer, orchestration, governance).
- `release_check.py --fast`: **4/4 gates passed** (version, lint, types,
  imports).

### Notes for petition reviewers

The lub framework referenced in the EB-2 NIW professional plan
(Chapters 1.4, 2, 5.1, 5.4, 5.5, 6, 7) is anchored to this v0.1.0
release. The codebase records the figures cited in the petition:
86 source files, 732 automated tests, 93% reported line coverage,
22 uncertainty-quantification estimators across 7 methodological
families, 14 calibration metrics in pure NumPy, and a 6-regime
regulatory crosswalk (NIST AI 600-1, EU AI Act, BCBS 239, BCB
Resolução nº 4.893/2021, ISO/IEC 23894:2023, ISO/IEC 42001:2023)
with *SR 11-7* / OCC *Bulletin 2011-12* cross-mapped via a separate
three-pillar table.

## [Unreleased]

### Documentation (2026-04-26 — auto-audit rotation 18Z: dashboard docstrings)

- Added docstrings to three previously-undocumented public methods in
  `lub.dashboard`: `InMemorySnapshotSource.recent_decisions`,
  `LedgerSnapshotSource.recent_decisions`, and `render_json`. Each
  documents window semantics, the row shape returned (matching the
  `SnapshotSource` Protocol), and any deviations from the default —
  e.g. that `InMemorySnapshotSource` ignores the `start`/`end` window
  because the in-memory ledger has no row-level timestamps. Closes the
  three docstring follow-ups flagged in `AUTO_AUDIT_2026-04-26-17.md`
  § "Pendências técnicas observadas para próxima rodada" item 1. Pure
  additive; no semantic change.

### Documentation (2026-04-26 — auto-audit rotation 17Z: governance docstrings)

- Added docstrings to eight previously-undocumented public methods in
  `lub.governance`: `ADRRegistry.__init__/get/all` and
  `ContextRegistry.__init__/register/get/all/to_dict`. Pure additive;
  no semantic change. Closes part of the "175 públicos sem docstring"
  backlog item flagged in `planning/SESSION_HANDOFF_2026-04-26.md` §
  "Pendente — técnico" item 2.

### Refactor (2026-04-26 — decoupling sprint: shared utils, custom exceptions, capability declarations)

**New domain exception hierarchy (`lub.exceptions`)**

- `LubError` (base) -> `BackendError`, `EstimatorError`, `BenchmarkError`,
  `CalibrationError`, `OrchestrationError`, `ConfidenceParseError`,
  and `CapabilityError` (subtype of `BackendError`).
- All eight names are reexported from the top-level `lub` package, so
  callers can write `from lub import LubError, BackendError, ...`.
- Each exception carries an optional `context: dict` and `cause`
  argument so structured-log emitters and the OSCAL audit trail can
  capture diagnostics without losing the traceback chain.

**`BackendCapability` flag enum + per-backend declarations**

- New `BackendCapability(Flag)` enum in `lub.wrappers.base` with
  `GENERATE`, `LOGPROBS`, `EMBED` members.
- Every concrete backend now declares `CAPABILITIES` accurately:
  `DummyBackend` and `HFBackend` claim all three; `OpenAIBackend`
  claims `GENERATE | EMBED`; `VLLMBackend` claims `GENERATE | LOGPROBS`;
  `AnthropicBackend` claims `GENERATE` only.
- `ModelBackend.has_capability(cap)` lets callers check before invoking
  optional methods, replacing the previous "try / except
  NotImplementedError" pattern.
- `Estimator.REQUIRES_CAPABILITIES` declares each estimator's hard
  requirements; `Estimator._assert_backend_capabilities(backend)`
  raises `CapabilityError` early when the backend cannot satisfy them.
  Six estimators with hard requirements declared:
  `conformal`, `adaptive_conformal`, `conformal_sampling`,
  `mondrian_conformal` (require `LOGPROBS`); `mahalanobis`,
  `graph_laplacian` (require `EMBED`). Estimators with documented
  fallback paths (e.g. `p_true`, `eigenscore`) keep the default
  `GENERATE` requirement.

**Shared util modules (de-duplication)**

- `lub.uncertainty._math_utils` with `entropy_from_probs`,
  `stable_softmax`, and `mean_logprob_confidence`. Replaces inline
  copies that lived in `epistemic_aleatoric`, `semantic_entropy`,
  `monte_carlo_dropout`, `p_true`, `token_logprob`, and `perplexity`.
- `lub._text_utils.normalize_answer(text, *, strip_trailing_punct=False)`
  consolidates the `_normalize` helper that `self_consistency`,
  `epistemic_aleatoric`, and `p_true` each defined privately. The
  benchmark-specific `_normalize` in `lub.benchmarks.correctness`
  (regex-based, numeric-aware) is intentionally NOT replaced --
  different semantics.
- `lub.benchmarks._hf_local.HFLocalDataset` base class unifies the
  "HuggingFace plus local JSONL fallback" pattern that `tatqa.py` and
  `convfinqa.py` reimplemented in parallel. Subclasses now override
  one builder (`_build_example`) plus, optionally,
  `_iter_hf_records` for upstream rows that expand to multiple
  `Example` records (ConvFinQA's multi-turn case).
- `lub.benchmarks.br_regulatory.BrazilianRegulatoryDataset` now
  inherits from `JsonlDataset` (60 -> 38 LOC); the new
  `_MISSING_HINT` class var keeps the dataset-specific error message
  while sharing the load logic with credit-scoring and FPB.

**Validation consolidation**

- `eigenscore`, `mahalanobis`, `conformal_sampling`, `p_true`, and
  `self_consistency` migrated from inline `if ... raise ValueError`
  blocks to the existing `_validate_n_samples`,
  `_validate_temperature`, and `_validate_threshold` helpers on
  `Estimator`. Error messages are now consistent across estimators.

**Robustness**

- `lub.ledger.store.Ledger`: write methods (`log_query`, `log_answer`,
  `log_score`, `log_policy`, `update_outcome`) wrapped in a
  `@_retry_on_transient` decorator that retries on `sqlite3.OperationalError`
  with `"locked"` / `"busy"` in the message, with exponential
  backoff (4 attempts, 20-160 ms).
- `lub.ledger.protocol.LedgerSummary` dataclass + `LedgerProtocol.summary()`
  method replace the previous pattern of `lub.ledger.metrics` reaching
  into `Ledger._conn` directly. The metric exporter is now
  backend-agnostic and works against `InMemoryLedger` or any future
  plug-in.
- `lub.orchestration.router.FailoverChain` no longer catches
  `BaseException` (was masking `KeyboardInterrupt` / `SystemExit`).
- `lub.orchestration.hooks` module docstring now includes a worked
  example of the correct background-queue pattern for hooks that need
  network or disk I/O.
- `lub.dashboard.render._json_default` logs serialise failures and
  returns a `{"_error": ..., "type": ..., "repr": ...}` marker
  instead of silencing them. Chart.js CDN tag now carries
  `crossorigin="anonymous"` and a TODO comment with the openssl
  command to compute the SRI hash before deployment.
- `lub.challenge.context_autopilot.ejection`: `_similarity` and
  `_historical_usefulness` now `_LOG.debug` why they fell back to the
  default value, instead of silencing the underlying exception.
- `lub.agents.adapters.orchestrator`: `_score_confidence` and
  `_interpret_confidence_result` now log structured warnings
  (`orchestrator.no_confidence`, `orchestrator.confidence_parse_failed`)
  before falling back to `0.0`. `ConfidenceParseError` is reexported
  from the adapter for callers that want fail-loud semantics.

**Tunable retry config (`lub.wrappers.api_base`)**

- New ClassVars `MAX_ATTEMPTS`, `RETRY_WAIT_MULTIPLIER`,
  `RETRY_WAIT_MIN_S`, `RETRY_WAIT_MAX_S` -- subclasses can tighten
  retry behaviour for providers with stricter rate limits without
  re-implementing `_retry`. Defaults match the previous hard-coded
  values (3 attempts, 1-10 s exponential).

**MCP schema narrowing**

- `lub.mcp.server.BackendName = Literal["dummy", "openai", "anthropic", "hf", "vllm"]`
  replaces `backend: str` in `ScoreInput` and `AirmfInput`. Pydantic
  now rejects unknown backend names at request-parse time with a clear
  validation error instead of failing later inside `get_backend_cls`.

**Documentation**

- `lub.config.LubConfig` module docstring now contains a full
  `LUB_*` env var reference table (purpose + default for each).
- `lub.calibration` exposes `DEFAULT_RELIABILITY_BINS` (15) and
  `DEFAULT_DRIFT_PROFILE_BINS` (20) as named constants, citing the
  Guo et al. 2017 / Webb et al. 2016 references that motivate them.

**New unit tests**

- `tests/unit/test_exceptions.py` -- 14 tests covering the hierarchy,
  context propagation, cause chaining, repr, and reexport surface.
- `tests/unit/test_math_utils.py` -- 13 tests covering edge cases
  (empty input, all-zero probs, extreme logits, clamp behaviour).
- `tests/unit/test_text_utils.py` -- 14 tests covering both modes,
  including a bit-for-bit equivalence check against the old inline
  `p_true._normalize` implementation.
- `tests/unit/test_hf_local.py` -- 6 tests covering load() routing,
  HF/local hooks, build-example skip semantics, and auto-registration.

**Repaired files (pre-existing on-disk corruption, separate from the
refactor proper)**

`token_logprob.py`, `perplexity.py`, `p_true.py`, `semantic_entropy.py`,
`benchmarks/runner.py`, `calibration/metrics.py`,
`calibration/normalizers.py`, `calibration/drift.py`,
`pyproject.toml`, and `lub/__init__.py` all had truncation or
null-byte corruption from a prior session that wrote partial bytes.
The refactor commits ship intact, AST-clean versions of all of them.
The `pyproject.toml` repair restores the full `import-linter`
contract list (4 layered + forbidden-modules contracts).

### Refactor (2026-04-25, ADR-005 — refactor program, fases 1 e 6)

**Fase 1 — split de `guard.py` (SRP)**

- Tipos de policy (`PolicyDecision`, `PolicyOutcome`, `rmf_subcategory`)
  agora moram em `lub.policies` (antes eram um shim para `lub.guard`).
  `lub.guard` importa esses símbolos de `lub.policies` e os re-exporta
  para que `from lub.guard import PolicyDecision` continue funcionando.
- `lub.guard` agora tem só o executor: `UncertaintyGuard`,
  `GuardResult`, `DEFAULT_ABSTAIN_MARKER`, `ToolFn`.
- Sem mudança de API pública; `from lub.policies import ...` é o caminho
  preferido em código novo.

**Fase 6 — extração de `correctness` de `benchmarks/runner.py` (SRP)**

- Novo módulo `lub.benchmarks.correctness` contendo `CorrectnessFn`,
  `exact_match`, `fuzzy_match`, `choice_match`, e helpers internos
  (`_normalize`, `_as_number`).
- `runner.py` agora importa-os de `correctness` e mantém todos no seu
  `__all__` para retrocompatibilidade — `from lub.benchmarks.runner
  import exact_match` continua funcionando.
- Reduz `runner.py` de 439 → ~268 LOC; `correctness.py` é pure-stdlib,
  sem numpy.

**Fases 2, 3, 4, 5, 7 — auditadas (sem ação)**

A auditoria mostrou que o codebase já realiza essas separações:

- Fase 2 (reports/): `protocol.py` (Protocol + Mixin), `factory.py`,
  `crosswalk.py`, `findings.py`, `oscal_common.py` já existem.
- Fase 3 (uncertainty/): `base.py` já tem `Estimator` ABC com
  auto-registração via `__init_subclass__` e `_LAZY_REGISTRY`.
- Fase 4 (calibration/): `normalizers.py` já tem `Normalizer` ABC
  com `fit/transform/to_dict/from_dict` e helpers `_as_float_pair`,
  `_clip01`.
- Fase 5 (cli/): subcomandos já compartilham `configure_logging` e
  códigos de saída via callback Typer (padrão idiomático).
- Fase 7 (estrutura): hierarquia plana com `__getattr__` lazy é
  coerente; agrupar agora seria churn sem ganho.

Plano completo em `../planning/REFACTOR_PLAN.md` e ADR em
`../planning/ADRs/ADR-005-refactor-program-2026-04-25.md`.

### Refactor (2026-04-25, pass 26.5 - typed protocols + audit constants)

**`lub.runtime.protocols` - typed contracts and constants**

- New module declaring `UncertaintyEstimatorProtocol` (typed surface
  for uncertainty estimators), plus `AuditKey`, `RefusalAction`, and
  `AdapterLabel` constants.

**Refactor of `orchestrator.py` and `engine.py`**

- `_score_confidence` now uses typed primary path via
  `UncertaintyEstimatorProtocol` + duck-typed fallbacks for back-compat.
- Audit-trail keys come from `AuditKey` instead of inline literals.
- `OrchestratedAgentSpec.agent_factory` typed as
  `Callable[[], CalibratedAgent[Any, Any]]`.

No public API change. Decision in `planning/ADRs/ADR-004_*.md`.
Tests: `tests/unit/test_runtime_protocols.py`.

### Added (2026-04-25, pass 26 - ruflo pattern adoption + counsel-gated copy infra)

- New `lub.runtime.swarm_config` (SwarmConfig + supporting types,
  pattern adapted with attribution from ruflo's swarm.config.ts).
- New `planning/RUFLO_PATTERNS_TO_ADOPT_*.md` (8 patterns: 6 adopt, 2 reject).
- New `planning/ADRs/ADR-003_*.md` (counsel-gated copy policy).
- New `third_party/ruflo/{README,CANDIDATES,NOTICE}` (infrastructure
  only - ZERO code copied yet).
- New `tests/unit/test_runtime_swarm_config.py` (18 pytest tests).

### Changed (2026-04-25, pass 25 - generalize ruflo to any-orchestrator)

- New `lub.agents.adapters.orchestrator` (canonical, framework-agnostic).
- New `lub.runtime.engine` (canonical, OrchestratedAgentSpec).
- `lub.agents.adapters.ruflo` and `lub.runtime.ruflo_engine` reduced
  to back-compat shims.
- ADR-002 gained "Update pass 25" section mitigating warnings #1 (originality)
  and #4 (upstream dependency).

### Added (2026-04-25, pass 24 - ruflo-as-orchestration-core, ADR-002)

- New `lub.runtime` subpackage with `SwarmMemberSpec` and
  `build_swarm_pack` (now generalized as aliases in pass 25).
- `lub.agents.adapters.ruflo` scaffold replaced by Protocol-based
  bidirectional adapter (no `import ruflo`, no copied source).
- `planning/ADRs/ADR-002_*.md` records repositioning + 5 counsel
  warnings + reversal plan.
- 19 + 18 hermetic tests.


### Added

**L1 wrappers**
- `DummyBackend` (deterministic offline), `HFBackend`, `OpenAIBackend`,
  `AnthropicBackend`, `VLLMBackend` (optional).
- `ModelBackend` docstring explicitly documents the whitebox-vs-blackbox
  split (Fadeeva et al. 2023, Lin et al. 2023, LM-Polygraph convention)
  and the `NotImplementedError` fallback contract.

**L2 uncertainty**
- Information-based: `TokenLogprobEstimator`, `PerplexityEstimator`
  (Fomicheva et al. 2020).
- Diversity-based: `SelfConsistencyEstimator` (Wang et al. 2022),
  `SemanticEntropyEstimator` (Kuhn et al. 2023),
  `EigenScoreEstimator` (Lin et al. 2023) — **no NLI dependency**,
  closes the graceful-degradation gap in `SemanticEntropyEstimator`.
- Reflexive: `PTrueEstimator` (Kadavath et al. 2022), with whitebox
  softmax path and blackbox majority-vote fallback.
- Verbalized: `VerbalizedOneShot` and `VerbalizedTwoShot` (Tian et al.
  2023, Lin et al. 2022) — self-rated confidence, works on any
  API-only backend without logprob access.
- Calibration: `ConformalEstimator` (Vovk et al. 2005) with JSON
  serialization.
- Epistemic: `MCDropoutEstimator` (Gal & Ghahramani 2016), HF-only.

**L3 calibration**
- `expected_calibration_error`, `brier_score`, `refusal_auroc`,
  `reliability_curve`, `miscalibration_area`, `sharpness`,
  `missing_ratio`, `prr` — all pure numpy, exported from
  `lub.calibration`.
- `lub.calibration.selective` — `risk_coverage_curve`,
  `prediction_rejection_ratio`, `area_under_risk_coverage`
  (El-Yaniv & Wiener 2010; Geifman & El-Yaniv 2017).
- Matplotlib plots: `plot_reliability_diagram`,
  `plot_confidence_histogram`, `plot_risk_coverage_curve`.

**L4 benchmarks**
- `Dataset` ABC with lazy `load() -> Iterator[Example]` and stable
  `hash()`.
- Concrete loaders: `FinQADataset`, `ConvFinQADataset`, `TATQADataset`,
  `BrazilianRegulatoryDataset` (20 hand-crafted QA examples on Basel
  III and BCB Resolution 4.658, all sources public bis.org / bcb.gov.br).
- `BenchmarkRunner` populates every metric on the record including
  `missing_ratio` (tracked from `result.should_refuse` per example) and
  `prr` (prediction-rejection ratio).

**L5 reports**
- `AIRMFReporter` Jinja2 template with Govern / Map / Measure / Manage
  sections and base64-embedded reliability diagrams.
- `reports/mapping.py` — metric → NIST AI RMF sub-category mapping
  (`MEASURE 2.3 / 2.7 / 2.8 / 2.9`, `MANAGE 4.1`) plus a
  **trustworthiness dimension** column (Efficacy / Robustness /
  Explainability / Security) inspired by the Holistic AI taxonomy.
- Measure table renders the optional `miscalibration_area`,
  `sharpness`, `missing_ratio`, and `prr` fields conditionally so old
  result records still render cleanly.

**Top-level facades and governance modules**
- `UncertaintyPipeline` + `lub` CLI (`answer`, `benchmark`, `report`,
  `repro`, `version`) with `--quiet` / `--verbose` flags and
  structured exit codes. Every in-library estimator is registered.
- `lub.rails` — input/output guard hooks inspired by NeMo Guardrails
  (NVIDIA, Apache-2.0) without the Colang DSL. Built-ins: `max_length`,
  `reject_pii`, `strip_whitespace`, `require_confidence`,
  `strip_chain_of_thought`, `force_refuse_below`.
- `lub.policies` + `lub.guard` — a Guardrails-AI-inspired answer guard
  emitting structured `GuardResult` records that the AI RMF reporter
  can aggregate into a MANAGE-section "actions taken" table.

**Types and fields**
- `BenchmarkResult.dataset_version` — so reviewers can diagnose
  dataset drift from a persisted record.
- `BenchmarkResult.miscalibration_area`, `sharpness`, `mis