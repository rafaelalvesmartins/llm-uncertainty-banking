# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Bridge platform configuration — declarative, loadable from YAML or env.

This module owns the *declarative* surface of the Bridge subsystem.
Where :mod:`lub.bridge.platform` is the imperative orchestrator and
:mod:`lub.bridge` defines the domain types, :class:`BridgeConfig` is the
single source of truth for the operational knobs that govern a Bridge
deployment:

* **confidence_threshold** — the minimum calibrated confidence below
  which a completion is gated by the :class:`~lub.guard.UncertaintyGuard`.
  Defaults to ``0.7``, matching the Bradesco Bridge production
  calibration that yields ≈83% resolution at ≈89% retention.
* **max_retries** — bounded retry budget for transient agent failures;
  banking workflows must never retry indefinitely (regulator-visible
  SLOs cap end-to-end latency).
* **supported_channels** — which delivery surfaces (WhatsApp, mobile
  app, web) this deployment is licensed to serve. A query whose
  channel is not in this set must be refused by the caller before it
  reaches the platform.
* **compliance_mode** — the regulatory regime(s) under which the
  deployment operates (BCB 4893, BCBS 239, SR 11-7). The mode does not
  change behavior on its own; it tags the audit trail so the L5 AI RMF
  reporter can route evidence to the right regulator package.
* **audit_enabled** — when ``False``, the platform skips audit-trail
  emission. Disabled only in unit tests; production deployments must
  keep this on for BCB 4893 §4 evidence retention.

Loading
-------

Two equivalent constructors are exposed:

* :meth:`BridgeConfig.from_yaml` reads a YAML document. Useful for the
  Bradesco deployment scripts that ship a versioned ``bridge.yaml`` next
  to each environment.
* :meth:`BridgeConfig.from_env` reads environment variables with the
  ``LUB_BRIDGE_`` prefix. Useful for Kubernetes/container deployments
  where secrets and topology come from the cluster manifest.

Both constructors validate aggressively — banking software must fail
loud at startup rather than silently degrade in production.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog
import yaml

__all__ = [
    "BridgeConfig",
    "BridgeConfigError",
    "Channel",
    "ComplianceMode",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_MAX_RETRIES",
    "ENV_PREFIX",
]

_LOG = structlog.get_logger("lub.bridge.config")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CONFIDENCE_THRESHOLD: float = 0.7
"""Calibrated confidence floor below which the guard gates the completion.

Matches the threshold used by the Bradesco Bridge production deployment
that achieves ≈83% resolution and ≈89% retention. Changing this without
re-running the calibration suite invalidates those metrics.
"""

DEFAULT_MAX_RETRIES: int = 3
"""Default retry budget for transient agent failures.

Kept small on purpose: banking SLOs visible to regulators cap end-to-end
latency, and unbounded retries are a known failure mode in agentic
systems (silent cost blow-ups, cascading queue saturation).
"""

ENV_PREFIX: str = "LUB_BRIDGE_"
"""Prefix used by :meth:`BridgeConfig.from_env` for environment variables."""


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BridgeConfigError(ValueError):
    """Raised when a configuration document is malformed or out of range.

    Subclasses :class:`ValueError` so existing ``except ValueError`` handlers
    in deployment scripts continue to catch configuration issues, but the
    distinct type lets the L5 reporter tag the failure as a configuration
    fault rather than a runtime fault.
    """


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Channel(StrEnum):
    """Delivery surface for a Bridge deployment.

    The set deliberately mirrors the three Bradesco Bridge customer
    channels. Adding a channel here requires the corresponding
    compliance review (each surface has its own BCB licensing).
    """

    WHATSAPP = "whatsapp"
    APP = "app"
    WEB = "web"


class ComplianceMode(StrEnum):
    """Regulatory regime tags applied to the audit trail.

    A deployment may operate under more than one regime simultaneously
    (BCB 4893 *and* BCBS 239 is the typical Bradesco production
    configuration). The tag is informational — it does not change
    runtime behavior, only the labelling of evidence emitted to the
    audit log.
    """

    BCB_4893 = "BCB_4893"
    BCBS_239 = "BCBS_239"
    SR_11_7 = "SR_11_7"


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeConfig:
    """Frozen configuration for a :class:`~lub.bridge.platform.BridgePlatform`.

    Parameters
    ----------
    confidence_threshold:
        Minimum calibrated confidence in the inclusive range ``[0.0, 1.0]``.
        Defaults to :data:`DEFAULT_CONFIDENCE_THRESHOLD`.
    max_retries:
        Non-negative integer bounding transient-failure retries.
        Defaults to :data:`DEFAULT_MAX_RETRIES`.
    supported_channels:
        Iterable of :class:`Channel` values the deployment is licensed
        to serve. Must be non-empty — a Bridge deployment with no
        channels is a configuration error, not a degraded state.
    compliance_mode:
        Iterable of :class:`ComplianceMode` regimes. Must be non-empty
        because banking workflows are *always* under at least one
        regulator's jurisdiction.
    audit_enabled:
        Whether the platform emits structured audit events. Defaults
        to ``True`` and must stay ``True`` in production (BCB 4893 §4).

    Notes
    -----
    The dataclass is frozen so configuration cannot drift mid-process —
    re-loading the config requires constructing a new
    :class:`~lub.bridge.platform.BridgePlatform`, which is the only way
    the audit log can mark the boundary between the old and new
    configuration generations.
    """

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    max_retries: int = DEFAULT_MAX_RETRIES
    supported_channels: frozenset[Channel] = field(
        default_factory=lambda: frozenset({Channel.WHATSAPP, Channel.APP, Channel.WEB})
    )
    compliance_mode: frozenset[ComplianceMode] = field(
        default_factory=lambda: frozenset({ComplianceMode.BCB_4893, ComplianceMode.BCBS_239})
    )
    audit_enabled: bool = True

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def __post_init__(self) -> None:
        """Validate field ranges and types.

        Raises
        ------
        BridgeConfigError
            If any field is out of range, of the wrong type, or empty
            where a non-empty value is required. Errors fire at
            construction time so misconfiguration cannot surface as a
            mid-flight runtime crash.
        """
        # ``frozen=True`` forbids attribute assignment, so coerce via
        # ``object.__setattr__`` after validating. We coerce the
        # iterable channel/compliance fields up front so callers may
        # pass lists or tuples and still end up with a frozenset.
        self._validate_confidence_threshold(self.confidence_threshold)
        self._validate_max_retries(self.max_retries)

        channels = _coerce_channels(self.supported_channels)
        modes = _coerce_compliance_modes(self.compliance_mode)
        if not isinstance(self.audit_enabled, bool):
            raise BridgeConfigError(
                f"audit_enabled must be bool, got {type(self.audit_enabled).__name__}"
            )

        object.__setattr__(self, "supported_channels", channels)
        object.__setattr__(self, "compliance_mode", modes)

        _LOG.info(
            "bridge.config.validated",
            confidence_threshold=self.confidence_threshold,
            max_retries=self.max_retries,
            supported_channels=sorted(c.value for c in channels),
            compliance_mode=sorted(m.value for m in modes),
            audit_enabled=self.audit_enabled,
        )

    @staticmethod
    def _validate_confidence_threshold(value: Any) -> None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise BridgeConfigError(
                f"confidence_threshold must be a number, got {type(value).__name__}"
            )
        if not 0.0 <= float(value) <= 1.0:
            raise BridgeConfigError(f"confidence_threshold must be in [0.0, 1.0], got {value!r}")

    @staticmethod
    def _validate_max_retries(value: Any) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise BridgeConfigError(
                f"max_retries must be a non-negative int, got {type(value).__name__}"
            )
        if value < 0:
            raise BridgeConfigError(f"max_retries must be >= 0, got {value!r}")

    # ------------------------------------------------------------------ #
    # Inspection helpers
    # ------------------------------------------------------------------ #

    def supports_channel(self, channel: Channel | str) -> bool:
        """Return ``True`` when ``channel`` is in :attr:`supported_channels`.

        Accepts either a :class:`Channel` value or its string name so
        callers do not need to coerce before checking — keeps the call
        sites in HTTP handlers and message brokers readable.
        """
        try:
            resolved = channel if isinstance(channel, Channel) else Channel(channel)
        except ValueError:
            return False
        return resolved in self.supported_channels

    def has_compliance_mode(self, mode: ComplianceMode | str) -> bool:
        """Return ``True`` when ``mode`` is one of the configured regimes."""
        try:
            resolved = mode if isinstance(mode, ComplianceMode) else ComplianceMode(mode)
        except ValueError:
            return False
        return resolved in self.compliance_mode

    def to_dict(self) -> dict[str, Any]:
        """Serialize for audit logs, /healthz responses, and YAML round-trip.

        Sets are emitted as sorted lists so the output is deterministic —
        important for diff-based audit reviews where regulators compare
        the configuration of two deployment generations.
        """
        return {
            "confidence_threshold": float(self.confidence_threshold),
            "max_retries": int(self.max_retries),
            "supported_channels": sorted(c.value for c in self.supported_channels),
            "compliance_mode": sorted(m.value for m in self.compliance_mode),
            "audit_enabled": bool(self.audit_enabled),
        }

    # ------------------------------------------------------------------ #
    # Loaders
    # ------------------------------------------------------------------ #

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BridgeConfig:
        """Build a :class:`BridgeConfig` from a plain mapping.

        Used as the common backend for both :meth:`from_yaml` and any
        caller that already holds a parsed mapping (e.g. a deployment
        manifest fetched from a config service).

        Unknown keys raise :class:`BridgeConfigError` rather than being
        silently ignored — typo-tolerance is a known footgun for
        regulated configuration surfaces.
        """
        if not isinstance(data, Mapping):
            raise BridgeConfigError(
                f"BridgeConfig.from_dict expects a mapping, got {type(data).__name__}"
            )

        allowed = {
            "confidence_threshold",
            "max_retries",
            "supported_channels",
            "compliance_mode",
            "audit_enabled",
        }
        unknown = set(data) - allowed
        if unknown:
            raise BridgeConfigError(
                f"Unknown BridgeConfig fields: {sorted(unknown)!r}. Allowed: {sorted(allowed)!r}"
            )

        kwargs: dict[str, Any] = {}
        if "confidence_threshold" in data:
            kwargs["confidence_threshold"] = float(data["confidence_threshold"])
        if "max_retries" in data:
            value = data["max_retries"]
            if isinstance(value, bool) or not isinstance(value, int):
                raise BridgeConfigError(f"max_retries must be an int, got {type(value).__name__}")
            kwargs["max_retries"] = value
        if "supported_channels" in data:
            kwargs["supported_channels"] = _coerce_channels(data["supported_channels"])
        if "compliance_mode" in data:
            kwargs["compliance_mode"] = _coerce_compliance_modes(data["compliance_mode"])
        if "audit_enabled" in data:
            audit = data["audit_enabled"]
            if not isinstance(audit, bool):
                raise BridgeConfigError(f"audit_enabled must be bool, got {type(audit).__name__}")
            kwargs["audit_enabled"] = audit

        return cls(**kwargs)

    @classmethod
    def from_yaml(cls, path: str | Path) -> BridgeConfig:
        """Load a configuration from a YAML file.

        The file must contain a top-level mapping; lists or scalars at
        the root are rejected. The loader uses ``yaml.safe_load`` so a
        malicious YAML document cannot construct arbitrary Python
        objects (banking-grade defensive default).

        Raises
        ------
        BridgeConfigError
            If the file does not exist, is not readable, contains
            invalid YAML, or does not parse to a mapping.
        """
        resolved = Path(path)
        if not resolved.is_file():
            raise BridgeConfigError(f"BridgeConfig YAML not found: {resolved!s}")
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            raise BridgeConfigError(
                f"Failed to read BridgeConfig YAML {resolved!s}: {exc}"
            ) from exc

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise BridgeConfigError(f"Invalid YAML in BridgeConfig {resolved!s}: {exc}") from exc

        if data is None:
            # Empty YAML file → use defaults; explicit because PyYAML
            # returns ``None`` for empty documents and we want that
            # behavior to be intentional rather than accidental.
            _LOG.warning(
                "bridge.config.empty_yaml",
                path=str(resolved),
                action="using defaults",
            )
            return cls()
        if not isinstance(data, Mapping):
            raise BridgeConfigError(
                f"BridgeConfig YAML root must be a mapping, got "
                f"{type(data).__name__} in {resolved!s}"
            )

        _LOG.info("bridge.config.loaded_yaml", path=str(resolved))
        return cls.from_dict(data)

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        prefix: str = ENV_PREFIX,
    ) -> BridgeConfig:
        """Load a configuration from environment variables.

        Recognized variables (with the default ``LUB_BRIDGE_`` prefix)::

            LUB_BRIDGE_CONFIDENCE_THRESHOLD   float in [0.0, 1.0]
            LUB_BRIDGE_MAX_RETRIES            non-negative int
            LUB_BRIDGE_SUPPORTED_CHANNELS     comma-separated channel names
            LUB_BRIDGE_COMPLIANCE_MODE        comma-separated regime tags
            LUB_BRIDGE_AUDIT_ENABLED          one of ``1/0/true/false/yes/no``

        Missing variables fall back to the dataclass defaults. Pass an
        explicit ``env`` mapping for testing; production callers should
        let it default to :data:`os.environ`.
        """
        source: Mapping[str, str] = env if env is not None else os.environ
        overrides: dict[str, Any] = {}

        raw_threshold = source.get(f"{prefix}CONFIDENCE_THRESHOLD")
        if raw_threshold is not None:
            try:
                overrides["confidence_threshold"] = float(raw_threshold)
            except ValueError as exc:
                raise BridgeConfigError(
                    f"{prefix}CONFIDENCE_THRESHOLD must be a float, got {raw_threshold!r}"
                ) from exc

        raw_retries = source.get(f"{prefix}MAX_RETRIES")
        if raw_retries is not None:
            try:
                overrides["max_retries"] = int(raw_retries)
            except ValueError as exc:
                raise BridgeConfigError(
                    f"{prefix}MAX_RETRIES must be an int, got {raw_retries!r}"
                ) from exc

        raw_channels = source.get(f"{prefix}SUPPORTED_CHANNELS")
        if raw_channels is not None:
            overrides["supported_channels"] = _split_csv(raw_channels)

        raw_modes = source.get(f"{prefix}COMPLIANCE_MODE")
        if raw_modes is not None:
            overrides["compliance_mode"] = _split_csv(raw_modes)

        raw_audit = source.get(f"{prefix}AUDIT_ENABLED")
        if raw_audit is not None:
            overrides["audit_enabled"] = _parse_bool(raw_audit, f"{prefix}AUDIT_ENABLED")

        if not overrides:
            _LOG.info(
                "bridge.config.from_env.no_overrides",
                prefix=prefix,
                action="using defaults",
            )
            return cls()

        _LOG.info(
            "bridge.config.from_env",
            prefix=prefix,
            overrides=sorted(overrides),
        )
        return cls.from_dict(overrides)


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _coerce_channels(value: Any) -> frozenset[Channel]:
    """Convert an iterable of channel names/values into a non-empty frozenset.

    Accepts :class:`Channel` instances, strings, or any mixed iterable
    thereof. Sets/frozensets are accepted directly. A bare string is
    rejected — using ``"web"`` instead of ``["web"]`` is a common
    YAML-authoring mistake that silently iterates per character, so we
    fail loudly.
    """
    if isinstance(value, frozenset) and all(isinstance(item, Channel) for item in value):
        if not value:
            raise BridgeConfigError("supported_channels must be non-empty")
        return value
    if isinstance(value, str):
        raise BridgeConfigError(
            f"supported_channels must be a list/set of channel names, not a bare string {value!r}"
        )
    if not isinstance(value, Iterable):
        raise BridgeConfigError(f"supported_channels must be iterable, got {type(value).__name__}")

    resolved: set[Channel] = set()
    for item in value:
        if isinstance(item, Channel):
            resolved.add(item)
            continue
        if not isinstance(item, str):
            raise BridgeConfigError(
                f"supported_channels entries must be str or Channel, got {type(item).__name__}"
            )
        try:
            resolved.add(Channel(item))
        except ValueError as exc:
            allowed = sorted(c.value for c in Channel)
            raise BridgeConfigError(f"Unknown channel {item!r}; allowed: {allowed!r}") from exc

    if not resolved:
        raise BridgeConfigError("supported_channels must be non-empty")
    return frozenset(resolved)


def _coerce_compliance_modes(value: Any) -> frozenset[ComplianceMode]:
    """Convert an iterable of regime tags into a non-empty frozenset."""
    if isinstance(value, frozenset) and all(isinstance(item, ComplianceMode) for item in value):
        if not value:
            raise BridgeConfigError("compliance_mode must be non-empty")
        return value
    if isinstance(value, str):
        raise BridgeConfigError(
            f"compliance_mode must be a list/set of regime tags, not a bare string {value!r}"
        )
    if not isinstance(value, Iterable):
        raise BridgeConfigError(f"compliance_mode must be iterable, got {type(value).__name__}")

    resolved: set[ComplianceMode] = set()
    for item in value:
        if isinstance(item, ComplianceMode):
            resolved.add(item)
            continue
        if not isinstance(item, str):
            raise BridgeConfigError(
                f"compliance_mode entries must be str or ComplianceMode, got {type(item).__name__}"
            )
        try:
            resolved.add(ComplianceMode(item))
        except ValueError as exc:
            allowed = sorted(m.value for m in ComplianceMode)
            raise BridgeConfigError(
                f"Unknown compliance mode {item!r}; allowed: {allowed!r}"
            ) from exc

    if not resolved:
        raise BridgeConfigError("compliance_mode must be non-empty")
    return frozenset(resolved)


def _split_csv(raw: str) -> list[str]:
    """Split a comma-separated env-var value into a list of trimmed tokens."""
    return [piece.strip() for piece in raw.split(",") if piece.strip()]


def _parse_bool(raw: str, variable_name: str) -> bool:
    """Parse a permissive boolean env-var value.

    Accepts the standard truthy/falsy spellings; anything else raises
    so a typo cannot silently flip an audit-trail switch in production.
    """
    lowered = raw.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise BridgeConfigError(
        f"{variable_name} must be one of 1/0/true/false/yes/no/on/off, got {raw!r}"
    )
