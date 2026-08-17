# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Metric export from the uncertainty ledger.

Two output formats, both stdlib-only:

1. **Prometheus textfile-collector** -- write a ``.prom`` file that the
   node_exporter textfile collector can scrape. Each metric carries
   ``method``, ``context``, and ``tier`` labels where applicable.

2. **Grafana SimpleJson-compatible JSON** -- a flat JSON blob suitable
   for a static datasource or for piping into an HTTP endpoint.

Neither format requires a network dependency: the exporter returns the
body as a string, and a thin :func:`write_prometheus_textfile` helper
writes it atomically if the caller wants to drop it in
``/var/lib/node_exporter/textfile_collector/``.

This module previously reached into the sqlite-specific ``Ledger._conn``
attribute to compute aggregates. It now uses the backend-agnostic
:meth:`~lub.ledger.protocol.LedgerProtocol.summary` API, so any ledger
implementation (sqlite, in-memory test double, or future Postgres
plug-in) can drive the same exporter.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from lub.governance.drift import compute_ece

if TYPE_CHECKING:
    from lub.ledger.protocol import LedgerProtocol

_LOG = structlog.get_logger("lub.ledger.metrics")


@dataclass(frozen=True)
class LedgerMetrics:
    """Aggregate metrics computed off a single ledger snapshot.

    Attributes
    ----------
    n_answers:
        Count of rows in ``answers``.
    n_scored:
        Count of rows in ``uq_scores``.
    n_outcomes:
        Count of rows in ``outcomes`` (answers that have ground truth).
    accuracy:
        Fraction of ``outcomes`` with ``correct=1``. ``None`` if
        ``n_outcomes == 0``.
    abstain_rate:
        Fraction of ``policy_decisions`` whose ``decision`` equals
        ``"abstain"``. ``None`` if no policy decisions were logged.
    tier_counts:
        Mapping from tier label (``answers.tier`` or ``answers.model``
        as fallback) to count of answers routed to it.
    ece_by_method:
        Mapping from ``uq_scores.method`` to its ECE computed by
        replaying 10 buckets.
    """

    n_answers: int
    n_scored: int
    n_outcomes: int
    accuracy: float | None
    abstain_rate: float | None
    tier_counts: dict[str, int]
    ece_by_method: dict[str, float]


def collect_metrics(
    ledger: LedgerProtocol,
    *,
    methods: list[str] | None = None,
    n_buckets: int = 10,
) -> LedgerMetrics:
    """Compute a :class:`LedgerMetrics` snapshot.

    Parameters
    ----------
    ledger:
        Any object satisfying
        :class:`~lub.ledger.protocol.LedgerProtocol` -- typically the
        sqlite-backed :class:`~lub.ledger.store.Ledger`, but the
        in-memory test double and any future plug-in implementations
        work too.
    methods:
        UQ methods to compute ECE for. ``None`` means "auto-discover
        every distinct method in ``uq_scores``".
    n_buckets:
        Buckets for the ECE computation.
    """
    summary = ledger.summary()

    accuracy: float | None = None
    if summary.n_outcomes > 0:
        accuracy = summary.n_correct / summary.n_outcomes

    abstain_rate: float | None = None
    if summary.n_policy_decisions > 0:
        abstain_rate = summary.n_abstain / summary.n_policy_decisions

    discovered_methods: list[str] = (
        list(summary.distinct_methods) if methods is None else list(methods)
    )

    ece_by_method: dict[str, float] = {}
    for m in discovered_methods:
        # ``replay_calibration`` is not part of LedgerProtocol yet -- it
        # lives on the concrete sqlite Ledger. Future ledger plug-ins
        # will need to expose an equivalent reader; until then we
        # duck-type it here so a backend that does not support replay
        # can still surface counts without crashing the exporter.
        replay = getattr(ledger, "replay_calibration", None)
        if replay is None:
            continue
        points = replay(method=m, n_buckets=n_buckets)
        ece_by_method[m] = compute_ece(points)

    return LedgerMetrics(
        n_answers=summary.n_answers,
        n_scored=summary.n_scored,
        n_outcomes=summary.n_outcomes,
        accuracy=accuracy,
        abstain_rate=abstain_rate,
        tier_counts=dict(summary.tier_counts),
        ece_by_method=ece_by_method,
    )


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def to_prometheus(metrics: LedgerMetrics, *, namespace: str = "lub") -> str:
    """Render :class:`LedgerMetrics` as a Prometheus textfile body.

    Output shape follows ``node_exporter``'s textfile collector: one
    ``# HELP`` / ``# TYPE`` header per series, followed by one data
    line per label combination.
    """
    ns = namespace.rstrip("_")
    lines: list[str] = []

    def _gauge(name: str, help_: str, value: float, labels: str = "") -> None:
        metric = f"{ns}_{name}"
        lines.append(f"# HELP {metric} {help_}")
        lines.append(f"# TYPE {metric} gauge")
        suffix = f"{{{labels}}}" if labels else ""
        lines.append(f"{metric}{suffix} {value}")

    _gauge("ledger_answers_total", "Total answers logged to the ledger.", float(metrics.n_answers))
    _gauge("ledger_scores_total", "Total UQ scores logged to the ledger.", float(metrics.n_scored))
    _gauge(
        "ledger_outcomes_total",
        "Total labelled outcomes logged to the ledger.",
        float(metrics.n_outcomes),
    )
    if metrics.accuracy is not None:
        _gauge("accuracy", "Fraction of labelled outcomes marked correct.", metrics.accuracy)
    if metrics.abstain_rate is not None:
        _gauge(
            "abstain_rate",
            "Fraction of policy decisions that abstained.",
            metrics.abstain_rate,
        )

    for tier, n in metrics.tier_counts.items():
        labels = f'tier="{_escape_label(tier)}"'
        _gauge(
            "tier_answers_total",
            "Answers routed to each tier.",
            float(n),
            labels=labels,
        )

    for method, ece in metrics.ece_by_method.items():
        labels = f'method="{_escape_label(method)}"'
        _gauge(
            "calibration_ece",
            "Expected Calibration Error by UQ method.",
            ece,
            labels=labels,
        )

    return "\n".join(lines) + "\n"


def to_grafana_json(metrics: LedgerMetrics) -> str:
    """Render :class:`LedgerMetrics` as a Grafana SimpleJson payload.

    Shape is a flat dict of ``{"target": <name>, "datapoints":
    [[value, timestamp_ms]]}``. Callers who want a richer shape (say,
    with per-method time series) should read the underlying
    :class:`LedgerMetrics` directly and serialise themselves.
    """
    import time

    ts_ms = int(time.time() * 1000)
    series: list[dict[str, object]] = []

    def _point(name: str, value: float | None) -> None:
        if value is None:
            return
        series.append({"target": name, "datapoints": [[value, ts_ms]]})

    _point("ledger_answers_total", float(metrics.n_answers))
    _point("ledger_scores_total", float(metrics.n_scored))
    _point("ledger_outcomes_total", float(metrics.n_outcomes))
    _point("accuracy", metrics.accuracy)
    _point("abstain_rate", metrics.abstain_rate)
    for tier, n in metrics.tier_counts.items():
        _point(f"tier_answers_total{{tier={tier}}}", float(n))
    for method, ece in metrics.ece_by_method.items():
        _point(f"calibration_ece{{method={method}}}", ece)

    return json.dumps(series, indent=2, sort_keys=False)


def write_prometheus_textfile(
    metrics: LedgerMetrics,
    path: Path | str,
    *,
    namespace: str = "lub",
) -> Path:
    """Atomically write the Prometheus textfile to *path*.

    Writes to a sibling ``.tmp`` file then renames in-place so a
    concurrent scrape never sees a half-written body.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = to_prometheus(metrics, namespace=namespace)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    _LOG.info("metrics.textfile.written", path=str(path), bytes=len(body))
    return path


__all__ = [
    "LedgerMetrics",
    "collect_metrics",
    "to_grafana_json",
    "to_prometheus",
    "write_prometheus_textfile",
]
