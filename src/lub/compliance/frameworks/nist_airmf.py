# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""NIST AI RMF 1.0 + NIST AI 600-1 (Generative AI Profile)."""

from __future__ import annotations

from typing import Final

from lub.reports.crosswalk import ControlMapping, Regime, get_all_controls_for_regime

REGIME: Final[Regime] = Regime.NIST_GENAI
CROSSWALK_KEY: Final[str] = "NIST_GENAI"
TITLE: Final[str] = "NIST AI 600-1 Generative AI Profile of AI RMF 1.0"


def get_controls() -> list[ControlMapping]:
    """Return the NIST AI 600-1 control mappings from :mod:`lub.reports.crosswalk`.

    Typed as ``list[ControlMapping]`` to satisfy
    :class:`lub.compliance.frameworks.protocols.ComplianceFrameworkProtocol`;
    runtime return is unchanged (delegates to
    :func:`lub.reports.crosswalk.get_all_controls_for_regime`).
    """
    return list(get_all_controls_for_regime(REGIME))


__all__ = ["CROSSWALK_KEY", "REGIME", "TITLE", "get_controls"]
