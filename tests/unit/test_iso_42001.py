# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for :mod:`lub.compliance.frameworks.iso_42001`.

The generic per-framework contract is exercised in
``tests/unit/test_compliance_frameworks.py`` for all seven skeletons.
This file pins the **ISO/IEC 42001:2023**-specific facts:

* The three module-level constants have the expected types and values.
* ``get_controls()`` delegates to
  :func:`lub.reports.crosswalk.get_all_controls_for_regime` and returns
  a **new** ``list`` (defensive copy) typed as ``list[ControlMapping]``.
* Every returned mapping is a well-formed
  :class:`lub.reports.crosswalk.ControlMapping` belonging to the
  ISO/IEC 42001 regime.
* The module satisfies
  :class:`lub.compliance.frameworks.protocols.ComplianceFrameworkProtocol`
  structurally.

Hermetic: no network, no backend, no LLM. The module under test makes
no I/O at call time (the TOML is parsed once at
:mod:`lub.reports.crosswalk` import).
"""

from __future__ import annotations

import pytest

from lub.compliance.frameworks import iso_42001
from lub.compliance.frameworks.protocols import ComplianceFrameworkProtocol
from lub.reports.crosswalk import Regime, get_all_controls_for_regime

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def controls() -> list[dict]:
    """One call to ``get_controls()`` shared across the module's tests."""
    return iso_42001.get_controls()


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_regime_is_iso_42001() -> None:
    assert iso_42001.REGIME is Regime.ISO_42001


def test_crosswalk_key_matches_regime_name() -> None:
    """``CROSSWALK_KEY`` must equal ``REGIME.name`` for regime-backed frameworks.

    The protocol docstring states the key equals ``REGIME.name`` for
    regime-backed frameworks; ``"ISO_42001"`` is the enum member name.
    """
    assert iso_42001.CROSSWALK_KEY == "ISO_42001"
    assert iso_42001.CROSSWALK_KEY == Regime.ISO_42001.name


def test_title_is_human_readable_iso_string() -> None:
    assert iso_42001.TITLE == "ISO/IEC 42001:2023 — AI management system"
    assert isinstance(iso_42001.TITLE, str)


def test_dunder_all_is_exact() -> None:
    assert iso_42001.__all__ == ["CROSSWALK_KEY", "REGIME", "TITLE", "get_controls"]


# ---------------------------------------------------------------------------
# get_controls()
# ---------------------------------------------------------------------------


def test_get_controls_returns_list(controls: list[dict]) -> None:
    assert isinstance(controls, list)


def test_get_controls_is_non_empty(controls: list[dict]) -> None:
    """ISO/IEC 42001 must contribute at least one crosswalk control."""
    assert len(controls) > 0


def test_get_controls_returns_defensive_copy() -> None:
    """``get_controls()`` wraps the underlying call in ``list(...)``.

    Successive calls must return distinct list objects so a caller
    mutating the result cannot poison subsequent callers. The mappings
    inside are ``TypedDict`` (i.e. ``dict``) values — identity of those
    inner dicts is not part of the contract, only the outer list.
    """
    first = iso_42001.get_controls()
    second = iso_42001.get_controls()
    assert first is not second
    assert first == second


def test_get_controls_matches_crosswalk_helper(controls: list[dict]) -> None:
    """The module is a thin delegate to ``get_all_controls_for_regime``."""
    assert controls == list(get_all_controls_for_regime(Regime.ISO_42001))


def test_every_control_has_required_keys(controls: list[dict]) -> None:
    """Each entry must satisfy the ``ControlMapping`` TypedDict shape."""
    required = {"control_id", "control_title", "description"}
    for cm in controls:
        assert required.issubset(cm.keys()), cm
        assert isinstance(cm["control_id"], str) and cm["control_id"]
        assert isinstance(cm["control_title"], str) and cm["control_title"]
        assert isinstance(cm["description"], str) and cm["description"]


def test_control_ids_are_unique_and_sorted(controls: list[dict]) -> None:
    """``get_all_controls_for_regime`` de-duplicates and sorts by ``control_id``."""
    ids = [cm["control_id"] for cm in controls]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Structural protocol conformance
# ---------------------------------------------------------------------------


def test_module_satisfies_compliance_framework_protocol() -> None:
    """A module object conforms to the runtime-checkable Protocol structurally."""
    assert isinstance(iso_42001, ComplianceFrameworkProtocol)
