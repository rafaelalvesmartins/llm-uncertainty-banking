# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for ISO/IEC 42001:2023 catalog in OSCAL output."""

from __future__ import annotations

import json

from lub.reports.mapping import get_iso42001_mapping, get_rmf_mapping
from lub.reports.oscal import build_component_definition, render_oscal_json
from tests import make_benchmark_result


def test_iso42001_mapping_returns_all_rmf_keys() -> None:
    rmf = get_rmf_mapping()
    iso = get_iso42001_mapping()
    assert set(iso.keys()) == set(rmf.keys())


def test_iso42001_entries_have_required_fields() -> None:
    for name, entry in get_iso42001_mapping().items():
        assert "clause" in entry, f"{name} missing clause"
        assert "description" in entry, f"{name} missing description"
        assert "annex" in entry, f"{name} missing annex"


def test_oscal_has_two_control_implementations() -> None:
    cd = build_component_definition(make_benchmark_result())
    comp = cd.components[0]
    assert len(comp.control_implementations) == 2


def test_oscal_second_ci_is_iso42001() -> None:
    text = render_oscal_json(make_benchmark_result())
    parsed = json.loads(text)
    comp = parsed["component-definition"]["components"][0]
    sources = [ci["source"] for ci in comp["control-implementations"]]
    assert "NIST_AI_RMF_1.0" in sources
    assert "ISO_IEC_42001_2023" in sources


def test_iso42001_carries_clause_based_control_ids() -> None:
    text = render_oscal_json(make_benchmark_result())
    parsed = json.loads(text)
    comp = parsed["component-definition"]["components"][0]
    iso_ci = [
        ci for ci in comp["control-implementations"]
        if ci["source"] == "ISO_IEC_42001_2023"
    ][0]
    control_ids = {ir["control-id"] for ir in iso_ci["implemented-requirements"]}
    assert any("iso42001" in cid for cid in control_ids)


def test_iso42001_by_components_carry_annex_prop() -> None:
    text = render_oscal_json(make_benchmark_result())
    parsed = json.loads(text)
    comp = parsed["component-definition"]["components"][0]
    iso_ci = [
        ci for ci in comp["control-implementations"]
        if ci["source"] == "ISO_IEC_42001_2023"
    ][0]
    all_bcs = [bc for ir in iso_ci["implemented-requirements"] for bc in ir.get("by-components", [])]
    assert len(all_bcs) >= 1
    prop_names = {p["name"] for bc in all_bcs for p in bc.get("props", [])}
    assert "iso42001_annex" in prop_names


def test_iso42001_description_mentions_eu_ai_act() -> None:
    text = render_oscal_json(make_benchmark_result())
    parsed = json.loads(text)
    comp = parsed["component-definition"]["components"][0]
    iso_ci = [
        ci for ci in comp["control-implementations"]
        if ci["source"] == "ISO_IEC_42001_2023"
    ][0]
    assert "EU AI Act" in iso_ci["description"]
