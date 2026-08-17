---
name: lub-dev
description: Orient work inside the `llm-uncertainty-banking` (import name `lub`) flagship repo — enforced dev gates (ruff, mypy --strict, import-linter layers, pytest with 80% coverage), the layered architecture, and the local pre-release check. Invoke when the user asks to "work on lub", "add an estimator", "fix a bug in lub", "prepare a release", "cut a version", "run the pre-flight checks", or any task that modifies code under `06_Projeto_GitHub/llm-uncertainty-banking/`.
---

# lub-dev — Working inside the flagship repo

## 1. Purpose

The flagship Python library `llm-uncertainty-banking` (import: `lub`) has
strict invariants that CI enforces. Before this skill existed, those
invariants lived only in `README.md`, `pyproject.toml`, and CI config — so
AI-assisted changes routinely tripped them and had to be fixed in a second
pass. This skill pulls the invariants up front and gives Claude a single
local pre-flight command to verify before anything gets pushed.

Scope:

- Knows the layered architecture and what may import what
- Knows the CI gates and the numeric thresholds (coverage, etc.)
- Provides `scripts/release_check.py` as the local equivalent of CI

Out of scope:

- Generating new estimators or benchmarks from scratch (those are judgement
  calls and shouldn't be templated)
- Publishing to PyPI — `scripts/reproduce_release.sh` and the GitHub
  Actions release workflow handle that
- Writing arXiv submission materials (separate scripts in `scripts/`)

## 2. When to invoke

- Any code change under `06_Projeto_GitHub/llm-uncertainty-banking/`
- Before opening a PR or pushing to `main`
- Before cutting a release or bumping the version
- When adding a new module and unsure which layer it belongs in

Do NOT invoke for:

- Petition-side work (Sections, exhibits, drafts) — wrong codebase
- Pure reading / Q&A about the library — just use `README.md`

## 3. Enforced invariants

These are gates CI fails on. Don't push code that breaks them.

| Gate | Tool | Threshold / rule |
|---|---|---|
| Lint | `ruff check src tests` | zero violations |
| Type-check | `mypy src` | `strict = true` — no implicit `Any`, all returns typed |
| Import layers | `lint-imports` | see §4 |
| Tests | `pytest -q --cov=lub --cov-fail-under=80` | 80% branch coverage minimum |
| Python version | `pyproject.toml` / CI matrix | 3.11 and 3.12 |

## 4. Layered architecture (import-linter contract)

Higher layers may import lower, never the reverse. Declared in
`pyproject.toml` under `[[tool.importlinter.contracts]]`.

```
lub.reports       (top — SR 11-7, NIST AI RMF, OSCAL generators)
  ↑
lub.benchmarks    (German Credit, financial sentiment, runners)
  ↑
lub.calibration   (temperature, quantile, UCC/AUUCC curves)
  ↑
lub.uncertainty   (22 estimators: p_true, perplexity, SAR, etc.)
  ↑
lub.wrappers      (bottom — backend ABCs, DummyBackend)
```

Orthogonal layers (not part of the linear stack): `lub.guard`,
`lub.policies`, `lub.cli`. They sit outside the layered contract.

If `lint-imports` fails, the usual cause is a new utility that reached
backwards into a lower layer. Either move the utility up, or move the
shared helper into a common module below all current call sites.

## 5. Local pre-flight: `scripts/release_check.py`

Runs the same gates CI runs, plus local-only checks CI can't do (version
string consistency, etc.).

Full pre-flight (mirrors CI):

```
python scripts/release_check.py
```

Fast mode — skip the long test suite, keep lint / types / imports / version:

```
python scripts/release_check.py --fast
```

Only a subset (comma-separated from: `version`, `lint`, `types`, `imports`, `tests`):

```
python scripts/release_check.py --only version,lint
```

Override coverage threshold (default 80 matches CI):

```
python scripts/release_check.py --cov-min 85
```

### Exit codes

- `0` — all selected gates passed
- `1` — at least one gate failed
- `2` — invocation error (unknown `--only` value, missing pyproject.toml)

### The `version` gate specifically

Checks that `pyproject.toml`'s `version = "..."` matches
`CITATION.cff`'s `version:`. This catches a common drift: bumping one but
not the other. Both must match before tagging a release.

## 6. Release workflow checklist

Roughly, the order for cutting a release:

1. Implementation / tests landed on `main`
2. Bump `version` in `pyproject.toml`
3. Bump matching `version:` in `CITATION.cff`
4. Update `CHANGELOG.md` (if present) — headline entry for the new version
5. `python scripts/release_check.py` — expect `5/5 gates passed`
6. Commit, tag `vX.Y.Z`, push tag — `.github/workflows/release.yml` handles
   the rest (build, PyPI upload if configured)

Step 5 is what this skill exists to make reliably easy.

## 7. Common failures and their fixes

- **`ruff check` failure.** Almost always fixable with `ruff check --fix
  src tests`. Review the diff before committing.
- **`mypy` strict failure on a new function.** Add explicit type hints for
  every argument and the return. `from __future__ import annotations` is
  already set; use PEP 604 `X | None` freely.
- **`lint-imports` failure.** A lower-layer module imported a higher one.
  Do not add `# type: ignore` or reshuffle the contract — move the code.
- **Coverage fell below 80%.** Either add tests for the new branch, or
  prove the uncovered path is unreachable and mark it with `# pragma: no
  cover` (sparingly).
- **Version mismatch between `pyproject.toml` and `CITATION.cff`.** Update
  whichever is wrong so they agree. Known live issue at skill creation
  time: `pyproject=0.0.1` vs `CITATION.cff=0.1.0` — resolve before the
  first release.

## 8. Dependencies (to run the pre-flight locally)

Install dev extras once:

```
pip install -e ".[dev]"
```

That pulls `ruff`, `mypy`, `import-linter`, `pytest`, `pytest-cov`.
`scripts/release_check.py` uses only stdlib (subprocess, argparse, re).

## 9. What this skill does NOT do

- Does not edit code — it tells Claude what the contracts are and how to
  check them
- Does not run network operations — no PyPI, no GitHub API, no arXiv
- Does not replace CI; think of it as the pre-commit safety net
- Does not bump versions automatically — that's a deliberate human decision

## 10. Extending

If a new gate shows up in CI (e.g., bandit, pip-audit, a typed-contract
tool), add it to `GATES_IN_ORDER` in `release_check.py` with a `check_<name>`
runner, then update §3 and §4 of this file. Keep `fast` as the escape
hatch for long-running gates.
