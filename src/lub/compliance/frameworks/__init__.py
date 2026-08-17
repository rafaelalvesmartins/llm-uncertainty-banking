# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""lub.compliance.frameworks -- per-regime compliance modules (skeleton, v0.3+).

Per spec 30 each compliance regime should eventually own its catalog
of controls + an emit format + a crosswalk to the others. v0.1 keeps
the consolidated mapping under :mod:`lub.reports.mapping` and
:mod:`lub.reports.crosswalk`; this namespace ships **lazy aliases**
that let v0.3-targeted code import the framework-shaped names today.

Pre-shipped frameworks (skeleton -- re-exports only):

* :mod:`lub.compliance.frameworks.sr_11_7`     — Federal Reserve SR 11-7 / OCC Bulletin 2011-12
* :mod:`lub.compliance.frameworks.nist_airmf`  — NIST AI RMF 1.0 + AI 600-1 GenAI Profile
* :mod:`lub.compliance.frameworks.iso_42001`   — ISO/IEC 42001:2023 AI management system
* :mod:`lub.compliance.frameworks.eu_ai_act`   — Regulation (EU) 2024/1689
* :mod:`lub.compliance.frameworks.bcbs_239`    — BCBS 239 risk data aggregation principles
* :mod:`lub.compliance.frameworks.bcb_4893`    — BCB Resolução 4.893/2021 (Brasil)
* :mod:`lub.compliance.frameworks.iso_23894`   — ISO/IEC 23894:2023 AI risk management

Each module exposes:

* ``REGIME``: the :class:`lub.reports.crosswalk.Regime` enum value
  (None for SR 11-7 which is cross-referenced rather than a regime).
* ``get_controls()``: the framework's controls from
  :mod:`lub.reports.crosswalk` (or empty for SR 11-7 in v0.1).
* ``CROSSWALK_KEY``: the string key used in ``crosswalk_data.toml``.
* ``TITLE``: a human-readable framework title for report headers.

The contract is formalized as
:class:`lub.compliance.frameworks.protocols.ComplianceFrameworkProtocol`
(structural, ``runtime_checkable``). Adding a new compliance regime in
v0.3+ means creating a new ``lub.compliance.frameworks.<name>`` module
that satisfies that Protocol -- no registry edit, no central wiring.
v0.1 keeps the data side under TOML so this namespace is mostly
metadata pointers.
"""

from __future__ import annotations

from types import ModuleType

from lub.compliance.frameworks import (  # noqa: F401
    bcb_4893,
    bcbs_239,
    eu_ai_act,
    iso_23894,
    iso_42001,
    nist_airmf,
    sr_11_7,
)
from lub.compliance.frameworks.protocols import ComplianceFrameworkProtocol

#: Tuple of every shipped compliance-framework module, in stable alphabetical
#: order. Concretizes the "callers can iterate over an arbitrary set of
#: frameworks without depending on the concrete module names" claim in
#: :mod:`lub.compliance.frameworks.protocols` -- consumers (dashboard, OSCAL
#: emitters, future plug-ins) can iterate this tuple instead of hard-coding
#: framework names. Each member structurally satisfies
#: :class:`ComplianceFrameworkProtocol`.
FRAMEWORKS: tuple[ModuleType, ...] = (
    bcb_4893,
    bcbs_239,
    eu_ai_act,
    iso_23894,
    iso_42001,
    nist_airmf,
    sr_11_7,
)

__all__ = [
    "ComplianceFrameworkProtocol",
    "FRAMEWORKS",
    "bcb_4893",
    "bcbs_239",
    "eu_ai_act",
    "iso_23894",
    "iso_42001",
    "nist_airmf",
    "sr_11_7",
]
