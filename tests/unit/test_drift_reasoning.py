# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.challenge.drift_reasoning`."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
from types import SimpleNamespace
from typing import Any

import pytest

from lub.challenge.drift_reasoning import (
    DriftHypothesis,
    _build_paragraph,
    _classify_psi,
    _direction,
    _resolve_drift_event,
    explain_drift_event,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _Neighbour:
    """Minimal evidence-store neighbour stub."""

    def __init__(self, ident: str, similarity: float, question: str = "") -> None:
        self.id = ident
        self.cosine_similarity = similarity
        self.question = question


class _EvidenceStore:
    """Stub evidence store with a configurable query() and drift_events dict."""

    def __init__(
        self,
        neighbours: list[_Neighbour] | None = None,
        drift_events: dict[str, Any] | None = None,
        positional_only: bool = False,
        raise_on_query: bool = False,
    ) -> None:
        self._neighbours = neighbours or []
        self.drift_events = drift_events or {}
        self._positional_only = positional_only
        self._raise_on_query = raise_on_query
        self.calls: list[tuple[str, int]] = []

    def query(self, query_text: str, k: int = 5) -> list[_Neighbour]:
        if self._positional_only:
            # Simulate a query function that does not accept k=... kwarg.
            # The first call (with k=...) should raise TypeError so the
            # production code falls back to the positional invocation.
            raise NotImplementedError  # pragma: no cover - replaced below

        if self._raise_on_query:
            raise RuntimeError("evidence store unavailable")

        self.calls.append((query_text, k))
        return list(self._neighbours)


class _PositionalOnlyStore:
    """Evidence store whose query() rejects k as a keyword argument."""

    def __init__(self, neighbours: list[_Neighbour]) -> None:
        self._neighbours = neighbours
        self.drift_events: dict[str, Any] = {}
        self.calls: list[tuple[str, int]] = []

    def query(self, *args: Any, **kwargs: Any) -> list[_Neighbour]:
        if kwargs:
            raise TypeError("query() takes no keyword arguments")
        query_text, k = args
        self.calls.append((query_text, k))
        return list(self._neighbours)


class _Ledger:
    """Stub ledger that may carry drift_events."""

    def __init__(self, drift_events: dict[str, Any] | None = None) -> None:
        self.drift_events = drift_events or {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_ledger() -> _Ledger:
    return _Ledger()


@pytest.fixture()
def empty_store() -> _EvidenceStore:
    return _EvidenceStore()


@pytest.fixture()
def significant_event() -> dict[str, Any]:
    return {
        "psi": 0.42,
        "reference_mean": 0.80,
        "current_mean": 0.55,
        "domain": "credit_scoring",
    }


# ---------------------------------------------------------------------------
# DriftHypothesis dataclass
# ---------------------------------------------------------------------------


class TestDriftHypothesis:
    def test_defaults(self) -> None:
        h = DriftHypothesis(drift_event_id="evt-1", hypothesis="text")
        assert h.drift_event_id == "evt-1"
        assert h.hypothesis == "text"
        assert h.support_evidence_ids == []
        assert h.similarity_score == 0.0
        assert h.metadata == {}

    def test_is_frozen(self) -> None:
        h = DriftHypothesis(drift_event_id="evt-1", hypothesis="t")
        with pytest.raises(FrozenInstanceError):
            h.hypothesis = "mutated"  # type: ignore[misc]

    def test_distinct_default_containers_per_instance(self) -> None:
        a = DriftHypothesis(drift_event_id="a", hypothesis="x")
        b = DriftHypothesis(drift_event_id="b", hypothesis="y")
        assert a.support_evidence_ids is not b.support_evidence_ids
        assert a.metadata is not b.metadata

    def test_round_trip_via_asdict(self) -> None:
        h = DriftHypothesis(
            drift_event_id="evt",
            hypothesis="why",
            support_evidence_ids=["q1", "q2"],
            similarity_score=0.7,
            metadata={"severity": "moderate"},
        )
        d = asdict(h)
        assert d["drift_event_id"] == "evt"
        assert d["support_evidence_ids"] == ["q1", "q2"]
        assert d["similarity_score"] == 0.7
        assert d["metadata"] == {"severity": "moderate"}
        # And rebuild from the serialized form.
        rebuilt = DriftHypothesis(**d)
        assert rebuilt == h


# ---------------------------------------------------------------------------
# _classify_psi -- OCC 2011-12 thresholds
# ---------------------------------------------------------------------------


class TestClassifyPsi:
    def test_zero_psi_is_none(self) -> None:
        sev, phrase = _classify_psi(0.0)
        assert sev == "none"
        assert "no material" in phrase

    def test_just_below_moderate_threshold(self) -> None:
        sev, _ = _classify_psi(0.0999)
        assert sev == "none"

    def test_at_moderate_threshold(self) -> None:
        # 0.10 is the inclusive lower bound of "moderate".
        sev, phrase = _classify_psi(0.10)
        assert sev == "moderate"
        assert "moderate" in phrase

    def test_just_below_significant_threshold(self) -> None:
        sev, _ = _classify_psi(0.2499)
        assert sev == "moderate"

    def test_at_significant_threshold(self) -> None:
        sev, phrase = _classify_psi(0.25)
        assert sev == "significant"
        assert "significant" in phrase

    def test_large_psi_is_significant(self) -> None:
        sev, _ = _classify_psi(5.0)
        assert sev == "significant"


# ---------------------------------------------------------------------------
# _direction
# ---------------------------------------------------------------------------


class TestDirection:
    def test_essentially_flat(self) -> None:
        assert _direction(0.50, 0.505) == "essentially flat confidence"
        assert _direction(0.50, 0.495) == "essentially flat confidence"

    def test_confidence_rose(self) -> None:
        out = _direction(0.50, 0.80)
        assert out.startswith("confidence rose by")
        assert "+0.30" in out

    def test_confidence_fell(self) -> None:
        out = _direction(0.80, 0.55)
        assert out.startswith("confidence fell by")
        # The signed format keeps the minus sign.
        assert "-0.25" in out


# ---------------------------------------------------------------------------
# _resolve_drift_event
# ---------------------------------------------------------------------------


class TestResolveDriftEvent:
    def test_found_in_ledger(self) -> None:
        evt = {"psi": 0.3}
        ledger = _Ledger({"evt-1": evt})
        store = _EvidenceStore()
        assert _resolve_drift_event("evt-1", ledger, store) is evt

    def test_found_in_store_when_absent_from_ledger(self) -> None:
        evt = {"psi": 0.4}
        ledger = _Ledger()
        store = _EvidenceStore(drift_events={"evt-2": evt})
        assert _resolve_drift_event("evt-2", ledger, store) is evt

    def test_unknown_event_returns_none(self) -> None:
        assert _resolve_drift_event("missing", _Ledger(), _EvidenceStore()) is None

    def test_ignores_non_dict_event(self) -> None:
        ledger = _Ledger({"evt-1": "not-a-dict"})  # type: ignore[dict-item]
        store = _EvidenceStore()
        assert _resolve_drift_event("evt-1", ledger, store) is None

    def test_ledger_without_drift_events_attribute(self) -> None:
        bare = SimpleNamespace()
        store = _EvidenceStore(drift_events={"evt-1": {"psi": 0.1}})
        out = _resolve_drift_event("evt-1", bare, store)
        assert out == {"psi": 0.1}


# ---------------------------------------------------------------------------
# _build_paragraph
# ---------------------------------------------------------------------------


class TestBuildParagraph:
    def test_no_neighbours_mentions_psi_only(self) -> None:
        out = _build_paragraph(
            severity="none",
            severity_phrase="no material distributional shift",
            direction_phrase="essentially flat confidence",
            psi=0.05,
            n_neighbours=0,
            max_similarity=0.0,
            domain=None,
        )
        assert "PSI=0.050" in out
        assert "No similar past drift events" in out
        assert "informational" in out  # action for "none"

    def test_significant_with_neighbours_and_domain(self) -> None:
        out = _build_paragraph(
            severity="significant",
            severity_phrase="a significant distributional shift",
            direction_phrase="confidence fell by -0.25",
            psi=0.42,
            n_neighbours=3,
            max_similarity=0.87,
            domain="credit_scoring",
        )
        assert "PSI=0.420" in out
        assert "on the credit_scoring domain" in out
        assert "3 historically" in out
        assert "0.87" in out
        assert "Tier-2 spot" in out  # significant-severity action

    def test_moderate_action_text(self) -> None:
        out = _build_paragraph(
            severity="moderate",
            severity_phrase="a moderate distributional shift",
            direction_phrase="confidence rose by +0.05",
            psi=0.15,
            n_neighbours=1,
            max_similarity=0.5,
            domain="kyc",
        )
        assert "monitoring this signal" in out
        assert "two windows" in out


# ---------------------------------------------------------------------------
# explain_drift_event -- main API
# ---------------------------------------------------------------------------


class TestExplainDriftEvent:
    def test_invalid_k_raises(self, empty_ledger: _Ledger, empty_store: _EvidenceStore) -> None:
        with pytest.raises(ValueError, match="k must be positive"):
            explain_drift_event("evt", empty_ledger, empty_store, k=0)
        with pytest.raises(ValueError, match="k must be positive"):
            explain_drift_event("evt", empty_ledger, empty_store, k=-1)

    def test_unknown_event_yields_neutral_hypothesis(
        self, empty_ledger: _Ledger, empty_store: _EvidenceStore
    ) -> None:
        h = explain_drift_event("missing", empty_ledger, empty_store)
        assert isinstance(h, DriftHypothesis)
        assert h.drift_event_id == "missing"
        assert h.support_evidence_ids == []
        assert h.similarity_score == 0.0
        assert h.metadata["severity"] == "none"
        assert h.metadata["psi"] == 0.0
        assert h.metadata["k"] == 5
        # similarity must always live in [0, 1] to satisfy banking-policy bounds.
        assert 0.0 <= h.similarity_score <= 1.0

    def test_significant_event_with_neighbours(
        self, empty_ledger: _Ledger, significant_event: dict[str, Any]
    ) -> None:
        neighbours = [
            _Neighbour("q1", 0.91),
            _Neighbour("q2", 0.55),
            _Neighbour("q3", 0.40),
        ]
        store = _EvidenceStore(
            neighbours=neighbours,
            drift_events={"evt-sig": significant_event},
        )
        h = explain_drift_event("evt-sig", empty_ledger, store, k=3)

        assert h.drift_event_id == "evt-sig"
        assert h.support_evidence_ids == ["q1", "q2", "q3"]
        assert h.similarity_score == pytest.approx(0.91)
        # The query was issued against the configured store with the right k.
        assert store.calls == [(store.calls[0][0], 3)]
        assert h.metadata == {
            "severity": "significant",
            "psi": 0.42,
            "reference_mean": 0.80,
            "current_mean": 0.55,
            "domain": "credit_scoring",
            "k": 3,
        }
        assert "Tier-2 spot" in h.hypothesis
        assert "credit_scoring" in h.hypothesis

    def test_event_resolved_from_ledger_first(self) -> None:
        ledger_evt = {"psi": 0.30, "reference_mean": 0.7, "current_mean": 0.6, "domain": "x"}
        store_evt = {"psi": 0.05}
        ledger = _Ledger({"evt-1": ledger_evt})
        store = _EvidenceStore(drift_events={"evt-1": store_evt})
        h = explain_drift_event("evt-1", ledger, store)
        assert h.metadata["psi"] == 0.30
        assert h.metadata["severity"] == "significant"

    def test_alternate_mean_keys_are_accepted(self) -> None:
        ledger = _Ledger({"evt": {"psi": 0.12, "ref_mean": 0.80, "cur_mean": 0.79}})
        store = _EvidenceStore()
        h = explain_drift_event("evt", ledger, store)
        assert h.metadata["reference_mean"] == 0.80
        assert h.metadata["current_mean"] == 0.79
        # 0.79 - 0.80 = -0.01, |delta| not < 0.01 -> "fell"
        assert "fell" in h.hypothesis or "flat" in h.hypothesis

    def test_no_neighbours_keeps_similarity_zero(
        self, empty_ledger: _Ledger, significant_event: dict[str, Any]
    ) -> None:
        store = _EvidenceStore(neighbours=[], drift_events={"evt": significant_event})
        h = explain_drift_event("evt", empty_ledger, store)
        assert h.support_evidence_ids == []
        assert h.similarity_score == 0.0
        assert "No similar past drift events" in h.hypothesis

    def test_similarity_score_bounded_in_unit_interval(
        self, empty_ledger: _Ledger
    ) -> None:
        # All neighbour cosine sims live in [0, 1] in production; guard
        # asserts the property holds for the worst-case neighbour set we expect.
        store = _EvidenceStore(
            neighbours=[_Neighbour("a", 0.0), _Neighbour("b", 1.0)],
            drift_events={"evt": {"psi": 0.05}},
        )
        h = explain_drift_event("evt", empty_ledger, store)
        assert 0.0 <= h.similarity_score <= 1.0
        assert h.similarity_score == 1.0

    def test_neighbour_falls_back_to_question_when_id_missing(
        self, empty_ledger: _Ledger
    ) -> None:
        n = SimpleNamespace(cosine_similarity=0.6, question="how-much-can-i-borrow")
        store = _EvidenceStore(
            neighbours=[n],  # type: ignore[list-item]
            drift_events={"evt": {"psi": 0.30}},
        )
        h = explain_drift_event("evt", empty_ledger, store)
        assert h.support_evidence_ids == ["how-much-can-i-borrow"]

    def test_neighbour_with_no_identifier_is_skipped(
        self, empty_ledger: _Ledger
    ) -> None:
        n = SimpleNamespace(cosine_similarity=0.5)  # no .id, no .question
        store = _EvidenceStore(
            neighbours=[n],  # type: ignore[list-item]
            drift_events={"evt": {"psi": 0.30}},
        )
        h = explain_drift_event("evt", empty_ledger, store)
        assert h.support_evidence_ids == []
        # The similarity is still recorded -- only the id list is filtered.
        assert h.similarity_score == pytest.approx(0.5)

    def test_query_without_k_kwarg_falls_back_to_positional(
        self, empty_ledger: _Ledger
    ) -> None:
        store = _PositionalOnlyStore([_Neighbour("p1", 0.42)])
        store.drift_events = {"evt": {"psi": 0.30}}
        h = explain_drift_event("evt", empty_ledger, store, k=4)
        assert store.calls and store.calls[0][1] == 4
        assert h.support_evidence_ids == ["p1"]

    def test_evidence_store_without_query_callable(
        self, empty_ledger: _Ledger, significant_event: dict[str, Any]
    ) -> None:
        store = SimpleNamespace(drift_events={"evt": significant_event})
        h = explain_drift_event("evt", empty_ledger, store)
        # No query() -> no neighbours, no support evidence.
        assert h.support_evidence_ids == []
        assert h.similarity_score == 0.0
        assert h.metadata["severity"] == "significant"
        # Still produces a paragraph based on PSI alone.
        assert "PSI=" in h.hypothesis

    def test_default_k_is_five(self, empty_ledger: _Ledger) -> None:
        store = _EvidenceStore(
            neighbours=[],
            drift_events={"evt": {"psi": 0.05}},
        )
        h = explain_drift_event("evt", empty_ledger, store)
        assert store.calls and store.calls[0][1] == 5
        assert h.metadata["k"] == 5
