# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for the multi-regime regulatory crosswalk."""

from __future__ import annotations

from lub.reports.crosswalk import (
    Regime,
    get_all_controls_for_regime,
    get_crosswalk,
    get_crosswalk_for_regime,
    regimes,
)


def test_crosswalk_is_nonempty_tuple() -> None:
    cw = get_crosswalk()
    assert isinstance(cw, tuple)
    assert len(cw) >= 15


def test_every_entry_has_at_least_one_regime() -> None:
    for entry in get_crosswalk():
        assert entry.mappings, f"metric {entry.metric!r} has no regime mappings"


def test_regimes_returns_all_six() -> None:
    r = regimes()
    assert len(r) == 6
    names = {str(x) for x in r}
    assert "NIST_AI_600-1" in names
    assert "EU_AI_ACT_2024/1689" in names
    assert "BCBS_239" in names
    assert "BCB_Res4893" in names
    assert "ISO/IEC_23894:2023" in names


def test_legacy_bcbs_d475_string_coerces_to_bcbs_239() -> None:
    """Legacy persisted artifacts with 'BCBS_d475' must still resolve."""
    import warnings

    from lub.reports.crosswalk import Regime, coerce_legacy_regime

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        regime = coerce_legacy_regime("BCBS_d475")
    assert regime is Regime.BCBS
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_get_crosswalk_for_regime_filters_correctly() -> None:
    nist = get_crosswalk_for_regime(Regime.NIST_GENAI)
    assert isinstance(nist, dict)
    assert "accuracy" in nist
    assert "ece" in nist
    bcb = get_crosswalk_for_regime(Regime.BCB)
    assert "accuracy" in bcb or "ece" in bcb


def test_get_all_controls_for_regime_deduplicates() -> None:
    for regime in regimes():
        controls = get_all_controls_for_regime(regime)
        ids = [c["control_id"] for c in controls]
        assert len(ids) == len(set(ids)), f"duplicate control IDs in {regime}"


def test_nist_genai_has_measure_controls() -> None:
    controls = get_all_controls_for_regime(Regime.NIST_GENAI)
    ids = {c["control_id"] for c in controls}
    assert any(cid.startswith("MS-") for cid in ids)


def test_eu_ai_act_has_article_controls() -> None:
    controls = get_all_controls_for_regime(Regime.EU_AI_ACT)
    ids = {c["control_id"] for c in controls}
    assert any("Art9" in cid or "Art10" in cid for cid in ids)


def test_bcbs_has_principle_controls() -> None:
    controls = get_all_controls_for_regime(Regime.BCBS)
    ids = {c["control_id"] for c in controls}
    assert any("P1" in cid or "P3" in cid or "P5" in cid for cid in ids)


def test_bcb_has_resolution_controls() -> None:
    controls = get_all_controls_for_regime(Regime.BCB)
    ids = {c["control_id"] for c in controls}
    assert any("Res4893" in cid or "Circ3978" in cid for cid in ids)


def test_iso_has_clause_controls() -> None:
    controls = get_all_controls_for_regime(Regime.ISO_23894)
    ids = {c["control_id"] for c in controls}
    assert any("ISO23894" in cid for cid in ids)


def test_control_mapping_has_required_fields() -> None:
    for entry in get_crosswalk():
        for regime, mappings in entry.mappings.items():
            for cm in mappings:
                assert "control_id" in cm
                assert "control_title" in cm
                assert "description" in cm
                assert cm["control_id"], f"empty control_id for {entry.metric}"
                assert cm["control_title"], f"empty title for {entry.metric}"


def test_trust_dimensions_are_valid() -> None:
    valid = {"Efficacy", "Robustness", "Bias", "Explainability", "Security"}
    for entry in get_crosswalk():
        assert entry.trust_dimension in valid, (
            f"metric {entry.metric!r} has invalid trust_dimension "
            f"{entry.trust_dimension!r}"
        )
