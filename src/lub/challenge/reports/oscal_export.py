# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge.reports.oscal_export -- emit CEC report as OSCAL JSON.

Tags the assessment-results as AIRMF MANAGE 4.1 (continuous
monitoring) + MEASURE 2.7 (re-assessment over time) evidence.

Spec: planning/24_CEC_Spec_2026-04-25.md section 1.4 + section 4 step 6.
"""

from __future__ import annotations

from typing import Any

from lub.reports.mapping import get_rmf_mapping
from lub.reports.oscal_common import (
    OSCAL_VERSION,
    gen_uuid,
    now_iso,
)


def _airmf_props() -> list[dict[str, str]]:
    """Return AIRMF MANAGE 4.1 + MEASURE 2.7 control properties."""
    rmf = get_rmf_mapping()
    props: list[dict[str, str]] = []
    for code in ("MANAGE 4.1", "MEASURE 2.7"):
        entry = rmf.get(code)
        desc = entry["description"] if entry else f"AIRMF {code}"
        props.append(
            {
                "name": "airmf-control",
                "value": code,
                "ns": "https://lub.dev/ns/airmf",
            }
        )
        props.append(
            {
                "name": "airmf-description",
                "value": desc,
                "ns": "https://lub.dev/ns/airmf",
            }
        )
    return props


def _replay_observations(report: Any) -> list[dict[str, Any]]:
    obs: list[dict[str, Any]] = []
    for rr in getattr(report, "replay_summary", []):
        obs.append(
            {
                "uuid": gen_uuid(),
                "title": (f"Replay: {type(rr.alternative).__name__} ({rr.sample_size} rows)"),
                "description": (
                    f"Counterfactual abstention {rr.counterfactual_abstention_rate:.3f} "
                    f"vs baseline {rr.baseline_abstention_rate:.3f}; "
                    f"cost delta per 1k = {rr.cost_delta_estimate:.4f} USD."
                ),
                "methods": ["TEST"],
                "types": ["evidence"],
                "collected": now_iso(),
                "props": [
                    {
                        "name": "baseline_abstention_rate",
                        "value": f"{rr.baseline_abstention_rate:.4f}",
                    },
                    {
                        "name": "counterfactual_abstention_rate",
                        "value": f"{rr.counterfactual_abstention_rate:.4f}",
                    },
                    {
                        "name": "cost_delta_estimate_usd_per_1k",
                        "value": f"{rr.cost_delta_estimate:.4f}",
                    },
                    {
                        "name": "sample_size",
                        "value": str(rr.sample_size),
                    },
                ],
            }
        )
    return obs


def _drift_observations(report: Any) -> list[dict[str, Any]]:
    obs: list[dict[str, Any]] = []
    for dh in getattr(report, "drift_hypotheses", []):
        obs.append(
            {
                "uuid": gen_uuid(),
                "title": f"Drift hypothesis: {dh.drift_event_id}",
                "description": dh.hypothesis,
                "methods": ["EXAMINE"],
                "types": ["evidence"],
                "collected": now_iso(),
                "props": [
                    {
                        "name": "psi",
                        "value": f"{(dh.metadata or {}).get('psi', 0.0):.4f}",
                    },
                    {
                        "name": "severity",
                        "value": str((dh.metadata or {}).get("severity", "unknown")),
                    },
                    {
                        "name": "similarity_score",
                        "value": f"{dh.similarity_score:.4f}",
                    },
                    {
                        "name": "n_support_evidence",
                        "value": str(len(dh.support_evidence_ids)),
                    },
                ],
            }
        )
    return obs


def _meta_calibration_observations(report: Any) -> list[dict[str, Any]]:
    snap = getattr(report, "meta_calibration_snapshot", None)
    if snap is None:
        return []
    return [
        {
            "uuid": gen_uuid(),
            "title": "Meta-calibration snapshot",
            "description": (
                f"Reliability curve over {len(snap.bins)} bin(s); ECE = {snap.ece:.4f}."
            ),
            "methods": ["TEST"],
            "types": ["evidence"],
            "collected": now_iso(),
            "props": [
                {"name": "meta_calibration_ece", "value": f"{snap.ece:.4f}"},
                {"name": "n_bins", "value": str(len(snap.bins))},
            ],
        }
    ]


def to_oscal_assessment_results(cec_report: Any) -> dict[str, Any]:
    """Render a :class:`CECReport` as OSCAL Assessment-Results JSON."""
    if cec_report is None:
        raise ValueError("cec_report must not be None")

    period_start = cec_report.period_start.isoformat()
    period_end = cec_report.period_end.isoformat()

    observations = (
        _replay_observations(cec_report)
        + _drift_observations(cec_report)
        + _meta_calibration_observations(cec_report)
    )

    findings = [
        {
            "uuid": gen_uuid(),
            "title": (
                "Continuous Effective Challenge -- periodic finding "
                f"({period_start} -> {period_end})"
            ),
            "description": (
                f"{len(cec_report.replay_summary)} replay scenario(s) and "
                f"{len(cec_report.drift_hypotheses)} drift hypothesis(es) "
                "produced for this period."
            ),
            "target": {
                "type": "objective-id",
                "target-id": "AIRMF-MANAGE-4.1",
                "props": _airmf_props(),
            },
            "related-observations": [{"observation-uuid": o["uuid"]} for o in observations],
        }
    ]

    result_block: dict[str, Any] = {
        "uuid": gen_uuid(),
        "title": "CEC Periodic Result",
        "description": (
            f"Period {period_start} -> {period_end}: aggregate continuous "
            "effective-challenge evidence emitted by lub.challenge."
        ),
        "start": period_start,
        "end": period_end,
        "props": _airmf_props()
        + [
            {
                "name": "report-kind",
                "value": "cec-periodic",
                "ns": "https://lub.dev/ns/challenge",
            },
            {
                "name": "n_recommendations",
                "value": str(len(cec_report.recommendations)),
            },
        ],
        "observations": observations,
        "findings": findings,
        "reviewed-controls": {
            "control-selections": [
                {
                    "include-controls": [
                        {"control-id": "manage-4.1"},
                        {"control-id": "measure-2.7"},
                    ]
                }
            ]
        },
    }

    metadata: dict[str, Any] = {
        "title": "CEC Assessment Results",
        "last-modified": now_iso(),
        "version": cec_report.signed_provenance.get("repo_version", "0.0.0+local"),
        "oscal-version": OSCAL_VERSION,
    }

    envelope: dict[str, Any] = {
        "assessment-results": {
            "uuid": gen_uuid(),
            "metadata": metadata,
            "results": [result_block],
        }
    }
    return envelope


__all__ = ["to_oscal_assessment_results"]
