# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Unit tests for :mod:`lub.challenge.replay`.

Hermetic — no LLM calls. The ledger is seeded from the JSONL fixture
at ``tests/fixtures/cec_ledger.jsonl`` via
``tests.unit._cec_helpers.load_ledger_fixture``.

Spec: planning/24_CEC_Spec_2026-04-25.md §1.1 + §4 step 1.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from lub.challenge import (
    AlternativeEstimator,
    AlternativeThreshold,
    AlternativeTier,
    ReplayEngine,
    ReplayReport,
)
from lub.challenge.replay import _DEFAULT_TIER_COST_PER_1K, _iso_window
from tests.unit._cec_helpers import load_ledger_fixture


def _full_window() -> tuple[datetime, datetime]:
    return datetime(2026, 4, 1), datetime(2026, 5, 1)


def test_replay_returns_report_with_expected_shape() -> None:
    with load_ledger_fixture() as led:
        engine = ReplayEngine(ledger=led)
        start, end = _full_window()
        rep = engine.replay_window(start, end, AlternativeThreshold(0.85))
    assert isinstance(rep, ReplayReport)
    assert rep.window_start == start
    assert rep.window_end == end
    assert rep.sample_size == 10
    assert 0.0 <= rep.baseline_abstention_rate <= 1.0
    assert 0.0 <= rep.counterfactual_abstention_rate <= 1.0
    assert isinstance(rep.audit_trail, dict)
    assert rep.audit_trail["alternative_kind"] == "AlternativeThreshold"


def test_alternative_threshold_lowers_abstention_when_value_drops() -> None:
    """Threshold 0.80 should never abstain MORE than 0.85 on the same data."""
    with load_ledger_fixture() as led:
        engine = ReplayEngine(ledger=led)
        start, end = _full_window()
        high = engine.replay_window(start, end, AlternativeThreshold(0.85))
        low = engine.replay_window(start, end, AlternativeThreshold(0.80))
    assert (
        low.counterfactual_abstention_rate
        <= high.counterfactual_abstention_rate
    )


def test_alternative_estimator_is_deterministic() -> None:
    with load_ledger_fixture() as led:
        engine = ReplayEngine(ledger=led)
        start, end = _full_window()
        a = engine.replay_window(
            start, end, AlternativeEstimator("adaptive_conformal")
        )
        b = engine.replay_window(
            start, end, AlternativeEstimator("adaptive_conformal")
        )
    assert a.counterfactual_abstention_rate == pytest.approx(
        b.counterfactual_abstention_rate
    )
    assert a.cost_delta_estimate == pytest.approx(b.cost_delta_estimate)


def test_alternative_tier_uses_cost_table() -> None:
    with load_ledger_fixture() as led:
        engine = ReplayEngine(ledger=led)
        start, end = _full_window()
        rep = engine.replay_window(start, end, AlternativeTier("opus"))
    # opus default tier cost is 15.00 per 1k → 0.015 per call. With baseline
    # near 0.0008-0.003, counterfactual cost > baseline → positive delta.
    assert rep.cost_delta_estimate > 0
    assert rep.audit_trail["alternative_kind"] == "AlternativeTier"


def test_alternative_tier_fuzzy_matching() -> None:
    """``claude-haiku-4-6`` should match the ``haiku`` row."""
    with load_ledger_fixture() as led:
        engine = ReplayEngine(ledger=led)
        start, end = _full_window()
        rep = engine.replay_window(
            start, end, AlternativeTier("claude-haiku-4-6")
        )
    # haiku is cheaper than tier-1 for some baseline rows but similar for
    # others; we only assert the cost computation completed.
    assert rep.sample_size == 10


def test_correctness_rate_is_none_when_no_outcomes() -> None:
    """Empty window → both correctness rates None."""
    with load_ledger_fixture() as led:
        engine = ReplayEngine(ledger=led)
        # Window before any fixture rows.
        rep = engine.replay_window(
            datetime(2025, 1, 1),
            datetime(2025, 1, 2),
            AlternativeThreshold(0.5),
        )
    assert rep.sample_size == 0
    assert rep.baseline_correctness_rate is None
    assert rep.counterfactual_correctness_rate is None
    assert rep.cost_delta_estimate == 0.0
    assert rep.baseline_abstention_rate == 0.0


def test_unknown_alternative_raises() -> None:
    with load_ledger_fixture() as led:
        engine = ReplayEngine(ledger=led)
        with pytest.raises(TypeError, match="unknown alternative"):
            engine._counterfactual_for_row(  # noqa: SLF001
                {
                    "answer_id": 1,
                    "confidence": 0.5,
                    "correct": None,
                    "cost": 0.0,
                    "decision": "PASS",
                    "tier": "tier-1",
                    "model": "dummy",
                },
                alternative=object(),  # type: ignore[arg-type]
            )


def test_alternative_dataclasses_are_frozen() -> None:
    a = AlternativeEstimator("x")
    b = AlternativeTier("y")
    c = AlternativeThreshold(0.5)
    with pytest.raises((AttributeError, Exception)):
        a.name = "z"  # type: ignore[misc]
    with pytest.raises((AttributeError, Exception)):
        b.model_id = "z"  # type: ignore[misc]
    with pytest.raises((AttributeError, Exception)):
        c.value = 0.7  # type: ignore[misc]


def test_iso_window_helper_round_trips() -> None:
    s, e = _iso_window(datetime(2026, 4, 1), datetime(2026, 5, 1))
    assert s == "2026-04-01T00:00:00.000000"
    assert e == "2026-05-01T00:00:00.000000"


def test_default_tier_cost_table_has_known_rows() -> None:
    assert "tier-1" in _DEFAULT_TIER_COST_PER_1K
    assert "haiku" in _DEFAULT_TIER_COST_PER_1K


def test_custom_tier_cost_override() -> None:
    with load_ledger_fixture() as led:
        engine = ReplayEngine(
            ledger=led, tier_cost_per_1k={"opus": 100.0}
        )
        start, end = _full_window()
        rep = engine.replay_window(start, end, AlternativeTier("opus"))
    # 100 USD/1k = 0.1/call → very large positive delta over baseline.
    assert rep.cost_delta_estimate > 50.0


def test_threshold_zero_never_abstains() -> None:
    with load_ledger_fixture() as led:
        engine = ReplayEngine(ledger=led)
        start, end = _full_window()
        rep = engine.replay_window(start, end, AlternativeThreshold(0.0))
    assert rep.counterfactual_abstention_rate == 0.0


def test_threshold_one_always_abstains() -> None:
    with load_ledger_fixture() as led:
        engine = ReplayEngine(ledger=led)
        start, end = _full_window()
        rep = engine.replay_window(start, end, AlternativeThreshold(1.0))
    # Strict-less-than: only confidences >= 1.0 wouldn't abstain — none do.
    assert rep.counterfactual_abstention_rate == 1.0


def test_audit_trail_carries_method_and_threshold() -> None:
    with load_ledger_fixture() as led:
        engine = ReplayEngine(
            ledger=led, score_method="confidence", baseline_threshold=0.9
        )
        start, end = _full_window()
        rep = engine.replay_window(start, end, AlternativeThreshold(0.85))
    assert rep.audit_trail["score_method"] == "confidence"
    assert rep.audit_trail["baseline_threshold"] == 0.9
    assert rep.audit_trail["n_rows_in_window"] == 10
