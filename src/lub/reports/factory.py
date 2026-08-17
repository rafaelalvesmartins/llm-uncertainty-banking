# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Factory for creating report generators with lazy imports.

Decouples the CLI and other consumers from knowledge of specific reporter
implementations. New report formats can be added by extending the factory
without modifying existing code.
"""

from __future__ import annotations

from typing import Literal

from lub.reports.protocol import ReportGenerator
from lub.types import BenchmarkResult


def create_reporter(
    results: list[BenchmarkResult],
    report_type: Literal["airmf", "oscal", "giskard"] = "airmf",
) -> ReportGenerator:
    """Create a report generator with lazy imports.

    Parameters
    ----------
    results : list[BenchmarkResult]
        One or more benchmark results to include in the report.
    report_type : {"airmf", "oscal", "giskard"}
        Type of report to generate. Lazy-loads the corresponding reporter
        class only when this function is called.

    Returns
    -------
        ReportGenerator
            An object satisfying the ReportGenerator protocol.

    Raises
    ------
    ValueError
        If `report_type` is not a supported format.

    Examples
    --------
    >>> from lub.reports.factory import create_reporter
    >>> results = [...]  # list of BenchmarkResult
    >>> reporter = create_reporter(results, report_type="airmf")
    >>> md_output = reporter.render(format="md")
    >>> reporter.save("report.md", format="md")
    """
    if report_type == "airmf":
        from lub.reports.renderer import AIRMFReporter

        return AIRMFReporter(results=results)
    if report_type == "oscal":
        from lub.reports.oscal import OscalBatchReporter

        return OscalBatchReporter(results=results)
    if report_type == "giskard":
        from lub.reports.giskard_reporter import GiskardBatchReporter

        return GiskardBatchReporter(results=results)
    raise ValueError(
        f"unknown report type {report_type!r}; choose from 'airmf', 'oscal', 'giskard'"
    )


__all__ = [
    "create_reporter",
]
