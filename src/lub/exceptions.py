# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Custom exception hierarchy for ``lub``.

Domain errors raised at runtime so callers can ``except`` on something
more specific than bare ``Exception``. Does NOT replace stdlib
``ValueError`` / ``TypeError`` for bad function arguments -- those are
idiomatic Python and stay as-is.

Hierarchy: ``LubError`` (base) -> ``BackendError`` (with subtype
``CapabilityError``), ``EstimatorError``, ``BenchmarkError``,
``CalibrationError``, ``OrchestrationError``, ``ConfidenceParseError``.

All exceptions carry an optional ``context: dict`` and optional
``cause`` for structured-log + OSCAL audit-trail integration.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "LubError",
    "BackendError",
    "CapabilityError",
    "EgressViolation",
    "EstimatorError",
    "BenchmarkError",
    "CalibrationError",
    "OrchestrationError",
    "ConfidenceParseError",
]


class LubError(Exception):
    """Base class for all domain errors raised by :mod:`lub`."""

    def __init__(
        self,
        message: str,
        *,
        context: dict[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = dict(context) if context else {}
        self.cause = cause
        if cause is not None and "cause_type" not in self.context:
            self.context["cause_type"] = type(cause).__name__

    def __repr__(self) -> str:
        if self.context:
            return f"{type(self).__name__}({self.message!r}, context={self.context!r})"
        return f"{type(self).__name__}({self.message!r})"


class BackendError(LubError):
    """An LLM backend call failed (transport / rate limit / malformed)."""


class CapabilityError(BackendError):
    """The backend does not support the requested operation."""


class EgressViolation(BackendError):
    """A hosted backend was constructed under the air-gapped profile.

    Lives here rather than in :mod:`lub.governance.local_only` because
    :mod:`lub.wrappers` — a core layer — must raise it, and the import
    contract forbids core layers from importing governance. The policy
    itself (what counts as hosted, how to classify an object graph) stays
    in governance; only the error travels down.

    Carries the offending backend's class name so an audit record names
    what was refused, not merely that something was.
    """

    def __init__(self, backend_name: str) -> None:
        self.backend_name = backend_name
        super().__init__(
            f"{backend_name} sends prompts to a third-party endpoint and is refused "
            f"under the air-gapped profile (LUB_LOCAL_ONLY=1). Use a local backend "
            f"(VLLMBackend, HFBackend) or unset the profile deliberately.",
            context={"backend": backend_name},
        )


class EstimatorError(LubError):
    """An uncertainty estimator could not produce a valid score."""


class BenchmarkError(LubError):
    """A benchmark dataset loader failed (HF + local fallback both missing)."""


class CalibrationError(LubError):
    """A calibrator is in an inconsistent state."""


class OrchestrationError(LubError):
    """A router / swarm / phase pipeline failed to complete."""


class ConfidenceParseError(LubError):
    """An agent adapter could not extract a numeric confidence."""
