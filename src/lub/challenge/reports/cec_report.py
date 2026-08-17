# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge.reports.cec_report -- assemble periodic CEC report.

Composes:

* :mod:`lub.challenge.replay`             -- counterfactual findings
* :mod:`lub.challenge.drift_reasoning`    -- explained drift events
* :mod:`lub.challenge.meta_calibration`   -- CEC's own calibration health
* :mod:`lub.benchmarks.provenance`        -- signed provenance

Spec: planning/24_CEC_Spec_2026-04-25.md section 1.4 + section 4 step 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from lub.challenge.drift_reasoning import DriftHypothesis, explain_drift_event
from lub.challenge.meta_calibration import CalibrationCurve, MetaCalibrator
from lub.challenge.replay import (
    AlternativeThreshold,
    ReplayAlternative,
    ReplayEngine,
    ReplayReport,
)


@dataclass(frozen=True)
class CECReport:
    """Periodic Continuous Effective Challenge report."""

    period_start: datetime
    period_end: datetime
    replay_summary: list[Any] = field(default_factory=list)
    drift_hypotheses: list[Any] = field(default_factory=list)
    meta_calibration_snapshot: Any = None
    recommendations: list[str] = field(default_factory=list)
    signed_provenance: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _list_drift_events_in_window(
    period_start: datetime,
    period_end: datetime,
    ledger: Any,
    evidence_store: Any,
) -> list[str]:
    """Return drift event ids whose ``detected_at`` falls in the window."""

    def _in_window(payload: Any) -> bool:
        ts = (payload or {}).get("detected_at")
        if ts is None:
            return True
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            return True
        if t.tzinfo is not None:
            t = t.replace(tzinfo=None)
        return period_start <= t < period_end

    out: list[str] = []
    for source in (ledger, evidence_store):
        events = getattr(source, "drift_events", None)
        if isinstance(events, dict):
            for k, v in events.items():
                if _in_window(v):
                    out.append(str(k))
    seen: set[str] = set()
    deduped: list[str] = []
    for k in out:
        if k not in seen:
            deduped.append(k)
            seen.add(k)
    return deduped


def _generate_recommendations(
    replay_summary: list[ReplayReport],
    drift_hypotheses: list[DriftHypothesis],
    meta_curve: CalibrationCurve | None,
) -> list[str]:
    recs: list[str] = []

    for rr in replay_summary:
        delta_abst = rr.counterfactual_abstention_rate - rr.baseline_abstention_rate
        if abs(delta_abst) >= 0.05:
            kind = type(rr.alternative).__name__
            direction = "raises" if delta_abst > 0 else "lowers"
            recs.append(
                f"Replay finding ({kind}): the alternative {direction} "
                f"abstention by {delta_abst * 100:+.1f} percentage points "
                "over the period -- consider a Tier-2 spot check."
            )

    for dh in drift_hypotheses:
        severity = (dh.metadata or {}).get("severity")
        if severity == "significant":
            recs.append(
                f"Drift event {dh.drift_event_id}: significant PSI; "
                "trigger an out-of-cycle calibration review."
            )
        elif severity == "moderate":
            recs.append(
                f"Drift event {dh.drift_event_id}: moderate PSI; "
                "monitor across the next two periods."
            )

    if meta_curve is not None and meta_curve.ece > 0.10:
        recs.append(
            f"Meta-calibration ECE {meta_curve.ece:.2f} exceeds 0.10; "
            "CEC's own confidence numbers are over- or under-stated and "
            "should be re-fit before the next report."
        )

    if not recs:
        recs.append(
            "No material findings in this period -- model risk posture "
            "is within OCC 2011-12 stability bounds."
        )
    return recs


def _capture_provenance() -> dict[str, Any]:
    """Best-effort signed provenance via :mod:`lub.benchmarks.provenance`."""
    try:
        from lub.benchmarks.provenance import Provenance

        prov = Provenance.capture()
        return {
            "repo_version": prov.repo_version,
            "python_version": prov.python_version,
            "git_sha": prov.git_sha,
            "package_versions_hash": _hash_pkg_map(prov.package_versions),
            "n_packages": len(prov.package_versions),
        }
    except Exception:  # pragma: no cover -- defensive
        return {"repo_version": "unknown", "git_sha": None}


def _hash_pkg_map(pkgs: dict[str, str]) -> str:
    import hashlib

    payload = "\n".join(f"{k}=={v}" for k, v in sorted(pkgs.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assemble_cec_report(
    period_start: datetime,
    period_end: datetime,
    ledger: Any,
    evidence_store: Any,
    *,
    replay_alternatives: list[ReplayAlternative] | None = None,
) -> CECReport:
    """Compose a :class:`CECReport` for the period."""
    if period_end <= period_start:
        raise ValueError("period_end must be strictly after period_start")

    alternatives: list[ReplayAlternative] = (
        replay_alternatives if replay_alternatives is not None else [AlternativeThreshold(0.85)]
    )

    engine = ReplayEngine(ledger=ledger)
    replay_summary: list[ReplayReport] = [
        engine.replay_window(period_start, period_end, alt) for alt in alternatives
    ]

    drift_ids = _list_drift_events_in_window(period_start, period_end, ledger, evidence_store)
    drift_hypotheses: list[DriftHypothesis] = [
        explain_drift_event(eid, ledger=ledger, evidence_store=evidence_store) for eid in drift_ids
    ]

    meta_curve: CalibrationCurve | None = None
    try:
        mc = MetaCalibrator(ledger=ledger)
        meta_curve = mc.reliability_curve()
    except Exception:  # pragma: no cover -- defensive
        meta_curve = None

    recommendations = _generate_recommendations(replay_summary, drift_hypotheses, meta_curve)

    return CECReport(
        period_start=period_start,
        period_end=period_end,
        replay_summary=replay_summary,
        drift_hypotheses=drift_hypotheses,
        meta_calibration_snapshot=meta_curve,
        recommendations=recommendations,
        signed_provenance=_capture_provenance(),
    )


def render_markdown(report: CECReport) -> str:
    """Render a :class:`CECReport` to Markdown via the bundled Jinja template."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).with_name("templates")
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(disabled_extensions=("md", "j2")),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template("cec_report.md.j2")
    return template.render(report=report)


__all__ = ["CECReport", "assemble_cec_report", "render_markdown"]
