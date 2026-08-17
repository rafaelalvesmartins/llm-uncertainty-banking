# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Plural alias for :mod:`lub.ledger.protocol`.

CODE_ORGANIZATION_REVIEW item A.2 (2026-04-25) flagged the
``protocol.py`` (singular) vs ``protocols.py`` (plural) split. This
shim makes the plural import path work for ``lub.ledger``; the
canonical singular module stays in v0.1 because it is consumed by
production code paths (``lub.dashboard.in_memory_source``,
``lub.ledger.metrics``, ``lub.ledger.store``). Plural becomes canonical
in v0.3 with a deprecation cycle.
"""

from __future__ import annotations

from lub.ledger.protocol import *  # noqa: F401, F403
from lub.ledger.protocol import __all__ as _all

__all__ = list(_all)
