"""Provider registry — the plugin substrate for swappable backends/integrations.

A *provider* is anything external the bridge talks to: an LLM backend today; cache /
audit / cloud later. Each provider implements a small Protocol, registers a factory
under a name, declares what it needs plus a health check, and is selected by config.

    Add a provider   = register it (or pip-install a plugin) + one config line.
    Remove a provider = disable it in config.
    The core pipeline never changes.

This is the foundation layer (`core`); higher layers (`backends`, `server`) build on
it — it imports nothing internal, so the import-linter layering stays clean.
See docs/PROVIDER_PLUGIN_ARCHITECTURE.md. This module is additive: nothing imports it
until Phase 1 Part B wires `backends._select_backend()` to `backend_registry.resolve()`.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar, runtime_checkable


@dataclass(frozen=True)
class ProviderHealth:
    """What a provider reports about itself (feeds the honesty layer + Conexões dots)."""

    status: str  # "active" | "reachable" | "not_configured" | "unreachable"
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("active", "reachable")


@dataclass
class ProviderConfig:
    """Per-provider settings pulled from env / secret manager (never hardcoded)."""

    name: str
    options: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, name: str, *keys: str) -> ProviderConfig:
        opts = {k: v for k in keys if (v := os.getenv(k)) is not None}
        return cls(name=name, options=opts)


@dataclass(frozen=True)
class ProviderSpec:
    """Declarative descriptor: how to build a provider + what it requires."""

    name: str
    factory: Callable[[ProviderConfig], object]
    requires_env: tuple[str, ...] = ()  # env vars needed to count as "configured"
    summary: str = ""


T = TypeVar("T")


class Registry(Generic[T]):
    """``name -> ProviderSpec`` for one layer. Built-ins register at import; plugins via
    entry-points; selection via config. Generic over the layer's provider Protocol."""

    def __init__(self, layer: str) -> None:
        self._layer = layer
        self._specs: dict[str, ProviderSpec] = {}

    def register(self, spec: ProviderSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"{self._layer} provider {spec.name!r} already registered")
        self._specs[spec.name] = spec

    def names(self) -> list[str]:
        return sorted(self._specs)

    def is_configured(self, name: str) -> bool:
        spec = self._specs.get(name)
        if spec is None:
            return False
        return all(os.getenv(e) for e in spec.requires_env)

    def health(self, name: str) -> ProviderHealth:
        spec = self._specs.get(name)
        if spec is None:
            return ProviderHealth("unreachable", f"unknown {self._layer} provider {name!r}")
        if not self.is_configured(name):
            missing = ", ".join(e for e in spec.requires_env if not os.getenv(e))
            return ProviderHealth("not_configured", f"missing env: {missing}")
        return ProviderHealth("reachable")

    def resolve(self, name: str, config: ProviderConfig | None = None) -> T:
        """Build the active provider. Raises ``KeyError`` if unknown — callers fall back."""
        spec = self._specs.get(name)
        if spec is None:
            raise KeyError(f"no {self._layer} provider {name!r}; have {self.names()}")
        return spec.factory(config or ProviderConfig(name))  # type: ignore[return-value]


# ---- LLM-backend layer (Phase 1 target) -------------------------------------------
# Backends self-register here; `_select_backend()` will resolve from it (Part B).


@runtime_checkable
class LLMBackend(Protocol):
    name: str

    def health(self) -> ProviderHealth: ...

    # def generate(self, req: Request) -> Response: ...
    #   ^ wired in Part B against the real Request/Response types in backends.py


backend_registry: Registry[LLMBackend] = Registry("llm-backend")


def register_backend(
    name: str, *, requires_env: tuple[str, ...] = (), summary: str = ""
) -> Callable[[Callable[[ProviderConfig], LLMBackend]], Callable[[ProviderConfig], LLMBackend]]:
    """Decorator: turn a factory into a registered backend provider.

    Example::

        @register_backend("openai", requires_env=("OPENAI_API_KEY",))
        def _make_openai(cfg: ProviderConfig) -> LLMBackend: ...
    """

    def deco(factory: Callable[[ProviderConfig], LLMBackend]) -> Callable[[ProviderConfig], LLMBackend]:
        backend_registry.register(
            ProviderSpec(name=name, factory=factory, requires_env=requires_env, summary=summary)
        )
        return factory

    return deco


__all__ = [
    "ProviderHealth",
    "ProviderConfig",
    "ProviderSpec",
    "Registry",
    "LLMBackend",
    "backend_registry",
    "register_backend",
]
