#!/bin/bash
# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0
#
# Package complete arXiv submission: PDF + source code + CITATION.cff + README.
#
# Output: arxiv_submission.tar.gz  (in project root)
#
# Usage:
#   bash scripts/package_arxiv_submission.sh
#   bash scripts/package_arxiv_submission.sh --skip-pdf   # if PDF already built

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

STAGING_DIR="$PROJECT_ROOT/.arxiv_staging"
ARCHIVE="$PROJECT_ROOT/arxiv_submission.tar.gz"
SKIP_PDF=false

if [[ "${1:-}" == "--skip-pdf" ]]; then
    SKIP_PDF=true
fi

echo "════════════════════════════════════════════════════════════════"
echo "     Packaging arXiv submission for llm-uncertainty-banking"
echo "════════════════════════════════════════════════════════════════"
echo

# ── Clean previous staging ────────────────────────────────────────
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

# ── 1. Build PDF (unless --skip-pdf) ─────────────────────────────
PDF="$PROJECT_ROOT/docs/tech-report/draft.pdf"

if [[ "$SKIP_PDF" == false ]]; then
    if command -v pandoc &>/dev/null; then
        echo "[1/6] Building PDF via build_arxiv_pdf.sh ..."
        bash "$PROJECT_ROOT/scripts/build_arxiv_pdf.sh"
    else
        echo "[1/6] WARNING: pandoc not installed — skipping PDF build."
        echo "       Install pandoc and run: bash scripts/build_arxiv_pdf.sh"
        echo "       Or build manually and place at: docs/tech-report/draft.pdf"
    fi
else
    echo "[1/6] Skipping PDF build (--skip-pdf)."
fi

if [[ -f "$PDF" ]]; then
    cp "$PDF" "$STAGING_DIR/draft.pdf"
    echo "      PDF: $(du -h "$PDF" | cut -f1)"
else
    echo "      WARNING: No PDF found at $PDF"
    echo "      The submission package will be created without the PDF."
    echo "      You must add draft.pdf before uploading to arXiv."
fi

# ── 2. Manuscript source ──────────────────────────────────────────
echo "[2/6] Copying manuscript source ..."
mkdir -p "$STAGING_DIR/docs/tech-report"
cp "$PROJECT_ROOT/docs/tech-report/draft.md" "$STAGING_DIR/docs/tech-report/"

# Copy figures if they exist
if [[ -d "$PROJECT_ROOT/docs/figures" ]]; then
    cp -r "$PROJECT_ROOT/docs/figures" "$STAGING_DIR/docs/"
    echo "      Figures: $(ls "$PROJECT_ROOT/docs/figures/"*.png 2>/dev/null | wc -l) PNGs"
fi

# Copy artifacts (reliability diagrams, etc.) if they exist
if [[ -d "$PROJECT_ROOT/docs/tech-report/artifacts" ]]; then
    cp -r "$PROJECT_ROOT/docs/tech-report/artifacts" "$STAGING_DIR/docs/tech-report/"
    echo "      Artifacts: $(ls "$PROJECT_ROOT/docs/tech-report/artifacts/"*.png 2>/dev/null | wc -l) PNGs"
fi

# ── 3. Source code (excluding junk) ──────────────────────────────
echo "[3/6] Packaging source code ..."
mkdir -p "$STAGING_DIR/code"

# Use tar to copy src/ excluding __pycache__, .pyc, .git, .egg-info
tar -cf - \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.git' \
    --exclude='.mypy_cache' \
    --exclude='*.egg-info' \
    --exclude='.pytest_cache' \
    --exclude='.tox' \
    --exclude='node_modules' \
    --exclude='.venv' \
    --exclude='venv' \
    -C "$PROJECT_ROOT" src/ | tar -xf - -C "$STAGING_DIR/code/"

echo "      Source: $(find "$STAGING_DIR/code/src" -name '*.py' | wc -l) Python files"

# Include key scripts for reproducibility
mkdir -p "$STAGING_DIR/code/scripts"
for script in \
    scripts/arxiv_benchmark_suite.py \
    scripts/generate_paper_artifacts.py \
    scripts/reproduce_release.sh; do
    if [[ -f "$PROJECT_ROOT/$script" ]]; then
        cp "$PROJECT_ROOT/$script" "$STAGING_DIR/code/scripts/"
    fi
done

# Include pyproject.toml for dependency info
if [[ -f "$PROJECT_ROOT/pyproject.toml" ]]; then
    cp "$PROJECT_ROOT/pyproject.toml" "$STAGING_DIR/code/"
fi

# ── 4. CITATION.cff ──────────────────────────────────────────────
echo "[4/6] Copying CITATION.cff ..."
if [[ -f "$PROJECT_ROOT/CITATION.cff" ]]; then
    cp "$PROJECT_ROOT/CITATION.cff" "$STAGING_DIR/"
    echo "      CITATION.cff: OK"
else
    echo "      WARNING: CITATION.cff not found. Run prepare_arxiv_submission.sh first."
fi

# ── 5. README ─────────────────────────────────────────────────────
echo "[5/6] Copying README ..."
if [[ -f "$PROJECT_ROOT/README.md" ]]; then
    cp "$PROJECT_ROOT/README.md" "$STAGING_DIR/"
    echo "      README.md: OK"
fi

# Include the arXiv-specific README if it exists
if [[ -f "$PROJECT_ROOT/docs/README_ARXIV.md" ]]; then
    cp "$PROJECT_ROOT/docs/README_ARXIV.md" "$STAGING_DIR/"
fi

# ── 6. Create archive ────────────────────────────────────────────
echo "[6/6] Creating archive ..."
tar -czf "$ARCHIVE" -C "$STAGING_DIR" .

# Clean up staging
rm -rf "$STAGING_DIR"

# ── Summary ───────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════════════"
echo "  arXiv submission package ready"
echo "════════════════════════════════════════════════════════════════"
echo
echo "  Archive : $ARCHIVE"
echo "  Size    : $(du -h "$ARCHIVE" | cut -f1)"
echo
echo "  Contents:"
echo "    draft.pdf                    — Manuscript (PDF)"
echo "    docs/tech-report/draft.md    — Manuscript (Markdown source)"
echo "    docs/figures/                — Figures"
echo "    docs/tech-report/artifacts/  — Reliability diagrams, plots"
echo "    code/src/lub/                — Library source code"
echo "    code/scripts/                — Reproducibility scripts"
echo "    code/pyproject.toml          — Dependencies"
echo "    CITATION.cff                 — Citation metadata"
echo "    README.md                    — Project README"
echo
echo "  To inspect:"
echo "    tar -tzf $ARCHIVE | head -30"
echo
echo "  Upload to: https://arxiv.org/submit"
echo "════════════════════════════════════════════════════════════════"
