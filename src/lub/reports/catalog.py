# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""OSCAL Catalog generator for regulatory frameworks.

Generates machine-readable OSCAL 1.1.2 Catalog JSON documents from the
crosswalk table in :mod:`lub.reports.crosswalk`.  Each catalog represents
one regulatory framework (NIST AI 600-1, EU AI Act, BCBS 239, BCB, or
ISO/IEC 23894) and lists the controls that LUB metrics provide evidence
for.

.. note::
   The BCBS regime was renamed 2026-04-26 from ``"BCBS_d475"`` (the wrong
   document — d475 is the 2019 BIS paper on derivatives margining) to
   ``"BCBS_239"`` (Principles for effective risk data aggregation and
   risk reporting, January 2013).  Legacy strings still resolve through
   :func:`lub.reports.crosswalk.coerce_legacy_regime`.

An OSCAL Catalog is the foundational layer of the OSCAL stack:
``Catalog → Profile → System-Security-Plan → Assessment-Plan →
Assessment-Results``.  By publishing catalogs, LUB lets GRC tools
(NIST Trestle, Regscale, Lula, OSCAL-CLI) import controls and build
assessment pipelines without manual data entry.

No open-source project publishes OSCAL catalogs for the EU AI Act or
BCBS 239 as of April 2026.  LUB is the first.

References:
    NIST OSCAL 1.1.2 Catalog schema:
      https://pages.nist.gov/OSCAL/reference/1.1.2/catalog/json-outline/
    NIST AI 600-1 (July 2024):
      https://doi.org/10.6028/NIST.AI.600-1
    EU AI Act (Regulation 2024/1689):
      https://eur-lex.europa.eu/eli/reg/2024/1689
"""

from __future__ import annotations

import json as _json
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from lub.reports.crosswalk import (
    ControlMapping,
    Regime,
    get_all_controls_for_regime,
    regimes,
)
from lub.reports.oscal_common import (
    OSCAL_VERSION as _OSCAL_VERSION,
)
from lub.reports.oscal_common import (
    OscalMetadata,
    OscalProp,
)
from lub.reports.oscal_common import (
    gen_uuid as _gen_uuid,
)
from lub.reports.oscal_common import (
    now_iso as _now_iso,
)

_LOG = structlog.get_logger("lub.reports.catalog")

# ---- Regime metadata ----

_REGIME_META: dict[Regime, dict[str, str]] = {
    Regime.NIST_GENAI: {
        "title": "NIST AI 600-1 — Artificial Intelligence Risk Management Framework: "
        "Generative AI Profile",
        "version": "1.0",
        "source_url": "https://doi.org/10.6028/NIST.AI.600-1",
    },
    Regime.EU_AI_ACT: {
        "title": "EU AI Act (Regulation 2024/1689) — High-Risk AI System Requirements",
        "version": "2024/1689",
        "source_url": "https://eur-lex.europa.eu/eli/reg/2024/1689",
    },
    Regime.BCBS: {
        "title": "BCBS 239 — Principles for effective risk data aggregation and risk reporting",
        "version": "2013",
        "source_url": "https://www.bis.org/publ/bcbs239.htm",
    },
    Regime.BCB: {
        "title": "BCB — Resolução 4.893/2021 (Gestão de Risco de Tecnologia) "
        "e Circular 3.978 (Governança de Dados)",
        "version": "2021",
        "source_url": "https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo"
        "?tipo=Resolu%C3%A7%C3%A3o%20BCB&numero=4893",
    },
    Regime.ISO_23894: {
        "title": "ISO/IEC 23894:2023 — Information technology — Artificial intelligence "
        "— Guidance on risk management",
        "version": "2023",
        "source_url": "https://www.iso.org/standard/77304.html",
    },
    Regime.ISO_42001: {
        "title": "ISO/IEC 42001:2023 — Information technology — Artificial intelligence "
        "— Management system",
        "version": "2023",
        "source_url": "https://www.iso.org/standard/81230.html",
    },
}


# ---------------------------------------------------------------------------
# Pydantic models — OSCAL Catalog subset
# ---------------------------------------------------------------------------


class CatalogPart(BaseModel):
    """A prose ``part`` within a control (typically the statement)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    prose: str


class CatalogControl(BaseModel):
    """One control within a catalog group."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    props: list[OscalProp] = Field(default_factory=list)
    parts: list[CatalogPart] = Field(default_factory=list)


class CatalogGroup(BaseModel):
    """A group of related controls (e.g. all Measure-family controls)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    controls: list[CatalogControl] = Field(default_factory=list)


class OscalCatalog(BaseModel):
    """OSCAL Catalog document root."""

    model_config = ConfigDict(extra="forbid")

    uuid: str
    metadata: OscalMetadata
    groups: list[CatalogGroup] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _group_controls(controls: list[ControlMapping]) -> dict[str, list[ControlMapping]]:
    """Group controls by prefix (e.g. 'MS', 'MG', 'EU-AIA', 'BCBS', 'BCB', 'ISO')."""
    groups: dict[str, list[ControlMapping]] = {}
    for cm in controls:
        cid = cm["control_id"]
        # Use first segment before the first '-' that isn't a digit
        parts = cid.split("-")
        prefix = parts[0]
        # For multi-segment prefixes like EU-AIA, BCB-Res4893.  BCBS-239-* IDs
        # intentionally resolve to the bare "BCBS" prefix because the second
        # segment ("239") starts with a digit and so by-passes this branch.
        if len(parts) > 1 and not parts[1][0:1].isdigit():
            prefix = f"{parts[0]}-{parts[1]}"
        groups.setdefault(prefix, []).append(cm)
    return groups


_GROUP_TITLES: dict[str, str] = {
    "MS": "Measure — Performance and Uncertainty Assessment",
    "MG": "Manage — Change Management and Governance",
    "EU-AIA": "EU AI Act — High-Risk AI System Obligations",
    "BCBS": "BCBS 239 — Risk Data Aggregation and Risk Reporting Principles",
    "BCB-Res4893": "BCB — Gestão de Risco de Tecnologia",
    "BCB-Circ3978": "BCB — Governança de Dados",
    "ISO23894": "ISO/IEC 23894 — AI Risk Management",
    "ISO42001": "ISO/IEC 42001 — AI Management System",
}


def build_catalog(regime: Regime) -> OscalCatalog:
    """Build an OSCAL Catalog for the given regulatory regime.

    The catalog contains one group per control-family prefix, with
    each control carrying a statement part containing the crosswalk
    description and a ``regime`` property.
    """
    meta = _REGIME_META[regime]
    controls = get_all_controls_for_regime(regime)
    grouped = _group_controls(controls)

    catalog_groups: list[CatalogGroup] = []
    for prefix, cms in sorted(grouped.items()):
        group_title = _GROUP_TITLES.get(prefix, f"{prefix} Controls")
        catalog_controls: list[CatalogControl] = []
        for cm in cms:
            catalog_controls.append(
                CatalogControl(
                    id=cm["control_id"],
                    title=cm["control_title"],
                    props=[
                        OscalProp(name="regime", value=str(regime)),
                        OscalProp(
                            name="source",
                            value=meta["source_url"],
                            ns="https://lub.readthedocs.io/oscal",
                        ),
                    ],
                    parts=[
                        CatalogPart(
                            id=f"{cm['control_id']}-stmt",
                            name="statement",
                            prose=cm["description"],
                        )
                    ],
                )
            )
        catalog_groups.append(
            CatalogGroup(
                id=prefix.lower().replace("-", "_"),
                title=group_title,
                controls=catalog_controls,
            )
        )

    return OscalCatalog(
        uuid=_gen_uuid(),
        metadata=OscalMetadata(
            **{
                "title": meta["title"],
                "last-modified": _now_iso(),
                "version": meta["version"],
                "oscal-version": _OSCAL_VERSION,
            }
        ),
        groups=catalog_groups,
    )


def build_all_catalogs() -> dict[Regime, OscalCatalog]:
    """Build OSCAL Catalogs for all supported regimes."""
    return {r: build_catalog(r) for r in regimes()}


def render_catalog_json(
    regime: Regime,
    *,
    indent: int = 2,
) -> str:
    """Return the OSCAL Catalog for ``regime`` as a JSON string.

    Output conforms to the OSCAL 1.1.2 top-level envelope:
    ``{"catalog": { uuid, metadata, groups }}``.
    """
    cat = build_catalog(regime)
    payload = cat.model_dump(by_alias=True, exclude_none=True)
    envelope: dict[str, Any] = {"catalog": payload}
    return _json.dumps(envelope, indent=indent)


def render_all_catalogs_json(*, indent: int = 2) -> dict[str, str]:
    """Return ``{regime_value: json_string}`` for all regimes."""
    return {str(r): render_catalog_json(r, indent=indent) for r in regimes()}


__all__ = [
    "CatalogControl",
    "CatalogGroup",
    "OscalMetadata",
    "CatalogPart",
    "OscalProp",
    "OscalCatalog",
    "build_all_catalogs",
    "build_catalog",
    "render_all_catalogs_json",
    "render_catalog_json",
]
