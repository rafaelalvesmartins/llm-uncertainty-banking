# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Hardening: pin the crosswalk shape "6 regimes / 23 metrics / 32 controls"
and its referential integrity against silent drift.

CANONICAL_FACTS records the crosswalk as **6 regimes - 23 metrics - 32
controls**. Existing tests cover parts of this:

* ``test_petition_claims.py`` -> ``len(regimes()) == 6``;
* ``test_crosswalk_integrity.py`` -> control-id grammar + field presence;
* ``test_crosswalk_consistency.py`` -> per-regime mapping coverage.

None of them pins the literal **23** and **32**, nor guards the one hole
that would let a typo slip through: the loader *silently skips* unknown
regime keys in a ``[metrics.*]`` table (``crosswalk.py``: "skip unknown
regime keys silently"), so a mistyped key would degrade the crosswalk
without any error. This file parses the raw TOML (the single source of
truth) and asserts the counts + that every regime key is a real enum
member and every referenced control is defined.

"32 controls" means regime-backed control *definitions*: 37 total
``[controls.*]`` tables minus the 5 ``SR_11_7_*`` controls (SR 11-7 is
cross-referenced via ``[sr_11_7.pillars.*]``, not a ``Regime``). Note this
is a count of *definitions*, not *usages* — one control (``BCBS_P5_GENAI``)
is defined but not yet referenced by any metric, so only 31 distinct
controls are used in mappings. The canonical claim counts definitions.

If the crosswalk genuinely grows, update CANONICAL_FACTS AND this test in
the same commit.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from lub.reports import crosswalk as cw

CROSSWALK_TOML = Path(cw.__file__).with_name("crosswalk_data.toml")


def _raw() -> dict:
    """Parse the crosswalk TOML directly — the auditor-facing source."""
    return tomllib.loads(CROSSWALK_TOML.read_text(encoding="utf-8"))


def test_crosswalk_data_file_exists_next_to_loader() -> None:
    """The single source of truth ships alongside its loader."""
    assert CROSSWALK_TOML.is_file()


def test_crosswalk_has_twenty_three_metrics() -> None:
    """23 metric-to-control mapping tables, via loader and raw TOML."""
    assert len(cw.get_crosswalk()) == 23
    assert len(_raw()["metrics"]) == 23


def test_crosswalk_has_thirty_two_regime_backed_controls() -> None:
    """32 regime-backed control definitions (37 total minus 5 SR 11-7)."""
    controls = _raw()["controls"]
    regime_backed = [k for k in controls if not k.startswith("SR_11_7")]
    assert len(regime_backed) == 32


def test_control_definitions_split_into_37_total_and_5_sr_11_7() -> None:
    """The 32 regime-backed controls plus the 5 SR 11-7 controls = 37."""
    controls = _raw()["controls"]
    sr_controls = [k for k in controls if k.startswith("SR_11_7")]
    assert len(controls) == 37
    assert len(sr_controls) == 5


def test_every_metric_maps_only_to_valid_regime_keys() -> None:
    """Guards the loader's silent skip of unknown regime keys.

    Each ``[metrics.<name>]`` table keys its mappings by regime name (plus
    a ``trust_dimension`` label). A mistyped regime key would be dropped
    silently by the loader; asserting against the enum names catches it.
    """
    valid = {r.name for r in cw.Regime}
    offenders = [
        (metric, key)
        for metric, mapping in _raw()["metrics"].items()
        for key in mapping
        if key != "trust_dimension" and key not in valid
    ]
    assert offenders == [], f"unknown regime keys in crosswalk: {offenders}"


def test_no_dangling_control_references() -> None:
    """Every control referenced by a metric mapping is actually defined."""
    data = _raw()
    defined = set(data["controls"])
    dangling = [
        (metric, key, ref)
        for metric, mapping in data["metrics"].items()
        for key, refs in mapping.items()
        if key != "trust_dimension"
        for ref in refs
        if ref not in defined
    ]
    assert dangling == [], f"dangling control refs: {dangling}"


def test_every_crosswalk_entry_has_mappings() -> None:
    """No metric ships with an empty mapping (a bookkeeping bug)."""
    assert all(entry.mappings for entry in cw.get_crosswalk())


def test_all_six_regimes_are_actually_referenced() -> None:
    """The count of 6 is not inflated by an unused enum member: every
    regime appears in at least one metric mapping."""
    referenced = {
        key
        for mapping in _raw()["metrics"].values()
        for key in mapping
        if key != "trust_dimension"
    }
    assert referenced == {r.name for r in cw.Regime}
