#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# verify.sh — run ALL bridge-ui gates in order and summarize PASS/FAIL.
# Turns "did everything pass?" into one command instead of a re-derived prompt.
#
# Prerequisites (once):
#   cd 09_Projeto_GitHub/llm-uncertainty-banking
#   pip install -e ".[dev]" && pip install -r bridge-ui/backend/requirements.txt
#   ( cd bridge-ui/frontend && npm ci )
#
# Usage:
#   scripts/verify.sh                 # everything (frontend + backend + truncation)
#   scripts/verify.sh --frontend      # frontend only
#   scripts/verify.sh --backend       # backend only
#   scripts/verify.sh --quick         # skip the next build (faster)
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# Deterministic gates. This machine may have Ollama running, in which case
# server.py's _select_backend() would pick the REAL LLM at import time — making
# pytest (and even the import in mypy/lint-imports) non-deterministic and slow.
# Force the fake backend + an in-memory audit DB (so pytest never touches the
# persisted chain or hits a Windows file-lock). Override by exporting either var
# before running if you intentionally want a real-backend run.
export BRIDGE_USE_REAL_LLM="${BRIDGE_USE_REAL_LLM:-off}"
export BRIDGE_AUDIT_DB="${BRIDGE_AUDIT_DB:-:memory:}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"                    # scripts/ -> code repo root
FE="$REPO/bridge-ui/frontend"; BE="$REPO/bridge-ui/backend"

ONLY=""; QUICK=0
for a in "$@"; do case "$a" in --frontend) ONLY=fe;; --backend) ONLY=be;; --quick) QUICK=1;; esac; done

PASS=(); FAIL=()
gate(){ printf '\n=== %s ===\n' "$1"; if bash -c "$2"; then echo "✓ $1"; PASS+=("$1"); else echo "✗ $1"; FAIL+=("$1"); fi; }

if [ "$ONLY" != be ]; then
  gate "frontend · lint"  "cd '$FE' && npm run lint"
  gate "frontend · tsc"   "cd '$FE' && npx tsc --noEmit"
  [ "$QUICK" = 1 ] || gate "frontend · build" "cd '$FE' && npm run build"
fi
if [ "$ONLY" != fe ]; then
  gate "backend · ruff"         "cd '$BE' && ruff check ."
  gate "backend · mypy"         "cd '$BE' && mypy ."
  gate "backend · lint-imports" "cd '$BE/..' && python -c \"import sys;from importlinter.cli import lint_imports;sys.exit(lint_imports(config_filename='backend/pyproject.toml'))\""
  gate "backend · pytest"       "cd '$BE' && pytest -q"
fi

# Truncation gate — whenever the scanner exists (walks up to the git root).
TRUNC="$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null)/09_Projeto_GitHub/scripts/check_truncation.sh"
[ -f "$TRUNC" ] && gate "truncation guard" "bash '$TRUNC' --threshold 5"

printf '\n──────── SUMMARY ────────\n'
printf 'PASS: %d   FAIL: %d\n' "${#PASS[@]}" "${#FAIL[@]}"
if [ "${#FAIL[@]}" -gt 0 ]; then printf '  ✗ %s\n' "${FAIL[@]}"; echo "A GATE FAILED."; exit 1; fi
echo "all green ✓"
