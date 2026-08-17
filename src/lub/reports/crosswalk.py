# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Multi-regime regulatory crosswalk for LUB metrics.

.. note::
   **Canonical crosswalk (2026-04-22 onward): 6 regimes —** NIST AI 600-1
   (Generative AI Profile of AI RMF 1.0), EU AI Act (Regulation 2024/1689),
   BCBS 239 (Principles for effective risk data aggregation and risk
   reporting; renamed 2026-04-26 from "BCBS d475" — see
   :func:`coerce_legacy_regime` for the back-compat path), BCB Resolução
   4.893/2021, ISO/IEC 23894:2023, and ISO/IEC 42001:2023. SR 11-7 /
   OCC 2011-12 is cross-mapped via the three-pillar table in the library
   README rather than as a separate :class:`Regime` enum.

   Verified 2026-04-22 by direct parse of ``crosswalk_data.toml``:
   NIST_GENAI (8 refs), EU_AI_ACT (6), BCBS (3), BCB (3), ISO_23894 (4),
   ISO_42001 (7) — 23 metrics × 32 controls. Prior claim that BCBS and
   BCB were "legacy back-compat values" was stale and has been retracted.

Control definitions and metric-to-control mappings are stored in the
adjacent ``crosswalk_data.toml`` so that auditors can review the
regulatory mapping without reading Python. This module loads the TOML
at import time and exposes the same public API as before.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, TypedDict

_DATA_PATH = Path(__file__).with_name("crosswalk_data.toml")


class Regime(StrEnum):
    """Supported regulatory regimes."""

    NIST_GENAI = "NIST_AI_600-1"
    EU_AI_ACT = "EU_AI_ACT_2024/1689"
    BCBS = "BCBS_239"
    BCB = "BCB_Res4893"
    ISO_23894 = "ISO/IEC_23894:2023"
    ISO_42001 = "ISO/IEC_42001:2023"


class ControlMapping(TypedDict):
    """One metric-to-control mapping within a regime."""

    control_id: str
    control_title: str
    description: str


@dataclass(frozen=True)
class CrosswalkEntry:
    """A LUB metric and all the controls it maps to across regimes."""

    metric: str
    trust_dimension: str
    mappings: dict[Regime, list[ControlMapping]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# TOML loader
# ---------------------------------------------------------------------------

# Map TOML regime keys → Regime enum values.
_REGIME_KEY_TO_ENUM: dict[str, Regime] = {r.name: r for r in Regime}


def _load_toml() -> tuple[
    dict[str, Any],
    dict[str, ControlMapping],
    tuple[CrosswalkEntry, ...],
]:
    """Parse ``crosswalk_data.toml`` once and return (raw, controls, entries)."""
    raw = _DATA_PATH.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))

    controls: dict[str, ControlMapping] = {}
    for key, val in data.get("controls", {}).items():
        controls[key] = ControlMapping(
            control_id=val["control_id"],
            control_title=val["control_title"],
            description=val["description"],
        )

    entries: list[CrosswalkEntry] = []
    for metric_name, metric_data in data.get("metrics", {}).items():
        trust_dimension = metric_data["trust_dimension"]
        mappings: dict[Regime, list[ControlMapping]] = {}
        for regime_key, control_refs in metric_data.items():
            if regime_key == "trust_dimension":
                continue
            regime = _REGIME_KEY_TO_ENUM.get(regime_key)
            if regime is None:
                continue  # skip unknown regime keys silently
            mappings[regime] = [controls[ref] for ref in control_refs]
        entries.append(
            CrosswalkEntry(
                metric=metric_name,
                trust_dimension=trust_dimension,
                mappings=mappings,
            )
        )
    return data, controls, tuple(entries)


_RAW_TOML, _CONTROLS_BY_KEY, _CROSSWALK = _load_toml()


# ---------------------------------------------------------------------------
# Public API (unchanged from the original module)
# ---------------------------------------------------------------------------


def get_crosswalk() -> tuple[CrosswalkEntry, ...]:
    """Return the full crosswalk table (immutable tuple)."""
    return _CROSSWALK


def get_crosswalk_for_regime(regime: Regime) -> dict[str, list[ControlMapping]]:
    """Return ``{metric: [ControlMapping, ...]}`` filtered to one regime."""
    result: dict[str, list[ControlMapping]] = {}
    for entry in _CROSSWALK:
        if regime in entry.mappings:
            result[entry.metric] = entry.mappings[regime]
    return result


def get_all_controls_for_regime(regime: Regime) -> list[ControlMapping]:
    """Return de-duplicated controls for a regime, sorted by control_id."""
    seen: set[str] = set()
    controls: list[ControlMapping] = []
    for entry in _CROSSWALK:
        for cm in entry.mappings.get(regime, []):
            if cm["control_id"] not in seen:
                seen.add(cm["control_id"])
                controls.append(cm)
    return sorted(controls, key=lambda c: c["control_id"])


def regimes() -> tuple[Regime, ...]:
    """Return all supported regimes."""
    return tuple(Regime)


def get_control_by_key(key: str) -> ControlMapping:
    """Resolve a TOML control key (e.g. ``"BCBS_P3"``, ``"SR_11_7_V_A"``) to its mapping.

    Cross-referenced frameworks that do not appear as a :class:`Regime` value
    (SR 11-7) use this to share the same control table as the regime-backed
    siblings without re-parsing the TOML.
    """
    return _CONTROLS_BY_KEY[key]


def get_raw_section(name: str) -> dict[str, Any]:
    """Return a top-level ``[name.*]`` TOML section (e.g. ``"sr_11_7"``).

    Cross-referenced frameworks store their pillar / control mappings outside
    the per-regime ``[metrics.*]`` shape and read them via this accessor so
    the TOML is parsed exactly once at package import.
    """
    section = _RAW_TOML.get(name, {})
    return section if isinstance(section, dict) else {}


# ---------------------------------------------------------------------------
# Back-compat: legacy regime-string coercion
# ---------------------------------------------------------------------------

# Map legacy / superseded regime string values to the canonical Regime
# member. Loaded artifacts (OSCAL JSON, ledger rows, JSONL benchmark
# results) persisted before 2026-04-26 may carry legacy values like
# ``"BCBS_d475"``; ``coerce_legacy_regime`` lets those resolve without
# breaking the read path.
_LEGACY_REGIME_VALUES: dict[str, Regime] = {
    "BCBS_d475": Regime.BCBS,
}


def coerce_legacy_regime(value: str) -> Regime:
    """Resolve a regime string, accepting legacy / pre-rename values.

    Accepts any current :class:`Regime` value and any superseded value
    listed in :data:`_LEGACY_REGIME_VALUES`. Legacy values emit a
    :class:`DeprecationWarning` so callers know to re-serialize.

    Parameters
    ----------
    value:
        Regime value string (e.g. ``"BCBS_239"`` or the legacy
        ``"BCBS_d475"``).

    Returns
    -------
    Regime
        The canonical :class:`Regime` member.

    Raises
    ------
    ValueError
        If ``value`` is neither a current regime value nor a known
        legacy alias.

    .. note::
       Renamed 2026-04-26: ``"BCBS_d475"`` -> :attr:`Regime.BCBS`
       (now ``"BCBS_239"``). The previous label was wrong (BCBS d475 /
       BIS July 2019 covers margin requirements for non-centrally
       cleared derivatives, not risk data aggregation). New persisted
       artifacts use ``"BCBS_239"``; legacy artifacts continue to load
       through this helper.
    """
    import warnings

    if value in _LEGACY_REGIME_VALUES:
        canonical = _LEGACY_REGIME_VALUES[value]
        warnings.warn(
            f"Regime value {value!r} is deprecated; use "
            f"{canonical.value!r} instead. Re-serialize artifacts to "
            "drop this warning.",
            DeprecationWarning,
            stacklevel=2,
        )
        return canonical
    try:
        return Regime(value)
    except ValueError as exc:
        known = ", ".join(sorted(r.value for r in Regime))
        legacy = ", ".join(sorted(_LEGACY_REGIME_VALUES))
        raise ValueError(
            f"Unknown regime value {value!r}; expected one of [{known}] or legacy [{legacy}]."
        ) from exc


__all__ = [
    "ControlMapping",
    "CrosswalkEntry",
    "Regime",
    "coerce_legacy_regime",
    "get_all_controls_for_regime",
    "get_control_by_key",
    "get_crosswalk",
    "get_crosswalk_for_regime",
    "get_raw_section",
    "regimes",
]
