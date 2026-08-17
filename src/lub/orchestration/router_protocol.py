# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.orchestration.router_protocol -- pluggable routing-policy surface.

Pass-36 (per spec 31 §3): introduces the :class:`RouterPolicy` Protocol so
plug-in routing policies (contextual bandits, real-time-budget-aware,
AlternativeRufloPool from spec 27 §2.3, etc.) can drop in without
modifying :mod:`lub.orchestration.router`.

The existing :class:`~lub.orchestration.router.TieredRouter` and
:class:`~lub.orchestration.router.FailoverChain` already satisfy this
Protocol structurally (both expose ``.answer(query)``); a thin
:class:`RouterPolicyRegistry` lets external code resolve policies by
short name.

This module is **purely additive** -- nothing in the existing router
module changes. v0.1 callers continue to import the concrete
:class:`TieredRouter` directly; v0.3+ callers can register and resolve
arbitrary policies via the registry.

Spec: planning/31_Storage_Genericity_Spec_2026-04-25.md §2.3.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = [
    "RouterPolicy",
    "register_router_policy",
    "get_router_policy",
    "list_router_policies",
]


@runtime_checkable
class RouterPolicy(Protocol):
    """Decide which model tier (or backend) to route a query to.

    The minimum interface is just ``.answer(query) -> Any``. Optional
    methods (``feedback``, ``introspect``) are read when present and
    ignored otherwise.
    """

    def answer(self, query: Any) -> Any:
        """Route the query and return whatever the underlying tier returns."""
        ...


# ---------------------------------------------------------------------------
# Registry (additive; plug-in friendly)
# ---------------------------------------------------------------------------


_ROUTER_POLICY_REGISTRY: dict[str, RouterPolicy] = {}


def register_router_policy(name: str, policy: RouterPolicy) -> None:
    """Register a router policy under a short name.

    Args:
        name: Stable short identifier (e.g. ``"primary"``, ``"failover"``,
            ``"alt_ruflo_pool"``).
        policy: Anything satisfying :class:`RouterPolicy`.

    Raises:
        ValueError: If ``name`` is empty.
        TypeError: If ``policy`` does not expose a callable ``.answer``.
    """
    if not name:
        raise ValueError("name must be a non-empty string")
    if not callable(getattr(policy, "answer", None)):
        raise TypeError(
            f"policy must expose a callable .answer() method (got {type(policy).__name__})"
        )
    _ROUTER_POLICY_REGISTRY[name] = policy


def get_router_policy(name: str) -> RouterPolicy:
    """Look up a registered router policy by name.

    Raises:
        KeyError: If no policy is registered under ``name``.
    """
    try:
        return _ROUTER_POLICY_REGISTRY[name]
    except KeyError as exc:
        known = sorted(_ROUTER_POLICY_REGISTRY)
        raise KeyError(f"unknown router policy {name!r}; choose from {known}") from exc


def list_router_policies() -> list[str]:
    """Return all registered policy names, sorted."""
    return sorted(_ROUTER_POLICY_REGISTRY)
