# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Audit trail for every AI decision in the Bradesco Bridge platform.

A separate, append-only ledger of every :class:`~lub.bridge.BridgeResult`
produced by :class:`~lub.bridge.BridgePlatform`. This module is the
single source of truth used to demonstrate compliance with three
regulatory regimes that govern Bradesco's automated channels:

* **BCB Resolução 4.893** — cyber-resilience and operational risk. The
  central bank requires that every automated customer interaction be
  reconstructable end-to-end, including the model that produced it and
  the confidence level on which the bank acted.
* **BCBS 239** — risk-data aggregation. Decisions taken by AI on behalf
  of the bank must be queryable across customers, agents, and time
  windows so risk roll-ups remain consistent.
* **SR 11-7** (US Federal Reserve guidance on model risk management) —
  every model output that influences a customer-facing decision needs an
  immutable record retained for the model's lifecycle, including the
  exact estimator confidence and policy decision that gated the answer.

Design contract
---------------

The trail is **append-only**: once :meth:`AuditTrail.log_decision`
returns, the entry is durable in the backing JSONL file (an ``fsync``
is performed) and the in-memory cache holds a frozen copy. There is no
public API to mutate or delete entries — the file is opened in
``"a"`` mode and never truncated. Operators who must redact a record
(e.g., LGPD right-to-erasure for a customer who left the bank) use an
out-of-band tool that takes ops approval; doing so from Python code
would defeat the audit guarantee this module exists to provide.

The collector is intentionally transport-agnostic: it writes a local
JSONL file and exposes :meth:`export_csv` for regulator-friendly
tabular output. Shipping the JSONL to a SIEM or compliance lake is the
caller's responsibility — keeping that concern out of this module keeps
the audit path itself dependency-free and trivially testable.
"""

from __future__ import annotations

import csv
import json
import os
import threading
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from lub.connectors.bridge import AgentResponse, AgentRole, BridgeResult, EscalationReason
from lub.guard import GuardResult, PolicyDecision

__all__ = [
    "AuditDecision",
    "AuditEntry",
    "AuditTrail",
    "AuditTrailError",
]

_LOG = structlog.get_logger("lub.bridge.audit")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AuditTrailError(RuntimeError):
    """Raised when the audit trail cannot fulfil its durability contract.

    Because a banking decision without a durable audit record is itself
    a compliance breach (BCB 4893 §III), the trail prefers to surface a
    failure loudly rather than silently drop entries. Callers should
    treat any :class:`AuditTrailError` as a stop-the-line incident.
    """


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


# ``AuditDecision`` mirrors :class:`PolicyDecision` plus ``ESCALATE`` so the
# audit record carries a single column the regulator can filter on without
# needing to join across the guard's policy outcome and the platform's
# escalation flag. We avoid extending ``PolicyDecision`` itself because the
# guard layer must remain free of platform-level concepts.
class AuditDecision:
    """Enumeration of decision values written to the trail.

    Defined as a class with string constants (rather than ``StrEnum``) so
    Pydantic v2's strict-string validation accepts the value coming out
    of either an enum member or a serialized JSON string when entries
    are reloaded from disk.
    """

    PASSTHROUGH = "passthrough"
    FLAG = "flag"
    ABSTAIN = "abstain"
    RAISE = "raise"
    ESCALATE = "escalate"
    UNKNOWN = "unknown"

    _VALUES = frozenset({PASSTHROUGH, FLAG, ABSTAIN, RAISE, ESCALATE, UNKNOWN})

    @classmethod
    def values(cls) -> frozenset[str]:
        return cls._VALUES


class AuditEntry(BaseModel):
    """One immutable row in the audit trail.

    Frozen Pydantic v2 model — once constructed, fields cannot be
    reassigned. This matches the regulatory expectation that an audit
    record represents a fact captured at a moment in time and is not
    subject to later edits.

    Field semantics
    ---------------

    ``entry_id``
        Stable identifier; defaults to a fresh UUID4. Allows downstream
        SIEM systems to deduplicate on replay.
    ``customer_id``
        Pseudonymous customer reference. The trail intentionally does
        not validate the format — Bradesco uses an internal hashed
        identifier rather than a CPF/CNPJ so the file is not itself a
        PII silo. Callers are responsible for never passing raw PII.
    ``session_id``
        Conversation grouping key, typically from
        :class:`~lub.bridge.session.Session`.
    ``query``
        The customer-supplied prompt. Truncated by the caller before
        passing in if it exceeds local retention rules.
    ``response``
        The post-guard answer actually returned to the customer. May be
        an empty string when the guard ABSTAIN-ed or the agent failed.
    ``confidence``
        Guard confidence in ``[0, 1]``. ``None`` when the guard could
        not produce a verdict (e.g., agent error before the guard ran).
    ``decision``
        One of :class:`AuditDecision`'s values. The combined view of
        the guard's :class:`~lub.guard.PolicyDecision` and the platform's
        escalation flag.
    ``agent_used``
        Role of the agent that handled the query
        (chatbot/call_center/smart_payments).
    ``model_used``
        Identifier of the underlying model (e.g., ``"gpt-4.1-azure"``,
        ``"claude-opus-4-7"``, ``"local-llama-3-70b"``). Carrying this
        on the entry is what makes the trail useful for SR 11-7 model-
        risk reviews after a model swap.
    ``latency_ms``
        End-to-end wall-clock latency from prompt received to response
        returned. Negative values are clamped to zero by the validator.
    ``escalated``
        Whether the platform routed this query to a human operator.
    ``escalation_reason``
        Free-form reason string, defaulting to ``None``.
    ``timestamp``
        UTC capture time; serialized as ISO-8601.
    ``extra``
        Open-ended metadata bag for caller-specific labels (intent,
        channel, A/B test arm). Kept on a dedicated field so the
        regulatory columns above stay stable across schema evolutions.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: str
    session_id: str
    query: str
    response: str
    confidence: float | None = None
    decision: str
    agent_used: str
    model_used: str
    latency_ms: float = 0.0
    escalated: bool = False
    escalation_reason: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, value: str) -> str:
        if value not in AuditDecision.values():
            raise ValueError(
                f"decision must be one of {sorted(AuditDecision.values())!r}, got {value!r}"
            )
        return value

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value != value:  # NaN
            return None
        # Clamp into [0, 1] rather than raising — telemetry bugs upstream
        # must never silently drop the audit record for a real decision.
        return max(0.0, min(1.0, float(value)))

    @field_validator("latency_ms")
    @classmethod
    def _validate_latency(cls, value: float) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return 0.0
        if v != v or v < 0.0:  # NaN or negative
            return 0.0
        return v

    def to_json(self) -> str:
        """Serialize to a single-line JSON string for the JSONL file."""
        return self.model_dump_json()

    def to_row(self) -> dict[str, Any]:
        """Flat dict suitable for CSV export.

        Nested ``extra`` is JSON-encoded so the column is stable across
        rows even when callers add ad-hoc labels.
        """
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "customer_id": self.customer_id,
            "session_id": self.session_id,
            "agent_used": self.agent_used,
            "model_used": self.model_used,
            "decision": self.decision,
            "confidence": "" if self.confidence is None else f"{self.confidence:.6f}",
            "latency_ms": f"{self.latency_ms:.3f}",
            "escalated": "true" if self.escalated else "false",
            "escalation_reason": self.escalation_reason or "",
            "query": self.query,
            "response": self.response,
            "extra": json.dumps(self.extra, sort_keys=True, ensure_ascii=False)
            if self.extra
            else "",
        }


# ---------------------------------------------------------------------------
# Trail
# ---------------------------------------------------------------------------


_CSV_COLUMNS: tuple[str, ...] = (
    "entry_id",
    "timestamp",
    "customer_id",
    "session_id",
    "agent_used",
    "model_used",
    "decision",
    "confidence",
    "latency_ms",
    "escalated",
    "escalation_reason",
    "query",
    "response",
    "extra",
)


class AuditTrail:
    """Append-only audit ledger for the Bridge platform.

    Parameters
    ----------
    path:
        Path to the JSONL backing file. The parent directory is created
        on demand. Existing entries in the file are eagerly loaded into
        the in-memory cache so :meth:`query_trail` is fast after a
        restart. Pass ``None`` for a memory-only trail (tests).
    fsync:
        Whether to ``fsync`` after every append. Defaults to ``True``
        because the trail's durability guarantee is what makes it
        admissible as regulatory evidence; disable only in tests.

    Notes
    -----
    The trail is safe to share across threads — all public methods
    acquire a single re-entrant lock around the file handle and the
    in-memory cache, so concurrent dispatches from
    :class:`~lub.bridge.BridgePlatform` cannot interleave a partial
    write with another thread's read.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None, *, fsync: bool = True) -> None:
        self._path: Path | None = Path(path) if path is not None else None
        self._fsync = bool(fsync)
        self._lock = threading.RLock()
        self._entries: list[AuditEntry] = []
        self._file: IO[str] | None = None

        if self._path is not None:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._load_existing()
                # Open in append mode; never truncated.
                self._file = self._path.open("a", encoding="utf-8")
            except OSError as exc:
                _LOG.error(
                    "bridge.audit.open_failed",
                    path=str(self._path),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                raise AuditTrailError(f"unable to open audit trail at {self._path}: {exc}") from exc

        _LOG.info(
            "bridge.audit.initialized",
            path=str(self._path) if self._path else None,
            preloaded=len(self._entries),
            fsync=self._fsync,
        )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """Flush and close the backing file handle.

        Safe to call multiple times. After close, any further write
        attempt raises :class:`AuditTrailError` — callers that need to
        rotate the file should drop and recreate the trail.
        """
        with self._lock:
            if self._file is not None:
                try:
                    self._file.flush()
                    self._file.close()
                except OSError as exc:
                    _LOG.warning(
                        "bridge.audit.close_failed",
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                finally:
                    self._file = None

    def __enter__(self) -> AuditTrail:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    def log_decision(self, entry: AuditEntry) -> AuditEntry:
        """Append ``entry`` to the trail.

        Returns the entry that was persisted (the same object — entries
        are frozen). Raises :class:`AuditTrailError` if the entry could
        not be durably written; the caller should treat this as a
        compliance-blocking incident and refuse to return the customer
        an answer until the trail is restored.
        """
        if not isinstance(entry, AuditEntry):
            raise TypeError(f"log_decision requires an AuditEntry, got {type(entry).__name__}")

        with self._lock:
            if self._path is not None and self._file is None:
                raise AuditTrailError(
                    "audit trail is closed; refusing to drop a banking decision record"
                )

            line = entry.to_json()
            if self._file is not None:
                try:
                    self._file.write(line)
                    self._file.write("\n")
                    self._file.flush()
                    if self._fsync:
                        os.fsync(self._file.fileno())
                except OSError as exc:
                    _LOG.error(
                        "bridge.audit.write_failed",
                        path=str(self._path),
                        entry_id=entry.entry_id,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                    raise AuditTrailError(
                        f"failed to persist audit entry {entry.entry_id}: {exc}"
                    ) from exc

            self._entries.append(entry)

        _LOG.info(
            "bridge.audit.logged",
            entry_id=entry.entry_id,
            customer_id=entry.customer_id,
            session_id=entry.session_id,
            decision=entry.decision,
            escalated=entry.escalated,
            agent_used=entry.agent_used,
            model_used=entry.model_used,
        )
        return entry

    def log_bridge_result(
        self,
        result: BridgeResult,
        *,
        customer_id: str,
        session_id: str,
        model_used: str,
        latency_ms: float,
        extra: Mapping[str, Any] | None = None,
    ) -> AuditEntry:
        """Build an :class:`AuditEntry` from a :class:`BridgeResult` and log it.

        Convenience wrapper so callers don't have to thread the same
        seven fields through every dispatch site. Pulls the guard
        verdict and escalation state directly off the result so the
        audit record cannot disagree with what the platform reports.
        """
        entry = _entry_from_result(
            result=result,
            customer_id=customer_id,
            session_id=session_id,
            model_used=model_used,
            latency_ms=latency_ms,
            extra=extra,
        )
        return self.log_decision(entry)

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def query_trail(self, customer_id: str) -> list[AuditEntry]:
        """Return every entry recorded for ``customer_id``.

        Results are ordered by insertion (which is wall-clock-monotonic
        for a single trail). Returns an empty list if the customer has
        no recorded interactions.
        """
        if not isinstance(customer_id, str) or not customer_id:
            return []
        with self._lock:
            return [e for e in self._entries if e.customer_id == customer_id]

    def query_by_session(self, session_id: str) -> list[AuditEntry]:
        """Return every entry recorded for ``session_id``."""
        if not isinstance(session_id, str) or not session_id:
            return []
        with self._lock:
            return [e for e in self._entries if e.session_id == session_id]

    def query_by_period(
        self,
        start: datetime,
        end: datetime,
    ) -> list[AuditEntry]:
        """Return entries whose ``timestamp`` falls in ``[start, end)``."""
        start_utc, end_utc = _normalize_period(start, end)
        with self._lock:
            return [e for e in self._entries if start_utc <= _as_utc(e.timestamp) < end_utc]

    def all_entries(self) -> tuple[AuditEntry, ...]:
        """Return an immutable snapshot of every entry currently held."""
        with self._lock:
            return tuple(self._entries)

    # ------------------------------------------------------------------ #
    # Export
    # ------------------------------------------------------------------ #

    def export_csv(
        self,
        period: tuple[datetime, datetime],
        *,
        output_dir: str | os.PathLike[str] | None = None,
        filename: str | None = None,
    ) -> Path:
        """Export entries from ``period`` to a CSV file and return its path.

        Parameters
        ----------
        period:
            ``(start, end)`` half-open UTC interval. Naive datetimes are
            treated as UTC. Required: regulators always scope evidence
            packages to a date range, never "everything".
        output_dir:
            Directory for the generated CSV. Defaults to the trail's
            JSONL parent directory (or the current working directory if
            the trail is memory-only). Created on demand.
        filename:
            Optional filename. When omitted, defaults to
            ``bridge_audit_<start>_<end>.csv`` with UTC timestamps
            collapsed to ``YYYYMMDDTHHMMSSZ``.

        The CSV columns are stable across releases — adding a new
        :class:`AuditEntry` field appends a column rather than
        reordering — so downstream regulator-side parsers do not break.
        """
        start_utc, end_utc = _normalize_period(*period)
        rows = self.query_by_period(start_utc, end_utc)

        if output_dir is not None:
            out_dir = Path(output_dir)
        elif self._path is not None:
            out_dir = self._path.parent
        else:
            out_dir = Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            filename = f"bridge_audit_{_period_tag(start_utc)}_{_period_tag(end_utc)}.csv"
        out_path = out_dir / filename

        try:
            with out_path.open("w", encoding="utf-8", newline="") as fp:
                writer = csv.DictWriter(fp, fieldnames=list(_CSV_COLUMNS))
                writer.writeheader()
                for entry in rows:
                    writer.writerow(entry.to_row())
        except OSError as exc:
            _LOG.error(
                "bridge.audit.export_failed",
                path=str(out_path),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise AuditTrailError(f"failed to write audit CSV {out_path}: {exc}") from exc

        _LOG.info(
            "bridge.audit.exported",
            path=str(out_path),
            rows=len(rows),
            period_start=start_utc.isoformat(),
            period_end=end_utc.isoformat(),
        )
        return out_path

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _load_existing(self) -> None:
        """Replay the JSONL file into the in-memory cache, skipping bad lines."""
        if self._path is None or not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as fp:
                for lineno, raw in enumerate(fp, start=1):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        entry = AuditEntry.model_validate(payload)
                    except Exception as exc:  # noqa: BLE001 — tolerate one bad row
                        _LOG.warning(
                            "bridge.audit.replay_skipped",
                            path=str(self._path),
                            line=lineno,
                            error=str(exc),
                            error_type=type(exc).__name__,
                        )
                        continue
                    self._entries.append(entry)
        except OSError as exc:
            _LOG.error(
                "bridge.audit.replay_failed",
                path=str(self._path),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise AuditTrailError(f"unable to replay audit trail at {self._path}: {exc}") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry_from_result(
    *,
    result: BridgeResult,
    customer_id: str,
    session_id: str,
    model_used: str,
    latency_ms: float,
    extra: Mapping[str, Any] | None,
) -> AuditEntry:
    """Construct an :class:`AuditEntry` from a :class:`BridgeResult`."""
    primary: AgentResponse = result.primary
    role = primary.role.value if isinstance(primary.role, AgentRole) else str(primary.role)

    confidence: float | None = None
    verdict: GuardResult | None = primary.guard_result
    if verdict is not None:
        try:
            confidence = float(verdict.raw.confidence)
        except Exception:  # noqa: BLE001 — tolerate exotic estimator outputs
            confidence = None

    decision = _decision_label(result, verdict)

    escalation_reason: str | None = None
    if result.escalation_reason is not None:
        escalation_reason = (
            result.escalation_reason.value
            if isinstance(result.escalation_reason, EscalationReason)
            else str(result.escalation_reason)
        )

    return AuditEntry(
        customer_id=customer_id,
        session_id=session_id,
        query=primary.prompt,
        response=primary.answer,
        confidence=confidence,
        decision=decision,
        agent_used=role,
        model_used=model_used,
        latency_ms=latency_ms,
        escalated=result.escalated,
        escalation_reason=escalation_reason,
        extra=dict(extra) if extra else {},
    )


def _decision_label(result: BridgeResult, verdict: GuardResult | None) -> str:
    """Map (guard verdict, escalation flag) to an :class:`AuditDecision` value."""
    if verdict is not None:
        outcome = getattr(verdict, "outcome", None) or getattr(verdict, "policy_outcome", None)
        decision = (
            getattr(outcome, "decision", None) if outcome else getattr(verdict, "decision", None)
        )
        if isinstance(decision, PolicyDecision):
            return decision.value
        if isinstance(decision, str) and decision in AuditDecision.values():
            return decision
    if result.escalated:
        return AuditDecision.ESCALATE
    return AuditDecision.UNKNOWN


def _normalize_period(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Coerce ``(start, end)`` to UTC and validate ordering."""
    start_utc = _as_utc(start)
    end_utc = _as_utc(end)
    if end_utc < start_utc:
        raise ValueError(
            f"period end ({end_utc.isoformat()}) precedes start ({start_utc.isoformat()})"
        )
    return start_utc, end_utc


def _as_utc(value: datetime) -> datetime:
    """Return ``value`` as a timezone-aware UTC datetime."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _period_tag(value: datetime) -> str:
    """Format a UTC datetime as ``YYYYMMDDTHHMMSSZ`` for filenames."""
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
