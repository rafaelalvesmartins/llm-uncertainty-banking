#!/usr/bin/env bash
# =============================================================================
# setup_public_repo.sh — Phase 1 of EB-2 NIW go-to-market plan
#
# Creates a clean public copy of llm-uncertainty-banking, ready for push
# to github.com/rafaelmartinsalves/llm-uncertainty-banking.
#
# Usage:
#   bash scripts/setup_public_repo.sh [--dry-run] [--output-dir DIR]
#
# Flags:
#   --dry-run       Print what would be done without executing anything
#   --output-dir    Target directory (default: /tmp/lub-public-YYYYMMDD)
#
# Idempotent: safe to re-run. Overwrites the staging directory each time.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DRY_RUN=false
TODAY=$(date +%Y%m%d)
OUTPUT_DIR=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GITHUB_USER="rafaelmartinsalves"
REPO_NAME="llm-uncertainty-banking"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)  DRY_RUN=true; shift ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        -h|--help)
            head -17 "$0" | tail -15
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

[[ -z "$OUTPUT_DIR" ]] && OUTPUT_DIR="/tmp/lub-public-${TODAY}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
step()  { echo -e "\n\033[1;32m==>\033[0m $*"; }
dry()   { echo -e "  \033[1;90m[DRY-RUN]\033[0m would: $*"; }

# ---------------------------------------------------------------------------
# Step 0: Manual pre-requisites checklist
# ---------------------------------------------------------------------------
step "Step 0 — Manual pre-requisites (verify before proceeding)"
cat <<'CHECKLIST'

  Before running this script for real, confirm the following:

  [ ] 1. GPG key created and added to GitHub
         gpg --list-keys --keyid-format long
         → copy the key ID, then: git config --global user.signingkey <KEY_ID>

  [ ] 2. GitHub account ready: github.com/rafaelmartinsalves

  [ ] 3. UNICAMP acknowledgment email sent and response received
         (see 11_Legal_Acknowledgments/01_Email_Orientador_UNICAMP.md)

  [ ] 4. BRB compliance email sent and response received
         (see 11_Legal_Acknowledgments/02_Email_BRB_Compliance.md)

  [ ] 5. DESIGN_DECISIONS.md written by hand (Rafael's voice, no AI)

  [ ] 6. git user.name and user.email configured for the public identity
         git config --global user.name "Rafael Martins Alves"
         git config --global user.email "<your-public-email>"

  [ ] 7. gh CLI authenticated (for later push step)
         gh auth status

CHECKLIST

if $DRY_RUN; then
    info "Dry-run mode — printing plan only, no files will be created."
    echo ""
fi

# ---------------------------------------------------------------------------
# Exclusion patterns for rsync
# ---------------------------------------------------------------------------
EXCLUDES=(
    "__pycache__"
    ".git"
    ".mypy_cache"
    ".pytest_cache"
    "*.egg-info"
    ".venv"
    "venv"
    ".tox"
    ".nox"
    ".ruff_cache"
    ".coverage"
    ".coverage.*"
    "htmlcov"
    ".cache"
    "data/raw"
    "data/processed"
    ".DS_Store"
    "*.swp"
    "*.swo"
    ".idea"
    ".vscode"
    "build"
    "dist"
    ".eggs"
    "pip-wheel-metadata"
)

# Build rsync exclude flags
RSYNC_EXCLUDES=()
for pat in "${EXCLUDES[@]}"; do
    RSYNC_EXCLUDES+=(--exclude "$pat")
done

# ---------------------------------------------------------------------------
# Step 1: Create staging directory
# ---------------------------------------------------------------------------
step "Step 1 — Prepare staging directory: $OUTPUT_DIR"
if $DRY_RUN; then
    dry "rm -rf $OUTPUT_DIR && mkdir -p $OUTPUT_DIR"
else
    rm -rf "$OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR"
    info "Created $OUTPUT_DIR"
fi

# ---------------------------------------------------------------------------
# Step 2: Copy repo contents (excluding build artifacts)
# ---------------------------------------------------------------------------
step "Step 2 — Copy llm-uncertainty-banking contents"
if $DRY_RUN; then
    dry "rsync -a ${RSYNC_EXCLUDES[*]} $REPO_ROOT/ $OUTPUT_DIR/"
    dry "Excluded patterns: ${EXCLUDES[*]}"
else
    if command -v rsync &>/dev/null; then
        rsync -a "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "$OUTPUT_DIR/"
    else
        # Fallback: use cp + manual cleanup (Windows/Git Bash without rsync)
        info "rsync not found, falling back to cp + cleanup"
        cp -r "$REPO_ROOT/"* "$OUTPUT_DIR/" 2>/dev/null || true
        cp "$REPO_ROOT/.gitignore" "$OUTPUT_DIR/" 2>/dev/null || true
        # Remove excluded directories
        for pat in "${EXCLUDES[@]}"; do
            find "$OUTPUT_DIR" -name "$pat" -exec rm -rf {} + 2>/dev/null || true
        done
    fi
    info "Copied $(find "$OUTPUT_DIR" -type f | wc -l | tr -d ' ') files"
fi

# ---------------------------------------------------------------------------
# Step 3: Initialize git repo + .gitignore
# ---------------------------------------------------------------------------
step "Step 3 — Initialize fresh git repository"
if $DRY_RUN; then
    dry "cd $OUTPUT_DIR && git init"
    dry "Verify .gitignore exists (copied from source)"
else
    cd "$OUTPUT_DIR"
    git init
    # .gitignore should already be copied; verify
    if [[ ! -f .gitignore ]]; then
        warn ".gitignore not found — copying from source"
        cp "$REPO_ROOT/.gitignore" "$OUTPUT_DIR/.gitignore"
    fi
    info "Git initialized in $OUTPUT_DIR"
fi

# ---------------------------------------------------------------------------
# Step 4: Stage all files and create initial GPG-signed commit
# ---------------------------------------------------------------------------
step "Step 4 — Create initial commit (GPG-signed)"
if $DRY_RUN; then
    dry "git add -A"
    dry 'git commit --gpg-sign -m "Initial release: llm-uncertainty-banking v0.0.1 ..."'
else
    cd "$OUTPUT_DIR"
    git add -A
    git commit --gpg-sign -m "Initial release: llm-uncertainty-banking v0.0.1

Calibrated uncertainty quantification for LLMs in regulated banking.
22 estimators, OSCAL/SR 11-7 compliance reporting, production-ready guards.

Signed-off-by: Rafael Martins Alves <$(git config user.email)>"
    info "Initial commit created (GPG-signed)"
fi

# ---------------------------------------------------------------------------
# Step 5: Create v0.0.1 tag (signed)
# ---------------------------------------------------------------------------
step "Step 5 — Create v0.0.1 tag (GPG-signed)"
if $DRY_RUN; then
    dry 'git tag -s v0.0.1 -m "v0.0.1 — initial public release"'
else
    cd "$OUTPUT_DIR"
    git tag -s v0.0.1 -m "v0.0.1 — initial public release

First public version of llm-uncertainty-banking (lub).
See README.md for quickstart and CHANGELOG.md for details."
    info "Tag v0.0.1 created"
fi

# ---------------------------------------------------------------------------
# Step 6: Summary + next steps
# ---------------------------------------------------------------------------
step "Step 6 — Next steps (manual)"
cat <<NEXT

  The clean repo is staged at:
    $OUTPUT_DIR

  Remaining manual steps:

  1. CREATE the GitHub repo (do NOT initialize with README):
     gh repo create $GITHUB_USER/$REPO_NAME --public --description \\
       "Calibrated uncertainty quantification for LLMs in regulated banking" \\
       --homepage "https://github.com/$GITHUB_USER/$REPO_NAME"

  2. PUSH to GitHub:
     cd $OUTPUT_DIR
     git remote add origin git@github.com:$GITHUB_USER/$REPO_NAME.git
     git push -u origin main
     git push --tags

  3. VERIFY the push:
     gh repo view $GITHUB_USER/$REPO_NAME --web

  4. ENABLE GitHub Actions:
     - Go to repo Settings > Actions > General
     - Enable "Allow all actions and reusable workflows"
     - Verify ci.yml, docs.yml, release.yml run on next push

  5. CONFIGURE branch protection:
     gh api repos/$GITHUB_USER/$REPO_NAME/branches/main/protection \\
       -X PUT -f required_status_checks='{"strict":true,"contexts":["tests"]}' \\
       -f enforce_admins=true

  6. ARCHIVE on Wayback Machine immediately:
     curl -s "https://web.archive.org/save/https://github.com/$GITHUB_USER/$REPO_NAME" \\
       -o /dev/null -w "Wayback archive: %{http_code}\\n"

  7. SUBMIT to Papers With Code:
     - https://paperswithcode.com/
     - Link arXiv paper + repo once arXiv is submitted (Phase 2)

  8. PUBLISH to PyPI (verify install works):
     cd $OUTPUT_DIR
     pip install build twine
     python -m build
     twine upload dist/*
     pip install llm-uncertainty-banking  # verify

NEXT

if $DRY_RUN; then
    echo ""
    info "Dry-run complete. No files were created or modified."
fi

echo ""
info "Done. Phase 1 staging complete."
