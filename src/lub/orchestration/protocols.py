# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Plural alias for :mod:`lub.orchestration.router_protocol`.

CODE_ORGANIZATION_REVIEW item A.2 (2026-04-25) flagged the
``protocol.py`` (singular) vs ``protocols.py`` (plural) naming split
across the codebase. The convergence target is the plural form;
``lub.{benchmarks, ledger, reports, evidence, agents}`` and
``lub.compliance.frameworks`` already ship a ``protocols`` (plural)
module (some canonical, some alias). This shim brings
``lub.orchestration`` into the same convention.

The canonical module remains :mod:`lub.orchestration.router_protocol`
in v0.1 because it is consumed by tests and ``test_storage_protocols``;
the plural form will become canonical in v0.3 with a deprecation cycle.

.. note::
   The singular module is named ``router_protocol`` (specific) rather
   than ``protocol`` (generic) because the orchestration package may
   ship additional Protocol families (hooks, swarm topology) under
   distinct module names. This shim re-exports the router-policy surface
   only; future additions register through the same plural import path.
"""

from __future__ import annotations

from lub.orchestration.router_protocol import *  # noqa: F401, F403
from lub.orchestration.router_protocol import __all__ as _all

__all__ = list(_all)
