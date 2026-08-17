# --------------------------------------------------------------------------
# lub — CI / development image
# --------------------------------------------------------------------------
# This Dockerfile builds a minimal image for running the test suite,
# type-checking, and linting.  It does NOT ship a service — lub is a
# library.  See reference/ for a Docker Compose example of how a bank
# would integrate lub into its own API gateway.
# --------------------------------------------------------------------------

FROM python:3.12-slim AS base

WORKDIR /app

# System deps for numpy/scipy wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/
COPY tests/ tests/

RUN pip install --no-cache-dir -e ".[dev]"

# --------------------------------------------------------------------------
# test stage — default: run the full suite
# --------------------------------------------------------------------------
FROM base AS test

CMD ["python", "-m", "pytest", "-q", "--tb=short"]

# --------------------------------------------------------------------------
# lint stage — mypy + ruff + import-linter
# --------------------------------------------------------------------------
FROM base AS lint

CMD ["sh", "-c", \
     "python -m mypy src/lub --strict && \
      python -m ruff check src/lub tests && \
      python -c 'from importlinter import cli; cli.lint_imports_command()'"]
