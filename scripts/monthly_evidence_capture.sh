#!/usr/bin/env bash
# =============================================================================
# monthly_evidence_capture.sh — Phase 7 evidence collection for EB-2 NIW
#
# Captures monthly metrics snapshot from the llm-uncertainty-banking repo
# and saves dated artifacts to the Evidencias_Profissionais directory.
#
# Usage:
#   bash scripts/monthly_evidence_capture.sh [--repo-dir DIR] [--evidence-dir DIR]
#
# Defaults:
#   --repo-dir      Current repo root (auto-detected)
#   --evidence-dir  ../../../02_Evidencias_Profissionais/GitHub_Project
#
# Run this on the last business day of each month.
# Idempotent: re-running overwrites the current day's snapshot.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
TODAY=$(date +%Y-%m-%d)
MONTH_TAG=$(date +%Y-%m)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR=""
EVIDENCE_DIR=""

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-dir)     REPO_DIR="$2"; shift 2 ;;
        --evidence-dir) EVIDENCE_DIR="$2"; shift 2 ;;
        -h|--help)
            head -15 "$0" | tail -13
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

[[ -z "$REPO_DIR" ]] && REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
[[ -z "$EVIDENCE_DIR" ]] && EVIDENCE_DIR="$(cd "$REPO_DIR/../../.." && pwd)/02_Evidencias_Profissionais/GitHub_Project"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
step()  { echo -e "\n\033[1;32m==>\033[0m $*"; }

# Create output directories
LOGS_DIR="$EVIDENCE_DIR/logs"
METRICS_DIR="$EVIDENCE_DIR/metrics"
mkdir -p "$LOGS_DIR" "$METRICS_DIR"

info "Date:         $TODAY"
info "Repo:         $REPO_DIR"
info "Evidence dir: $EVIDENCE_DIR"

# ---------------------------------------------------------------------------
# 1. GitHub repo screenshots (manual — print instructions)
# ---------------------------------------------------------------------------
step "1. GitHub repo screenshots (MANUAL)"
GITHUB_USER="rafaelmartinsalves"
REPO_NAME="llm-uncertainty-banking"
cat <<SCREENSHOTS

  Take the following screenshots and save to:
    $EVIDENCE_DIR/screenshots/

  Filename format: ${TODAY}_<description>.png

  Required screenshots:
    [ ] ${TODAY}_repo_main_page.png     — Main repo page (shows stars, forks, description)
    [ ] ${TODAY}_traffic_clones.png     — Insights > Traffic > Clones
    [ ] ${TODAY}_traffic_visitors.png   — Insights > Traffic > Visitors
    [ ] ${TODAY}_traffic_referrers.png  — Insights > Traffic > Referring sites
    [ ] ${TODAY}_stars_history.png      — Use star-history.com/#$GITHUB_USER/$REPO_NAME
    [ ] ${TODAY}_pypi_downloads.png     — pypistats.org/packages/$REPO_NAME
    [ ] ${TODAY}_actions_status.png     — Actions tab (shows green CI badges)

  Optional (if applicable):
    [ ] ${TODAY}_issues_prs.png         — Issues/PRs from external contributors
    [ ] ${TODAY}_linkedin_post.png      — LinkedIn post engagement stats

SCREENSHOTS
mkdir -p "$EVIDENCE_DIR/screenshots"

# ---------------------------------------------------------------------------
# 2. Export git log to dated file
# ---------------------------------------------------------------------------
step "2. Export git log"

# Full stat log
GIT_LOG_FILE="$LOGS_DIR/${TODAY}_git_log_stat.txt"
git -C "$REPO_DIR" log --stat --all > "$GIT_LOG_FILE" 2>/dev/null || warn "git log --stat failed (not a git repo?)"
info "Saved: $GIT_LOG_FILE"

# Graph log (compact)
GIT_GRAPH_FILE="$LOGS_DIR/${TODAY}_git_log_graph.txt"
git -C "$REPO_DIR" log --oneline --all --graph > "$GIT_GRAPH_FILE" 2>/dev/null || warn "git log graph failed"
info "Saved: $GIT_GRAPH_FILE"

# Contributors
CONTRIBUTORS_FILE="$LOGS_DIR/${TODAY}_contributors.txt"
git -C "$REPO_DIR" shortlog -sne --all > "$CONTRIBUTORS_FILE" 2>/dev/null || warn "git shortlog failed"
info "Saved: $CONTRIBUTORS_FILE"

# ---------------------------------------------------------------------------
# 3. Test count + coverage percentage
# ---------------------------------------------------------------------------
step "3. Test count and coverage"

TEST_METRICS_FILE="$METRICS_DIR/${TODAY}_test_metrics.txt"
{
    echo "=== Test Metrics — $TODAY ==="
    echo ""

    # Count test files and test functions
    TEST_FILES=$(find "$REPO_DIR/tests" -name "test_*.py" -o -name "*_test.py" 2>/dev/null | wc -l | tr -d ' ')
    TEST_FUNCTIONS=$(grep -r "def test_" "$REPO_DIR/tests" 2>/dev/null | wc -l | tr -d ' ')
    echo "Test files:     $TEST_FILES"
    echo "Test functions: $TEST_FUNCTIONS"
    echo ""

    # Try to run pytest with coverage (non-fatal if it fails)
    echo "--- pytest output (summary) ---"
    if command -v python &>/dev/null; then
        # Run in a subshell so failures don't kill the script
        (
            cd "$REPO_DIR"
            python -m pytest tests/ --tb=no -q --co -q 2>/dev/null | tail -5
            echo ""
            echo "--- coverage (if available) ---"
            python -m pytest tests/ --tb=no -q --cov=lub --cov-report=term-missing 2>/dev/null | grep -E "^(TOTAL|tests/|Name|---)" | head -20
        ) || warn "pytest/coverage run failed — counts above are from static analysis"
    else
        warn "python not found — skipping dynamic test count"
    fi
} > "$TEST_METRICS_FILE" 2>&1
info "Saved: $TEST_METRICS_FILE"

# ---------------------------------------------------------------------------
# 4. Git stats (files, lines, contributors)
# ---------------------------------------------------------------------------
step "4. Git repository statistics"

STATS_FILE="$METRICS_DIR/${TODAY}_git_stats.txt"
{
    echo "=== Git Repository Statistics — $TODAY ==="
    echo ""

    # Total tracked files
    TOTAL_FILES=$(git -C "$REPO_DIR" ls-files 2>/dev/null | wc -l | tr -d ' ')
    echo "Tracked files:  $TOTAL_FILES"

    # Lines of code (Python source only)
    PY_FILES=$(git -C "$REPO_DIR" ls-files '*.py' 2>/dev/null)
    if [[ -n "$PY_FILES" ]]; then
        PY_LINES=$(echo "$PY_FILES" | xargs -I{} cat "$REPO_DIR/{}" 2>/dev/null | wc -l | tr -d ' ')
        PY_COUNT=$(echo "$PY_FILES" | wc -l | tr -d ' ')
        echo "Python files:   $PY_COUNT"
        echo "Python lines:   $PY_LINES"
    fi
    echo ""

    # Total commits
    TOTAL_COMMITS=$(git -C "$REPO_DIR" rev-list --all --count 2>/dev/null || echo "N/A")
    echo "Total commits:  $TOTAL_COMMITS"

    # Contributors
    echo ""
    echo "--- Contributors ---"
    git -C "$REPO_DIR" shortlog -sne --all 2>/dev/null || echo "(no contributors found)"

    # First and last commit dates
    echo ""
    FIRST_COMMIT=$(git -C "$REPO_DIR" log --reverse --format="%ai" 2>/dev/null | head -1)
    LAST_COMMIT=$(git -C "$REPO_DIR" log -1 --format="%ai" 2>/dev/null)
    echo "First commit:   $FIRST_COMMIT"
    echo "Last commit:    $LAST_COMMIT"

    # Tags
    echo ""
    echo "--- Tags ---"
    git -C "$REPO_DIR" tag -l --sort=-v:refname 2>/dev/null || echo "(no tags)"

} > "$STATS_FILE" 2>&1
info "Saved: $STATS_FILE"

# ---------------------------------------------------------------------------
# 5. Dated metrics snapshot (append to CSV)
# ---------------------------------------------------------------------------
step "5. Metrics snapshot (CSV)"

CSV_FILE="$EVIDENCE_DIR/metrics_history.csv"
# Create header if file doesn't exist
if [[ ! -f "$CSV_FILE" ]]; then
    echo "date,test_files,test_functions,tracked_files,python_files,python_lines,total_commits,contributors,stars,forks" > "$CSV_FILE"
    info "Created $CSV_FILE with header"
fi

# Gather values (reuse variables from above where possible)
N_TEST_FILES=$(find "$REPO_DIR/tests" -name "test_*.py" -o -name "*_test.py" 2>/dev/null | wc -l | tr -d ' ')
N_TEST_FUNCS=$(grep -r "def test_" "$REPO_DIR/tests" 2>/dev/null | wc -l | tr -d ' ')
N_TRACKED=$(git -C "$REPO_DIR" ls-files 2>/dev/null | wc -l | tr -d ' ')
N_PY=$(git -C "$REPO_DIR" ls-files '*.py' 2>/dev/null | wc -l | tr -d ' ')
N_PY_LINES=$(git -C "$REPO_DIR" ls-files '*.py' 2>/dev/null | xargs -I{} cat "$REPO_DIR/{}" 2>/dev/null | wc -l | tr -d ' ')
N_COMMITS=$(git -C "$REPO_DIR" rev-list --all --count 2>/dev/null || echo "0")
N_CONTRIBUTORS=$(git -C "$REPO_DIR" shortlog -sne --all 2>/dev/null | wc -l | tr -d ' ')

# Try to get stars/forks via gh CLI (non-fatal)
STARS="N/A"
FORKS="N/A"
if command -v gh &>/dev/null; then
    GH_JSON=$(gh api "repos/$GITHUB_USER/$REPO_NAME" --jq '.stargazers_count,.forks_count' 2>/dev/null || true)
    if [[ -n "$GH_JSON" ]]; then
        STARS=$(echo "$GH_JSON" | head -1)
        FORKS=$(echo "$GH_JSON" | tail -1)
    fi
fi

# Remove any existing row for today (idempotent)
if grep -q "^${TODAY}," "$CSV_FILE" 2>/dev/null; then
    grep -v "^${TODAY}," "$CSV_FILE" > "${CSV_FILE}.tmp" && mv "${CSV_FILE}.tmp" "$CSV_FILE"
fi

echo "${TODAY},${N_TEST_FILES},${N_TEST_FUNCS},${N_TRACKED},${N_PY},${N_PY_LINES},${N_COMMITS},${N_CONTRIBUTORS},${STARS},${FORKS}" >> "$CSV_FILE"
info "Appended row for $TODAY to $CSV_FILE"

# ---------------------------------------------------------------------------
# 6. Wayback Machine archive command
# ---------------------------------------------------------------------------
step "6. Wayback Machine archive"
cat <<WAYBACK

  Archive the following URLs on the Wayback Machine:

  Run these commands (or visit the URLs in a browser):

    curl -s "https://web.archive.org/save/https://github.com/$GITHUB_USER/$REPO_NAME" \\
      -o /dev/null -w "Main repo: %{http_code}\\n"

    curl -s "https://web.archive.org/save/https://pypi.org/project/$REPO_NAME/" \\
      -o /dev/null -w "PyPI page: %{http_code}\\n"

    curl -s "https://web.archive.org/save/https://github.com/$GITHUB_USER/$REPO_NAME/actions" \\
      -o /dev/null -w "Actions page: %{http_code}\\n"

  Verify archives at:
    https://web.archive.org/web/*/github.com/$GITHUB_USER/$REPO_NAME

WAYBACK

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
step "Summary"
echo ""
echo "  Files created/updated this run:"
echo "    $GIT_LOG_FILE"
echo "    $GIT_GRAPH_FILE"
echo "    $CONTRIBUTORS_FILE"
echo "    $TEST_METRICS_FILE"
echo "    $STATS_FILE"
echo "    $CSV_FILE"
echo ""
echo "  Manual steps remaining:"
echo "    [ ] Take screenshots (see step 1 above)"
echo "    [ ] Archive on Wayback Machine (see step 6 above)"
echo "    [ ] Save any email replies as PDF to $EVIDENCE_DIR/../_Anexos/"
echo ""
info "Monthly evidence capture complete for $TODAY."
