# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for the OSCAL Catalog generator."""

from __future__ import annotations

import json

from lub.reports.catalog import (
    OscalCatalog,
    build_all_catalogs,
    build_catalog,
    render_all_catalogs_json,
    render_catalog_json,
)
from lub.reports.crosswalk import Regime, regimes


def test_build_catalog_returns_oscal_catalog() -> None:
    cat = build_catalog(Regime.NIST_GENAI)
    assert isinstance(cat, OscalCatalog)


def test_catalog_has_uuid_and_metadata() -> None:
    cat = build_catalog(Regime.EU_AI_ACT)
    assert cat.uuid
    assert cat.metadata.title
    assert cat.metadata.version
    assert cat.metadata.oscal_version == "1.1.2"


def test_catalog_has_groups_with_controls() -> None:
    cat = build_catalog(Regime.NIST_GENAI)
    assert len(cat.groups) >= 1
    total_controls = sum(len(g.controls) for g in cat.groups)
    assert total_controls >= 3


def test_every_control_has_statement_part() -> None:
    for regime in regimes():
        cat = build_catalog(regime)
        for group in cat.groups:
            for ctrl in group.controls:
                assert ctrl.parts, f"control {ctrl.id} in {regime} has no parts"
                assert any(
                    p.name == "statement" for p in ctrl.parts
                ), f"control {ctrl.id} missing statement part"


def test_every_control_has_regime_prop() -> None:
    for regime in regimes():
        cat = build_catalog(regime)
        for group in cat.groups:
            for ctrl in group.controls:
                prop_names = {p.name for p in ctrl.props}
                assert "regime" in prop_names, f"control {ctrl.id} missing regime prop"


def test_render_catalog_json_produces_valid_json() -> None:
    text = render_catalog_json(Regime.NIST_GENAI)
    parsed = json.loads(text)
    assert "catalog" in parsed
    cat = parsed["catalog"]
    assert "uuid" in cat
    assert "metadata" in cat
    assert "groups" in cat


def test_render_catalog_json_envelope_structure() -> None:
    for regime in regimes():
        text = render_catalog_json(regime)
        parsed = json.loads(text)
        assert "catalog" in parsed
        groups = parsed["catalog"]["groups"]
        assert len(groups) >= 1


def test_build_all_catalogs_covers_all_regimes() -> None:
    all_cats = build_all_catalogs()
    assert set(all_cats.keys()) == set(regimes())
    for regime, cat in all_cats.items():
        assert isinstance(cat, OscalCatalog)
        assert len(cat.groups) >= 1


def test_render_all_catalogs_json_returns_dict() -> None:
    result = render_all_catalogs_json()
    assert isinstance(result, dict)
    assert len(result) == 6
    for regime_str, json_str in result.items():
        parsed = json.loads(json_str)
        assert "catalog" in parsed


def test_eu_ai_act_catalog_has_article_controls() -> None:
    cat = build_catalog(Regime.EU_AI_ACT)
    all_ids = {ctrl.id for g in cat.groups for ctrl in g.controls}
    assert any("Art9" in cid for cid in all_ids)
    assert any("Art14" in cid for cid in all_ids)
    assert any("Art15" in cid for cid in all_ids)


def test_bcbs_catalog_has_principle_controls() -> None:
    cat = build_catalog(Regime.BCBS)
    all_ids = {ctrl.id for g in cat.groups for ctrl in g.controls}
    assert any("P1" in cid for cid in all_ids)
    assert any("P3" in cid for cid in all_ids)


def test_bcb_catalog_has_resolution_controls() -> None:
    cat = build_catalog(Regime.BCB)
    all_ids = {ctrl.id for g in cat.groups for ctrl in g.controls}
    assert any("Res4893" in cid for cid in all_ids)


def test_iso_catalog_has_clause_controls() -> None:
    cat = build_catalog(Regime.ISO_23894)
    all_ids = {ctrl.id for g in cat.groups for ctrl in g.controls}
    assert any("ISO23894" in cid for cid in all_ids)
