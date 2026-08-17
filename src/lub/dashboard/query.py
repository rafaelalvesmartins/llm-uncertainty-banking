# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.dashboard.query -- assemble the data snapshot the dashboard renders.

Post pass-33 refactor: this module is **generic over any SnapshotSource**.
It contains no SQL, no ledger-specific knowledge, and no schema strings.
Concrete data-source code lives in :mod:`lub.dashboard.ledger_source` (the
default implementation) and any plug-in sources users register.

Back-compat: ``build_snapshot(ledger, ...)`` still accepts a
:class:`~lub.ledger.Ledger` directly -- it transparently wraps it in a
:class:`~lub.dashboard.ledger_source.LedgerSnapshotSource`. Callers that
want to use a different source (CSV, Prometheus, in-memory test double)
pass an instance of any object satisfying
:class:`~lub.dashboard.protocols.SnapshotSource`.

Spec: planning/29_Dashboard_Spec_2026-04-25.md section 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from lub.dashboard.protocols import SnapshotSource

__all__ = ["DashboardSnapshot", "build_snapshot"]


@dataclass(frozen=True)
class DashboardSnapshot:
    """One rendering's worth of data for the dashboard.

    Fields are intentionally JSON-friendly: primitives + lists/dicts of
    primitives. The composable artifacts (``cec_report``,
    ``oscal_envelope``) are typed ``Any`` so consumers without
    ``lub.challenge`` available can still construct a snapshot.
    """

    period_start: datetime
    period_end: datetime
    tenant: str
    git_sha: str

    # KPI strip
    decisions_in_window: int = 0
    abstention_rate: float = 0.0
    correctness_rate: float | None = None
    n_outcomes_recorded: int = 0
    meta_calibration_ece: float | None = None

    # Composable artifacts
    cec_report: Any = None
    oscal_envelope: dict[str, Any] = field(default_factory=dict)
    recent_decisions: list[dict[str, Any]] = field(default_factory=list)


def _coerce_to_source(obj: Any) -> SnapshotSource | None:
    """Return *obj* if it satisfies SnapshotSource; otherwise wrap it
    in a LedgerSnapshotSource if it looks like a Ledger; otherwise None.

    The wrapping is the back-compat shim: legacy callers that passed a
    :class:`~lub.ledger.Ledger` keep working without code changes.
    """
    if isinstance(obj, SnapshotSource):
        return obj
    if hasattr(obj, "_conn"):
        # Late import so a stripped-down install (no lub.ledger) still
        # works -- you just have to pass a SnapshotSource directly.
        from lub.dashboard.ledger_source import LedgerSnapshotSource

        try:
            return LedgerSnapshotSource(obj)
        except TypeError:
            return None
    return None


def _try_compose_cec_report(
    ledger: Any,
    evidence_store: Any,
    *,
    period_start: datetime,
    period_end: datetime,
) -> tuple[Any, dict[str, Any]]:
    """Best-effort compose a CECReport + OSCAL envelope.

    Imported lazily so the dashboard works even on installs that disable
    Phase 2 (e.g. a stripped-down distribution that ships only L1-L5).
    Any exception is swallowed with a marker so the dashboard still
    renders the rest of the snapshot.
    """
    try:
        from lub.challenge import assemble_cec_report
        from lub.challenge.reports.oscal_export import (
            to_oscal_assessment_results,
        )
    except ImportError:
        return None, {}
    try:
        report = assemble_cec_report(
            ledger=ledger,
            evidence_store=evidence_store,
            period_start=period_start,
            period_end=period_end,
        )
    except Exception as exc:  # noqa: BLE001 -- defensive
        return None, {"_error": f"cec_report.compose: {type(exc).__name__}: {exc}"}
    try:
        envelope = to_oscal_assessment_results(report)
    except Exception as exc:  # noqa: BLE001
        envelope = {"_error": f"oscal.compose: {type(exc).__name__}: {exc}"}
    return report, envelope


def build_snapshot(
    source: Any,
    evidence_store: Any | None = None,
    *,
    period_start: datetime,
    period_end: datetime,
    tenant: str = "default",
    git_sha: str = "unknown",
    recent_limit: int = 25,
) -> DashboardSnapshot:
    """Compose a :class:`DashboardSnapshot` from any data source.

    Args:
        source: Any object satisfying
            :class:`~lub.dashboard.protocols.SnapshotSource`. For
            back-compat, an :class:`~lub.ledger.Ledger` is also accepted
            and gets wrapped in :class:`LedgerSnapshotSource` automatically.
        evidence_store: Optional store forwarded to
            ``lub.challenge.assemble_cec_report`` when available. Pass
            ``None`` to skip CEC composition entirely.
        period_start: Inclusive lower bound for the KPI window.
        period_end: Inclusive upper bound.
        tenant: Tenant identifier; pass-through, used by the renderer.
        git_sha: Git SHA of the producing build; pass-through.
        recent_limit: How many recent decisions to include.

    Returns:
        A populated :class:`DashboardSnapshot`. On an empty / unrecognised
        source this returns a snapshot with zero counts and ``None`` for
        any rate-style KPI; it never raises.
    """
    snap_source = _coerce_to_source(source)
    if snap_source is None:
        # Honest empty snapshot; no fake data.
        return DashboardSnapshot(
            period_start=period_start,
            period_end=period_end,
            tenant=tenant,
            git_sha=git_sha,
        )

    decisions_in_window, abstention_rate = snap_source.kpi_decisions(
        period_start,
        period_end,
    )
    n_outcomes_recorded, correctness_rate = snap_source.kpi_outcomes(
        period_start,
        period_end,
    )
    meta_cal_ece = snap_source.kpi_meta_calibration_ece()
    recent = snap_source.recent_decisions(period_start, period_end, recent_limit)

    cec_report: Any = None
    oscal_envelope: dict[str, Any] = {}
    if evidence_store is not None:
        # CEC composition still uses the underlying ledger if the source
        # was wrapped from one; otherwise skip (CEC is ledger-coupled by
        # design and not part of the SnapshotSource Protocol).
        underlying = getattr(snap_source, "_ledger", source)
        cec_report, oscal_envelope = _try_compose_cec_report(
            underlying,
            evidence_store,
            period_start=period_start,
            period_end=period_end,
        )

    return DashboardSnapshot(
        period_start=period_start,
        period_end=period_end,
        tenant=tenant,
        git_sha=git_sha,
        decisions_in_window=decisions_in_window,
        abstention_rate=abstention_rate,
        correctness_rate=correctness_rate,
        n_outcomes_recorded=n_outcomes_recorded,
        meta_calibration_ece=meta_cal_ece,
        cec_report=cec_report,
        oscal_envelope=oscal_envelope,
        recent_decisions=recent,
    )
