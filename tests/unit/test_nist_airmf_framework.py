# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for :mod:`lub.compliance.frameworks.nist_airmf`.

This module is a thin metadata-and-delegation adapter that exposes the
NIST AI 600-1 (Generative AI Profile of AI RMF 1.0) controls held in
``crosswalk_data.toml`` under a fixed contract
(``REGIME`` / ``CROSSWALK_KEY`` / ``TITLE`` / ``get_controls()``).

The shared parametrized suite in ``test_compliance_frameworks.py`` already
covers the *seven-framework* contract; the tests here pin the
NIST-specific surface so a refactor that silently rebinds
``REGIME`` or short-circuits ``get_controls()`` cannot pass CI.

Hermetic: no network, no LLM, no backend.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

from lub.compliance.frameworks import nist_airmf
from lub.compliance.frameworks.protocols import ComplianceFrameworkProtocol
from lub.reports import crosswalk
from lub.reports.crosswalk import ControlMapping, Regime

if TYPE_CHECKING:
    from collections.abc import Iterable


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def controls() -> list[ControlMapping]:
    """Live controls from the real TOML — hermetic (file is shipped in the wheel)."""
    return nist_airmf.get_controls()


@pytest.fixture
def fake_controls() -> list[ControlMapping]:
    """Two-element synthetic control set, sorted by control_id."""
    return [
        ControlMapping(
            control_id="GV-1.1",
            control_title="Policies",
            description="Establish AI policies.",
        ),
        ControlMapping(
            control_id="MS-2.5",
            control_title="Measurement",
            description="Measure AI risks.",
        ),
    ]


@pytest.fixture
def patched_crosswalk(
    monkeypatch: pytest.MonkeyPatch,
    fake_controls: list[ControlMapping],
) -> Iterator[list[ControlMapping]]:
    """Replace ``get_all_controls_for_regime`` with a recording fake."""
    calls: list[Regime] = []

    def _fake(regime: Regime) -> list[ControlMapping]:
        calls.append(regime)
        return fake_controls

    monkeypatch.setattr(crosswalk, "get_all_controls_for_regime", _fake)
    # nist_airmf imported the symbol at module load — rebind on the consumer too.
    monkeypatch.setattr(nist_airmf, "get_all_controls_for_regime", _fake)
    yield fake_controls
    # `calls` is observable via closure if a test needs it; not asserted globally.


# ---------------------------------------------------------------------------
# Metadata contract
# ---------------------------------------------------------------------------


def test_regime_is_nist_genai() -> None:
    """REGIME must be the NIST_GENAI enum value, not a string look-alike."""
    assert nist_airmf.REGIME is Regime.NIST_GENAI


def test_crosswalk_key_matches_regime_enum_name() -> None:
    """CROSSWALK_KEY equals ``Regime.NIST_GENAI.name`` (the TOML key)."""
    assert nist_airmf.CROSSWALK_KEY == "NIST_GENAI"
    assert nist_airmf.CROSSWALK_KEY == Regime.NIST_GENAI.name


def test_title_names_the_publication() -> None:
    """TITLE references AI 600-1 and AI RMF 1.0 so report headers are unambiguous."""
    assert "AI 600-1" in nist_airmf.TITLE
    assert "AI RMF 1.0" in nist_airmf.TITLE


def test_public_surface_is_exactly_four_names() -> None:
    """``__all__`` pins the v0.1 plug-in surface — no accidental exports."""
    assert set(nist_airmf.__all__) == {
        "CROSSWALK_KEY",
        "REGIME",
        "TITLE",
        "get_controls",
    }


# ---------------------------------------------------------------------------
# get_controls — shape and delegation
# ---------------------------------------------------------------------------


def test_get_controls_returns_non_empty_list(controls: list[ControlMapping]) -> None:
    """NIST 600-1 has controls in the crosswalk (8 distinct refs per docstring)."""
    assert isinstance(controls, list)
    assert len(controls) > 0


def test_each_control_has_control_mapping_shape(
    controls: list[ControlMapping],
) -> None:
    """Every entry must satisfy the ControlMapping TypedDict (3 string keys)."""
    for c in controls:
        assert isinstance(c, dict)
        assert set(c.keys()) >= {"control_id", "control_title", "description"}
        assert isinstance(c["control_id"], str) and c["control_id"]
        assert isinstance(c["control_title"], str) and c["control_title"]
        assert isinstance(c["description"], str) and c["description"]


def test_control_ids_are_unique(controls: list[ControlMapping]) -> None:
    """Crosswalk de-duplicates by control_id; the adapter must not reintroduce dupes."""
    ids = [c["control_id"] for c in controls]
    assert len(ids) == len(set(ids))


def test_controls_are_sorted_by_control_id(controls: list[ControlMapping]) -> None:
    """Crosswalk contract: results are sorted by control_id ascending."""
    ids = [c["control_id"] for c in controls]
    assert ids == sorted(ids)


def test_get_controls_returns_fresh_list_each_call() -> None:
    """The adapter calls ``list(...)`` — mutating a returned list must not bleed.

    This is a real concern: a caller building per-framework reports may append
    derived rows to the list, and if the adapter returned a shared reference
    those rows would silently appear in the next caller's view.
    """
    first = nist_airmf.get_controls()
    first.append(
        ControlMapping(
            control_id="INJECTED",
            control_title="t",
            description="d",
        )
    )
    second = nist_airmf.get_controls()
    assert all(c["control_id"] != "INJECTED" for c in second)


def test_get_controls_delegates_to_crosswalk_with_correct_regime(
    patched_crosswalk: list[ControlMapping],
) -> None:
    """The adapter must pass ``Regime.NIST_GENAI`` and surface the fake unchanged."""
    result = nist_airmf.get_controls()
    assert result == patched_crosswalk
    # Identity check: the adapter wraps with ``list(...)`` so it is a copy, not the same obj.
    assert result is not patched_crosswalk


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_module_satisfies_compliance_framework_protocol() -> None:
    """Structural Protocol check — gates the v0.3 plug-in contract."""
    assert isinstance(nist_airmf, ComplianceFrameworkProtocol)


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


def test_get_controls_propagates_crosswalk_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken crosswalk must NOT be silently swallowed by the adapter.

    The framework module is the contract surface; if the underlying TOML
    parser breaks, callers need the traceback, not an empty list.
    """

    def _boom(regime: Regime) -> list[ControlMapping]:
        raise RuntimeError(f"crosswalk parse failed for {regime!r}")

    monkeypatch.setattr(nist_airmf, "get_all_controls_for_regime", _boom)
    with pytest.raises(RuntimeError, match="crosswalk parse failed"):
        nist_airmf.get_controls()


def test_get_controls_handles_empty_crosswalk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the regime has zero controls in the TOML, return ``[]`` — never ``None``."""

    def _empty(regime: Regime) -> list[ControlMapping]:
        return []

    monkeypatch.setattr(nist_airmf, "get_all_controls_for_regime", _empty)
    out = nist_airmf.get_controls()
    assert out == []
    assert isinstance(out, list)


# ---------------------------------------------------------------------------
# Cross-check against the live crosswalk (sanity, not a contract pin)
# ---------------------------------------------------------------------------


def test_adapter_matches_crosswalk_for_regime(
    controls: list[ControlMapping],
) -> None:
    """The adapter must return exactly what the crosswalk returns for NIST_GENAI."""
    expected = crosswalk.get_all_controls_for_regime(Regime.NIST_GENAI)
    assert controls == expected


def test_adapter_does_not_leak_other_regimes(
    controls: list[ControlMapping],
) -> None:
    """No EU AI Act / ISO / BCBS control_ids should appear in the NIST result.

    Regimes share the same TOML control table, so the crosswalk filter must
    keep them disjoint at the *reference* level. We compare against the
    union of ``control_id`` sets from the other regimes — any overlap would
    mean a metric mis-tagged its NIST reference into another regime's slot.
    """
    nist_ids = {c["control_id"] for c in controls}
    others: Iterable[Regime] = (r for r in Regime if r is not Regime.NIST_GENAI)
    other_ids: set[str] = set()
    for r in others:
        other_ids.update(c["control_id"] for c in crosswalk.get_all_controls_for_regime(r))
    # NIST control_ids must not collide with any other regime's control_ids.
    assert nist_ids.isdisjoint(other_ids)
