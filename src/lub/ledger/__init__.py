# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""SQLite-backed uncertainty ledger.

Durable, queryable store of every (prompt, answer, UQ-scores, policy,
outcome) tuple produced by the runtime. Inspired by ruflo's
``.swarm/memory.db`` coordination pattern, scoped to selective
prediction audit.

The ledger is the substrate for:

* Nightly reliability-diagram regeneration (see :meth:`Ledger.replay_calibration`).
* Drift detection (compare today's ECE against the last 30 days).
* Regulator-ready audit trail: every abstention, every human verdict,
  every uncertainty signal, linked by foreign key.
"""

from __future__ import annotations

from lub.ledger.metrics import (
    LedgerMetrics,
    collect_metrics,
    to_grafana_json,
    to_prometheus,
    write_prometheus_textfile,
)
from lub.ledger.protocol import (
    InMemoryLedger,
    LedgerProtocol,
    LedgerSummary,
)
from lub.ledger.schema import SCHEMA_SQL
from lub.ledger.store import Ledger

__all__ = [
    "SCHEMA_SQL",
    "InMemoryLedger",
    "Ledger",
    "LedgerMetrics",
    "LedgerProtocol",
    "LedgerSummary",
    "collect_metrics",
    "to_grafana_json",
    "to_prometheus",
    "write_prometheus_textfile",
]
