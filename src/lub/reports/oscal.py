# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""NIST OSCAL 1.1 Component Definition output.

Renders a :class:`~lub.types.BenchmarkResult` as an OSCAL Component
Definition JSON document so that GRC tools (Trestle, Regscale, the
FedRAMP Automation Tracker) can ingest LUB's evidence programmatically.

OSCAL (https://pages.nist.gov/OSCAL/) is the NIST standard for
machine-readable expression of security and privacy controls. A
Component Definition describes a component (here: an LLM + uncertainty
estimator combination) and the controls it implements along with
structured evidence of implementation.

The mapping LUB uses:

- ``component`` — one per benchmark run, naming the
  ``backend:model/estimator`` combination.
- ``control-implementation`` ��� one per control catalog (NIST AI RMF 1.0
  and ISO/IEC 42001:2023).
- ``implemented-requirement`` — one per metric produced by
  :func:`lub.calibration.metrics.compute_all`, keyed by its sub-category
  (``MEASURE 2.9``, ``MEASURE 2.7``, etc.) from
  :func:`lub.reports.mapping.get_rmf_mapping`.
- ``by-component.description`` — carries the metric name, numeric
  value, and the finding/observation/pass severity label from
  :class:`~lub.reports.findings.FindingClassifier`.

The output conforms to the OSCAL Component Definition schema version
1.1.2 (https://github.com/usnistgov/OSCAL/tree/v1.1.2/json/schema).
Pydantic models here are a *subset* of the full schema — just the
fields LUB actually populates. Tools expecting the full schema treat
missing optional fields as absent, which is valid.

No new hard dependency. Every import is pydantic v2 + stdlib.
"""

from __future__ import annotations

from typing import Any, Final, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

from lub.reports.findings import FindingClassifier, Report, Severity
from lub.reports.mapping import get_iso42001_mapping, get_rmf_mapping
from lub.reports.oscal_common import (
    OSCAL_VERSION as _OSCAL_VERSION,
)
from lub.reports.oscal_common import (
    OscalLink,
    OscalMetadata,
    OscalProp,
)
from lub.reports.oscal_common import (
    gen_uuid as _gen_uuid,
)
from lub.reports.oscal_common import (
    now_iso as _now_iso,
)
from lub.reports.protocol import ReportSaveMixin
from lub.types import BenchmarkResult

_LOG = structlog.get_logger("lub.reports.oscal")

_CATALOG_NIST_AI_RMF: Final = "NIST_AI_RMF_1.0"
_CATALOG_ISO_42001: Final = "ISO_IEC_42001_2023"
_SEVERITY_REMARKS = {
    Severity.FINDING: "FINDING — material deviation requiring remediation before production approval.",
    Severity.OBSERVATION: "OBSERVATION — non-material note for follow-up; does not block approval.",
    Severity.PASS: "PASS — within expected bounds.",
}


class OscalByComponent(BaseModel):
    """``by-component`` — the component-specific implementation record.

    Each implemented-requirement can be satisfied by one or more
    components; this record ties a metric to the component that
    produced its value.
    """

    model_config = ConfigDict(extra="forbid")

    component_uuid: str = Field(alias="component-uuid")
    uuid: str
    description: str
    props: list[OscalProp] = Field(default_factory=list)


class OscalImplementedRequirement(BaseModel):
    """One ``implemented-requirement`` — a control mapped to evidence."""

    model_config = ConfigDict(extra="forbid")

    uuid: str
    control_id: str = Field(alias="control-id")
    description: str
    props: list[OscalProp] = Field(default_factory=list)
    by_components: list[OscalByComponent] = Field(default_factory=list, alias="by-components")


class OscalControlImplementation(BaseModel):
    """A set of implemented-requirements drawn from one control catalog."""

    model_config = ConfigDict(extra="forbid")

    uuid: str
    source: str
    description: str
    implemented_requirements: list[OscalImplementedRequirement] = Field(
        alias="implemented-requirements"
    )


class OscalComponent(BaseModel):
    """An OSCAL component — here, one (backend, estimator) combination."""

    model_config = ConfigDict(extra="forbid")

    uuid: str
    type: Literal["service", "software"] = "software"
    title: str
    description: str
    props: list[OscalProp] = Field(default_factory=list)
    control_implementations: list[OscalControlImplementation] = Field(
        alias="control-implementations"
    )


class OscalComponentDefinition(BaseModel):
    """OSCAL Component Definition document root."""

    model_config = ConfigDict(extra="forbid")

    uuid: str
    metadata: OscalMetadata
    components: list[OscalComponent]


def _props_from_record(record: BenchmarkResult) -> list[OscalProp]:
    props: list[OscalProp] = [
        OscalProp(name="repo_version", value=record.repo_version),
        OscalProp(name="backend", value=record.backend),
        OscalProp(name="estimator", value=record.estimator),
        OscalProp(name="dataset", value=record.dataset),
        OscalProp(name="dataset_version", value=record.dataset_version or ""),
        OscalProp(name="dataset_hash", value=record.dataset_hash),
        OscalProp(name="timestamp", value=record.timestamp),
        OscalProp(name="n", value=str(record.n)),
        OscalProp(name="seed", value=str(record.seed)),
    ]
    if record.git_sha:
        props.append(OscalProp(name="git_sha", value=record.git_sha))
    return props


def _implemented_requirements(
    record: BenchmarkResult,
    report: Report,
    component_uuid: str,
    rmf_mapping: dict[str, Any],
) -> list[OscalImplementedRequirement]:
    """Group metrics by AI RMF sub-category and render one IR per group."""
    by_subcategory: dict[str, list[tuple[str, float, Severity]]] = {}
    for classified in report.classified:
        entry = rmf_mapping.get(classified.name)
        if not entry:
            continue
        by_subcategory.setdefault(entry["subcategory"], []).append(
            (classified.name, classified.value, classified.severity)
        )

    irs: list[OscalImplementedRequirement] = []
    for subcategory, metrics in sorted(by_subcategory.items()):
        control_id = subcategory.lower().replace(" ", "_").replace(".", "_")
        description = (
            f"NIST AI RMF 1.0 {subcategory} — evidence from {len(metrics)} metric(s) "
            f"computed on dataset {record.dataset!r} ({record.n} examples, "
            f"seed {record.seed}, {record.backend}/{record.estimator})."
        )
        bc_items: list[OscalByComponent] = []
        for metric_name, value, severity in metrics:
            props = [
                OscalProp(name="metric", value=metric_name),
                OscalProp(name="value", value=f"{value:.6f}"),
                OscalProp(name="severity", value=str(severity.value)),
                OscalProp(
                    name="trust_dimension",
                    value=rmf_mapping[metric_name]["trust_dimension"],
                ),
            ]
            bc_items.append(
                OscalByComponent.model_validate(
                    {
                        "component-uuid": component_uuid,
                        "uuid": _gen_uuid(),
                        "description": (
                            f"{metric_name} = {value:.6f} "
                            f"[{_SEVERITY_REMARKS[severity]}] "
                            f"{rmf_mapping[metric_name]['description']}"
                        ),
                        "props": props,
                    }
                )
            )
        irs.append(
            OscalImplementedRequirement.model_validate(
                {
                    "uuid": _gen_uuid(),
                    "control-id": control_id,
                    "description": description,
                    "props": [],
                    "by-components": bc_items,
                }
            )
        )
    return irs


def _iso42001_implemented_requirements(
    record: BenchmarkResult,
    report: Report,
    component_uuid: str,
    iso_mapping: dict[str, Any],
) -> list[OscalImplementedRequirement]:
    """Group metrics by ISO 42001 clause and render one IR per group."""
    by_clause: dict[str, list[tuple[str, float, Severity]]] = {}
    for classified in report.classified:
        entry = iso_mapping.get(classified.name)
        if not entry:
            continue
        by_clause.setdefault(entry["clause"], []).append(
            (classified.name, classified.value, classified.severity)
        )

    irs: list[OscalImplementedRequirement] = []
    for clause, metrics in sorted(by_clause.items()):
        control_id = f"iso42001_{clause.replace('.', '_')}"
        description = (
            f"ISO/IEC 42001:2023 Clause {clause} — evidence from {len(metrics)} metric(s) "
            f"computed on dataset {record.dataset!r} ({record.n} examples, "
            f"seed {record.seed}, {record.backend}/{record.estimator})."
        )
        bc_items: list[OscalByComponent] = []
        for metric_name, value, severity in metrics:
            entry = iso_mapping[metric_name]
            props = [
                OscalProp(name="metric", value=metric_name),
                OscalProp(name="value", value=f"{value:.6f}"),
                OscalProp(name="severity", value=str(severity.value)),
                OscalProp(name="iso42001_annex", value=entry["annex"]),
            ]
            bc_items.append(
                OscalByComponent.model_validate(
                    {
                        "component-uuid": component_uuid,
                        "uuid": _gen_uuid(),
                        "description": (
                            f"{metric_name} = {value:.6f} "
                            f"[{_SEVERITY_REMARKS[severity]}] "
                            f"{entry['description']}"
                        ),
                        "props": props,
                    }
                )
            )
        irs.append(
            OscalImplementedRequirement.model_validate(
                {
                    "uuid": _gen_uuid(),
                    "control-id": control_id,
                    "description": description,
                    "props": [],
                    "by-components": bc_items,
                }
            )
        )
    return irs


def build_component_definition(
    record: BenchmarkResult,
    *,
    title: str | None = None,
    classifier: FindingClassifier | None = None,
) -> OscalComponentDefinition:
    """Render ``record`` as an OSCAL Component Definition.

    Parameters
    ----------
    record:
        One persisted benchmark result.
    title:
        Optional override for the component-definition title. Defaults
        to ``"LUB — {backend}/{estimator} on {dataset}"``.
    classifier:
        Optional :class:`FindingClassifier` for severity banding. A
        default with OCC 2011-12 heuristics is used when omitted.
    """
    _LOG.info(
        "oscal.component_definition.build",
        backend=record.backend,
        estimator=record.estimator,
        dataset=record.dataset,
        n_metrics=len(record.metrics),
    )
    report = (classifier or FindingClassifier()).classify(record)
    component_uuid = _gen_uuid()
    mapping = get_rmf_mapping()
    iso_mapping = get_iso42001_mapping()

    nist_irs = _implemented_requirements(record, report, component_uuid, mapping)
    iso_irs = _iso42001_implemented_requirements(record, report, component_uuid, iso_mapping)

    # OSCAL requires implemented-requirements to be non-empty; skip CIs with no IRs.
    control_implementations = []
    if nist_irs:
        control_implementations.append(
            OscalControlImplementation.model_validate(
                {
                    "uuid": _gen_uuid(),
                    "source": _CATALOG_NIST_AI_RMF,
                    "description": (
                        "NIST AI RMF 1.0 sub-categories satisfied by this "
                        "component, as evidenced by calibration metrics "
                        "computed on the evaluation set."
                    ),
                    "implemented-requirements": nist_irs,
                }
            )
        )
    if iso_irs:
        control_implementations.append(
            OscalControlImplementation.model_validate(
                {
                    "uuid": _gen_uuid(),
                    "source": _CATALOG_ISO_42001,
                    "description": (
                        "ISO/IEC 42001:2023 clauses satisfied by this "
                        "component. EU AI Act Annex IV references ISO 42001; "
                        "this catalog enables multi-jurisdictional compliance "
                        "from a single benchmark run."
                    ),
                    "implemented-requirements": iso_irs,
                }
            )
        )

    component = OscalComponent.model_validate(
        {
            "uuid": component_uuid,
            "type": "software",
            "title": f"{record.backend} / {record.estimator}",
            "description": (
                f"llm-uncertainty-banking pipeline using backend "
                f"{record.backend!r} with estimator {record.estimator!r}. "
                f"Evaluated on dataset {record.dataset!r} "
                f"({record.dataset_version or 'unversioned'}), "
                f"{record.n} examples, seed {record.seed}."
            ),
            "props": _props_from_record(record),
            "control-implementations": control_implementations,
        }
    )

    return OscalComponentDefinition(
        uuid=_gen_uuid(),
        metadata=OscalMetadata(
            **{
                "title": title or f"LUB — {record.backend}/{record.estimator} on {record.dataset}",
                "last-modified": _now_iso(),
                "version": record.repo_version,
                "oscal-version": _OSCAL_VERSION,
            }
        ),
        components=[component],
    )


def render_oscal_json(
    record: BenchmarkResult,
    *,
    indent: int = 2,
    title: str | None = None,
    classifier: FindingClassifier | None = None,
) -> str:
    """Return the OSCAL Component Definition as a JSON string.

    The output conforms to the OSCAL 1.1.2 top-level envelope:
    ``{"component-definition": { uuid, metadata, components }}``.
    """
    import json as _json

    cd = build_component_definition(record, title=title, classifier=classifier)
    payload = cd.model_dump(by_alias=True, exclude_none=True)
    envelope = {"component-definition": payload}
    return _json.dumps(envelope, indent=indent)


class OscalBatchReporter(ReportSaveMixin):
    """OSCAL batch reporter for multiple BenchmarkResult records.

    Implements the :class:`~lub.reports.protocol.ReportGenerator` protocol
    for rendering multiple benchmark results as OSCAL component definitions.

    Each result is rendered as a separate JSON object, separated by blank lines,
    producing a stream of OSCAL documents suitable for GRC tool ingestion.
    """

    def __init__(
        self,
        results: list[BenchmarkResult],
    ) -> None:
        """Initialize the OSCAL batch reporter.

        Parameters
        ----------
        results : list[BenchmarkResult]
            One or more benchmark results to render.
        """
        if not results:
            raise ValueError("results must be non-empty")
        self.results = results

    def render(self, format: str = "json") -> str:
        """Render all results as OSCAL component definitions (JSON format).

        Parameters
        ----------
        format : str, optional
            Output format. Currently only "json" is supported.
            Default is "json".

        Returns
        -------
        str
            Newline-separated OSCAL JSON objects, one per result.

        Raises
        ------
        ValueError
            If format is not "json".
        """
        if format != "json":
            raise ValueError(f"OSCAL only supports 'json' format, got {format!r}")
        return "\n\n".join(render_oscal_json(r) for r in self.results)

    # save() inherited from ReportSaveMixin


__all__ = [
    "OscalBatchReporter",
    "OscalByComponent",
    "OscalComponent",
    "OscalComponentDefinition",
    "OscalControlImplementation",
    "OscalImplementedRequirement",
    "OscalLink",
    "OscalMetadata",
    "OscalProp",
    "build_component_definition",
    "render_oscal_json",
]
