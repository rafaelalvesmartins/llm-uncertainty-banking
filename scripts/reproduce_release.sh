#!/usr/bin/env bash
# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# reproduce_release.sh — verify that a tagged release still produces its
# published benchmark numbers within a small tolerance.
#
# Usage:
#   ./scripts/reproduce_release.sh <git-tag>
#   ./scripts/reproduce_release.sh --help

set -euo pipefail

TOL_ACCURACY="${TOL_ACCURACY:-0.01}"
TOL_ECE="${TOL_ECE:-0.02}"

usage() {
    cat <<'EOF'
reproduce_release.sh — re-run a release and diff against committed results

Usage:
  scripts/reproduce_release.sh <git-tag>
  scripts/reproduce_release.sh --help

Environment:
  TOL_ACCURACY   allowable absolute accuracy delta (default: 0.01)
  TOL_ECE        allowable absolute ECE delta      (default: 0.02)

Exit 0 if every result file in the tag's benchmarks/results/ reproduces
within tolerance, 1 otherwise.
EOF
}

if [[ "$#" -eq 0 || "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    [[ "$#" -eq 0 ]] && exit 1 || exit 0
fi

if [[ "$#" -ne 1 ]]; then
    usage
    echo "error: expected exactly one argument (git tag)" >&2
    exit 1
fi

TAG="$1"

log() {
    printf 'level=info ts=%s msg=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

err() {
    printf 'level=error ts=%s msg=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

if ! command -v uv >/dev/null 2>&1; then
    err "uv not found on PATH; install from https://github.com/astral-sh/uv"
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    err "git not found on PATH"
    exit 1
fi

if ! git rev-parse "refs/tags/${TAG}" >/dev/null 2>&1; then
    err "tag not found: ${TAG}"
    exit 1
fi

WORK_ROOT="$(mktemp -d -t lub-repro-XXXXXX)"
trap 'rm -rf "${WORK_ROOT}"' EXIT
WORKTREE="${WORK_ROOT}/src"
VENV="${WORK_ROOT}/venv"

log "tag=${TAG} worktree=${WORKTREE}"
git worktree add --detach "${WORKTREE}" "refs/tags/${TAG}" >/dev/null

log "creating venv=${VENV}"
uv venv "${VENV}"
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

log "installing project at tag=${TAG}"
(cd "${WORKTREE}" && uv pip install -e .)

RESULTS_DIR="${WORKTREE}/benchmarks/results"
if [[ ! -d "${RESULTS_DIR}" ]]; then
    err "no benchmarks/results directory in tag ${TAG}"
    exit 1
fi

shopt -s nullglob
RESULT_FILES=("${RESULTS_DIR}"/*.json)
if [[ "${#RESULT_FILES[@]}" -eq 0 ]]; then
    err "no result files under ${RESULTS_DIR}"
    exit 1
fi

PASS=0
FAIL=0
printf '\n%-50s %-8s %s\n' "file" "status" "notes"
printf -- '---\n'
for f in "${RESULT_FILES[@]}"; do
    if (cd "${WORKTREE}" && lub repro "${f}" \
            --tolerance "${TOL_ACCURACY}" >/tmp/lub_repro.out 2>/tmp/lub_repro.err); then
        PASS=$((PASS + 1))
        printf '%-50s %-8s %s\n' "$(basename "${f}")" "PASS" "-"
    else
        FAIL=$((FAIL + 1))
        REASON="$(tail -1 /tmp/lub_repro.err 2>/dev/null || echo "see /tmp/lub_repro.err")"
        printf '%-50s %-8s %s\n' "$(basename "${f}")" "FAIL" "${REASON}"
    fi
done

log "summary pass=${PASS} fail=${FAIL} total=${#RESULT_FILES[@]}"
if [[ "${FAIL}" -gt 0 ]]; then
    exit 1
fi
exit 0
