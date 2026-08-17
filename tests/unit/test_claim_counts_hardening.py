# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Hardening: pin the canonical claim counts (22 / 14 / 6) that are NOT
already guarded elsewhere, and the cross-surface invariants that keep the
three estimator enumerations in sync.

The petition narrative + CANONICAL_FACTS claim **22 uncertainty
estimators (7 families)**, **14 calibration metrics**, and **6 regulatory
regimes**. Existing tests already pin some of these:

* ``test_uncertainty_families.py`` -> 22 estimators / 7 families;
* ``test_petition_claims.py`` -> ``len(regimes()) == 6``, BCBS_239 value,
  the ``BCBS_d475`` deprecation coercion.

This file deliberately does **not** duplicate those. It adds the angles
that are currently unguarded and easy to break silently in a refactor:

* the **14 calibration metrics** count + exact membership;
* the **22-vs-23** distinction — the public estimator surface is the 22
  in-house estimators *plus* the single third-party ``LMPolygraph``
  adapter (asserted against the static ``__all__`` / ``FAMILIES``
  surfaces, which are stable regardless of lazy-load order);
* the exact **6-regime** member set + values, and the fact that SR 11-7
  is cross-referenced (not a ``Regime`` member).

If the framework genuinely changes (e.g. a 23rd in-house estimator, a
15th metric, a 7th regime), update the petition narrative / CANONICAL_FACTS
AND this test in the same commit.
"""

from __future__ import annotations

from lub import uncertainty as unc
from lub.calibration import metrics
from lub.compliance.frameworks import FRAMEWORKS, sr_11_7
from lub.reports.crosswalk import Regime, regimes
from lub.uncertainty import families as fam

# --- canonical, verified memberships (the source of truth is the code
# below; these literals exist so a drift produces a readable diff) ---
CALIBRATION_METRICS = frozenset(
    {
        "adversarial_group_calibration",
        "brier_score",
        "expected_calibration_error",
        "expected_normalized_calibration_error",
        "kendall_tau",
        "matthews_correlation",
        "miscalibration_area",
        "missing_ratio",
        "refusal_auroc",
        "reliability_curve",
        "reversed_pairs_proportion",
        "root_mean_squared_calibration_error",
        "sharpness",
        "spearman_rank_correlation",
    }
)
REGIME_NAMES = frozenset(
    {"NIST_GENAI", "EU_AI_ACT", "BCBS", "BCB", "ISO_23894", "ISO_42001"}
)
REGIME_VALUES = [
    "NIST_AI_600-1",
    "EU_AI_ACT_2024/1689",
    "BCBS_239",
    "BCB_Res4893",
    "ISO/IEC_23894:2023",
    "ISO/IEC_42001:2023",
]

# ---------------------------------------------------------------------------
# 14 calibration metrics
# ---------------------------------------------------------------------------


def test_calibration_metrics_count_is_fourteen() -> None:
    """``lub.calibration.metrics`` defines exactly 14 metric functions.

    ``metrics.__all__`` has 15 names; the 15th is ``compute_all``, a
    convenience bundler for the benchmark runner, not a metric itself.
    """
    assert "compute_all" in metrics.__all__
    metric_names = [n for n in metrics.__all__ if n != "compute_all"]
    assert len(metric_names) == 14


def test_calibration_metric_names_are_canonical() -> None:
    """The 14 metric names match the pinned membership exactly."""
    metric_names = {n for n in metrics.__all__ if n != "compute_all"}
    assert metric_names == CALIBRATION_METRICS


def test_every_calibration_metric_is_callable() -> None:
    """Each declared metric name resolves to a callable on the module."""
    for name in metrics.__all__:
        if name == "compute_all":
            continue
        assert callable(getattr(metrics, name)), name


# ---------------------------------------------------------------------------
# 22 estimators — cross-surface sync (the 22-vs-23 distinction)
# ---------------------------------------------------------------------------


def test_public_estimator_surface_is_families_plus_one_adapter() -> None:
    """The public estimator surface is the 22 in-house estimators plus the
    single ``LMPolygraph`` third-party adapter (= 23 classes).

    ``lub.uncertainty.__all__`` also exports the ``Estimator`` ABC, which
    is excluded here. Guards against the two common drifts: a new in-house
    estimator that never lands in ``families`` (would break the equality),
    or the adapter silently entering the family table.
    """
    public_estimators = {n for n in unc.__all__ if n != "Estimator"}
    family_members = {m for members in fam.FAMILIES.values() for m in members}

    assert len(public_estimators) == 23
    assert public_estimators - family_members == {"LMPolygraphEstimator"}
    assert family_members | {"LMPolygraphEstimator"} == public_estimators


def test_lmpolygraph_adapter_is_public_but_not_a_family_member() -> None:
    """The third-party adapter is exported but intentionally family-less."""
    assert "LMPolygraphEstimator" in unc.__all__
    assert fam.family_of("LMPolygraphEstimator") is None


# ---------------------------------------------------------------------------
# 6 regimes — exact set + SR 11-7 cross-reference + framework sync
# ---------------------------------------------------------------------------


def test_regime_enum_member_set_is_canonical() -> None:
    """Exactly the 6 canonical regimes, by stable ``.name``."""
    assert len(Regime) == 6
    assert {r.name for r in Regime} == REGIME_NAMES


def test_regime_values_are_canonical() -> None:
    """Regime string values (used in persisted OSCAL/JSON) are pinned."""
    assert [r.value for r in Regime] == REGIME_VALUES


def test_regimes_helper_matches_enum() -> None:
    """The ``regimes()`` helper returns exactly the enum members."""
    assert regimes() == tuple(Regime)


def test_sr_11_7_is_cross_referenced_not_a_regime() -> None:
    """SR 11-7 / OCC 2011-12 is cross-referenced, never a ``Regime`` value."""
    assert not hasattr(Regime, "SR_11_7")
    assert sr_11_7.REGIME is None
    assert sr_11_7.CROSSWALK_KEY == "SR_11_7"


def test_framework_modules_stay_in_sync_with_regime_enum() -> None:
    """The shipped framework modules track the enum: 7 modules, of which
    exactly one (SR 11-7) is regime-less, and the remaining six carry
    exactly the six canonical ``Regime`` members."""
    assert len(FRAMEWORKS) == 7
    regime_less = [m for m in FRAMEWORKS if getattr(m, "REGIME", None) is None]
    assert len(regime_less) == 1
    carried = {m.REGIME for m in FRAMEWORKS if getattr(m, "REGIME", None) is not None}
    assert carried == set(Regime)
