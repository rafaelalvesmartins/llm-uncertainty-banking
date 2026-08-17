# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""EU AI Act — Regulation (EU) 2024/1689."""

from __future__ import annotations

from typing import Final

from lub.reports.crosswalk import ControlMapping, Regime, get_all_controls_for_regime

REGIME: Final[Regime] = Regime.EU_AI_ACT
CROSSWALK_KEY: Final[str] = "EU_AI_ACT"
TITLE: Final[str] = "Regulation (EU) 2024/1689 — EU AI Act"


def get_controls() -> list[ControlMapping]:
    """Return the EU AI Act control mappings from :mod:`lub.reports.crosswalk`.

    Typed as ``list[ControlMapping]`` to satisfy
    :class:`lub.compliance.frameworks.protocols.ComplianceFrameworkProtocol`;
    runtime return is unchanged (delegates to
    :func:`lub.reports.crosswalk.get_all_controls_for_regime`).
    """
    return list(get_all_controls_for_regime(REGIME))


__all__ = ["CROSSWALK_KEY", "REGIME", "TITLE", "get_controls"]
