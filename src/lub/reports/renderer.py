# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""AI RMF report renderer.

Loads the packaged Jinja2 template, feeds it a list of
:class:`~lub.types.BenchmarkResult` records plus the metric -> AI RMF
mapping, and renders to markdown or HTML. Reliability-diagram PNGs may be
supplied per-result and are embedded as base64 ``data:`` URIs so that the
HTML output is a single self-contained file.
"""

from __future__ import annotations

import base64
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape

from lub.reports.findings import FindingClassifier, Report
from lub.reports.mapping import get_rmf_mapping
from lub.reports.protocol import ReportSaveMixin
from lub.types import BenchmarkResult

_TEMPLATE_DIR: Final = Path(__file__).parent
_TEMPLATE_NAME: Final = "airmf_template.md.j2"
_REPORT_VERSION: Final = "1.0"


def _encode_png(data: bytes | None) -> str | None:
    if data is None:
        return None
    return base64.b64encode(data).decode("ascii")


@dataclass
class _SubgroupResult:
    overall_ece: float
    adversarial_ece: float


def _build_jsonld_context(results: list[BenchmarkResult]) -> str:
    """Build a JSON-LD context linking report metrics to benchmark runs."""
    items = []
    for i, r in enumerate(results):
        items.append(
            {
                "@type": "DataCatalog",
                "name": f"run-{i + 1}",
                "identifier": r.dataset_hash[:16],
                "dateCreated": r.timestamp,
                "creator": r.backend,
                "about": {
                    "dataset": r.dataset,
                    "dataset_version": r.dataset_version,
                    "estimator": r.estimator,
                    "git_sha": r.git_sha,
                    "seed": r.seed,
                },
            }
        )
    ctx = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "llm-uncertainty-banking evaluation",
        "hasPart": items,
    }
    return json.dumps(ctx, indent=2, sort_keys=True)


class AIRMFReporter(ReportSaveMixin):
    """Render benchmark results as an AI RMF markdown or HTML report."""

    def __init__(
        self,
        results: list[BenchmarkResult],
        reliability_pngs: list[bytes | None] | None = None,
        title: str | None = None,
        template_path: Path | str | None = None,
    ) -> None:
        """Initialize the AI RMF reporter.

        Parameters
        ----------
        results:
            One or more benchmark results to include in the report.
        reliability_pngs:
            Optional list of PNG bytes for reliability diagram figures,
            one per result.  Length must match ``results``.
        title:
            Custom report title.  Defaults to a generated title.
        template_path:
            Path to a custom Jinja2 template file.  Defaults to the
            built-in ``airmf_template.md.j2``.  Use for branding,
            localization, or institution-specific report layouts.
        """
        if not results:
            raise ValueError("results must be non-empty")
        if reliability_pngs is not None and len(reliability_pngs) != len(results):
            raise ValueError("reliability_pngs length must match results length")
        self.results = results
        self.reliability_pngs = reliability_pngs
        self.title = title

        if template_path is not None:
            custom = Path(template_path)
            if not custom.is_file():
                # Fail at construction with a path-level message, rather
                # than deferring to Jinja's TemplateNotFound which surfaces
                # only the file name. Catches the common typo of passing a
                # directory, a relative path that doesn't resolve, or a
                # missing file — all failure modes an MRM reviewer will
                # hit when wiring up an institution-custom template.
                raise ValueError(f"template_path does not point to a file: {custom!s}")
            template_dir = str(custom.parent)
            self._template_name = custom.name
        else:
            template_dir = str(_TEMPLATE_DIR)
            self._template_name = _TEMPLATE_NAME

        self._env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(enabled_extensions=("html",)),
            keep_trailing_newline=True,
        )

    def render(self, format: Literal["md", "html", "json"] = "md") -> str:
        """Render the report to the configured output format."""
        if format not in ("md", "html"):
            raise ValueError(f"AIRMF only supports 'md' or 'html' format, got {format!r}")

        template = self._env.get_template(self._template_name)
        encoded_pngs: list[str | None] | None = None
        if self.reliability_pngs is not None:
            encoded_pngs = [_encode_png(p) for p in self.reliability_pngs]

        classifier = FindingClassifier()
        findings_reports: list[Report] = []
        subgroup_results: list[_SubgroupResult] = []
        for r in self.results:
            if r.metrics:
                findings_reports.append(classifier.classify(r))
            overall_ece = r.metrics.get("ece", r.ece) if r.metrics else r.ece
            adv_ece = r.metrics.get("adversarial_group_calibration") if r.metrics else None
            if adv_ece is not None:
                subgroup_results.append(
                    _SubgroupResult(overall_ece=overall_ece, adversarial_ece=adv_ece)
                )

        jsonld_context = _build_jsonld_context(self.results)

        markdown = template.render(
            title=self.title,
            results=self.results,
            rmf=get_rmf_mapping(),
            reliability_png_b64=encoded_pngs,
            findings_reports=findings_reports or None,
            subgroup_results=subgroup_results or None,
            jsonld_context=jsonld_context,
            generated_at=datetime.now(tz=UTC).isoformat(),
            report_version=_REPORT_VERSION,
            repo_version=self.results[0].repo_version,
            python_version=sys.version.split()[0],
        )
        if format == "md":
            return markdown

        from markdown_it import MarkdownIt  # lazy import

        md = MarkdownIt("commonmark", {"html": True}).enable("table")
        body = md.render(markdown)
        title = self.title or "AI RMF Report"
        return (
            '<!doctype html>\n<html><head><meta charset="utf-8">'
            f"<title>{title}</title></head><body>\n{body}\n</body></html>\n"
        )

    # save() inherited from ReportSaveMixin via protocol.py


__all__ = ["AIRMFReporter"]
