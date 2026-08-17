# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared OSCAL 1.1.2 Pydantic models and helpers.

Three OSCAL document types (Component Definition, Catalog, Assessment
Results) share the same ``Prop``, ``Metadata``, and ``Link`` primitives
plus the same UUID/timestamp helpers.  Consolidating them here avoids
maintaining three copies and ensures consistent schema behavior.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

OSCAL_VERSION: Final = "1.1.2"


def now_iso() -> str:
    """UTC timestamp in ISO 8601 with second precision."""
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def gen_uuid() -> str:
    """Random UUID4 as a string."""
    return str(uuid.uuid4())


class OscalProp(BaseModel):
    """OSCAL generic property ``{name, value, ns?}``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: str
    ns: str | None = None


class OscalLink(BaseModel):
    """OSCAL link record ``{href, rel}``."""

    model_config = ConfigDict(extra="forbid")

    href: str
    rel: str


class OscalMetadata(BaseModel):
    """OSCAL metadata block — title, version, timestamps."""

    model_config = ConfigDict(extra="forbid")

    title: str
    last_modified: str = Field(alias="last-modified")
    version: str
    oscal_version: str = Field(alias="oscal-version")


__all__ = [
    "OSCAL_VERSION",
    "OscalLink",
    "OscalMetadata",
    "OscalProp",
    "gen_uuid",
    "now_iso",
]
