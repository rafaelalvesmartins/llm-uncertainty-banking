#!/usr/bin/env bash
# Refresh the refactor baseline. Run from project root with Python 3.11+ in env.
# Usage:  bash planning/baselines/refresh_baselines.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
OUT="planning/baselines/run_${STAMP}"
mkdir -p "$OUT"

echo "[1/5] ruff..."
( ruff check src tests 2>&1 | tee "$OUT/ruff.txt" ) || true

echo "[2/5] mypy..."
( mypy src --strict 2>&1 | tee "$OUT/mypy.txt" ) || true

echo "[3/5] import-linter..."
( lint-imports 2>&1 | tee "$OUT/import_linter.txt" ) || true

echo "[4/5] pytest (full + coverage)..."
( pytest -q --cov=lub --cov-report=term --cov-report=xml:"$OUT/coverage.xml" 2>&1 | tee "$OUT/pytest.txt" ) || true

echo "[5/5] pytest selectors..."
{
  echo "=== unit ==="
  pytest -q -m "not integration" 2>&1 | tail -5
  echo "=== integration ==="
  pytest -q -m "integration and not real_backend" 2>&1 | tail -5
} | tee "$OUT/selectors.txt" || true

# Update LATEST.md pointer
{
  echo "# Latest baseline"
  echo
  echo "Run: $STAMP"
  echo "Path: planning/baselines/run_${STAMP}/"
  echo
  echo "Summary:"
  echo
  echo "- ruff: $(grep -E 'All checks passed|error' "$OUT/ruff.txt" | head -1)"
  echo "- mypy: $(grep -E 'Success|Found .* errors?' "$OUT/mypy.txt" | head -1)"
  echo "- import-linter: $(grep -E 'Contracts:|Kept|Broken' "$OUT/import_linter.txt" | head -3 | tr '\n' ' ')"
  echo "- pytest: $(grep -E 'passed|failed' "$OUT/pytest.txt" | tail -1)"
} > planning/baselines/LATEST.md

echo
echo "Done. Baseline written to $OUT and pointer updated in planning/baselines/LATEST.md"
