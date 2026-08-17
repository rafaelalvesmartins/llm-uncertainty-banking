"""
lub.runtime.protocols -- back-compat shim.

Pass-26.9 (RFC-004): the symbols originally defined here in pass 26.5
have been relocated to :mod:`lub.protocols` (top-level) to break the
``agents <-> runtime`` import cycle. This module re-exports them so
existing imports (``from lub.runtime.protocols import AuditKey``)
continue to work unchanged.

New code should prefer ``from lub.protocols import ...``.
"""

from __future__ import annotations

from lub.protocols import (
    AdapterLabel,
    AuditKey,
    RefusalAction,
    UncertaintyEstimatorProtocol,
)

__all__ = [
    "AdapterLabel",
    "AuditKey",
    "RefusalAction",
    "UncertaintyEstimatorProtocol",
]
