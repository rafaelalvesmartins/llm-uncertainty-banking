# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Session manager — conversation history per customer.

Stores the multi-turn state required by the three Bradesco Bridge
surfaces (chatbot, call center, smart payments). Two interchangeable
backends are provided behind the same :class:`SessionStore` protocol:

* :class:`InMemorySessionStore` — process-local, thread-safe, suitable
  for unit tests and the local pre-release check.
* :class:`SQLiteSessionStore` — file-backed, durable across process
  restarts, suitable for single-node pilot deployments. The schema is
  intentionally tiny (two tables) so a production rollout can mirror it
  on PostgreSQL with a one-line connection swap.

Why this matters for banking
----------------------------

BCB 4893 (cyber-resilience) and BCBS 239 (risk-data aggregation) both
require that customer interactions handled by automated systems be
*reconstructable*: a regulator must be able to replay every turn that
led to a decision. The :class:`Session` record below is therefore the
unit of replay — it carries the customer, channel, full message log,
guard verdicts, and resolution/escalation flags that feed the metrics
Bradesco reported on the reference page:

* **90%** retention rate (sessions resolved without human handoff)
* **95%** response accuracy (guard-passed responses over total)
* **40%** call-time reduction in the call-center surface
  (measured as average session duration vs. a baseline supplied at
  construction time)
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog

__all__ = [
    "Channel",
    "InMemorySessionStore",
    "Message",
    "MessageRole",
    "SQLiteSessionStore",
    "Session",
    "SessionManager",
    "SessionMetrics",
    "SessionNotFoundError",
    "SessionStore",
]

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SessionNotFoundError(KeyError):
    """Raised when a session_id is not present in the backing store."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MessageRole(StrEnum):
    """Speaker role inside a conversation turn."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Channel(StrEnum):
    """Customer-facing surface where the session originated."""

    WHATSAPP = "whatsapp"
    MOBILE_APP = "mobile_app"
    WEB = "web"
    CALL_CENTER = "call_center"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    """A single conversation turn.

    ``metadata`` is intentionally a free-form dict so callers can attach
    guard verdicts, model identifiers, or audit hashes without forcing a
    schema migration on every new field.
    """

    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize a conversation turn to a JSON-safe dict.

        Used by the SQLite backend and by the audit-export path that
        feeds BCBS 239 replay packages: every assistant turn carries its
        ``guard_decision`` inside ``metadata`` so a regulator can
        reconstruct why the chatbot/call-center/payments agent
        responded, escalated, or aborted.

        Returns
        -------
        dict[str, Any]
            ``role``/``content``/``timestamp`` (ISO-8601 UTC) plus a
            shallow copy of ``metadata`` so mutations on the returned
            dict do not bleed back into the frozen record.
        """
        return {
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """Rehydrate a turn produced by :meth:`to_dict`.

        Tolerant on the timestamp: a missing or non-string ``timestamp``
        falls back to ``now(UTC)`` so partially populated audit records
        and replay fixtures still load — important because the Bridge
        platform must keep degrading gracefully rather than refusing to
        serve a customer over a malformed history row.

        Parameters
        ----------
        data:
            Mapping previously produced by :meth:`to_dict` (or a
            compatible source such as an audit-trail row).
        """
        ts = data.get("timestamp")
        timestamp = datetime.fromisoformat(ts) if isinstance(ts, str) else datetime.now(UTC)
        return cls(
            role=MessageRole(data["role"]),
            content=data["content"],
            timestamp=timestamp,
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class Session:
    """All state for one customer conversation.

    ``resolved`` and ``escalated`` are mutually exclusive terminal flags
    used by :class:`SessionMetrics` to compute the headline Bradesco
    retention rate (resolved without escalation).
    """

    session_id: str
    customer_id: str
    channel: Channel
    messages: list[Message] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_active_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved: bool = False
    escalated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> timedelta:
        """Wall-clock duration between first and last activity."""
        return self.last_active_at - self.started_at

    def append(self, message: Message) -> None:
        """Append a message and bump ``last_active_at``."""
        self.messages.append(message)
        self.last_active_at = message.timestamp

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full session (turns + flags) for audit/export.

        This is the canonical wire-format consumed by
        :meth:`SessionManager.as_dict` and by the BCB 4893 audit-trail
        writer: it carries everything a regulator needs to replay the
        conversation — channel of origin, message log with guard
        verdicts, escalation reason in ``metadata``, and the two
        terminal flags that drive the retention metric.

        Returns
        -------
        dict[str, Any]
            JSON-safe snapshot with ISO-8601 UTC timestamps and a
            shallow-copied ``metadata`` dict.
        """
        return {
            "session_id": self.session_id,
            "customer_id": self.customer_id,
            "channel": self.channel.value,
            "messages": [m.to_dict() for m in self.messages],
            "started_at": self.started_at.isoformat(),
            "last_active_at": self.last_active_at.isoformat(),
            "resolved": self.resolved,
            "escalated": self.escalated,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        """Rehydrate a session produced by :meth:`to_dict`.

        Used both when reading from a JSON audit dump and as a
        convenience for cross-backend migrations (e.g. exporting an
        :class:`InMemorySessionStore` and importing into a
        :class:`SQLiteSessionStore`). The terminal flags are coerced via
        ``bool(...)`` so SQLite's 0/1 integers round-trip correctly.

        Parameters
        ----------
        data:
            Mapping previously produced by :meth:`to_dict`.
        """
        return cls(
            session_id=data["session_id"],
            customer_id=data["customer_id"],
            channel=Channel(data["channel"]),
            messages=[Message.from_dict(m) for m in data.get("messages", [])],
            started_at=datetime.fromisoformat(data["started_at"]),
            last_active_at=datetime.fromisoformat(data["last_active_at"]),
            resolved=bool(data.get("resolved", False)),
            escalated=bool(data.get("escalated", False)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class SessionMetrics:
    """Aggregate metrics aligned with the Bradesco reference deployment.

    * ``retention_rate`` — fraction of *closed* sessions that ended
      ``resolved`` and not ``escalated``. Bradesco reported **90%** on
      the chatbot surface.
    * ``accuracy_rate`` — fraction of assistant messages whose guard
      verdict (stored in ``metadata['guard_decision']``) is
      ``passthrough``. Bradesco reported **95%**.
    * ``call_time_reduction`` — relative reduction in average
      call-center session duration vs. a supplied baseline. Bradesco
      reported **40%** versus pre-AI call handling. ``None`` when no
      baseline was supplied or no call-center sessions exist.
    """

    total: int
    resolved: int
    escalated: int
    open_sessions: int
    retention_rate: float
    accuracy_rate: float
    avg_duration_seconds: float
    call_time_reduction: float | None
    by_channel: dict[str, int]


# ---------------------------------------------------------------------------
# Store protocol + backends
# ---------------------------------------------------------------------------


@runtime_checkable
class SessionStore(Protocol):
    """Minimal persistence contract every backend must satisfy."""

    def put(self, session: Session) -> None:
        """Insert or replace ``session`` keyed by its ``session_id``.

        Implementations must be idempotent and atomic per session — the
        Bridge platform calls :meth:`put` after every turn, and a
        partial write would leave the next agent invocation with a
        stale message log or a missing UncertaintyGuard verdict, which
        is unacceptable for the BCB 4893 replay guarantee.
        """
        ...

    def get(self, session_id: str) -> Session:
        """Return the session identified by ``session_id``.

        Raises
        ------
        SessionNotFoundError
            If the id is unknown. Agents must treat this as a hard
            error rather than silently starting a new conversation —
            losing state mid-flight in a banking workflow is the kind
            of failure SR 11-7 expects to be surfaced, not papered
            over.
        """
        ...

    def delete(self, session_id: str) -> None:
        """Remove a session by id; unknown ids must be a silent no-op.

        Exposed for the LGPD ``right-to-erasure`` path. Production
        callers should prefer escalating + archiving over deletion so
        the BCBS 239 audit trail stays intact.
        """
        ...

    def list_for_customer(self, customer_id: str) -> list[Session]:
        """Return every session belonging to ``customer_id`` across channels.

        Feeds the chatbot's cross-channel continuity ("you spoke to us
        on WhatsApp yesterday") and the compliance dashboard's
        repeat-escalation detector.
        """
        ...

    def all_sessions(self) -> list[Session]:
        """Snapshot every persisted session for metrics, TTL sweeps, and audit export.

        Must return a fresh list — :meth:`SessionManager.expire_idle`
        and :meth:`SessionManager.metrics` iterate the result without
        holding any store-internal lock.
        """
        ...


class InMemorySessionStore:
    """Thread-safe in-memory backend.

    Intended for tests and short-lived processes. State is lost when the
    process exits — use :class:`SQLiteSessionStore` for anything that
    must survive a restart.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def put(self, session: Session) -> None:
        """Insert or replace a session under its ``session_id``.

        Idempotent upsert used after every turn so the UncertaintyGuard
        verdict and any escalation flag are durably visible to the next
        agent invocation. The internal ``RLock`` keeps concurrent
        FastAPI workers from racing on the same conversation.
        """
        with self._lock:
            self._sessions[session.session_id] = session

    def get(self, session_id: str) -> Session:
        """Look up a session by id.

        Raises
        ------
        SessionNotFoundError
            If the id is unknown. Agents treat this as a hard error
            rather than silently starting a new session — banking
            workflows must never lose state for an in-flight customer.
        """
        with self._lock:
            try:
                return self._sessions[session_id]
            except KeyError as exc:
                raise SessionNotFoundError(session_id) from exc

    def delete(self, session_id: str) -> None:
        """Remove a session; silently ignore an unknown id.

        Used by the LGPD ``right-to-erasure`` path and by test
        teardown. Production code should prefer escalating + archiving
        over outright deletion so the BCBS 239 audit trail stays
        intact.
        """
        with self._lock:
            self._sessions.pop(session_id, None)

    def list_for_customer(self, customer_id: str) -> list[Session]:
        """Return every session belonging to one customer (any channel).

        Used by the chatbot to surface "you spoke to us yesterday about
        X" continuity and by the compliance dashboard to spot a
        customer repeatedly escalated across channels.
        """
        with self._lock:
            return [s for s in self._sessions.values() if s.customer_id == customer_id]

    def all_sessions(self) -> list[Session]:
        """Snapshot every session for metrics, TTL sweeps, and audit export.

        Returns a fresh list so :meth:`SessionManager.expire_idle` and
        :meth:`SessionManager.metrics` can iterate without holding the
        store lock.
        """
        with self._lock:
            return list(self._sessions.values())


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL,
    channel         TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    last_active_at  TEXT NOT NULL,
    resolved        INTEGER NOT NULL DEFAULT 0,
    escalated       INTEGER NOT NULL DEFAULT 0,
    metadata_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sessions_customer ON sessions(customer_id);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}',
    UNIQUE(session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
"""


class SQLiteSessionStore:
    """Durable single-node backend.

    Uses a single SQLite file with foreign keys enabled and one
    re-entrant lock to serialize writes — SQLite handles concurrent
    readers natively but only one writer. For multi-node deployments,
    swap the schema onto PostgreSQL; the SQL is intentionally portable.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(_SQLITE_SCHEMA)
            conn.commit()
        log.info("bridge.session.sqlite_initialized", path=self._path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            conn.close()

    def put(self, session: Session) -> None:
        """Upsert a session and atomically replace its message log.

        The two-statement transaction (``DELETE`` then ``INSERT`` of all
        messages) keeps the on-disk state consistent with the in-memory
        :class:`Session` after every turn — important for BCB 4893
        replay, because a crash mid-write must never leave a session
        with a missing or duplicated turn that would change the
        UncertaintyGuard verdict on replay. The single ``RLock``
        serializes writers; concurrent readers continue to work via
        SQLite's native MVCC.
        """
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions
                    (session_id, customer_id, channel, started_at, last_active_at,
                     resolved, escalated, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    customer_id    = excluded.customer_id,
                    channel        = excluded.channel,
                    started_at     = excluded.started_at,
                    last_active_at = excluded.last_active_at,
                    resolved       = excluded.resolved,
                    escalated      = excluded.escalated,
                    metadata_json  = excluded.metadata_json
                """,
                (
                    session.session_id,
                    session.customer_id,
                    session.channel.value,
                    session.started_at.isoformat(),
                    session.last_active_at.isoformat(),
                    int(session.resolved),
                    int(session.escalated),
                    json.dumps(session.metadata),
                ),
            )
            # Replace message log atomically — simpler and correct for
            # the volumes the pilot needs; switch to incremental append
            # when message counts per session exceed a few hundred.
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session.session_id,))
            conn.executemany(
                """
                INSERT INTO messages
                    (session_id, seq, role, content, timestamp, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        session.session_id,
                        seq,
                        m.role.value,
                        m.content,
                        m.timestamp.isoformat(),
                        json.dumps(m.metadata),
                    )
                    for seq, m in enumerate(session.messages)
                ],
            )
            conn.commit()

    def get(self, session_id: str) -> Session:
        """Load a session and its full message log from disk.

        The session row and its messages are read inside the same
        connection so a concurrent writer cannot interleave a
        :meth:`put` between the two queries and hand back a session
        whose turns belong to a different revision. Raises
        :class:`SessionNotFoundError` on an unknown id — the chatbot,
        call-center, and payments agents all treat this as a hard
        failure rather than silently starting fresh.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, customer_id, channel, started_at, last_active_at,
                       resolved, escalated, metadata_json
                FROM sessions WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                raise SessionNotFoundError(session_id)
            messages = self._load_messages(conn, session_id)
        return _row_to_session(row, messages)

    def delete(self, session_id: str) -> None:
        """Remove a session row; the FK cascade purges its messages.

        Unknown ids are a silent no-op. Used by the LGPD
        ``right-to-erasure`` path; production callers should prefer
        :meth:`SessionManager.escalate` + archival so the BCBS 239
        audit trail remains complete.
        """
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()

    def list_for_customer(self, customer_id: str) -> list[Session]:
        """Return every session for one customer, oldest first.

        Ordering by ``started_at ASC`` lets the chatbot replay the
        customer's history chronologically when building "you spoke to
        us about X" continuity, and lets the compliance dashboard
        spot repeated escalations across channels without an extra
        sort.
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, customer_id, channel, started_at, last_active_at,
                       resolved, escalated, metadata_json
                FROM sessions WHERE customer_id = ?
                ORDER BY started_at ASC
                """,
                (customer_id,),
            ).fetchall()
            return [_row_to_session(r, self._load_messages(conn, r[0])) for r in rows]

    def all_sessions(self) -> list[Session]:
        """Snapshot every persisted session, oldest first.

        Drives :meth:`SessionManager.expire_idle` (which needs to scan
        every open session against the TTL cutoff) and
        :meth:`SessionManager.metrics` (which aggregates retention,
        accuracy, and call-time reduction across the whole population).
        Returns a fresh list so callers can iterate without holding any
        store-internal lock.
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, customer_id, channel, started_at, last_active_at,
                       resolved, escalated, metadata_json
                FROM sessions ORDER BY started_at ASC
                """
            ).fetchall()
            return [_row_to_session(r, self._load_messages(conn, r[0])) for r in rows]

    @staticmethod
    def _load_messages(conn: sqlite3.Connection, session_id: str) -> list[Message]:
        rows = conn.execute(
            """
            SELECT role, content, timestamp, metadata_json
            FROM messages WHERE session_id = ? ORDER BY seq ASC
            """,
            (session_id,),
        ).fetchall()
        return [
            Message(
                role=MessageRole(role),
                content=content,
                timestamp=datetime.fromisoformat(ts),
                metadata=json.loads(meta) if meta else {},
            )
            for role, content, ts, meta in rows
        ]


def _row_to_session(row: Sequence[Any], messages: list[Message]) -> Session:
    (
        session_id,
        customer_id,
        channel,
        started_at,
        last_active_at,
        resolved,
        escalated,
        metadata_json,
    ) = row
    return Session(
        session_id=session_id,
        customer_id=customer_id,
        channel=Channel(channel),
        messages=messages,
        started_at=datetime.fromisoformat(started_at),
        last_active_at=datetime.fromisoformat(last_active_at),
        resolved=bool(resolved),
        escalated=bool(escalated),
        metadata=json.loads(metadata_json) if metadata_json else {},
    )


# ---------------------------------------------------------------------------
# High-level manager
# ---------------------------------------------------------------------------


class SessionManager:
    """Convenience API on top of any :class:`SessionStore`.

    The manager owns lifecycle policy (TTL expiry, resolution flagging,
    metric aggregation) so that agents and the :class:`BridgePlatform`
    can stay backend-agnostic.

    Parameters
    ----------
    store:
        Backing :class:`SessionStore`. Use :class:`InMemorySessionStore`
        in tests and :class:`SQLiteSessionStore` for pilot deployments.
    ttl:
        How long a session may remain idle before :meth:`expire_idle`
        marks it ``escalated`` and stops the conversation. Defaults to
        24h — matching the WhatsApp Business 24-hour window.
    call_center_baseline_seconds:
        Pre-AI average call-handling time, in seconds, used to compute
        the headline 40% call-time-reduction metric. Pass ``None`` to
        disable the comparison.
    """

    def __init__(
        self,
        store: SessionStore,
        *,
        ttl: timedelta = timedelta(hours=24),
        call_center_baseline_seconds: float | None = None,
    ) -> None:
        if ttl.total_seconds() <= 0:
            raise ValueError("ttl must be positive")
        self._store = store
        self._ttl = ttl
        self._baseline = call_center_baseline_seconds

    @property
    def store(self) -> SessionStore:
        """Underlying :class:`SessionStore`, for advanced/test access.

        The Bridge platform's audit-export and admin-reset endpoints
        reach through this property to call backend-specific operations
        (e.g. a SQLite ``VACUUM``) without subclassing the manager.
        Day-to-day code should keep going through :meth:`start`,
        :meth:`append`, :meth:`resolve`, and :meth:`escalate` so
        lifecycle policy stays in one place.
        """
        return self._store

    def start(
        self,
        customer_id: str,
        channel: Channel,
        *,
        session_id: str | None = None,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Open a new session and persist it before the first turn."""
        sid = session_id or str(uuid.uuid4())
        session = Session(
            session_id=sid,
            customer_id=customer_id,
            channel=channel,
            metadata=dict(metadata or {}),
        )
        if system_prompt:
            session.append(Message(role=MessageRole.SYSTEM, content=system_prompt))
        self._store.put(session)
        log.info(
            "bridge.session.started",
            session_id=sid,
            customer_id=customer_id,
            channel=channel.value,
        )
        return session

    def get(self, session_id: str) -> Session:
        return self._store.get(session_id)

    def append(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Append a turn and persist the updated session."""
        session = self._store.get(session_id)
        if session.resolved or session.escalated:
            raise ValueError(
                f"cannot append to closed session {session_id!r} "
                f"(resolved={session.resolved}, escalated={session.escalated})"
            )
        session.append(Message(role=role, content=content, metadata=dict(metadata or {})))
        self._store.put(session)
        return session

    def resolve(self, session_id: str) -> Session:
        """Mark a session as successfully resolved (counts toward retention)."""
        session = self._store.get(session_id)
        session.resolved = True
        session.last_active_at = datetime.now(UTC)
        self._store.put(session)
        log.info("bridge.session.resolved", session_id=session_id)
        return session

    def escalate(self, session_id: str, reason: str) -> Session:
        """Mark a session as escalated to a human operator."""
        session = self._store.get(session_id)
        session.escalated = True
        session.metadata = {**session.metadata, "escalation_reason": reason}
        session.last_active_at = datetime.now(UTC)
        self._store.put(session)
        log.info("bridge.session.escalated", session_id=session_id, reason=reason)
        return session

    def expire_idle(self, *, now: datetime | None = None) -> list[str]:
        """Escalate sessions idle longer than ``ttl``. Returns affected IDs."""
        cutoff = (now or datetime.now(UTC)) - self._ttl
        expired: list[str] = []
        for session in self._store.all_sessions():
            if session.resolved or session.escalated:
                continue
            if session.last_active_at < cutoff:
                self.escalate(session.session_id, reason="idle_ttl_exceeded")
                expired.append(session.session_id)
        if expired:
            log.info("bridge.session.expire_idle", count=len(expired))
        return expired

    def history(self, session_id: str) -> list[dict[str, Any]]:
        """Return the message log in a shape consumable by chat LLMs."""
        session = self._store.get(session_id)
        return [{"role": m.role.value, "content": m.content} for m in session.messages]

    def metrics(self) -> SessionMetrics:
        """Compute the headline Bradesco metrics across all sessions."""
        sessions = self._store.all_sessions()
        total = len(sessions)
        closed = [s for s in sessions if s.resolved or s.escalated]
        resolved = sum(1 for s in closed if s.resolved and not s.escalated)
        escalated = sum(1 for s in sessions if s.escalated)
        open_count = total - len(closed)

        retention_rate = (resolved / len(closed)) if closed else 0.0
        accuracy_rate = _accuracy_rate(sessions)
        avg_duration = _avg_duration_seconds(sessions)
        call_reduction = _call_time_reduction(sessions, self._baseline)

        by_channel: dict[str, int] = {}
        for s in sessions:
            by_channel[s.channel.value] = by_channel.get(s.channel.value, 0) + 1

        return SessionMetrics(
            total=total,
            resolved=resolved,
            escalated=escalated,
            open_sessions=open_count,
            retention_rate=retention_rate,
            accuracy_rate=accuracy_rate,
            avg_duration_seconds=avg_duration,
            call_time_reduction=call_reduction,
            by_channel=by_channel,
        )

    def as_dict(self, session_id: str) -> dict[str, Any]:
        """Snapshot a session as plain JSON-able data (for audit export)."""
        return self._store.get(session_id).to_dict()


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


def _accuracy_rate(sessions: list[Session]) -> float:
    """Share of assistant turns whose guard verdict was passthrough.

    Guard verdicts are recorded by the caller in
    ``message.metadata['guard_decision']`` (see :mod:`lub.bridge`).
    Messages without a recorded verdict are excluded from the
    denominator so absent telemetry does not depress the headline.
    """
    total = 0
    passing = 0
    for session in sessions:
        for msg in session.messages:
            if msg.role != MessageRole.ASSISTANT:
                continue
            decision = msg.metadata.get("guard_decision")
            if decision is None:
                continue
            total += 1
            if decision == "passthrough":
                passing += 1
    return (passing / total) if total else 0.0


def _avg_duration_seconds(sessions: list[Session]) -> float:
    if not sessions:
        return 0.0
    return sum(s.duration.total_seconds() for s in sessions) / len(sessions)


def _call_time_reduction(sessions: list[Session], baseline_seconds: float | None) -> float | None:
    if baseline_seconds is None or baseline_seconds <= 0:
        return None
    call_sessions = [s for s in sessions if s.channel == Channel.CALL_CENTER]
    if not call_sessions:
        return None
    avg = sum(s.duration.total_seconds() for s in call_sessions) / len(call_sessions)
    return max(0.0, (baseline_seconds - avg) / baseline_seconds)
