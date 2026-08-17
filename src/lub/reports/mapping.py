# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Mapping from library metrics to compliance framework sub-categories.

Three frameworks are supported:

1. **Federal Reserve SR 11-7 / OCC 2011-12** — the mandatory US
   framework for model risk management at supervised banks.
2. **NIST AI RMF 1.0** — the primary US voluntary framework.
3. **ISO/IEC 42001:2023** — the international AI management-system
   standard, referenced by EU AI Act Annex IV.

Control definitions live in the adjacent ``mapping_data.toml`` so that
auditors can review the regulatory mapping without reading Python.
This module loads the TOML at import time and exposes the same public
API as before.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TypedDict

_DATA_PATH = Path(__file__).with_name("mapping_data.toml")


class RmfEntry(TypedDict):
    subcategory: str
    description: str
    trust_dimension: str


class Iso42001Entry(TypedDict):
    """Mapping entry for ISO/IEC 42001:2023 clauses."""

    clause: str
    description: str
    annex: str


class Sr117Entry(TypedDict):
    """Mapping entry for Federal Reserve SR 11-7 / OCC 2011-12.

    The three pillars are:

    - **Pillar 1 — Model Development and Implementation**
    - **Pillar 2 — Model Validation**
    - **Pillar 3 — Governance, Policies and Controls**

    Reference: Federal Reserve SR Letter 11-7 (April 4, 2011).
    """

    pillar: str
    section: str
    description: str


# ---------------------------------------------------------------------------
# TOML loader
# ---------------------------------------------------------------------------


def _load_toml() -> tuple[dict[str, RmfEntry], dict[str, Iso42001Entry], dict[str, Sr117Entry]]:
    """Parse ``mapping_data.toml`` and return all three mapping dicts."""
    raw = _DATA_PATH.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))

    rmf: dict[str, RmfEntry] = {
        k: RmfEntry(
            subcategory=v["subcategory"],
            description=v["description"],
            trust_dimension=v["trust_dimension"],
        )
        for k, v in data.get("rmf", {}).items()
    }

    iso: dict[str, Iso42001Entry] = {
        k: Iso42001Entry(
            clause=v["clause"],
            description=v["description"],
            annex=v["annex"],
        )
        for k, v in data.get("iso42001", {}).items()
    }

    sr117: dict[str, Sr117Entry] = {
        k: Sr117Entry(
            pillar=v["pillar"],
            section=v["section"],
            description=v["description"],
        )
        for k, v in data.get("sr117", {}).items()
    }

    return rmf, iso, sr117


_MAPPING, _ISO42001_MAPPING, _SR117_MAPPING = _load_toml()


# ---------------------------------------------------------------------------
# Public API (unchanged)
# ---------------------------------------------------------------------------


def get_rmf_mapping() -> dict[str, RmfEntry]:
    """Return a copy of the metric -> AI RMF sub-category mapping."""
    return {k: RmfEntry(**v) for k, v in _MAPPING.items()}


def get_iso42001_mapping() -> dict[str, Iso42001Entry]:
    """Return a copy of the metric -> ISO/IEC 42001:2023 clause mapping."""
    return {k: Iso42001Entry(**v) for k, v in _ISO42001_MAPPING.items()}


def get_sr117_mapping() -> dict[str, Sr117Entry]:
    """Return a copy of the metric -> SR 11-7 pillar mapping."""
    return {k: Sr117Entry(**v) for k, v in _SR117_MAPPING.items()}


__all__ = [
    "Iso42001Entry",
    "RmfEntry",
    "Sr117Entry",
    "get_iso42001_mapping",
    "get_rmf_mapping",
    "get_sr117_mapping",
]
