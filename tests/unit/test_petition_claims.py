# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Pin the remaining petition-relevant invariants not covered by
``test_uncertainty_families.py`` (which already pins 22 estimators / 7
families).

The petition narrative (Cap 1.4, Cap 2, CANONICAL_FACTS) claims:

* a regulatory crosswalk spanning **6 governance regimes** (NIST AI 600-1
  GenAI Profile, EU AI Act, BCBS 239, BCB 4.893, ISO/IEC 23894,
  ISO/IEC 42001), with SR 11-7 cross-mapped separately;
* legacy ``BCBS_d475`` naming still coerces (back-compat, item H);
* pure-NumPy calibration metrics including ECE and Brier score.

If the framework genuinely changes, update the petition narrative AND
this test in the same commit (see GAP_CLOSURE metric-consistency rule).
"""

from __future__ import annotations

import warnings

from lub.reports import crosswalk as cw


def test_crosswalk_spans_six_regimes() -> None:
    """The canonical crosswalk enumerates exactly 6 governance regimes."""
    assert len(cw.regimes()) == 6


def test_bcbs_239_is_a_regime_value() -> None:
    """BCBS 239 (not the mislabeled d475) is the canonical regime."""
    values = {r.value for r in cw.regimes()}
    assert "BCBS_239" in values, f"expected BCBS_239 in {sorted(values)}"


def test_legacy_bcbs_d475_coerces_with_deprecation_warning() -> None:
    """Item H back-compat: the superseded label still resolves."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        regime = cw.coerce_legacy_regime("BCBS_d475")
    assert regime in cw.regimes()
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_every_regime_has_mapped_controls() -> None:
    """No regime in the petition claim may be an empty mapping."""
    for regime in cw.regimes():
        controls = cw.get_all_controls_for_regime(regime)
        assert controls, f"regime {regime!r} has no mapped controls"


def test_calibration_exports_core_petition_metrics() -> None:
    """ECE and Brier score are named exports of lub.calibration."""
    import lub.calibration as cal

    names = " ".join(getattr(cal, "__all__", dir(cal))).lower()
    assert "ece" in names or "expected_calibration" in names, names
    assert "brier" in names, names
