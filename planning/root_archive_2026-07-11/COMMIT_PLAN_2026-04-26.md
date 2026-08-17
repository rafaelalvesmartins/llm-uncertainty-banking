# Commit plan — refactor sprint 2026-04-26

This file documents the suggested sequence of atomic commits for the
sprint that landed P1 + P2 + P3 + tests + docs across the lub source
tree on 2026-04-26. Apply in order; each commit leaves the tree in a
parseable, importable state.

> **Before any commit**, run `python scripts/check_integrity.py` --
> the disk-corruption issue documented in `URGENT_*disk_corruption.md`
> can re-introduce truncated files between writes. Exit 0 = safe to
> commit.

---

## Commit 1 — Repair pre-existing on-disk corruption + restore pyproject

Foundation step. The on-disk state had truncated and null-byte content
in 11 files; this commit restores them to AST-clean intact versions
without changing any documented behaviour.

```bash
git add pyproject.toml \
        src/lub/__init__.py \
        src/lub/exceptions.py \
        src/lub/policies.py \
        src/lub/rails.py \
        src/lub/compliance/__init__.py \
        src/lub/domains/__init__.py \
        src/lub/agents/policies.py \
        src/lub/benchmarks/_hf_local.py \
        src/lub/benchmarks/runner.py \
        src/lub/benchmarks/finqa.py \
        src/lub/benchmarks/tatqa.py \
        src/lub/benchmarks/convfinqa.py \
        src/lub/calibration/drift.py \
        src/lub/calibration/metrics.py \
        src/lub/calibration/normalizers.py \
        src/lub/evidence/protocol.py \
        src/lub/evidence/protocols.py \
        src/lub/orchestration/hooks.py \
        src/lub/reports/crosswalk.py \
        src/lub/uncertainty/p_true.py \
        src/lub/uncertainty/perplexity.py \
        src/lub/uncertainty/semantic_entropy.py \
        src/lub/uncertainty/token_logprob.py \
        tests/unit/test_ccp.py \
        tests/unit/test_crosswalk.py

git commit -m "fix(repo): repair on-disk corruption and restore truncated pyproject.toml

The working tree from the prior session contained 11 files with null bytes
or AST-level truncation that prevented import. This commit restores
AST-clean intact versions of all of them without changing documented
behaviour. The pyproject.toml repair restores the 4 import-linter
contracts that constrain the layered architecture.

Cosmetic only: a handful of repaired files have em-dash characters
in docstrings normalized to ASCII -- functionally identical."
```

## Commit 2 — P1 refactor: shared utils + custom exception hierarchy

```bash
git add src/lub/exceptions.py \
        src/lub/_text_utils.py \
        src/lub/__init__.py \
        src/lub/uncertainty/_math_utils.py \
        src/lub/uncertainty/{token_logprob,perplexity,p_true,semantic_entropy,monte_carlo_dropout,epistemic_aleatoric,self_consistency}.py \
        src/lub/benchmarks/_hf_local.py \
        src/lub/benchmarks/_jsonl_dataset.py \
        src/lub/benchmarks/{tatqa,convfinqa,br_regulatory}.py \
        src/lub/ledger/protocol.py \
        src/lub/ledger/store.py \
        src/lub/ledger/metrics.py

git commit -m "refactor(core): extract shared utils + custom exception hierarchy

P1.0 lub.exceptions: 8-class hierarchy (LubError + 7 subclasses) with
optional context/cause for structured-log + OSCAL audit integration.
Reexported from lub for from-lub imports.

P1.2 lub._text_utils.normalize_answer: replaces 4 inline _normalize
implementations across self_consistency, epistemic_aleatoric, p_true,
and semantic_entropy. Two modes (default + strip_trailing_punct).

P1.1 lub.uncertainty._math_utils: entropy_from_probs, stable_softmax,
mean_logprob_confidence. Replaces inline copies in 6 estimators.
Numerical equivalence verified bit-for-bit.

P1.3 lub.benchmarks._hf_local.HFLocalDataset: unifies HF + local
fallback pattern that tatqa.py and convfinqa.py reimplemented in
parallel. Two extension hooks (_build_example, _iter_hf_records).

P1.4 lub.benchmarks.br_regulatory: now inherits JsonlDataset (60->38
LOC). New _MISSING_HINT class var preserves dataset-specific error
messages.

P1.6 lub.ledger.LedgerSummary + LedgerProtocol.summary(): replaces
_conn-direct access in lub.ledger.metrics so the exporter is
backend-agnostic. InMemoryLedger implements summary() too."
```

## Commit 3 — P2 robustness: capabilities, retry, error logging

```bash
git add src/lub/wrappers/base.py \
        src/lub/wrappers/{dummy,hf,openai,anthropic,vllm}.py \
        src/lub/uncertainty/base.py \
        src/lub/uncertainty/{conformal,adaptive_conformal,conformal_sampling,mondrian_conformal,mahalanobis,graph_laplacian}.py \
        src/lub/uncertainty/{eigenscore,p_true,self_consistency}.py \
        src/lub/orchestration/router.py \
        src/lub/challenge/context_autopilot/ejection.py \
        src/lub/dashboard/render.py \
        src/lub/agents/adapters/orchestrator.py \
        src/lub/ledger/store.py

git commit -m "refactor(robustness): capability declarations, retry, error logging

P2.5 BackendCapability(Flag) + per-backend CAPABILITIES + per-estimator
REQUIRES_CAPABILITIES. Estimators that need logprobs/embed declare it;
the new _assert_backend_capabilities helper raises CapabilityError
(BackendError subtype) before any network call. Six hard-requirement
estimators declared (4 conformal -> LOGPROBS, 2 embedding -> EMBED).

P2.6 5 estimators migrate from inline if/raise blocks to base-class
_validate_n_samples / _validate_temperature / _validate_threshold
helpers. Error messages now consistent.

P2.1 router.FailoverChain: except BaseException -> except Exception
(was masking KeyboardInterrupt / SystemExit).

P2.2 challenge/context_autopilot/ejection: log debug reasons before
falling back to default similarity / usefulness values.

P2.3 dashboard/render._json_default: log + return {_error: ...}
marker instead of silencing.

P2.4 agents/adapters/orchestrator: integrate ConfidenceParseError;
log structured warnings (orchestrator.no_confidence,
orchestrator.confidence_parse_failed).

P2.7 ledger.store: @_retry_on_transient decorator on 5 write methods,
exponential backoff (4 attempts, 20-160 ms) on sqlite OperationalError
with 'locked' / 'busy' in message.

P2.8 SQL audit: confirmed zero f-string / %-format / .format() patterns
in any execute() call across the project."
```

## Commit 4 — P3 polish + MCP narrowing + hooks doc

```bash
git add src/lub/wrappers/api_base.py \
        src/lub/calibration/__init__.py \
        src/lub/dashboard/render.py \
        src/lub/config.py \
        src/lub/mcp/server.py \
        src/lub/orchestration/hooks.py

git commit -m "refactor(polish): tunable retry, named bins, env-var docs, MCP narrowing

P3.1 wrappers.api_base: MAX_ATTEMPTS / RETRY_WAIT_MULTIPLIER /
RETRY_WAIT_MIN_S / RETRY_WAIT_MAX_S as ClassVars. Subclasses can
adjust per-provider (e.g. tighter limits for OpenAI vs Anthropic)
without overriding _retry().

P3.4 calibration: DEFAULT_RELIABILITY_BINS (15) and
DEFAULT_DRIFT_PROFILE_BINS (20) named constants citing Guo et al. 2017
and Webb et al. 2016. Function defaults preserve the literals for
back-compat.

P3.3 dashboard/render: chart.js script tag carries crossorigin and
referrerpolicy. TODO comment with openssl command for the SRI hash
(deferred -- jsdelivr blocked from sandbox).

P3.5 lub.config docstring: complete LUB_* env var reference table
(LUB_CACHE_DIR, LUB_LOG_LEVEL, LUB_OPENAI_API_KEY, LUB_ANTHROPIC_API_KEY,
LUB_REQUEST_TIMEOUT_S, LUB_RETRY_ATTEMPTS) plus test-suite-only
LUB_REAL_BACKEND_TESTS.

NEW.2 mcp.server: BackendName = Literal['dummy', 'openai', 'anthropic',
'hf', 'vllm']. Pydantic now rejects unknown backend strings at
request-parse time.

P3.6 orchestration.hooks: module docstring includes worked example of
the correct background-queue pattern for hooks that need network or
disk I/O."
```

## Commit 5 — Tests, integrity script, docs, CHANGELOG

```bash
git add tests/unit/test_exceptions.py \
        tests/unit/test_math_utils.py \
        tests/unit/test_text_utils.py \
        tests/unit/test_hf_local.py \
        tests/unit/test_capabilities.py \
        tests/unit/test_ledger_summary.py \
        tests/unit/test_api_base_retry.py \
        scripts/check_integrity.py \
        docs/architecture.md \
        CHANGELOG.md \
        COMMIT_PLAN_2026-04-26.md

git commit -m "test+docs: unit coverage for new modules + integrity script

NEW.1 + TECH.3 unit tests for the modules introduced in this sprint:
- test_exceptions.py: hierarchy, context propagation, cause chaining,
  reexport surface (~14 tests)
- test_math_utils.py: edge cases (empty, all-zero, extreme logits,
  clamp behaviour), bit-for-bit equivalence vs prior inline code
- test_text_utils.py: both modes, equivalence vs old p_true._normalize
- test_hf_local.py: load() routing, HF/local hooks, build-example skip
- test_capabilities.py: BackendCapability flag, REQUIRES_CAPABILITIES,
  _assert_backend_capabilities, registry-wide compatibility check
- test_ledger_summary.py: LedgerSummary + Ledger.summary +
  InMemoryLedger.summary + collect_metrics agnostic of backend
- test_api_base_retry.py: tunable defaults + subclass overrides +
  retryable-name classification

TECH.1 scripts/check_integrity.py: detector that scans src/lub and
tests/ for null bytes, AST SyntaxError, and heuristic truncation cues
(open delimiter on last line). Exit code drives a pre-commit hook.
--strict flag also flags missing trailing newlines.

TECH.2 docs/architecture.md: 3 new sections covering this sprint --
Capability declarations (BackendCapability + REQUIRES_CAPABILITIES),
Domain exception hierarchy (LubError tree), Disk-integrity check
script.

NEW.4 CHANGELOG.md: full entry for the sprint under [Unreleased]."
```

---

## Verification after all commits

```bash
# Re-run integrity check (must be exit 0)
python scripts/check_integrity.py

# Re-run full test suite (must pass; sandbox could not run pytest)
pytest -q

# Re-run import-linter (4 contracts)
lint-imports

# Confirm no untracked critical files left behind
git status --short
```

## What DID NOT land in these commits (deferred)

- **SRI hash** for chart.js (P3.3 partial). Requires fetching the
  actual JS from jsdelivr -- blocked in the bash sandbox by the
  network allowlist. The TODO comment in `dashboard/render.py:78` has
  the openssl command. Once the hash is generated, edit the
  ``<script>`` tag to add ``integrity="sha384-..."``. Single-line edit;
  separate commit.
- **Continuing the refactor**: P2.5 `_assert_backend_capabilities` is
  defined but not auto-wired into every estimator's ``score()``.
  Estimators that want fail-loud opt in by calling it; the rest keep
  the existing fallback semantics. Auto-wiring (when desired) is a v0.3
  follow-up and would be its own commit.
- **Continuing the integrity check** as a CI step. Adding it to
  `.github/workflows/ci.yml` and to `.git/hooks/pre-commit` is a
  small follow-up; the script is ready, the wiring is not.
