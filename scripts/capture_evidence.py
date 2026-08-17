#!/usr/bin/env python3
"""Capture monthly evidence artifacts for the EB-2 NIW petition.

Usage:
    python scripts/capture_evidence.py [--evidence-dir PATH]

By default writes to ../../../02_Evidencias_Profissionais/GitHub_Project/ relative
to the repo root. Run this from the repo root on the last working day of each month.

What it captures (the offline-safe pieces — everything that does not need a browser):
    * logs/YYYY-MM-DD_git_log_stat.txt
    * logs/YYYY-MM-DD_git_log_graph.txt
    * logs/YYYY-MM-DD_contributors.txt
    * metrics.csv (appends one row via `gh api` if the GitHub CLI is available)

Browser-only captures (screenshots, traffic, PyPI, press) are listed in
MONTHLY_RUNBOOK.md and must be done manually.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_SLUG_DEFAULT = "llm-uncertainty-banking"


def run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(f"[warn] {' '.join(cmd)} exited {result.returncode}\n")
        sys.stderr.write(result.stderr)
    return result.stdout


def dump_git_logs(repo_root: Path, logs_dir: Path, today: str) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / f"{today}_git_log_stat.txt").write_text(
        run(["git", "log", "--stat", "--all"], cwd=repo_root), encoding="utf-8"
    )
    (logs_dir / f"{today}_git_log_graph.txt").write_text(
        run(["git", "log", "--oneline", "--all", "--graph"], cwd=repo_root),
        encoding="utf-8",
    )
    (logs_dir / f"{today}_contributors.txt").write_text(
        run(["git", "shortlog", "-sne", "--all"], cwd=repo_root), encoding="utf-8"
    )


def append_metrics_row(evidence_dir: Path, today: str, repo_slug: str) -> None:
    metrics_path = evidence_dir / "metrics.csv"
    header = [
        "date", "stars", "forks", "watchers", "open_issues",
        "closed_issues", "open_prs", "closed_prs", "contributors",
        "pypi_downloads_30d", "notes",
    ]
    if not metrics_path.exists():
        with metrics_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)

    row = {k: "" for k in header}
    row["date"] = today
    row["notes"] = "auto-captured; fill PyPI + traffic manually"

    if shutil.which("gh"):
        out = run(["gh", "api", f"repos/{repo_slug}"])
        if out:
            try:
                data = json.loads(out)
                row["stars"] = str(data.get("stargazers_count", ""))
                row["forks"] = str(data.get("forks_count", ""))
                row["watchers"] = str(data.get("subscribers_count", ""))
                row["open_issues"] = str(data.get("open_issues_count", ""))
            except json.JSONDecodeError:
                pass

    with metrics_path.open("a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=header).writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument("--repo-slug", default=REPO_SLUG_DEFAULT,
                        help="GitHub <owner>/<repo> for the `gh api` call")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    evidence_dir = args.evidence_dir or (
        repo_root.parent.parent / "02_Evidencias_Profissionais" / "GitHub_Project"
    )
    today = dt.date.today().isoformat()

    if not evidence_dir.exists():
        sys.stderr.write(f"evidence dir not found: {evidence_dir}\n")
        return 1

    print(f"Capturing evidence -> {evidence_dir} (date: {today})")
    dump_git_logs(repo_root, evidence_dir / "logs", today)
    append_metrics_row(evidence_dir, today, args.repo_slug)
    print("Done. Remaining manual steps: screenshots, traffic, PyPI, externals - see MONTHLY_RUNBOOK.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
