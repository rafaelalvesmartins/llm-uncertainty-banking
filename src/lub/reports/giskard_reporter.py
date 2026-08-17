# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Batch reporter adapter for Giskard vulnerability scans.

Wraps :func:`lub.reports.giskard_report.scan_benchmark_result` into the
:class:`~lub.reports.protocol.ReportGenerator` protocol so that the CLI
``lub report --report-type giskard`` works out of the box.

Output formats:
- ``json``: structured JSON array of vulnerability reports.
- ``md``: human-readable markdown with severity badges.
"""

from __future__ import annotations

import json
from typing import Literal

from lub.reports.giskard_report import scan_benchmark_result
from lub.reports.protocol import ReportSaveMixin
from lub.types import BenchmarkResult


class GiskardBatchReporter(ReportSaveMixin):
    """Run vulnerability scans on one or more BenchmarkResults."""

    def __init__(self, results: list[BenchmarkResult]) -> None:
        if not results:
            raise ValueError("results must be non-empty")
        self.results = results

    def render(self, format: Literal["md", "html", "json"] = "json") -> str:
        """Render the report to the configured output format."""
        reports = [scan_benchmark_result(r) for r in self.results]

        if format == "json":
            return json.dumps([r.to_dict() for r in reports], indent=2)

        lines: list[str] = ["# Vulnerability Report (Giskard-style)", ""]
        for i, report in enumerate(reports):
            lines.append(
                f"## Run {i + 1}: {report.backend} / {report.estimator} on {report.dataset}"
            )
            lines.append("")
            lines.append(f"- **Worst severity:** {report.worst_severity}")
            lines.append(f"- **Passed:** {'Yes' if report.passed else 'No'}")
            lines.append(f"- **Issues found:** {len(report.issues)}")
            lines.append("")
            if report.issues:
                lines.append("| Severity | Category | Metric | Value | Threshold | Description |")
                lines.append("|---|---|---|---|---|---|")
                for issue in report.issues:
                    lines.append(
                        f"| {issue.severity} | {issue.category} | "
                        f"`{issue.metric_name}` | {issue.metric_value:.4f} | "
                        f"{issue.threshold:.4f} | {issue.description} |"
                    )
                lines.append("")
            else:
                lines.append("No vulnerabilities detected.")
                lines.append("")

        return "\n".join(lines)

    # save() inherited from ReportSaveMixin


__all__ = ["GiskardBatchReporter"]
