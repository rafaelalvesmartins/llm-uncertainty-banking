# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""L5 AI RMF report templates, OSCAL output, and multi-regime crosswalk.

Report classes are lazy-loaded on first access via ``__getattr__``.
This avoids importing all reporting infrastructure (Jinja2 templates,
OSCAL schemas, crosswalk data) when the user only runs ``lub answer``.

.. note::
   **Two dashboards in lub, by design.** :mod:`lub.reports.dashboard`
   (loaded lazily via this package) is the **static, post-run** evidence
   viewer: composes finished :class:`~lub.benchmarks.BenchmarkResult`
   JSONs + OSCAL findings + crosswalk data into a single offline HTML
   file suitable for shipping to auditors. The sibling
   :mod:`lub.dashboard` is the **live, in-process** observability
   surface: a FastAPI app reading the ledger directly. Use
   :mod:`lub.reports.dashboard` for evidence packets that ship to
   auditors; use :mod:`lub.dashboard` for live monitoring. Mirror of
   the symmetric note in ``lub.dashboard.__init__``.
"""

_LAZY_MAP: dict[str, tuple[str, str]] = {
    # assessment
    "OscalAssessmentResults": ("lub.reports.assessment", "OscalAssessmentResults"),
    "build_assessment_results": ("lub.reports.assessment", "build_assessment_results"),
    "render_assessment_json": ("lub.reports.assessment", "render_assessment_json"),
    # catalog
    "OscalCatalog": ("lub.reports.catalog", "OscalCatalog"),
    "build_all_catalogs": ("lub.reports.catalog", "build_all_catalogs"),
    "build_catalog": ("lub.reports.catalog", "build_catalog"),
    "render_all_catalogs_json": ("lub.reports.catalog", "render_all_catalogs_json"),
    "render_catalog_json": ("lub.reports.catalog", "render_catalog_json"),
    # crosswalk
    "Regime": ("lub.reports.crosswalk", "Regime"),
    "get_crosswalk": ("lub.reports.crosswalk", "get_crosswalk"),
    "get_crosswalk_for_regime": ("lub.reports.crosswalk", "get_crosswalk_for_regime"),
    # factory
    "create_reporter": ("lub.reports.factory", "create_reporter"),
    # findings
    "DEFAULT_THRESHOLDS": ("lub.reports.findings", "DEFAULT_THRESHOLDS"),
    "ClassifiedMetric": ("lub.reports.findings", "ClassifiedMetric"),
    "FindingClassifier": ("lub.reports.findings", "FindingClassifier"),
    "MetricThreshold": ("lub.reports.findings", "MetricThreshold"),
    "Report": ("lub.reports.findings", "Report"),
    "Severity": ("lub.reports.findings", "Severity"),
    # giskard
    "VulnerabilityReport": ("lub.reports.giskard_report", "VulnerabilityReport"),
    "scan_benchmark_result": ("lub.reports.giskard_report", "scan_benchmark_result"),
    "GiskardBatchReporter": ("lub.reports.giskard_reporter", "GiskardBatchReporter"),
    # mapping
    "get_iso42001_mapping": ("lub.reports.mapping", "get_iso42001_mapping"),
    "get_rmf_mapping": ("lub.reports.mapping", "get_rmf_mapping"),
    # oscal
    "OscalBatchReporter": ("lub.reports.oscal", "OscalBatchReporter"),
    "OscalComponentDefinition": ("lub.reports.oscal", "OscalComponentDefinition"),
    "build_component_definition": ("lub.reports.oscal", "build_component_definition"),
    "render_oscal_json": ("lub.reports.oscal", "render_oscal_json"),
    # protocol
    "ReportGenerator": ("lub.reports.protocol", "ReportGenerator"),
    # renderer
    "AIRMFReporter": ("lub.reports.renderer", "AIRMFReporter"),
    # dashboard (static evidence dashboard, post-RUFLO_VS_LUB_GAP analysis)
    "DashboardCard": ("lub.reports.dashboard", "DashboardCard"),
    "DashboardData": ("lub.reports.dashboard", "DashboardData"),
    "build_dashboard": ("lub.reports.dashboard", "build_dashboard"),
    "collect_dashboard_data": ("lub.reports.dashboard", "collect_dashboard_data"),
    "render_dashboard_html": ("lub.reports.dashboard", "render_dashboard_html"),
    # dashboard_protocols (Protocol-pluggability surface for the static dashboard;
    # mirrors lub.dashboard.protocols re-exports per spec 30)
    "EvidenceRenderer": ("lub.reports.dashboard_protocols", "EvidenceRenderer"),
    "EvidenceSource": ("lub.reports.dashboard_protocols", "EvidenceSource"),
    "get_evidence_renderer": ("lub.reports.dashboard_protocols", "get_evidence_renderer"),
    "list_evidence_renderers": ("lub.reports.dashboard_protocols", "list_evidence_renderers"),
    "register_evidence_renderer": ("lub.reports.dashboard_protocols", "register_evidence_renderer"),
}


def __getattr__(name: str) -> object:
    if name in _LAZY_MAP:
        module_path, attr_name = _LAZY_MAP[name]
        import importlib

        mod = importlib.import_module(module_path)
        return getattr(mod, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Enable tab completion in IPython/Jupyter for lazy-loaded symbols."""
    return sorted(_LAZY_MAP.keys())


__all__ = sorted(_LAZY_MAP.keys())
