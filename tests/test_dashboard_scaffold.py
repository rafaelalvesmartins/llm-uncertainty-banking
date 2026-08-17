# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Smoke tests for ``lub.dashboard`` (post pass-33 refactor).

Pass 29 shipped scaffolds. Pass 31 made query/render real. Pass 32 added
real CLI + server (FastAPI optional). Pass 33 refactored the surface
to be Protocol-pluggable (SnapshotSource + SnapshotRenderer). This file
exercises the **post-pass-33 public surface**:

* ``build_snapshot`` accepts a ``SnapshotSource`` (or a Ledger via the
  back-compat shim) -- the first positional arg is now ``source``, not
  ``ledger``.
* ``build_app`` is real and takes a ``source_factory`` callable; when
  ``fastapi`` is missing it raises a clear ``ImportError`` instead of
  ``NotImplementedError``.
* ``run_uvicorn`` is real; raises ``ImportError`` when ``fastapi`` /
  ``uvicorn`` is missing.

Spec: planning/29_Dashboard_Spec_2026-04-25.md.
"""

from __future__ import annotations

import sys
from datetime import datetime
from unittest import mock

import pytest

from lub.dashboard import (
    DashboardSnapshot,
    LedgerSnapshotSource,
    build_snapshot,
    render_html,
    render_json,
    run_uvicorn,
)

# ---------------------------------------------------------------------------
# DashboardSnapshot dataclass shape (unchanged across passes)
# ---------------------------------------------------------------------------


def test_dashboard_snapshot_dataclass_shape():
    snap = DashboardSnapshot(
        period_start=datetime(2026, 4, 1),
        period_end=datetime(2026, 4, 30),
        tenant="br-banking-q2",
        git_sha="a1b2c3d",
    )
    assert snap.tenant == "br-banking-q2"
    assert snap.decisions_in_window == 0
    assert snap.recent_decisions == []
    assert snap.oscal_envelope == {}


# ---------------------------------------------------------------------------
# build_snapshot: post-pass-33 takes any SnapshotSource (positional `source`)
# ---------------------------------------------------------------------------


def test_build_snapshot_handles_non_source_input():
    """A non-source, non-ledger argument -> honest empty snapshot."""
    snap = build_snapshot(
        object(),  # no _conn, doesn't satisfy SnapshotSource
        evidence_store=None,
        period_start=datetime(2026, 4, 1),
        period_end=datetime(2026, 4, 30),
        tenant="t1",
        git_sha="abc1234",
    )
    assert isinstance(snap, DashboardSnapshot)
    assert snap.decisions_in_window == 0
    assert snap.abstention_rate == 0.0
    assert snap.correctness_rate is None
    assert snap.recent_decisions == []


def test_build_snapshot_against_empty_ledger(tmp_path):
    """Empty ledger via back-compat shim -> zero-counted snapshot."""
    from lub.ledger import Ledger

    ledger = Ledger(tmp_path / "uq.db")
    try:
        # Pass the Ledger directly; the shim wraps it in LedgerSnapshotSource.
        snap = build_snapshot(
            ledger,
            evidence_store=None,
            period_start=datetime(2026, 4, 1),
            period_end=datetime(2026, 4, 30),
        )
    finally:
        ledger.close()
    assert snap.decisions_in_window == 0
    assert snap.abstention_rate == 0.0
    assert snap.correctness_rate is None
    assert snap.n_outcomes_recorded == 0
    assert snap.meta_calibration_ece is None
    assert snap.recent_decisions == []
    assert snap.oscal_envelope == {}


def test_build_snapshot_aggregates_real_decisions(tmp_path):
    """A few logged decisions must appear in KPIs and recent_decisions."""
    from lub.ledger import Ledger

    ledger = Ledger(tmp_path / "uq.db")
    try:
        qid = ledger.log_query("Is X true?", domain="banking")
        aid_pass = ledger.log_answer(qid, "gpt-4o", "openai", "yes", tier="prime")
        aid_refuse = ledger.log_answer(qid, "gpt-4o", "openai", "unsure", tier="prime")
        ledger.log_score(aid_pass, "p_true", 0.92)
        ledger.log_score(aid_refuse, "p_true", 0.31)
        ledger.log_policy(aid_pass, "EMIT", 0.7, True, "above threshold")
        ledger.log_policy(aid_refuse, "REFUSE", 0.7, False, "below threshold")
        ledger.update_outcome(aid_pass, correct=True)
        # Use the explicit SnapshotSource constructor to exercise the
        # post-pass-33 canonical path (rather than the back-compat shim).
        source = LedgerSnapshotSource(ledger)
        snap = build_snapshot(
            source,
            evidence_store=None,
            period_start=datetime(2020, 1, 1),
            period_end=datetime(2030, 1, 1),
        )
    finally:
        ledger.close()
    assert snap.decisions_in_window == 2
    assert snap.abstention_rate == pytest.approx(0.5)
    assert snap.n_outcomes_recorded == 1
    assert snap.correctness_rate == pytest.approx(1.0)
    assert len(snap.recent_decisions) == 2
    for row in snap.recent_decisions:
        assert row["domain"] == "banking"
        assert row["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# render_json + render_html (real since pass 31)
# ---------------------------------------------------------------------------


def test_render_json_returns_valid_json():
    import json as _json

    snap = DashboardSnapshot(
        period_start=datetime(2026, 4, 1),
        period_end=datetime(2026, 4, 30),
        tenant="t1",
        git_sha="abc",
        decisions_in_window=5,
        abstention_rate=0.2,
    )
    parsed = _json.loads(render_json(snap))
    assert parsed["tenant"] == "t1"
    assert parsed["decisions_in_window"] == 5
    assert parsed["abstention_rate"] == 0.2
    assert "2026-04-01" in parsed["period_start"]


def test_render_html_returns_self_contained_document():
    snap = DashboardSnapshot(
        period_start=datetime(2026, 4, 1),
        period_end=datetime(2026, 4, 30),
        tenant="t1",
        git_sha="abc",
        decisions_in_window=42,
        abstention_rate=0.15,
        correctness_rate=0.93,
        n_outcomes_recorded=10,
        meta_calibration_ece=0.041,
    )
    out = render_html(snap)
    assert out.startswith("<!DOCTYPE html>")
    assert "</html>" in out
    assert "42" in out
    assert "15.0%" in out
    assert "93.0%" in out
    assert "0.041" in out
    assert "Reliability" in out or "reliability" in out
    assert "OSCAL" in out
    assert "No decisions in the selected window." in out


def test_render_html_escapes_user_supplied_strings():
    snap = DashboardSnapshot(
        period_start=datetime(2026, 4, 1),
        period_end=datetime(2026, 4, 30),
        tenant="<script>alert(1)</script>",
        git_sha="<svg>",
        recent_decisions=[
            {
                "created_at": "2026-04-15T12:00:00.000Z",
                "domain": "<x>",
                "model": "m",
                "tier": "t",
                "decision": "<bad>",
                "reason": "<ignored>",
                "passed": 1,
            }
        ],
    )
    out = render_html(snap)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
    assert "<bad>" not in out
    assert "&lt;bad&gt;" in out


# ---------------------------------------------------------------------------
# server: real since pass 32 — raises ImportError when fastapi is missing
# (NOT NotImplementedError as in pre-pass-32)
# ---------------------------------------------------------------------------


def test_build_app_raises_importerror_when_fastapi_missing(tmp_path):
    """If fastapi is unavailable, build_app must raise ImportError with hint."""
    db = tmp_path / "uq.db"
    db.touch()
    with mock.patch.dict(sys.modules, {"fastapi": None}):
        with pytest.raises(ImportError, match="fastapi"):
            # Use the convenience wrapper (the original signature kept the
            # ledger_path-style API).
            from lub.dashboard import build_app_from_ledger_path
            build_app_from_ledger_path(db)


def test_run_uvicorn_raises_importerror_when_uvicorn_missing(tmp_path):
    db = tmp_path / "uq.db"
    db.touch()
    with mock.patch.dict(sys.modules, {"uvicorn": None}):
        with pytest.raises(ImportError, match="uvicorn|fastapi"):
            run_uvicorn(db, port=8081)
