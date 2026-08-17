# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Unit tests for :mod:`lub.challenge.drift_reasoning`.

Spec: planning/24_CEC_Spec_2026-04-25.md §1.2 + §4 step 2.
"""

from __future__ import annotations

import pytest

from lub.challenge import DriftHypothesis, explain_drift_event
from lub.challenge.drift_reasoning import (
    _classify_psi,
    _direction,
    _resolve_drift_event,
)
from tests.unit._cec_helpers import (
    attach_drift_events,
    deterministic_evidence_store,
    load_ledger_fixture,
)


def test_classify_psi_thresholds() -> None:
    assert _classify_psi(0.05)[0] == "none"
    assert _classify_psi(0.20)[0] == "moderate"
    assert _classify_psi(0.30)[0] == "significant"


def test_direction_phrasing() -> None:
    assert "rose" in _direction(0.7, 0.85)
    assert "fell" in _direction(0.85, 0.70)
    assert "flat" in _direction(0.85, 0.851)


def test_resolve_drift_event_from_ledger_attribute() -> None:
    led = load_ledger_fixture()
    events = attach_drift_events(led)
    store = deterministic_evidence_store()
    payload = _resolve_drift_event("drift-2026-04-15", led, store)
    assert payload is not None
    assert payload["psi"] == events["drift-2026-04-15"]["psi"]
    led.close()


def test_resolve_drift_event_unknown_returns_none() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    assert _resolve_drift_event("does-not-exist", led, store) is None
    led.close()


def test_explain_drift_event_significant() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    dh = explain_drift_event(
        "drift-2026-04-15",
        ledger=led,
        evidence_store=store,
        k=5,
    )
    assert isinstance(dh, DriftHypothesis)
    assert dh.drift_event_id == "drift-2026-04-15"
    assert "significant" in dh.hypothesis.lower() or "calibration review" in dh.hypothesis.lower()
    assert dh.metadata["severity"] == "significant"
    assert 0.0 <= dh.similarity_score <= 1.0
    led.close()


def test_explain_drift_event_moderate() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    dh = explain_drift_event(
        "drift-2026-04-20",
        ledger=led,
        evidence_store=store,
    )
    assert dh.metadata["severity"] == "moderate"
    assert "moderate" in dh.hypothesis.lower() or "monitor" in dh.hypothesis.lower()
    led.close()


def test_explain_drift_event_unknown_id() -> None:
    """Unknown ids degrade gracefully — psi=0 → severity 'none'."""
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    dh = explain_drift_event(
        "ghost-event", ledger=led, evidence_store=store
    )
    assert dh.metadata["severity"] == "none"
    assert isinstance(dh.hypothesis, str)
    led.close()


def test_explain_drift_event_handles_no_evidence_store() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)

    class _Empty:
        pass

    dh = explain_drift_event("drift-2026-04-15", ledger=led, evidence_store=_Empty())
    assert dh.support_evidence_ids == []
    assert dh.similarity_score == 0.0
    led.close()


def test_explain_drift_event_rejects_non_positive_k() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    with pytest.raises(ValueError, match="positive"):
        explain_drift_event(
            "drift-2026-04-15", ledger=led, evidence_store=store, k=0
        )
    led.close()


def test_drift_hypothesis_is_one_paragraph() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    dh = explain_drift_event(
        "drift-2026-04-15", ledger=led, evidence_store=store
    )
    # No double newline → single paragraph.
    assert "\n\n" not in dh.hypothesis
    assert 30 < len(dh.hypothesis.split()) < 200
    led.close()


def test_support_evidence_ids_pulled_from_store() -> None:
    led = load_ledger_fixture()
    attach_drift_events(led)
    store = deterministic_evidence_store()
    dh = explain_drift_event(
        "drift-2026-04-15", ledger=led, evidence_store=store, k=3
    )
    assert len(dh.support_evidence_ids) <= 3
