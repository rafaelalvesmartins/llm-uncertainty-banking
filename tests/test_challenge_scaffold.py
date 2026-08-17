# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Public-surface smoke tests for ``lub.challenge`` (CEC).

History — three states this file has been in:

1. Pass 21 (2026-04-25): pure-scaffold mode. Asserted ``NotImplementedError``
   on every public entry point because every method was a stub.
2. Passes 22-24: scaffold filled in. ``replay``, ``drift_reasoning``,
   ``meta_calibration``, ``cec_report``, and ``oscal_export`` all moved
   from stubs to real implementations between scaffold-creation and now.
3. Pass 25 (this file): the NotImplementedError asserts are now stale —
   they would actively fail CI because the methods have real behavior.
   This file therefore retreats to **public-surface smoke tests only**:
   imports work, dataclasses are constructible, the API shape matches
   the spec at ``planning/24_CEC_Spec_2026-04-25.md``.

The full per-module behavior tests should live in per-module test files
(``test_challenge_replay.py``, ``test_challenge_drift_reasoning.py``,
``test_challenge_meta_calibration.py``, ``test_challenge_reports.py``)
written alongside the v0.3 implementation, with hermetic fixtures
(in-memory sqlite ledger seeded from JSONL, deterministic hash
embeddings). This file is kept only as the API-surface lock.
"""

from __future__ import annotations

from datetime import datetime

from lub.challenge import (
    AlternativeEstimator,
    AlternativeThreshold,
    AlternativeTier,
    CECReport,
    DriftHypothesis,
    MetaCalibrator,
    ReplayEngine,
    ReplayReport,
    assemble_cec_report,
    explain_drift_event,
)
from lub.challenge.reports.oscal_export import to_oscal_assessment_results


def test_replay_alternatives_are_constructible():
    """Frozen dataclasses for the three alternative shapes work as expected."""
    a = AlternativeEstimator("adaptive_conformal")
    b = AlternativeTier("claude-sonnet-4-6")
    c = AlternativeThreshold(0.85)

    assert a.name == "adaptive_conformal"
    assert b.model_id == "claude-sonnet-4-6"
    assert c.value == 0.85


def test_replay_report_dataclass_shape():
    """Lock the public field set on ReplayReport."""
    rr = ReplayReport(
        window_start=datetime(2026, 4, 1),
        window_end=datetime(2026, 4, 30),
        alternative=AlternativeThreshold(0.85),
        sample_size=0,
        baseline_abstention_rate=0.0,
        counterfactual_abstention_rate=0.0,
        baseline_correctness_rate=None,
        counterfactual_correctness_rate=None,
        cost_delta_estimate=0.0,
    )
    assert rr.sample_size == 0
    assert rr.cost_delta_estimate == 0.0
    assert rr.audit_trail == {}


def test_drift_hypothesis_dataclass_shape():
    """Lock the public field set on DriftHypothesis."""
    dh = DriftHypothesis(
        drift_event_id="drift-001",
        hypothesis="Stub.",
    )
    assert dh.drift_event_id == "drift-001"
    assert dh.hypothesis == "Stub."
    assert dh.support_evidence_ids == []
    assert dh.similarity_score == 0.0
    assert dh.metadata == {}


def test_cec_report_dataclass_shape():
    """Lock the public field set on CECReport."""
    rep = CECReport(
        period_start=datetime(2026, 4, 1),
        period_end=datetime(2026, 4, 30),
    )
    assert rep.replay_summary == []
    assert rep.drift_hypotheses == []
    assert rep.meta_calibration_snapshot is None
    assert rep.recommendations == []
    assert rep.signed_provenance == {}


def test_public_api_callables_exist():
    """Confirm the expected public callables are importable.

    The behavior tests live in per-module test files; this just
    locks the names so a future rename trips CI.
    """
    assert callable(ReplayEngine)
    assert callable(MetaCalibrator)
    assert callable(explain_drift_event)
    assert callable(assemble_cec_report)
    assert callable(to_oscal_assessment_results)
