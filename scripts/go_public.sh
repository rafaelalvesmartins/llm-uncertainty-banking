#!/usr/bin/env bash
# go_public.sh — orchestrator for the Phase 1 public-push runbook.
#
# Runs in --dry-run mode by default. Pass --execute to actually perform
# destructive / publishing steps (clean-history rebase, GitHub push,
# PyPI upload, Wayback submit, OpenTimestamps stamp).
#
# Reference runbook: planning/GO_PUBLIC_RUNBOOK_2026-04-28.md
# This script assumes it is run from the repo root of the PUBLIC fork
# directory (~/code/lub-public or equivalent), NOT the private repo.

set -euo pipefail

DRY_RUN=true
SKIP_PREFLIGHT=false
SKIP_TESTS=false
REPO_SLUG="rafaelmartinsalves/llm-uncertainty-banking"
VERSION="0.0.1"

log() { printf "\033[1;34m[go_public]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[warn]\033[0m %s\n" "$*" >&2; }
fail() { printf "\033[1;31m[fail]\033[0m %s\n" "$*" >&2; exit 1; }
run() {
  if $DRY_RUN; then
    printf "\033[0;90m[dry-run]\033[0m %s\n" "$*"
  else
    printf "\033[1;32m[exec]\033[0m %s\n" "$*"
    eval "$@"
  fi
}

usage() {
  cat <<EOF
Usage: $0 [--execute] [--skip-preflight] [--skip-tests]

Steps (each runs in dry-run unless --execute is passed):
  1. Pre-flight audits (BRB leakage, dataset URLs, licenses)
  2. Test + coverage snapshot
  3. Build + twine check
  4. Clean-history rebase (manual confirmation prompt in --execute mode)
  5. Create GitHub repo (manual step — script reminds but does not call API)
  6. git push origin main + v0.0.1 tag
  7. PyPI upload
  8. Wayback submit
  9. OpenTimestamps stamp
 10. Save Month-0 evidence snapshot
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) DRY_RUN=false; shift ;;
    --skip-preflight) SKIP_PREFLIGHT=true; shift ;;
    --skip-tests) SKIP_TESTS=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown arg: $1" ;;
  esac
done

if $DRY_RUN; then
  log "DRY RUN MODE. Pass --execute to actually perform steps."
else
  warn "EXECUTE MODE. Steps are destructive / publishing. Ctrl+C now if unsure."
  sleep 3
fi

# ------------------------------------------------------------------
# Step 1: pre-flight audits
# ------------------------------------------------------------------
if ! $SKIP_PREFLIGHT; then
  log "Step 1/10: pre-flight audits"

  mkdir -p _scratch

  log "  1a: BRB leakage grep"
  run "git log --all -p | grep -iE 'brb|banco[ ._-]?de[ ._-]?bras[íi]lia|bancobrb' > _scratch/hits_brb.txt || true"
  run "git grep -iE 'banco.{0,3}de.{0,3}bras[íi]lia' || true"
  run "git grep -iE 'bradesco|itau|santander' || true"
  run "git grep -iE '@brb\\.|brb\\.com\\.br|internal|proprietary|confidential' || true"

  log "  1b: dataset source_url audit"
  if [[ -f scripts/verify_source_urls.py ]]; then
    run "uv run python scripts/verify_source_urls.py \
      --dataset src/lub/benchmarks/data/br_regulatory.jsonl \
      --allowed-domains bis.org bcb.gov.br gov.br federalreserve.gov occ.gov fdic.gov \
      --out _scratch/url_audit.json"
  else
    warn "scripts/verify_source_urls.py not found — write it before executing."
  fi

  log "  1c: license-header check"
  if [[ -f scripts/check_license_headers.py ]]; then
    run "uv run python scripts/check_license_headers.py --root src/ --fail-on-missing"
  else
    warn "scripts/check_license_headers.py not found — write it before executing."
  fi

  log "  1d: dependency license audit"
  run "uv run pip-licenses --format=markdown --output-file _scratch/deps_licenses.md"
fi

# ------------------------------------------------------------------
# Step 2: tests + coverage
# ------------------------------------------------------------------
if ! $SKIP_TESTS; then
  log "Step 2/10: tests + coverage snapshot"
  run "uv run pytest --cov=lub --cov-report=term-missing --cov-report=xml \
    | tee _scratch/test_output.txt"
fi

# ------------------------------------------------------------------
# Step 3: build + twine check (dry upload)
# ------------------------------------------------------------------
log "Step 3/10: build + twine check"
run "rm -rf dist/"
run "uv run python -m build"
run "uv run twine check dist/*"

# ------------------------------------------------------------------
# Step 4: clean-history rebase
# ------------------------------------------------------------------
log "Step 4/10: clean-history rebase"
warn "This step is not scriptable — follow Step A in GO_PUBLIC_RUNBOOK_2026-04-28.md manually."
warn "Abort here if rebase is not already done."
if ! $DRY_RUN; then
  read -r -p "Has the clean-history rebase been completed manually? (y/N) " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || fail "clean-history rebase not done"
fi

# ------------------------------------------------------------------
# Step 5: GitHub repo creation (reminder only)
# ------------------------------------------------------------------
log "Step 5/10: GitHub repo creation (manual)"
warn "Create https://github.com/${REPO_SLUG} manually via the web UI."
warn "Confirm: Public visibility, correct topics, 2FA active on account."
if ! $DRY_RUN; then
  read -r -p "GitHub repo created at ${REPO_SLUG}? (y/N) " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || fail "repo not created"
fi

# ------------------------------------------------------------------
# Step 6: git push + tag
# ------------------------------------------------------------------
log "Step 6/10: git push + v${VERSION} tag"
run "git remote -v || git remote add origin git@github.com:${REPO_SLUG}.git"
run "git push -u origin main"
run "git tag -s v${VERSION} -m 'v${VERSION} — initial public release'"
run "git push origin v${VERSION}"

# ------------------------------------------------------------------
# Step 7: PyPI upload
# ------------------------------------------------------------------
log "Step 7/10: PyPI upload"
run "uv run twine upload dist/*"
warn "Verify install: pip install llm-uncertainty-banking==${VERSION}"

# ------------------------------------------------------------------
# Step 8: Wayback submission
# ------------------------------------------------------------------
log "Step 8/10: Wayback Machine submission"
for url in \
  "https://github.com/${REPO_SLUG}" \
  "https://github.com/${REPO_SLUG}/tree/main/docs" \
  "https://pypi.org/project/llm-uncertainty-banking/" ; do
  run "curl -s -o /dev/null -w '%{http_code}\\n' 'https://web.archive.org/save/${url}'"
done

# ------------------------------------------------------------------
# Step 9: OpenTimestamps
# ------------------------------------------------------------------
log "Step 9/10: OpenTimestamps stamp"
run "git rev-parse HEAD > _scratch/head_sha.txt"
run "ots stamp _scratch/head_sha.txt"
warn "Commit _scratch/head_sha.txt.ots to 02_Evidencias_Profissionais/ots/ in the evidence repo."

# ------------------------------------------------------------------
# Step 10: Month-0 evidence snapshot
# ------------------------------------------------------------------
log "Step 10/10: Month-0 evidence snapshot"
if [[ -f scripts/capture_evidence.py ]]; then
  run "uv run python scripts/capture_evidence.py --label month-0 --out _scratch/evidence_month0.json"
else
  warn "scripts/capture_evidence.py not found — see Prompt 10 / P10 deliverable."
fi

log "DONE. Next: Phase 2 — arXiv submission (see planning/19_Business_Launch_Plan_2026-04-21.md §Phase 2)."
