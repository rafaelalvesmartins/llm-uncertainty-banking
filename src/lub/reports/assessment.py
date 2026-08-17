# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""OSCAL Assessment-Results generator.

Produces OSCAL 1.1.2 Assessment-Results JSON from a
:class:`~lub.types.BenchmarkResult`, mapping live metric values to
controls across all regimes in the crosswalk.

The OSCAL Assessment-Results document is the top layer of the stack:

    Catalog → Profile → SSP → Assessment-Plan → **Assessment-Results**

Each metric value becomes an **observation** (type=TEST, with the
numeric value and severity as relevant-evidence props).  Observations
are linked to **findings** (one per control), where the finding
status is derived from the OCC 2011-12 severity classification
(:class:`~lub.reports.findings.FindingClassifier`).

A single ``render_assessment_json(record)`` call emits a document
covering *all* six regimes — NIST AI 600-1, EU AI Act, BCBS d475,
BCB, ISO/IEC 23894, and ISO/IEC 42001 — so the MRM team gets
cross-regime evidence from one evaluation run.

No new dependency beyond pydantic + stdlib.

References:
    OSCAL Assessment-Results schema:
      https://pages.nist.gov/OSCAL/reference/1.1.2/assessment-results/
"""

from __future__ import annotations

import json as _json
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from lub.reports.crosswalk import (
    CrosswalkEntry,
    Regime,
    get_crosswalk,
    regimes,
)
from lub.reports.findings import FindingClassifier, Report, Severity
from lub.reports.oscal_common import (
    OSCAL_VERSION as _OSCAL_VERSION,
)
from lub.reports.oscal_common import (
    OscalMetadata,
    OscalProp,
)
from lub.reports.oscal_common import (
    gen_uuid as _gen_uuid,
)
from lub.reports.oscal_common import (
    now_iso as _now_iso,
)
from lub.types import BenchmarkResult

_LOG = structlog.get_logger("lub.reports.assessment")

_SEVERITY_STATUS: dict[Severity, str] = {
    Severity.FINDING: "not-satisfied",
    Severity.OBSERVATION: "satisfied",  # observations don't block
    Severity.PASS: "satisfied",
}


# ---------------------------------------------------------------------------
# Pydantic models — OSCAL Assessment-Results subset
# ---------------------------------------------------------------------------

# ARProp and ARMetadata are aliases for the shared OSCAL models.
ARProp = OscalProp
ARMetadata = OscalMetadata


class ARRelevantEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    props: list[ARProp] = Field(default_factory=list)


class ARObservation(BaseModel):
    """An observation (one per metric × regime combination)."""

    model_config = ConfigDict(extra="forbid")
    uuid: str
    title: str
    description: str
    methods: list[str] = Field(default_factory=lambda: ["TEST"])
    collected: str
    relevant_evidence: list[ARRelevantEvidence] = Field(
        alias="relevant-evidence", default_factory=list
    )
    props: list[ARProp] = Field(default_factory=list)


class ARTargetStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str


class ARTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = "objective-id"
    target_id: str = Field(alias="target-id")
    status: ARTargetStatus


class ARRelatedObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_uuid: str = Field(alias="observation-uuid")


class ARFinding(BaseModel):
    """A finding (one per control across all regimes)."""

    model_config = ConfigDict(extra="forbid")
    uuid: str
    title: str
    description: str
    target: ARTarget
    related_observations: list[ARRelatedObservation] = Field(
        alias="related-observations", default_factory=list
    )
    props: list[ARProp] = Field(default_factory=list)


class ARControlSelection(BaseModel):
    """A control-selection entry within reviewed-controls."""

    model_config = ConfigDict(extra="forbid")
    description: str


class ARReviewedControls(BaseModel):
    """Minimal reviewed-controls block required by OSCAL."""

    model_config = ConfigDict(extra="forbid")
    description: str
    control_selections: list[ARControlSelection] = Field(
        alias="control-selections", default_factory=list
    )


class ARResult(BaseModel):
    """One result block — contains all observations and findings."""

    model_config = ConfigDict(extra="forbid")
    uuid: str
    title: str
    description: str
    start: str
    end: str
    reviewed_controls: ARReviewedControls = Field(alias="reviewed-controls")
    findings: list[ARFinding] = Field(default_factory=list)
    observations: list[ARObservation] = Field(default_factory=list)
    props: list[ARProp] = Field(default_factory=list)


class ARImportAp(BaseModel):
    """Reference to the Assessment Plan this assessment is based on."""

    model_config = ConfigDict(extra="forbid")
    href: str


class OscalAssessmentResults(BaseModel):
    """OSCAL Assessment-Results document root."""

    model_config = ConfigDict(extra="forbid")
    uuid: str
    metadata: ARMetadata
    import_ap: ARImportAp = Field(alias="import-ap")
    results: list[ARResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _build_observations(
    record: BenchmarkResult,
    report: Report,
    crosswalk: tuple[CrosswalkEntry, ...],
    collected: str,
) -> list[ARObservation]:
    """Create one observation per (metric, regime, control) triple."""
    severity_by_metric: dict[str, Severity] = {cm.name: cm.severity for cm in report.classified}
    observations: list[ARObservation] = []

    for entry in crosswalk:
        metric = entry.metric
        value: float | None = record.metrics.get(metric)
        if value is None:
            continue
        severity = severity_by_metric.get(metric, Severity.PASS)

        for regime, controls in entry.mappings.items():
            for cm in controls:
                obs_uuid = _gen_uuid()
                observations.append(
                    ARObservation.model_validate(
                        {
                            "uuid": obs_uuid,
                            "title": f"{metric} → {cm['control_id']}",
                            "description": (
                                f"Metric '{metric}' = {value:.6f} evaluated against "
                                f"control {cm['control_id']} ({cm['control_title']}) "
                                f"under regime {regime}."
                            ),
                            "methods": ["TEST"],
                            "collected": collected,
                            "relevant-evidence": [
                                ARRelevantEvidence(
                                    description=cm["description"],
                                    props=[
                                        ARProp(name="metric", value=metric),
                                        ARProp(name="value", value=f"{value:.6f}"),
                                        ARProp(name="severity", value=str(severity.value)),
                                        ARProp(name="trust_dimension", value=entry.trust_dimension),
                                        ARProp(name="regime", value=str(regime)),
                                        ARProp(name="control_id", value=cm["control_id"]),
                                    ],
                                )
                            ],
                            "props": [
                                ARProp(name="regime", value=str(regime)),
                                ARProp(name="backend", value=record.backend),
                                ARProp(name="estimator", value=record.estimator),
                                ARProp(name="dataset", value=record.dataset),
                            ],
                        }
                    )
                )
    return observations


def _build_findings(
    observations: list[ARObservation],
    report: Report,
) -> list[ARFinding]:
    """Create one finding per unique control, aggregating observations."""
    severity_by_metric: dict[str, Severity] = {cm.name: cm.severity for cm in report.classified}

    # Group observations by control_id
    by_control: dict[str, list[ARObservation]] = {}
    for obs in observations:
        # Extract control_id from props
        control_id = ""
        for ev in obs.relevant_evidence:
            for p in ev.props:
                if p.name == "control_id":
                    control_id = p.value
                    break
        if control_id:
            by_control.setdefault(control_id, []).append(obs)
        else:
            # An observation without a control_id evidence prop cannot be
            # attached to any finding and silently disappears from the
            # Assessment-Results document. This indicates a crosswalk
            # entry whose mapping dict is missing ``control_id`` - a data
            # bug in the crosswalk, not a runtime failure - so warn with
            # the observation UUID so an MRM reviewer can trace back to
            # which metric/regime produced it.
            _LOG.warning(
                "assessment.observation_missing_control_id",
                observation_uuid=obs.uuid,
                observation_title=obs.title,
            )

    findings: list[ARFinding] = []
    for control_id, obs_list in sorted(by_control.items()):
        # Worst severity across all metrics feeding this control
        worst = Severity.PASS
        for obs in obs_list:
            for ev in obs.relevant_evidence:
                for p in ev.props:
                    if p.name == "metric":
                        sev = severity_by_metric.get(p.value, Severity.PASS)
                        if sev == Severity.FINDING:
                            worst = Severity.FINDING
                        elif sev == Severity.OBSERVATION and worst != Severity.FINDING:
                            worst = Severity.OBSERVATION

        n_metrics = len(obs_list)
        status = _SEVERITY_STATUS[worst]
        description = (
            f"Control {control_id}: {worst.value.upper()} — "
            f"based on {n_metrics} metric observation(s). "
            f"{'Remediation required.' if worst == Severity.FINDING else 'No blocking issues.'}"
        )

        findings.append(
            ARFinding.model_validate(
                {
                    "uuid": _gen_uuid(),
                    "title": f"{control_id} assessment",
                    "description": description,
                    "target": {
                        "type": "objective-id",
                        "target-id": control_id,
                        "status": {"state": status},
                    },
                    "related-observations": [{"observation-uuid": obs.uuid} for obs in obs_list],
                    "props": [
                        ARProp(name="severity", value=worst.value),
                    ],
                }
            )
        )

    return findings


def build_assessment_results(
    record: BenchmarkResult,
    *,
    title: str | None = None,
    classifier: FindingClassifier | None = None,
    regime_filter: set[Regime] | None = None,
) -> OscalAssessmentResults:
    """Build OSCAL Assessment-Results from a benchmark record.

    Parameters
    ----------
    record:
        One persisted benchmark result with metrics.
    title:
        Optional document title override.
    classifier:
        Finding classifier for severity banding. Default OCC 2011-12.
    regime_filter:
        If provided, only include these regimes. Default: all six.
    """
    _LOG.info(
        "assessment.build.start",
        backend=record.backend,
        estimator=record.estimator,
        dataset=record.dataset,
        n_metrics=len(record.metrics),
        regime_filter=sorted(str(r) for r in regime_filter) if regime_filter else "all",
    )
    report = (classifier or FindingClassifier()).classify(record)
    crosswalk = get_crosswalk()

    if regime_filter:
        crosswalk = tuple(
            CrosswalkEntry(
                metric=e.metric,
                trust_dimension=e.trust_dimension,
                mappings={r: c for r, c in e.mappings.items() if r in regime_filter},
            )
            for e in crosswalk
            if any(r in regime_filter for r in e.mappings)
        )

    now = _now_iso()
    observations = _build_observations(record, report, crosswalk, now)
    findings = _build_findings(observations, report)

    regime_names = sorted(str(r) for r in (regime_filter or set(regimes())))

    result = ARResult.model_validate(
        {
            "uuid": _gen_uuid(),
            "title": (
                f"Assessment of {record.backend}/{record.estimator} on "
                f"{record.dataset} across {', '.join(regime_names)}"
            ),
            "description": (
                f"Automated assessment of LLM uncertainty pipeline "
                f"({record.backend}/{record.estimator}) on dataset "
                f"{record.dataset!r} ({record.n} examples, seed {record.seed}). "
                f"Generated by llm-uncertainty-banking v{record.repo_version}."
            ),
            "start": record.timestamp,
            "end": now,
            "reviewed-controls": {
                "description": (
                    f"Controls reviewed across {', '.join(regime_names)} "
                    f"using {len(observations)} metric observations."
                ),
                "control-selections": [
                    {
                        "description": (
                            f"All controls from {', '.join(regime_names)} "
                            f"that map to LUB calibration metrics."
                        ),
                    }
                ],
            },
            "findings": findings,
            "observations": observations,
            "props": [
                ARProp(name="backend", value=record.backend),
                ARProp(name="estimator", value=record.estimator),
                ARProp(name="dataset", value=record.dataset),
                ARProp(name="n_observations", value=str(len(observations))),
                ARProp(name="n_findings", value=str(len(findings))),
                ARProp(
                    name="worst_severity",
                    value=report.worst.value,
                ),
            ],
        }
    )

    doc_title = title or (
        f"LUB Assessment — {record.backend}/{record.estimator} on {record.dataset}"
    )

    ar = OscalAssessmentResults.model_validate(
        {
            "uuid": _gen_uuid(),
            "metadata": {
                "title": doc_title,
                "last-modified": now,
                "version": record.repo_version,
                "oscal-version": _OSCAL_VERSION,
            },
            "import-ap": {
                "href": "#lub-assessment-plan",
            },
            "results": [result.model_dump(by_alias=True)],
        }
    )
    _LOG.info(
        "assessment.build.done",
        n_observations=len(observations),
        n_findings=len(findings),
        worst_severity=report.worst.value,
    )
    return ar


def render_assessment_json(
    record: BenchmarkResult,
    *,
    indent: int = 2,
    title: str | None = None,
    classifier: FindingClassifier | None = None,
    regime_filter: set[Regime] | None = None,
) -> str:
    """Return OSCAL Assessment-Results as a JSON string.

    Output conforms to the OSCAL 1.1.2 top-level envelope:
    ``{"assessment-results": { uuid, metadata, results }}``.
    """
    ar = build_assessment_results(
        record,
        title=title,
        classifier=classifier,
        regime_filter=regime_filter,
    )
    payload = ar.model_dump(by_alias=True, exclude_none=True)
    envelope: dict[str, Any] = {"assessment-results": payload}
    return _json.dumps(envelope, indent=indent)


__all__ = [
    "ARFinding",
    "ARMetadata",
    "ARObservation",
    "ARProp",
    "ARRelevantEvidence",
    "ARResult",
    "ARTarget",
    "ARTargetStatus",
    "OscalAssessmentResults",
    "build_assessment_results",
    "render_assessment_json",
]
