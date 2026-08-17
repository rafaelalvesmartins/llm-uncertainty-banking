# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for ``lub.reports.mapping`` (metric -> regulatory framework)."""

from __future__ import annotations

import re

import pytest

from lub.reports import mapping
from lub.reports.mapping import (
    Iso42001Entry,
    RmfEntry,
    Sr117Entry,
    get_iso42001_mapping,
    get_rmf_mapping,
    get_sr117_mapping,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rmf() -> dict[str, RmfEntry]:
    return get_rmf_mapping()


@pytest.fixture
def iso() -> dict[str, Iso42001Entry]:
    return get_iso42001_mapping()


@pytest.fixture
def sr117() -> dict[str, Sr117Entry]:
    return get_sr117_mapping()


# ---------------------------------------------------------------------------
# Non-emptiness and required keys (TOML actually loaded)
# ---------------------------------------------------------------------------


CORE_METRICS = {
    "accuracy",
    "ece",
    "refusal_auroc",
    "brier",
    "prr",
    "spearman",
    "kendall_tau",
    "dataset_hash",
    "git_sha",
}


def test_rmf_mapping_loads_and_contains_core_metrics(rmf: dict[str, RmfEntry]) -> None:
    assert len(rmf) >= 20, "TOML appears unloaded or truncated"
    missing = CORE_METRICS - rmf.keys()
    assert not missing, f"RMF mapping missing metrics: {sorted(missing)}"


def test_iso42001_mapping_loads_and_contains_core_metrics(
    iso: dict[str, Iso42001Entry],
) -> None:
    assert len(iso) >= 20
    missing = CORE_METRICS - iso.keys()
    assert not missing, f"ISO 42001 mapping missing metrics: {sorted(missing)}"


def test_sr117_mapping_loads_and_contains_core_metrics(
    sr117: dict[str, Sr117Entry],
) -> None:
    assert len(sr117) >= 15
    missing = CORE_METRICS - sr117.keys()
    assert not missing, f"SR 11-7 mapping missing metrics: {sorted(missing)}"


# ---------------------------------------------------------------------------
# TypedDict shape: every entry must expose all required fields
# ---------------------------------------------------------------------------


def test_every_rmf_entry_has_required_fields(rmf: dict[str, RmfEntry]) -> None:
    required = {"subcategory", "description", "trust_dimension"}
    for metric, entry in rmf.items():
        assert required <= entry.keys(), f"RMF[{metric}] missing fields"
        assert all(isinstance(entry[k], str) and entry[k] for k in required), (
            f"RMF[{metric}] has empty/non-str field"
        )


def test_every_iso42001_entry_has_required_fields(
    iso: dict[str, Iso42001Entry],
) -> None:
    required = {"clause", "description", "annex"}
    for metric, entry in iso.items():
        assert required <= entry.keys(), f"ISO[{metric}] missing fields"
        assert all(isinstance(entry[k], str) and entry[k] for k in required), (
            f"ISO[{metric}] has empty/non-str field"
        )


def test_every_sr117_entry_has_required_fields(sr117: dict[str, Sr117Entry]) -> None:
    required = {"pillar", "section", "description"}
    for metric, entry in sr117.items():
        assert required <= entry.keys(), f"SR117[{metric}] missing fields"
        assert all(isinstance(entry[k], str) and entry[k] for k in required), (
            f"SR117[{metric}] has empty/non-str field"
        )


# ---------------------------------------------------------------------------
# Domain validity: subcategories / clauses / pillars must follow the spec
# ---------------------------------------------------------------------------


_RMF_FUNCTIONS = ("GOVERN", "MAP", "MEASURE", "MANAGE")
_RMF_TRUST_DIMENSIONS = {
    "Efficacy",
    "Robustness",
    "Bias",
    "Explainability",
    "Security",
    "Privacy",
    "Safety",
}


def test_rmf_subcategory_follows_function_dot_pattern(rmf: dict[str, RmfEntry]) -> None:
    pattern = re.compile(r"^(GOVERN|MAP|MEASURE|MANAGE) \d+(\.\d+)?$")
    for metric, entry in rmf.items():
        assert pattern.match(entry["subcategory"]), (
            f"RMF[{metric}].subcategory={entry['subcategory']!r} "
            f"is not 'FUNCTION N.M' (functions: {_RMF_FUNCTIONS})"
        )


def test_rmf_trust_dimension_in_known_set(rmf: dict[str, RmfEntry]) -> None:
    for metric, entry in rmf.items():
        assert entry["trust_dimension"] in _RMF_TRUST_DIMENSIONS, (
            f"RMF[{metric}].trust_dimension={entry['trust_dimension']!r} "
            "not in NIST trust-dimension set"
        )


def test_iso42001_clause_is_dotted_numeric(iso: dict[str, Iso42001Entry]) -> None:
    pattern = re.compile(r"^\d+(\.\d+){0,2}$")
    for metric, entry in iso.items():
        assert pattern.match(entry["clause"]), (
            f"ISO[{metric}].clause={entry['clause']!r} not 'N' or 'N.M' or 'N.M.K'"
        )


def test_iso42001_annex_starts_with_a_dot(iso: dict[str, Iso42001Entry]) -> None:
    for metric, entry in iso.items():
        assert entry["annex"].startswith("A."), (
            f"ISO[{metric}].annex={entry['annex']!r} should start with 'A.'"
        )


def test_sr117_pillar_is_one_through_three(sr117: dict[str, Sr117Entry]) -> None:
    valid = {"Pillar 1", "Pillar 2", "Pillar 3"}
    for metric, entry in sr117.items():
        assert entry["pillar"] in valid, (
            f"SR117[{metric}].pillar={entry['pillar']!r} not in {valid}"
        )


# ---------------------------------------------------------------------------
# Defensive-copy semantics: caller mutations must not leak into the cache
# ---------------------------------------------------------------------------


def test_get_rmf_mapping_returns_independent_copies() -> None:
    a = get_rmf_mapping()
    b = get_rmf_mapping()
    assert a == b
    assert a is not b, "get_rmf_mapping must return a fresh dict each call"

    # Mutating top-level dict must not affect a fresh copy.
    a.pop(next(iter(a)))
    c = get_rmf_mapping()
    assert len(c) == len(b)

    # Mutating an inner entry must not affect a fresh copy either.
    metric = next(iter(c))
    c[metric]["description"] = "TAMPERED"
    d = get_rmf_mapping()
    assert d[metric]["description"] != "TAMPERED"


def test_get_iso42001_mapping_returns_independent_copies() -> None:
    a = get_iso42001_mapping()
    b = get_iso42001_mapping()
    assert a is not b
    metric = next(iter(a))
    a[metric]["clause"] = "TAMPERED"
    assert get_iso42001_mapping()[metric]["clause"] != "TAMPERED"


def test_get_sr117_mapping_returns_independent_copies() -> None:
    a = get_sr117_mapping()
    b = get_sr117_mapping()
    assert a is not b
    metric = next(iter(a))
    a[metric]["pillar"] = "TAMPERED"
    assert get_sr117_mapping()[metric]["pillar"] != "TAMPERED"


# ---------------------------------------------------------------------------
# Cross-framework consistency
# ---------------------------------------------------------------------------


def test_iso42001_keys_are_a_subset_of_rmf_keys(
    rmf: dict[str, RmfEntry], iso: dict[str, Iso42001Entry]
) -> None:
    """Every ISO-mapped metric should also exist in the RMF mapping."""
    extra = iso.keys() - rmf.keys()
    assert not extra, f"ISO mapping has metrics absent from RMF: {sorted(extra)}"


def test_sr117_keys_are_a_subset_of_rmf_keys(
    rmf: dict[str, RmfEntry], sr117: dict[str, Sr117Entry]
) -> None:
    extra = sr117.keys() - rmf.keys()
    assert not extra, f"SR117 mapping has metrics absent from RMF: {sorted(extra)}"


# ---------------------------------------------------------------------------
# Module-level invariants
# ---------------------------------------------------------------------------


def test_public_api_surface() -> None:
    expected = {
        "Iso42001Entry",
        "RmfEntry",
        "Sr117Entry",
        "get_iso42001_mapping",
        "get_rmf_mapping",
        "get_sr117_mapping",
    }
    assert set(mapping.__all__) == expected


def test_data_path_resolves_to_existing_toml() -> None:
    assert mapping._DATA_PATH.exists(), (
        f"mapping_data.toml missing at {mapping._DATA_PATH}"
    )
    assert mapping._DATA_PATH.suffix == ".toml"


# ---------------------------------------------------------------------------
# Failure path: malformed TOML must surface, not silently load empty mappings
# ---------------------------------------------------------------------------


def test_load_toml_raises_on_malformed_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_bytes(b"this = is = not valid toml\n")
    monkeypatch.setattr(mapping, "_DATA_PATH", bad)
    with pytest.raises(Exception):  # tomllib.TOMLDecodeError subclass of ValueError
        mapping._load_toml()


def test_load_toml_tolerates_missing_sections(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """An empty TOML file must yield three empty dicts, not raise."""
    empty = tmp_path / "empty.toml"
    empty.write_bytes(b"")
    monkeypatch.setattr(mapping, "_DATA_PATH", empty)
    rmf, iso, sr117 = mapping._load_toml()
    assert rmf == {} and iso == {} and sr117 == {}
