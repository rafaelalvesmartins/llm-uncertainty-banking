# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Plural alias for :mod:`lub.benchmarks.protocol`.

CODE_ORGANIZATION_REVIEW item A.2 (2026-04-25) flagged the
``protocol.py`` (singular) vs ``protocols.py`` (plural) split across
the codebase. The convergence target is the plural form (5 of 9 modules
already use it). This shim makes the plural import path work for
``lub.benchmarks`` so downstream code can migrate over time without
breaking.

The canonical module remains :mod:`lub.benchmarks.protocol` (singular)
in v0.1 to avoid touching the production import surface; the plural
form will become canonical in v0.3 with a deprecation cycle.
"""

from __future__ import annotations

from lub.benchmarks.protocol import *  # noqa: F401, F403
from lub.benchmarks.protocol import __all__ as _all

__all__ = list(_all)
