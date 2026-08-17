# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Pin the petition-relevant invariants of `lub.uncertainty.families`.

The petition narrative claims `22 estimators in 7 methodological
families` (Cap 1.4, Cap 2). This test ensures any future refactor of
:mod:`lub.uncertainty.families` keeps those two numbers aligned with
the actual exports of :mod:`lub.uncertainty`. If the framework
genuinely changes (e.g. a 23rd estimator lands), update the petition
narrative AND this test in the same commit.
"""

from __future__ import annotations

from lub import uncertainty as unc
from lub.uncertainty import families as fam


def test_families_total_count_matches_petition_claim() -> None:
    """22 estimators across 7 families — the canonical claim."""
    assert fam.estimator_count() == 22
    assert fam.family_count() == 7


def test_each_family_has_at_least_one_estimator() -> None:
    """An empty family in the table is a bookkeeping bug."""
    for family, members in fam.FAMILIES.items():
        assert members, f"family {family!r} is empty"


def test_no_estimator_appears_in_two_families() -> None:
    """Each estimator belongs to exactly one family (mutually exclusive)."""
    seen: set[str] = set()
    for family, members in fam.FAMILIES.items():
        for name in members:
            assert name not in seen, (
                f"{name!r} appears in multiple families "
                f"(second occurrence: {family!r})"
            )
            seen.add(name)


def test_every_family_member_is_an_exported_estimator() -> None:
    """Family members must be real classes from `lub.uncertainty.__all__`.

    Catches drift between this grouping and the package's public surface
    — e.g. a renamed estimator would fail this assertion before merging.
    """
    public = set(unc.__all__)
    for family, members in fam.FAMILIES.items():
        for name in members:
            assert name in public, (
                f"family {family!r} references {name!r}, which is not "
                f"in lub.uncertainty.__all__"
            )


def test_family_of_lookup_works_for_every_member() -> None:
    """`family_of(name)` must return the correct family for every member."""
    for family, members in fam.FAMILIES.items():
        for name in members:
            assert fam.family_of(name) == family


def test_family_of_unknown_returns_none() -> None:
    """Unknown estimator name resolves to None (not KeyError)."""
    assert fam.family_of("NonExistentEstimator") is None
