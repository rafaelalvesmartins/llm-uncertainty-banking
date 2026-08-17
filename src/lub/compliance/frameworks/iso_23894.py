# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""ISO/IEC 23894:2023 — AI risk management."""

from __future__ import annotations

from typing import Final

from lub.reports.crosswalk import ControlMapping, Regime, get_all_controls_for_regime

REGIME: Final[Regime] = Regime.ISO_23894
CROSSWALK_KEY: Final[str] = "ISO_23894"
TITLE: Final[str] = "ISO/IEC 23894:2023 — AI risk management"


def get_controls() -> list[ControlMapping]:
    """Return the ISO/IEC 23894 control mappings from :mod:`lub.reports.crosswalk`.

    Typed as ``list[ControlMapping]`` to satisfy
    :class:`lub.compliance.frameworks.protocols.ComplianceFrameworkProtocol`;
    runtime return is unchanged (delegates to
    :func:`lub.reports.crosswalk.get_all_controls_for_regime`).
    """
    return list(get_all_controls_for_regime(REGIME))


__all__ = ["CROSSWALK_KEY", "REGIME", "TITLE", "get_controls"]
