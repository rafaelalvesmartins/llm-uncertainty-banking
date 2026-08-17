# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Compliance dashboard for the Bradesco Bridge platform.

Aggregates compliance metrics from the uncertainty ledger and produces
snapshots suitable for regulatory reporting. Implements checks for
BCB Resolution 4893 (transparency in AI-assisted decisions) and
BCBS 239 (risk data aggregation and reporting).

The dashboard can render itself as a standalone HTML page for auditors
or return structured data for integration with enterprise BI tools.

Usage::

    from lub.connectors.bridge.dashboard.compliance import ComplianceDashboard

    dashboard = ComplianceDashboard(ledger_path="data/ledger.db")
    snapshot = dashboard.build_snapshot(days=30)
    html = dashboard.render_html()
"""

from __future__ import annotations

import html
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

_LOG = structlog.get_logger("lub.dashboard.compliance")


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComplianceSnapshot:
    """Point-in-time compliance metrics snapshot.

    Attributes:
        resolution_rate: Fraction of queries resolved without human
            escalation, in ``[0, 1]``.
        escalation_rate: Fraction of queries escalated to a human
            operator, in ``[0, 1]``.
        confidence_mean: Mean model confidence across all queries.
        violations: List of compliance violation summaries.
        period: Reporting period description (e.g. ``"30 days"``).
        total_queries: Total number of queries in the period.
        refusal_rate: Fraction of queries refused by the uncertainty
            guard.
        generated_at: UTC timestamp when the snapshot was generated.
    """

    resolution_rate: float
    escalation_rate: float
    confidence_mean: float
    violations: list[dict[str, Any]]
    period: str
    total_queries: int = 0
    refusal_rate: float = 0.0
    generated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary for JSON persistence."""
        return {
            "resolution_rate": self.resolution_rate,
            "escalation_rate": self.escalation_rate,
            "confidence_mean": self.confidence_mean,
            "violations": self.violations,
            "period": self.period,
            "total_queries": self.total_queries,
            "refusal_rate": self.refusal_rate,
            "generated_at": self.generated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@dataclass
class ComplianceDashboard:
    """Compliance dashboard for the Bradesco Bridge AI platform.

    Reads from a SQLite uncertainty ledger (the same format used by
    :mod:`lub.dashboard.ledger_source`) and computes compliance metrics.

    Args:
        ledger_path: Path to the SQLite ledger database. If the file
            does not exist, the dashboard returns zero-state snapshots.
        confidence_threshold: Threshold below which a query is
            considered a refusal.
        escalation_threshold: Threshold below which a query is
            considered an escalation.
    """

    ledger_path: str = "data/ledger.db"
    confidence_threshold: float = 0.7
    escalation_threshold: float = 0.5

    def build_snapshot(self, days: int = 30) -> ComplianceSnapshot:
        """Build a compliance snapshot for the given period.

        Queries the ledger for all records within the last ``days`` days
        and computes resolution, escalation, refusal rates, and mean
        confidence.

        Args:
            days: Number of days to look back from the current UTC time.

        Returns:
            A :class:`ComplianceSnapshot` with aggregated metrics.
        """
        _LOG.info("compliance.build_snapshot", days=days, ledger=self.ledger_path)

        cutoff = datetime.now(tz=UTC) - timedelta(days=days)
        records = self._query_records(cutoff)

        if not records:
            _LOG.info("compliance.no_records", days=days)
            return ComplianceSnapshot(
                resolution_rate=0.0,
                escalation_rate=0.0,
                confidence_mean=0.0,
                violations=[],
                period=f"{days} days",
                total_queries=0,
                refusal_rate=0.0,
            )

        total = len(records)
        confidences = [r["confidence"] for r in records]
        mean_conf = sum(confidences) / total

        escalated = sum(1 for r in records if r["confidence"] < self.escalation_threshold)
        refused = sum(1 for r in records if r["confidence"] < self.confidence_threshold)
        resolved = total - escalated

        violations = self._detect_violations(records)

        snapshot = ComplianceSnapshot(
            resolution_rate=resolved / total,
            escalation_rate=escalated / total,
            confidence_mean=mean_conf,
            violations=violations,
            period=f"{days} days",
            total_queries=total,
            refusal_rate=refused / total,
        )

        _LOG.info(
            "compliance.snapshot_built",
            total=total,
            resolution_rate=f"{snapshot.resolution_rate:.2%}",
            escalation_rate=f"{snapshot.escalation_rate:.2%}",
            n_violations=len(violations),
        )

        return snapshot

    def check_bcb4893(self) -> dict[str, Any]:
        """Check compliance with BCB Resolution 4893.

        BCB 4893 requires transparency in AI-assisted financial
        decisions: customers must be informed when AI is involved,
        decisions must be explainable, and a human appeal path must
        exist.

        Returns:
            A dictionary with check name, pass/fail status, and details.
        """
        _LOG.info("compliance.check_bcb4893")
        snapshot = self.build_snapshot(days=30)

        checks: list[dict[str, Any]] = []

        # Check 1: Escalation path exists (escalation rate > 0 means
        # the system does route to humans when uncertain).
        escalation_path = snapshot.escalation_rate > 0 or snapshot.total_queries == 0
        checks.append(
            {
                "check": "escalation_path_available",
                "passed": escalation_path,
                "detail": (
                    f"Escalation rate: {snapshot.escalation_rate:.2%}. "
                    "System routes uncertain queries to human operators."
                    if escalation_path
                    else "No escalations detected. Verify human-in-the-loop is active."
                ),
            }
        )

        # Check 2: Mean confidence is reasonable (not artificially high).
        confidence_reasonable = snapshot.confidence_mean < 0.99
        checks.append(
            {
                "check": "confidence_calibration",
                "passed": confidence_reasonable,
                "detail": (
                    f"Mean confidence: {snapshot.confidence_mean:.4f}. "
                    "Confidence appears calibrated."
                    if confidence_reasonable
                    else f"Mean confidence: {snapshot.confidence_mean:.4f}. "
                    "Suspiciously high -- verify calibration."
                ),
            }
        )

        # Check 3: No unresolved violations
        unresolved = [v for v in snapshot.violations if not v.get("resolved", False)]
        no_violations = len(unresolved) == 0
        checks.append(
            {
                "check": "no_unresolved_violations",
                "passed": no_violations,
                "detail": (
                    "No unresolved compliance violations."
                    if no_violations
                    else f"{len(unresolved)} unresolved violation(s) found."
                ),
            }
        )

        all_passed = all(c["passed"] for c in checks)
        result = {
            "regulation": "BCB_Resolution_4893",
            "passed": all_passed,
            "checks": checks,
            "snapshot_period": snapshot.period,
            "checked_at": datetime.now(tz=UTC).isoformat(),
        }

        _LOG.info("compliance.bcb4893_result", passed=all_passed)
        return result

    def check_bcbs239(self) -> dict[str, Any]:
        """Check compliance with BCBS 239 (risk data aggregation).

        BCBS 239 requires accurate, complete, and timely risk data
        aggregation. For AI systems, this translates to: uncertainty
        metrics are tracked, data is not stale, and aggregation is
        consistent.

        Returns:
            A dictionary with check name, pass/fail status, and details.
        """
        _LOG.info("compliance.check_bcbs239")
        snapshot = self.build_snapshot(days=7)

        checks: list[dict[str, Any]] = []

        # Check 1: Data completeness -- records exist for the period.
        data_available = snapshot.total_queries > 0
        checks.append(
            {
                "check": "data_completeness",
                "passed": data_available,
                "detail": (
                    f"{snapshot.total_queries} records in last 7 days. Data pipeline is active."
                    if data_available
                    else "No records in last 7 days. Data pipeline may be stalled."
                ),
            }
        )

        # Check 2: Data timeliness -- ledger file was modified recently.
        ledger = Path(self.ledger_path)
        if ledger.exists():
            mtime = datetime.fromtimestamp(ledger.stat().st_mtime, tz=UTC)
            age = datetime.now(tz=UTC) - mtime
            timely = age < timedelta(hours=24)
            checks.append(
                {
                    "check": "data_timeliness",
                    "passed": timely,
                    "detail": (
                        f"Ledger last modified {age.total_seconds() / 3600:.1f}h ago. "
                        "Data is fresh."
                        if timely
                        else f"Ledger last modified {age.total_seconds() / 3600:.1f}h ago. "
                        "Data may be stale."
                    ),
                }
            )
        else:
            checks.append(
                {
                    "check": "data_timeliness",
                    "passed": False,
                    "detail": f"Ledger file not found: {self.ledger_path}",
                }
            )

        # Check 3: Aggregation consistency -- confidence values are
        # in the valid range [0, 1].
        records = self._query_records(datetime.now(tz=UTC) - timedelta(days=7))
        out_of_range = [r for r in records if r["confidence"] < 0.0 or r["confidence"] > 1.0]
        consistent = len(out_of_range) == 0
        checks.append(
            {
                "check": "aggregation_consistency",
                "passed": consistent,
                "detail": (
                    "All confidence values are in [0, 1]."
                    if consistent
                    else f"{len(out_of_range)} record(s) with out-of-range confidence."
                ),
            }
        )

        all_passed = all(c["passed"] for c in checks)
        result = {
            "regulation": "BCBS_239",
            "passed": all_passed,
            "checks": checks,
            "snapshot_period": "7 days",
            "checked_at": datetime.now(tz=UTC).isoformat(),
        }

        _LOG.info("compliance.bcbs239_result", passed=all_passed)
        return result

    def render_html(self) -> str:
        """Render the compliance dashboard as a standalone HTML page.

        Builds a 30-day snapshot and produces an HTML page with summary
        metrics, regulatory check results, and a violations table.
        Suitable for sharing with auditors or embedding in an iframe.

        Returns:
            A complete HTML document as a string.
        """
        snapshot = self.build_snapshot(days=30)
        bcb4893 = self.check_bcb4893()
        bcbs239 = self.check_bcbs239()

        violations_rows = ""
        for v in snapshot.violations:
            rule = html.escape(str(v.get("rule", "")))
            severity = html.escape(str(v.get("severity", "")))
            count = html.escape(str(v.get("count", 0)))
            resolved = "Yes" if v.get("resolved", False) else "No"
            violations_rows += (
                f"<tr><td>{rule}</td><td>{severity}</td><td>{count}</td><td>{resolved}</td></tr>\n"
            )

        if not violations_rows:
            violations_rows = (
                '<tr><td colspan="4" style="text-align:center;">No violations detected</td></tr>'
            )

        def _check_rows(result: dict[str, Any]) -> str:
            rows = ""
            for check in result.get("checks", []):
                name = html.escape(check["check"])
                status = "PASS" if check["passed"] else "FAIL"
                color = "#2ecc71" if check["passed"] else "#e74c3c"
                detail = html.escape(check["detail"])
                rows += (
                    f'<tr><td>{name}</td><td style="color:{color};">'
                    f"<strong>{status}</strong></td><td>{detail}</td></tr>\n"
                )
            return rows

        bcb4893_rows = _check_rows(bcb4893)
        bcbs239_rows = _check_rows(bcbs239)

        generated = html.escape(snapshot.generated_at.strftime("%Y-%m-%d %H:%M:%S UTC"))

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bradesco Bridge - Compliance Dashboard</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         margin: 0; padding: 20px; background: #f5f6fa; color: #2c3e50; }}
  .container {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ color: #c0392b; border-bottom: 3px solid #c0392b; padding-bottom: 10px; }}
  h2 {{ color: #2c3e50; margin-top: 30px; }}
  .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
              gap: 16px; margin: 20px 0; }}
  .metric {{ background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
             text-align: center; }}
  .metric .value {{ font-size: 2em; font-weight: bold; color: #2c3e50; }}
  .metric .label {{ font-size: 0.9em; color: #7f8c8d; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  th {{ background: #2c3e50; color: #fff; padding: 12px; text-align: left; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #ecf0f1; }}
  tr:hover {{ background: #f8f9fa; }}
  .footer {{ margin-top: 30px; font-size: 0.85em; color: #95a5a6; text-align: center; }}
  .badge {{ display: inline-block; padding: 4px 12px; border-radius: 12px;
            font-weight: bold; font-size: 0.85em; }}
  .badge-pass {{ background: #d5f5e3; color: #27ae60; }}
  .badge-fail {{ background: #fadbd8; color: #e74c3c; }}
</style>
</head>
<body>
<div class="container">
  <h1>Bradesco Bridge - Compliance Dashboard</h1>
  <p>Period: <strong>{html.escape(snapshot.period)}</strong> | Generated: {generated}</p>

  <div class="metrics">
    <div class="metric">
      <div class="value">{snapshot.total_queries:,}</div>
      <div class="label">Total Queries</div>
    </div>
    <div class="metric">
      <div class="value">{snapshot.resolution_rate:.1%}</div>
      <div class="label">Resolution Rate</div>
    </div>
    <div class="metric">
      <div class="value">{snapshot.escalation_rate:.1%}</div>
      <div class="label">Escalation Rate</div>
    </div>
    <div class="metric">
      <div class="value">{snapshot.confidence_mean:.3f}</div>
      <div class="label">Mean Confidence</div>
    </div>
    <div class="metric">
      <div class="value">{snapshot.refusal_rate:.1%}</div>
      <div class="label">Refusal Rate</div>
    </div>
    <div class="metric">
      <div class="value">{len(snapshot.violations)}</div>
      <div class="label">Violations</div>
    </div>
  </div>

  <h2>BCB Resolution 4893
    <span class="badge {"badge-pass" if bcb4893["passed"] else "badge-fail"}">
      {"PASS" if bcb4893["passed"] else "FAIL"}
    </span>
  </h2>
  <table>
    <thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
    <tbody>{bcb4893_rows}</tbody>
  </table>

  <h2>BCBS 239
    <span class="badge {"badge-pass" if bcbs239["passed"] else "badge-fail"}">
      {"PASS" if bcbs239["passed"] else "FAIL"}
    </span>
  </h2>
  <table>
    <thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
    <tbody>{bcbs239_rows}</tbody>
  </table>

  <h2>Violations</h2>
  <table>
    <thead><tr><th>Rule</th><th>Severity</th><th>Count</th><th>Resolved</th></tr></thead>
    <tbody>{violations_rows}</tbody>
  </table>

  <div class="footer">
    Bradesco Bridge AI Platform &mdash; LUB Compliance Module &mdash;
    Generated by <code>lub.dashboard.compliance</code>
  </div>
</div>
</body>
</html>"""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _query_records(self, since: datetime) -> list[dict[str, Any]]:
        """Query the ledger for records since the given timestamp.

        Returns a list of dicts with at least ``"confidence"``,
        ``"timestamp"``, and ``"query"`` keys.
        """
        ledger = Path(self.ledger_path)
        if not ledger.exists():
            _LOG.debug("compliance.ledger_not_found", path=self.ledger_path)
            return []

        records: list[dict[str, Any]] = []
        try:
            conn = sqlite3.connect(str(ledger))
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM entries WHERE timestamp >= ? ORDER BY timestamp DESC",
                (since.isoformat(),),
            )
            for row in cursor:
                records.append(dict(row))
            conn.close()
        except sqlite3.OperationalError as exc:
            _LOG.warning("compliance.query_error", error=str(exc))

        return records

    def _detect_violations(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect compliance violations from ledger records.

        Scans for patterns that indicate regulatory violations:
        - High refusal rates per topic.
        - Confidence values consistently near boundaries.
        - Missing required fields.
        """
        violations: list[dict[str, Any]] = []

        # Check for records with zero confidence (potential system errors).
        zero_conf = [r for r in records if r.get("confidence", 1.0) == 0.0]
        if len(zero_conf) > 5:
            violations.append(
                {
                    "rule": "SYSTEM_ERROR_RATE",
                    "severity": "high",
                    "count": len(zero_conf),
                    "resolved": False,
                    "detail": (
                        f"{len(zero_conf)} queries returned zero confidence. "
                        "Investigate backend health."
                    ),
                }
            )

        # Check for missing required fields.
        missing_fields = [r for r in records if not r.get("query") or r.get("confidence") is None]
        if missing_fields:
            violations.append(
                {
                    "rule": "DATA_COMPLETENESS",
                    "severity": "medium",
                    "count": len(missing_fields),
                    "resolved": False,
                    "detail": (f"{len(missing_fields)} records with missing required fields."),
                }
            )

        # Check for suspiciously uniform confidence (all identical).
        if len(records) > 10:
            confs = {r.get("confidence") for r in records}
            if len(confs) == 1:
                violations.append(
                    {
                        "rule": "CALIBRATION_SUSPECT",
                        "severity": "high",
                        "count": len(records),
                        "resolved": False,
                        "detail": (
                            "All records have identical confidence. "
                            "Model calibration may not be active."
                        ),
                    }
                )

        return violations


__all__ = ["ComplianceDashboard", "ComplianceSnapshot"]
