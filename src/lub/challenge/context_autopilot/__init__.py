# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge.context_autopilot -- runtime arm of CEC.

The CEC subpackage (:mod:`lub.challenge`) calibrates the *output* of
an LLM run after the fact. Context Autopilot extends the same posture
*upstream*, monitoring the **input context window** during long-running
analyses (regulatory document review, multi-turn questioning) and
ejecting content when staying inside the model's budget would force
the model to hallucinate.

The ejection rule is itself **calibrated** -- not FIFO, not LRU --
using :mod:`lub.evidence` k-NN over the active conversation against
historical "useful vs ejected" decisions logged in :mod:`lub.ledger`.

Composes:

* :mod:`lub.evidence`   -- k-NN store consumed by the ejection score
* :mod:`lub.ledger`     -- substrate (schema v3 adds three tables)
* :mod:`lub.calibration`-- shared with CEC for outcome history
* :mod:`lub.wrappers`   -- optional ``tiktoken`` token counter

Public API
----------

Monitor (passive token counter)::

    from lub.challenge.context_autopilot import ContextMonitor

Calibrated ejection::

    from lub.challenge.context_autopilot import (
        EjectedTurn, EjectionScore, eject_top_k, score_for_ejection,
    )

Recall risk flagging::

    from lub.challenge.context_autopilot import (
        RecallRiskFlag, detect_recall_risk,
    )

Reports::

    from lub.challenge.context_autopilot import (
        ContextWindowReport, EjectionReport, render_markdown,
    )

Spec: ``planning/25_Context_Autopilot_Spec_2026-04-25.md``.
"""

from __future__ import annotations

from lub.challenge.context_autopilot.ejection import (
    EjectedTurn,
    EjectionScore,
    Turn,
    eject_top_k,
    score_for_ejection,
)
from lub.challenge.context_autopilot.monitor import ContextMonitor
from lub.challenge.context_autopilot.recall import (
    EjectionLogEntry,
    RecallRiskFlag,
    detect_recall_risk,
)
from lub.challenge.context_autopilot.reports import (
    ContextWindowReport,
    EjectionReport,
    render_markdown,
)

__all__ = [
    # monitor
    "ContextMonitor",
    # ejection
    "Turn",
    "EjectionScore",
    "EjectedTurn",
    "score_for_ejection",
    "eject_top_k",
    # recall
    "EjectionLogEntry",
    "RecallRiskFlag",
    "detect_recall_risk",
    # reports
    "ContextWindowReport",
    "EjectionReport",
    "render_markdown",
]
