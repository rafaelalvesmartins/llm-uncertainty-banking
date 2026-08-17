# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""SR 11-7 / OCC Bulletin 2011-12 -- Federal Reserve model risk management.

SR 11-7 is cross-referenced rather than represented as a :class:`Regime`
enum value because it is supervisory guidance for traditional model risk,
not an AI-specific regulatory regime. The three-pillar table (Conceptual
Soundness / Outcome Analysis / Ongoing Monitoring), the five SR 11-7
controls (V.A, V.B, VI.A, VI.B, VI.C), and the pillar -> evidencing-metric
mapping live in ``crosswalk_data.toml`` under ``[controls.SR_11_7_*]``
and ``[sr_11_7.pillars.*]``; this module reads them through the shared
:mod:`lub.reports.crosswalk` loader so the TOML is parsed exactly once
at package import.

``REGIME`` stays ``None`` -- promoting SR 11-7 into the :class:`Regime`
enum pulls it into per-regime OSCAL emission and crosswalk filtering,
which is the path SR 11-7 intentionally sits outside of.
"""

from __future__ import annotations

from typing import Final

from lub.reports.crosswalk import ControlMapping, get_control_by_key, get_raw_section

REGIME = None  # SR 11-7 is cross-referenced, not a Regime enum value
CROSSWALK_KEY: Final[str] = "SR_11_7"
TITLE: Final[str] = "Federal Reserve SR 11-7 / OCC Bulletin 2011-12"
PILLARS: Final[tuple[str, str, str]] = (
    "Conceptual Soundness",
    "Outcome Analysis",
    "Ongoing Monitoring",
)

# Single source of truth: pillar -> {"controls": [...], "metrics": [...]}.
# Loaded once at import via the shared crosswalk loader.
_RAW_PILLARS: Final[dict[str, dict[str, list[str]]]] = get_raw_section("sr_11_7").get("pillars", {})


def _pillar(name: str) -> dict[str, list[str]]:
    return _RAW_PILLARS.get(name, {})


def get_controls() -> list[ControlMapping]:
    """Return the SR 11-7 pillar controls (V.A, V.B, VI.A, VI.B, VI.C).

    Deduplicated and sorted by ``control_id`` so the output is stable.
    """
    seen: set[str] = set()
    out: list[ControlMapping] = []
    for spec in _RAW_PILLARS.values():
        for key in spec.get("controls", []):
            if key in seen:
                continue
            seen.add(key)
            out.append(get_control_by_key(key))
    return sorted(out, key=lambda c: c["control_id"])


def get_pillar_controls() -> dict[str, list[ControlMapping]]:
    """Return SR 11-7 controls grouped by pillar name."""
    return {
        pillar: [get_control_by_key(k) for k in _pillar(pillar).get("controls", [])]
        for pillar in PILLARS
    }


def get_pillar_metrics() -> dict[str, list[str]]:
    """Return pillar -> lub metric names that evidence the pillar."""
    return {pillar: list(_pillar(pillar).get("metrics", [])) for pillar in PILLARS}


__all__ = [
    "CROSSWALK_KEY",
    "PILLARS",
    "REGIME",
    "TITLE",
    "get_controls",
    "get_pillar_controls",
    "get_pillar_metrics",
]
