# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Hardening: full referential integrity of the SR 11-7 pillar tables.

Existing tests pin the *aggregate* SR 11-7 facts (``test_compliance_frameworks``
asserts 3 pillars / 5 control-ids / per-pillar non-emptiness;
``test_claim_counts_hardening`` asserts ``REGIME is None``). What no test walks is
the ``[sr_11_7.pillars.*]`` tables' referential integrity — so a typo'd control
key (``SR_11_7_VI_D``) or metric name (``eece``) in a pillar list passes CI today.

This file parses ``crosswalk_data.toml`` directly (the auditor-facing source) and
pins:

* every control key under a pillar exists in ``[controls.*]`` and is an SR_11_7 key;
* the pillar control keys **partition** the 5 ``SR_11_7_*`` control definitions
  exactly — no orphan, no duplicate;
* every pillar **metric** name is a real crosswalk metric (a key of ``[metrics.*]``)
  — NOT ``metrics.__all__``: 13/21 pillar metrics are aliases / provenance fields,
  not calibration functions, so ``[metrics.*]`` is the correct realness set;
* the exact per-pillar metric membership, so any drift produces a readable diff.

If the SR 11-7 mapping genuinely changes, update the pinned memberships here in the
same commit. NB: the ``V.A``/``V.B``/``VI.*`` control-id letters are lub's own
crosswalk convention, not verbatim OCC 2011-12 subsection citations — see
``planning/32_SR117_Audit_Findings_2026-07-05.md`` and ``docs/sr-11-7.md``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from lub.reports import crosswalk as cw

CROSSWALK_TOML = Path(cw.__file__).with_name("crosswalk_data.toml")

SR_11_7_CONTROLS = frozenset(
    {"SR_11_7_V_A", "SR_11_7_V_B", "SR_11_7_VI_A", "SR_11_7_VI_B", "SR_11_7_VI_C"}
)
PILLAR_CONTROLS = {
    "Conceptual Soundness": {"SR_11_7_V_A"},
    "Outcome Analysis": {"SR_11_7_V_B"},
    "Ongoing Monitoring": {"SR_11_7_VI_A", "SR_11_7_VI_B", "SR_11_7_VI_C"},
}
PILLAR_METRICS = {
    "Conceptual Soundness": {
        "ece", "rmsce", "ence", "brier", "miscalibration_area", "sharpness",
        "spearman", "kendall_tau", "adversarial_group_calibration",
    },
    "Outcome Analysis": {
        "accuracy", "matthews_correlation", "refusal_auroc", "prr",
        "reversed_pairs_proportion", "aurc", "auucc",
    },
    "Ongoing Monitoring": {
        "dataset_hash", "dataset_version", "missing_ratio", "git_sha",
        "package_versions",
    },
}


def _pillars() -> dict:
    data = tomllib.loads(CROSSWALK_TOML.read_text(encoding="utf-8"))
    return data["sr_11_7"]["pillars"]


def _controls() -> dict:
    data = tomllib.loads(CROSSWALK_TOML.read_text(encoding="utf-8"))
    return data["controls"]


def test_three_named_pillars() -> None:
    """Exactly the three canonical validation pillars, by name."""
    assert set(_pillars()) == set(PILLAR_CONTROLS)


def test_every_pillar_control_key_resolves_and_is_sr_11_7() -> None:
    """No dangling / mistyped control key in any pillar table."""
    defined = set(_controls())
    for pillar, table in _pillars().items():
        for key in table["controls"]:
            assert key.startswith("SR_11_7_"), f"{pillar}: {key!r} is not an SR_11_7 key"
            assert key in defined, f"{pillar}: {key!r} has no [controls.*] definition"


def test_pillar_controls_partition_the_five_definitions() -> None:
    """The pillar control keys cover exactly the 5 SR_11_7 controls — no orphan,
    no duplicate across pillars."""
    seen: list[str] = []
    for table in _pillars().values():
        seen.extend(table["controls"])
    assert len(seen) == len(set(seen)), f"a control appears in two pillars: {seen}"
    assert set(seen) == SR_11_7_CONTROLS


def test_pillar_control_membership_is_pinned() -> None:
    """Per-pillar control lists match the pinned mapping exactly."""
    got = {p: set(t["controls"]) for p, t in _pillars().items()}
    assert got == {p: set(c) for p, c in PILLAR_CONTROLS.items()}


def test_every_pillar_metric_is_a_real_crosswalk_metric() -> None:
    """Each pillar metric name resolves to a ``[metrics.*]`` table (the correct
    'real metric' set — 13/21 are aliases/provenance, not metrics.__all__)."""
    data = tomllib.loads(CROSSWALK_TOML.read_text(encoding="utf-8"))
    metric_tables = set(data["metrics"])
    unknown = [
        (pillar, m)
        for pillar, table in data["sr_11_7"]["pillars"].items()
        for m in table["metrics"]
        if m not in metric_tables
    ]
    assert unknown == [], f"pillar metrics with no [metrics.*] table: {unknown}"


def test_pillar_metric_membership_is_pinned() -> None:
    """Per-pillar metric lists match the pinned mapping exactly (drift → diff)."""
    got = {p: set(t["metrics"]) for p, t in _pillars().items()}
    assert got == {p: set(m) for p, m in PILLAR_METRICS.items()}
