#!/bin/bash
# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0
#
# Build academic PDF from draft.md for arXiv submission.
#
# Requirements:
#   - pandoc >= 3.0        (https://pandoc.org/installing.html)
#   - texlive-xetex        (or any LaTeX distribution with xelatex)
#   - texlive-fonts-extra   (for Computer Modern / Latin Modern fonts)
#
# Install on Ubuntu/Debian:
#   sudo apt-get install pandoc texlive-xetex texlive-fonts-extra
#
# Install on macOS (Homebrew):
#   brew install pandoc
#   brew install --cask mactex-no-gui
#
# Install on Windows (winget / choco):
#   winget install --id JohnMacFarlane.Pandoc
#   choco install miktex          # or install MiKTeX from https://miktex.org
#
# Usage:
#   bash scripts/build_arxiv_pdf.sh
#   bash scripts/build_arxiv_pdf.sh --engine pdflatex   # alternate engine

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRAFT="$PROJECT_ROOT/docs/tech-report/draft.md"
OUTPUT="$PROJECT_ROOT/docs/tech-report/draft.pdf"
ARTIFACTS_DIR="$PROJECT_ROOT/docs/tech-report/artifacts"
ENGINE="${1:-xelatex}"

# ── Preflight checks ──────────────────────────────────────────────
if ! command -v pandoc &>/dev/null; then
    echo "ERROR: pandoc not found."
    echo "Install it first — see instructions at top of this script."
    exit 1
fi

if ! command -v "$ENGINE" &>/dev/null; then
    echo "WARNING: $ENGINE not found; falling back to pdflatex."
    ENGINE="pdflatex"
    if ! command -v pdflatex &>/dev/null; then
        echo "ERROR: No LaTeX engine found (tried xelatex, pdflatex)."
        echo "Install texlive-xetex or MiKTeX — see instructions at top of this script."
        exit 1
    fi
fi

echo "Building PDF with pandoc + $ENGINE ..."

# ── Build PDF ─────────────────────────────────────────────────────
# Flags rationale:
#   --pdf-engine        : xelatex for Unicode (Portuguese chars in BR-Regulatory)
#   -V geometry:margin  : 1-inch margins, standard for preprints
#   -V fontsize         : 11pt, readable on screen and print
#   -V documentclass    : article, standard for arXiv cs.CL/cs.LG
#   -V colorlinks       : clickable blue hyperlinks in PDF
#   -V header-includes  : compact title, single-column (arXiv default)
#   --highlight-style   : tango for code blocks
#   --number-sections   : numbered headings (matches draft.md structure)
#   --citeproc          : process @citations if .bib is added later
#   --resource-path     : resolve relative image paths from artifacts/
#   -f markdown+smart   : smart quotes, em-dashes
pandoc "$DRAFT" \
    -o "$OUTPUT" \
    -f markdown+smart \
    --pdf-engine="$ENGINE" \
    --highlight-style=tango \
    --number-sections \
    --resource-path="$ARTIFACTS_DIR:$PROJECT_ROOT/docs/figures" \
    -V geometry:margin=1in \
    -V fontsize=11pt \
    -V documentclass=article \
    -V colorlinks=true \
    -V linkcolor=blue \
    -V urlcolor=blue \
    -V citecolor=blue \
    -V header-includes='\usepackage{booktabs}\usepackage{longtable}' \
    -V title="Calibrated LLMs for Regulated Banking" \
    -V author="Rafael Martins Alves" \
    -V date="April 2026 — Preprint"

echo "Done: $OUTPUT"
echo "Size: $(du -h "$OUTPUT" | cut -f1)"
