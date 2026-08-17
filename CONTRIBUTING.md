# Contributing to llm-uncertainty-banking

Thank you for your interest in contributing.

## Development setup

```bash
git clone https://github.com/rafaelmartinsalves/llm-uncertainty-banking
cd llm-uncertainty-banking
uv venv
uv pip install -e ".[dev]"
pre-commit install
```

## Running checks

```bash
ruff check .
ruff format --check .
mypy src
pytest
lint-imports
```

All of the above must pass before a PR is merged.

### Pre-release one-shot

For an all-gates local pre-flight (mirrors CI, plus a version-consistency
check between `pyproject.toml` and `CITATION.cff` that CI can't easily do):

```bash
python scripts/release_check.py
```

Options:

```bash
python scripts/release_check.py --fast            # skip tests
python scripts/release_check.py --only version,lint
python scripts/release_check.py --cov-min 85      # override coverage gate
```

Exit code 0 = all green; 1 = at least one gate failed; 2 = invocation error.
Run this before tagging a release or bumping the version.

## Pull requests

- Open an issue first for non-trivial changes.
- Keep PRs focused — one logical change per PR.
- Add tests for new behavior.
- Update documentation when public API changes.
- Follow the 5-layer import contract described in the README.

## Commit style

Use short, imperative commit subjects (e.g. `add semantic entropy estimator`).

## Code of Conduct

By participating, you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).
