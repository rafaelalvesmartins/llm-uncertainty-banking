# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Deprecated singular module -- use :mod:`lub.evidence.protocols` instead.

This module previously co-existed with :mod:`lub.evidence.protocols`
(plural). On 2026-04-26 the plural form was made canonical and this
module became a back-compat shim that re-exports from it.

A ``DeprecationWarning`` fires on every import; the module will be
removed in v0.3.
"""

from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "lub.evidence.protocol (singular) is deprecated; import from "
    "lub.evidence.protocols (plural) instead. Removal scheduled for v0.3.",
    DeprecationWarning,
    stacklevel=2,
)

from lub.evidence.protocols import (  # noqa: E402, F401
    EvidenceStoreProtocol,
    InMemoryEvidenceStore,
    PersistentEvidenceStoreProtocol,
)

__all__ = [
    "EvidenceStoreProtocol",
    "InMemoryEvidenceStore",
    "PersistentEvidenceStoreProtocol",
]
