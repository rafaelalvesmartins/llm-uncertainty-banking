# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Lightweight input/output guard hooks for :class:`UncertaintyPipeline`.

A :class:`RailSet` is a pair of lists of pure Python callables:

- **Input rails** run on the user prompt before it reaches the
  estimator. They may reject (raise :class:`InputRailRejected`) or
  rewrite (return a modified string).
- **Output rails** run on the :class:`~lub.types.UncertaintyResult`
  produced by the estimator. They may return the result unchanged,
  return a modified result, or raise :class:`OutputRailRejected`.

This module is deliberately tiny -- no DSL, no async machinery. Use
:class:`lub.orchestration.hooks.HookRegistry` for non-mutating
observers; rails are for changing prompt or result.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import structlog

from lub.types import UncertaintyResult

_LOG = structlog.get_logger("lub.rails")

InputRail = Callable[[str], str]
OutputRail = Callable[[UncertaintyResult], UncertaintyResult]


class RailRejected(Exception):
    """Base class for rail-driven refusals."""


class InputRailRejected(RailRejected):
    """Raised by an input rail to block a prompt before generation."""


class OutputRailRejected(RailRejected):
    """Raised by an output rail to block a result after generation."""


@dataclass(frozen=True)
class RailSet:
    """A pair of input and output rail lists applied in order."""

    input_rails: tuple[InputRail, ...] = ()
    output_rails: tuple[OutputRail, ...] = ()

    def apply_input(self, prompt: str) -> str:
        """Run all input rails over ``prompt`` in order and return the result."""
        current = prompt
        for rail in self.input_rails:
            rail_name = getattr(rail, "__name__", type(rail).__name__)
            _LOG.debug("rail.input.apply", rail=rail_name)
            current = rail(current)
        return current

    def apply_output(self, result: UncertaintyResult) -> UncertaintyResult:
        """Run all output rails over ``result`` in order and return the result."""
        current = result
        for rail in self.output_rails:
            rail_name = getattr(rail, "__name__", type(rail).__name__)
            _LOG.debug("rail.output.apply", rail=rail_name)
            current = rail(current)
        return current


# Built-in input rails ------------------------------------------------------

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("cpf", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
)


def max_length(limit: int) -> InputRail:
    """Reject prompts whose length (in characters) exceeds ``limit``."""
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")

    def _rail(prompt: str) -> str:
        if len(prompt) > limit:
            raise InputRailRejected(f"prompt length {len(prompt)} exceeds max_length {limit}")
        return prompt

    return _rail


def reject_pii(
    categories: tuple[str, ...] | None = None,
    *,
    custom_patterns: tuple[tuple[str, re.Pattern[str]], ...] | None = None,
) -> InputRail:
    """Reject prompts that look like they contain PII in ``categories``."""
    active: list[tuple[str, re.Pattern[str]]] = [
        (name, pat) for name, pat in _PII_PATTERNS if categories is None or name in categories
    ]
    if custom_patterns:
        active.extend(custom_patterns)

    def _rail(prompt: str) -> str:
        for name, pat in active:
            if pat.search(prompt):
                raise InputRailRejected(f"prompt matches PII pattern {name!r}")
        return prompt

    return _rail


def strip_whitespace() -> InputRail:
    """Trim leading/trailing whitespace from the prompt."""

    def _rail(prompt: str) -> str:
        return prompt.strip()

    return _rail


# Built-in output rails -----------------------------------------------------


def require_confidence(min_confidence: float) -> OutputRail:
    """Reject the result if ``confidence < min_confidence``."""
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be in [0, 1], got {min_confidence}")

    def _rail(result: UncertaintyResult) -> UncertaintyResult:
        if result.confidence < min_confidence:
            raise OutputRailRejected(
                f"confidence {result.confidence:.3f} below floor {min_confidence:.3f}"
            )
        return result

    return _rail


def strip_chain_of_thought(marker: str = "Let's think step by step") -> OutputRail:
    """Drop any suffix after ``marker`` from the answer text."""

    def _rail(result: UncertaintyResult) -> UncertaintyResult:
        text = result.answer
        idx = text.find(marker)
        if idx != -1:
            return result.with_answer(text[:idx].strip())
        return result

    return _rail


def force_refuse_below(threshold: float) -> OutputRail:
    """Set ``should_refuse`` if confidence is below ``threshold``."""
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"threshold must be in [0, 1], got {threshold}")

    def _rail(result: UncertaintyResult) -> UncertaintyResult:
        if result.confidence < threshold:
            return result.with_should_refuse(True)
        return result

    return _rail


# Generalized hooks system (Pattern 5) --------------------------------------

#: Sentinel returned by an ``on_error`` hook to short-circuit dispatch.
STOP: object = object()

LIFECYCLE_HOOKS: frozenset[str] = frozenset({"pre_run", "post_run", "on_error", "on_terminate"})
UQ_HOOKS: frozenset[str] = frozenset({"pre_score", "post_score", "on_refusal"})
KNOWN_HOOKS: frozenset[str] = LIFECYCLE_HOOKS | UQ_HOOKS

HookFn = Callable[..., object]


class HookRegistry:
    """Generalized non-blocking hooks registry.

    Names are arbitrary strings; hooks may take any ``*args`` / ``**kwargs``;
    a hook that raises is logged + swallowed (except ``on_error``, where a
    hook may return :data:`STOP` to short-circuit further dispatch).
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookFn]] = {}

    def register(self, name: str, fn: HookFn) -> None:
        """Append ``fn`` to the hook list for ``name``."""
        if not isinstance(name, str) or not name:
            raise ValueError("HookRegistry.register: name must be a non-empty str")
        if not callable(fn):
            raise TypeError(f"HookRegistry.register: fn must be callable, got {type(fn).__name__}")
        if name not in KNOWN_HOOKS:
            _LOG.debug("hooks.unknown_name", name=name)
        self._hooks.setdefault(name, []).append(fn)

    def hooks_for(self, name: str) -> list[HookFn]:
        """Return a copy of the hook list registered under ``name``."""
        return list(self._hooks.get(name, ()))

    def dispatch(self, name: str, *args: object, **kwargs: object) -> object:
        """Fire every hook registered for ``name`` in insertion order.

        Returns :data:`STOP` if any ``on_error`` hook returned STOP,
        otherwise ``None``. Exceptions are logged and swallowed.
        """
        if name not in self._hooks:
            return None
        for hook in list(self._hooks[name]):
            try:
                ret = hook(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 -- non-blocking by contract
                _LOG.warning(
                    "hooks.error",
                    name=name,
                    hook=getattr(hook, "__name__", type(hook).__name__),
                    error=str(exc),
                )
                continue
            if name == "on_error" and ret is STOP:
                _LOG.info(
                    "hooks.short_circuit",
                    name=name,
                    hook=getattr(hook, "__name__", type(hook).__name__),
                )
                return STOP
        return None


__all__ = [
    "HookRegistry",
    "InputRailRejected",
    "KNOWN_HOOKS",
    "LIFECYCLE_HOOKS",
    "OutputRailRejected",
    "RailRejected",
    "RailSet",
    "STOP",
    "UQ_HOOKS",
    "force_refuse_below",
    "max_length",
    "reject_pii",
    "require_confidence",
    "strip_chain_of_thought",
    "strip_whitespace",
]
