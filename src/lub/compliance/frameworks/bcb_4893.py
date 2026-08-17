# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""BCB Resolução 4.893/2021 — Banco Central do Brasil cybersecurity / IT."""

from __future__ import annotations

from typing import Final

from lub.reports.crosswalk import ControlMapping, Regime, get_all_controls_for_regime

REGIME: Final[Regime] = Regime.BCB
CROSSWALK_KEY: Final[str] = "BCB"
TITLE: Final[str] = "BCB Resolução 4.893/2021"


def get_controls() -> list[ControlMapping]:
    """Return the BCB 4.893 control mappings from :mod:`lub.reports.crosswalk`.

    Typed as ``list[ControlMapping]`` to satisfy
    :class:`lub.compliance.frameworks.protocols.ComplianceFrameworkProtocol`;
    runtime return is unchanged (delegates to
    :func:`lub.reports.crosswalk.get_all_controls_for_regime`).
    """
    return list(get_all_controls_for_regime(REGIME))


__all__ = ["CROSSWALK_KEY", "REGIME", "TITLE", "get_controls"]
