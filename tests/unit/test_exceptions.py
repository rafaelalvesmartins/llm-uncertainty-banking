# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the lub.exceptions hierarchy.

Covers: class hierarchy, catch-all via :class:`LubError`, ``context``
dict propagation, ``cause`` chaining, repr formatting, and that every
name in ``__all__`` is importable.
"""

from __future__ import annotations

import pytest

from lub.exceptions import (
    BackendError,
    BenchmarkError,
    CalibrationError,
    CapabilityError,
    ConfidenceParseError,
    EstimatorError,
    LubError,
    OrchestrationError,
)

# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "subclass",
    [
        BackendError,
        CapabilityError,
        EstimatorError,
        BenchmarkError,
        CalibrationError,
        OrchestrationError,
        ConfidenceParseError,
    ],
)
def test_subclasses_inherit_from_lub_error(subclass: type) -> None:
    assert issubclass(subclass, LubError)
    assert issubclass(subclass, Exception)


def test_capability_error_is_a_backend_error() -> None:
    """CapabilityError sits under BackendError so callers that ``except
    BackendError`` catch capability mismatches too."""
    assert issubclass(CapabilityError, BackendError)


def test_lub_error_catches_every_subclass() -> None:
    """A bare ``except LubError`` must catch any domain exception
    raised by the package."""
    for cls in (
        BackendError, CapabilityError, EstimatorError, BenchmarkError,
        CalibrationError, OrchestrationError, ConfidenceParseError,
    ):
        with pytest.raises(LubError):
            raise cls("test")


def test_specific_catch_takes_precedence() -> None:
    with pytest.raises(ConfidenceParseError) as info:
        raise ConfidenceParseError("ruflo gave 'high'")
    assert info.value.message == "ruflo gave 'high'"


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_message_is_first_positional_arg() -> None:
    e = BackendError("openai 502")
    assert e.message == "openai 502"
    assert str(e) == "openai 502"


def test_context_defaults_to_empty_dict() -> None:
    e = BackendError("x")
    assert e.context == {}


def test_context_is_copied_not_aliased() -> None:
    """Caller's dict must not leak into the exception instance, otherwise
    later mutations of the original would change the audit log."""
    payload = {"backend": "openai"}
    e = BackendError("x", context=payload)
    payload["backend"] = "anthropic"
    assert e.context == {"backend": "openai"}


def test_cause_is_recorded_separately_from_chain() -> None:
    upstream = ValueError("bad json")
    e = BackendError("openai parse failed", cause=upstream)
    assert e.cause is upstream
    assert e.context["cause_type"] == "ValueError"


def test_explicit_cause_type_in_context_is_preserved() -> None:
    """When the caller supplies their own cause_type tag, do not
    overwrite it -- they may want a more domain-specific label."""
    e = BackendError(
        "x",
        cause=RuntimeError("y"),
        context={"cause_type": "TransientNetworkError"},
    )
    assert e.context["cause_type"] == "TransientNetworkError"


def test_python_chain_still_works_with_raise_from() -> None:
    upstream = ValueError("bad json")
    try:
        try:
            raise upstream
        except ValueError as exc:
            raise BackendError("wrapped", cause=exc) from exc
    except BackendError as e:
        assert e.__cause__ is upstream
        assert e.cause is upstream


# ---------------------------------------------------------------------------
# Repr
# ---------------------------------------------------------------------------

def test_repr_without_context() -> None:
    r = repr(EstimatorError("no generations"))
    assert r == "EstimatorError('no generations')"


def test_repr_with_context_includes_dict() -> None:
    r = repr(OrchestrationError("no quorum", context={"agents": 3, "yes": 1}))
    assert "OrchestrationError" in r
    assert "no quorum" in r
    assert "agents" in r


# ---------------------------------------------------------------------------
# __all__ surface
# ---------------------------------------------------------------------------

def test_all_exported_names_are_importable() -> None:
    import lub.exceptions as mod
    for name in mod.__all__:
        assert hasattr(mod, name), f"{name} listed in __all__ but missing"


def test_exceptions_are_reexported_from_top_level_package() -> None:
    """Petition-petition pipeline imports ``from lub import LubError`` --
    ensure the top-level package re-exports the whole hierarchy."""
    import lub
    for name in [
        "LubError", "BackendError", "CapabilityError", "EstimatorError",
        "BenchmarkError", "CalibrationError", "OrchestrationError",
        "ConfidenceParseError",
    ]:
        assert hasattr(lub, name), f"{name} must be reexported from lub"
