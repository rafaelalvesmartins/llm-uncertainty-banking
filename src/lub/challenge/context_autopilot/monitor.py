# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge.context_autopilot.monitor -- passive context-window observer.

A pure-Python token counter that hooks (passively) into a long-running
session. For each turn, records ``(session_id, turn_id,
input_tokens, cumulative_tokens, model_max_context, headroom_ratio)``
into the ``context_window_observations`` ledger table.

Pure side effect: ledger write + structlog event. No prompt is
intercepted, mutated, or cached.

Spec: planning/25_Context_Autopilot_Spec_2026-04-25.md section 1.1.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import structlog

_LOG = structlog.get_logger("lub.challenge.context_autopilot.monitor")


class ContextMonitor:
    """Passive observer of one session's context-window usage.

    Parameters
    ----------
    ledger:
        A :class:`lub.ledger.Ledger` instance. The monitor writes into
        the additive ``context_window_observations`` table introduced
        in schema v3.

    Notes
    -----
    The monitor is *side-effect-only*. It does not intercept the
    prompt, does not call any model, and does not own any state beyond
    a per-session cumulative-tokens counter (held in memory; the ledger
    is the system of record).
    """

    def __init__(self, ledger: Any) -> None:
        self._ledger = ledger
        # In-memory cumulative counter per session. The ledger is the
        # authoritative store; this just avoids a SELECT per observe().
        self._cumulative: dict[str, int] = {}

    def _conn(self) -> sqlite3.Connection:
        # First-party extension: the CEC modules use the same access
        # pattern. See lub.challenge.meta_calibration.
        return self._ledger._conn  # type: ignore[no-any-return]  # noqa: SLF001

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe(
        self,
        session_id: str,
        turn_id: int,
        input_tokens: int,
        model_max_context: int,
    ) -> None:
        """Record a single turn's context-window state.

        Parameters
        ----------
        session_id:
            Stable identifier for the long-running session.
        turn_id:
            Monotonically increasing turn index within the session
            (caller-supplied; the monitor does not assume any ordering
            beyond what the caller provides).
        input_tokens:
            Number of tokens in this turn's input prompt.
        model_max_context:
            Model's hard maximum context window size, in tokens.

        Raises
        ------
        ValueError
            If any numeric argument is out of range (negative tokens,
            non-positive max context, etc.).
        """
        if input_tokens < 0:
            raise ValueError(f"input_tokens must be non-negative, got {input_tokens}")
        if model_max_context <= 0:
            raise ValueError(f"model_max_context must be positive, got {model_max_context}")
        if turn_id < 0:
            raise ValueError(f"turn_id must be non-negative, got {turn_id}")

        sid = str(session_id)
        cumulative = self._cumulative.get(sid, 0) + int(input_tokens)
        self._cumulative[sid] = cumulative

        # Headroom is reported as a clamped ratio; values outside
        # [0, 1] would silently distort downstream charts.
        used_ratio = cumulative / float(model_max_context)
        headroom = max(0.0, min(1.0, 1.0 - used_ratio))

        conn = self._conn()
        conn.execute(
            "INSERT INTO context_window_observations"
            " (session_id, turn_id, input_tokens, cumulative_tokens,"
            "  model_max_context, headroom_ratio, observed_at)"
            " VALUES (?, ?, ?, ?, ?, ?,"
            "  strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (
                sid,
                int(turn_id),
                int(input_tokens),
                int(cumulative),
                int(model_max_context),
                float(headroom),
            ),
        )
        conn.commit()

        _LOG.info(
            "context_autopilot.observed",
            session_id=sid,
            turn_id=int(turn_id),
            input_tokens=int(input_tokens),
            cumulative_tokens=int(cumulative),
            model_max_context=int(model_max_context),
            headroom_ratio=float(headroom),
        )

    def reset_session(self, session_id: str) -> None:
        """Drop the in-memory cumulative counter for one session.

        The ledger rows are NOT deleted -- they remain the audit trail.
        """
        self._cumulative.pop(str(session_id), None)


__all__ = ["ContextMonitor"]
