# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Air-gapped ("sovereign") deployment profile.

Privacy is the first reason regulated institutions do not put an LLM in
front of customer data: a prompt sent to a hosted model is a disclosure
to a third party, whatever the contract says. This module turns "we do
not call out" from a deployment convention into an enforced invariant.

The check is **structural, not network-level**. Backends in
:mod:`lub.wrappers` that ship a prompt to a third-party endpoint derive
from :class:`~lub.wrappers.api_base.APIBackend`; local inference
backends (vLLM in-process, HuggingFace, dummy) do not. Refusing to
*construct* an ``APIBackend`` under the profile fails closed at wiring
time, before a single customer prompt exists — a far stronger position
than blocking the request that is already in flight.

Inheritance alone is not sufficient coverage, and pretending otherwise
would leave the guarantee holed. Hosted backends outside that hierarchy
must call :func:`enforce` themselves; today that means
:class:`~lub.connectors.bridge.integrations.azure_openai.AzureOpenAIBackend`,
which satisfies the chatbot's duck-typed ``LLMBackend`` protocol without
deriving from anything. Such a backend opts in twice: it calls
:func:`enforce` to be *refused* under the profile, and it sets
:data:`HOSTED_MARKER` so :func:`is_local_backend` *classifies* it
correctly. **Any new hosted backend has to do both** — a class that is
neither an ``APIBackend`` nor marked will be waved through as local.

Enable with ``LUB_LOCAL_ONLY=1`` (or ``LubConfig(local_only=True)``).

Scope, stated precisely
-----------------------

What the profile guarantees: **no customer prompt reaches a hosted LLM
provider**, because the objects that could carry one cannot be built.

What it does *not* claim:

* :class:`~lub.wrappers.hf.HFBackend` fetches model weights from the
  HuggingFace Hub on a cold cache. That is a *cache-warm* egress of
  public artifacts, not of customer data, and it stops once the cache
  is populated. Pre-seed ``LUB_CACHE_DIR`` for a genuinely offline host.
* It is not a firewall. Telemetry exporters, package installers, and
  anything else in the process are out of scope — enforce those at the
  network layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from lub.exceptions import EgressViolation

if TYPE_CHECKING:
    from lub.wrappers.base import ModelBackend

_LOG = structlog.get_logger("lub.governance.local_only")

LOCAL_ONLY_ENV_VAR = "LUB_LOCAL_ONLY"

# EgressViolation is defined in lub.exceptions, not here: lub.wrappers is a
# core layer and the import contract forbids it from importing governance, yet
# it is the layer that must raise on construction. The error travels down; the
# policy — what counts as hosted, how to classify an object graph — stays here.
# Re-exported so `from lub.governance.local_only import EgressViolation` keeps
# reading naturally at the call sites that care about the policy.


HOSTED_MARKER = "LUB_HOSTED"
"""Class attribute a hosted backend sets to ``True`` to declare egress.

Only needed by backends outside the :class:`APIBackend` hierarchy —
duck-typed ones that satisfy a protocol without inheriting anything.
"""


def is_local_backend(backend: Any) -> bool:
    """Return ``True`` if *backend* performs inference inside the perimeter.

    A backend is hosted if it descends from :class:`APIBackend` **or**
    declares :data:`HOSTED_MARKER`. Everything else is treated as local,
    so a new hosted backend that forgets the marker is classified wrong
    — the marker is a required part of adding one.
    """
    from lub.wrappers.api_base import APIBackend

    if isinstance(backend, APIBackend):
        return False
    return not bool(getattr(backend, HOSTED_MARKER, False))


def assert_local_only(*backends: ModelBackend) -> None:
    """Raise :class:`EgressViolation` if any of *backends* can egress.

    Use this to validate an object graph that was already built — for
    instance a router's tiers — when the profile was not set at
    construction time. Reports the first offender.
    """
    for backend in backends:
        if not is_local_backend(backend):
            raise EgressViolation(type(backend).__name__)


def enforce(backend: Any, *, local_only: bool) -> None:
    """Fail closed at construction when *local_only* is set.

    Called from :meth:`APIBackend.__init__`. Kept here rather than in
    the wrapper so the whole policy — the rule, the error, and the
    documented scope — lives in one auditable place.
    """
    if not local_only:
        return
    name = type(backend).__name__
    _LOG.warning("local_only.refused", backend=name)
    raise EgressViolation(name)


__all__ = [
    "HOSTED_MARKER",
    "LOCAL_ONLY_ENV_VAR",
    "EgressViolation",
    "assert_local_only",
    "enforce",
    "is_local_backend",
]
