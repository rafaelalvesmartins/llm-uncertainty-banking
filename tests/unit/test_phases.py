# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Hermetic tests for ``lub.orchestration.phases`` (Pattern 3)."""

from __future__ import annotations

import pytest

from lub.orchestration.phases import Phase, PhaseConfig, active_phases

# ---------------------------------------------------------------------------
# PhaseConfig validation
# ---------------------------------------------------------------------------


def test_phase_config_minimal():
    cfg = PhaseConfig(id="p1", start_week=1, end_week=2)
    assert cfg.id == "p1"
    assert cfg.start_week == 1
    assert cfg.end_week == 2
    assert cfg.prerequisites == ()


def test_phase_config_normalizes_prereq_list_to_tuple():
    cfg = PhaseConfig(
        id="p2", start_week=3, end_week=5, prerequisites=["p1"]
    )
    assert isinstance(cfg.prerequisites, tuple)
    assert cfg.prerequisites == ("p1",)


def test_phase_config_rejects_empty_id():
    with pytest.raises(ValueError, match="non-empty"):
        PhaseConfig(id="", start_week=1, end_week=2)


def test_phase_config_rejects_inverted_window():
    with pytest.raises(ValueError, match="start_week"):
        PhaseConfig(id="p", start_week=10, end_week=5)


def test_phase_config_allows_single_week_window():
    cfg = PhaseConfig(id="p", start_week=4, end_week=4)
    assert cfg.start_week == cfg.end_week


def test_phase_config_is_frozen():
    cfg = PhaseConfig(id="p", start_week=1, end_week=2)
    with pytest.raises(Exception):  # FrozenInstanceError, plus dataclass quirks
        cfg.id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase predicates
# ---------------------------------------------------------------------------


def test_phase_active_inside_window_no_prereqs():
    p = Phase(PhaseConfig(id="p1", start_week=1, end_week=3))
    assert p.is_active(1, set())
    assert p.is_active(2, set())
    assert p.is_active(3, set())


def test_phase_inactive_outside_window():
    p = Phase(PhaseConfig(id="p1", start_week=2, end_week=3))
    assert not p.is_active(1, set())
    assert not p.is_active(4, set())


def test_phase_with_unmet_prereq_is_inactive():
    p = Phase(PhaseConfig(
        id="p2", start_week=1, end_week=5, prerequisites=("p1",),
    ))
    assert not p.is_active(2, set())  # window OK, prereq missing
    assert not p.is_active(2, {"p3"})  # window OK, wrong prereq


def test_phase_with_met_prereq_becomes_active():
    p = Phase(PhaseConfig(
        id="p2", start_week=1, end_week=5, prerequisites=("p1",),
    ))
    assert p.is_active(2, {"p1"})


def test_phase_with_multiple_prereqs_requires_all():
    p = Phase(PhaseConfig(
        id="p3", start_week=1, end_week=5, prerequisites=("a", "b"),
    ))
    assert not p.is_active(2, {"a"})
    assert not p.is_active(2, {"b"})
    assert p.is_active(2, {"a", "b"})


def test_phase_is_blocked_predicate():
    p = Phase(PhaseConfig(
        id="p3", start_week=1, end_week=5, prerequisites=("a", "b"),
    ))
    assert p.is_blocked(set())
    assert p.is_blocked({"a"})
    assert not p.is_blocked({"a", "b"})


def test_phase_is_blocked_by_returns_unmet():
    p = Phase(PhaseConfig(
        id="p3", start_week=1, end_week=5, prerequisites=("a", "b", "c"),
    ))
    assert p.is_blocked_by(set()) == ("a", "b", "c")
    assert p.is_blocked_by({"a"}) == ("b", "c")
    assert p.is_blocked_by({"a", "b", "c"}) == ()


def test_phase_id_property_mirrors_config():
    p = Phase(PhaseConfig(id="hello", start_week=1, end_week=2))
    assert p.id == "hello"


# ---------------------------------------------------------------------------
# active_phases helper
# ---------------------------------------------------------------------------


def test_active_phases_filter_preserves_input_order():
    p1 = Phase(PhaseConfig(id="p1", start_week=1, end_week=10))
    p2 = Phase(PhaseConfig(id="p2", start_week=5, end_week=10,
                            prerequisites=("p1",)))
    p3 = Phase(PhaseConfig(id="p3", start_week=1, end_week=2))
    result = active_phases([p1, p2, p3], week=2, completed_phases={"p1"})
    assert [x.id for x in result] == ["p1", "p3"]


def test_active_phases_empty_when_nothing_qualifies():
    p1 = Phase(PhaseConfig(id="p1", start_week=10, end_week=20))
    assert active_phases([p1], week=1, completed_phases=set()) == []
