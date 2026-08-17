# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""BCBS 239 — Principles for effective risk data aggregation and risk reporting.

Renamed 2026-04-26 from "BCBS d475" (which is the wrong document — see
``lub.reports.crosswalk`` for the rename rationale and the
``coerce_legacy_regime`` back-compat helper).
"""

from __future__ import annotations

from typing import Final

from lub.reports.crosswalk import ControlMapping, Regime, get_all_controls_for_regime

REGIME: Final[Regime] = Regime.BCBS
CROSSWALK_KEY: Final[str] = "BCBS"
TITLE: Final[str] = "BCBS 239 — Principles for effective risk data aggregation and risk reporting"


def get_controls() -> list[ControlMapping]:
    """Return the BCBS 239 control mappings from :mod:`lub.reports.crosswalk`.

    Typed as ``list[ControlMapping]`` to satisfy
    :class:`lub.compliance.frameworks.protocols.ComplianceFrameworkProtocol`;
    runtime return is unchanged (delegates to
    :func:`lub.reports.crosswalk.get_all_controls_for_regime`).
    """
    return list(get_all_controls_for_regime(REGIME))


__all__ = ["CROSSWALK_KEY", "REGIME", "TITLE", "get_controls"]
