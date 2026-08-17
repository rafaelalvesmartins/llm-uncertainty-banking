# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Hermetic tests for the generalized HookRegistry in ``lub.rails``
(Pattern 5)."""

from __future__ import annotations

from lub.rails import (
    KNOWN_HOOKS,
    LIFECYCLE_HOOKS,
    STOP,
    UQ_HOOKS,
    HookRegistry,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_lifecycle_hooks_have_canonical_names():
    for name in ("pre_run", "post_run", "on_error", "on_terminate"):
        assert name in LIFECYCLE_HOOKS


def test_uq_hooks_have_canonical_names():
    for name in ("pre_score", "post_score", "on_refusal"):
        assert name in UQ_HOOKS


def test_known_hooks_is_union():
    assert KNOWN_HOOKS == LIFECYCLE_HOOKS | UQ_HOOKS


def test_stop_is_singleton_sentinel():
    assert STOP is STOP
    assert STOP is not None
    assert STOP is not False
    assert STOP is not 0  # noqa: F632 — identity check is the point


# ---------------------------------------------------------------------------
# Register + dispatch
# ---------------------------------------------------------------------------


def test_register_and_dispatch_calls_hook_with_args():
    registry = HookRegistry()
    seen = []

    def hook(payload):
        seen.append(payload)

    registry.register("pre_run", hook)
    registry.dispatch("pre_run", {"prompt": "hi"})
    assert seen == [{"prompt": "hi"}]


def test_register_multiple_hooks_dispatches_in_order():
    registry = HookRegistry()
    log = []
    registry.register("pre_run", lambda *_: log.append("first"))
    registry.register("pre_run", lambda *_: log.append("second"))
    registry.dispatch("pre_run", "ignored")
    assert log == ["first", "second"]


def test_dispatch_unknown_name_does_not_raise():
    # Unknown hook names are accepted (logged at debug); no callbacks
    # registered, dispatch is a no-op.
    registry = HookRegistry()
    registry.dispatch("never_registered")


def test_register_unknown_name_does_not_raise():
    # Domain-specific hook names (outside KNOWN_HOOKS) must be allowed
    # — typos are traceable via structlog, not via exceptions.
    registry = HookRegistry()
    registry.register("custom_hook_for_my_team", lambda: None)


# ---------------------------------------------------------------------------
# Exception swallowing
# ---------------------------------------------------------------------------


def test_hook_exception_is_swallowed_for_lifecycle_hooks():
    registry = HookRegistry()

    def boom(_):
        raise RuntimeError("hook crashed")

    log = []
    registry.register("pre_run", boom)
    registry.register("pre_run", lambda _: log.append("survived"))

    # Must not propagate.
    registry.dispatch("pre_run", {})

    # Subsequent hooks still ran.
    assert log == ["survived"]


def test_hook_exception_in_post_run_is_swallowed():
    registry = HookRegistry()
    registry.register("post_run", lambda _: 1 / 0)
    # Must not propagate.
    registry.dispatch("post_run", {})


# ---------------------------------------------------------------------------
# on_error short-circuit
# ---------------------------------------------------------------------------


def test_on_error_returning_stop_short_circuits_dispatch():
    registry = HookRegistry()
    log = []

    def first(_):
        return STOP

    def second(_):
        log.append("ran")

    registry.register("on_error", first)
    registry.register("on_error", second)
    result = registry.dispatch("on_error", RuntimeError("x"))
    assert result is STOP
    assert log == []  # second never ran


def test_on_error_returning_none_does_not_short_circuit():
    registry = HookRegistry()
    log = []

    def first(_):
        return None  # explicit no-op signal

    def second(_):
        log.append("ran")

    registry.register("on_error", first)
    registry.register("on_error", second)
    result = registry.dispatch("on_error", RuntimeError("x"))
    assert result is None
    assert log == ["ran"]


def test_other_hooks_returning_stop_does_not_short_circuit():
    # STOP is privileged only on the on_error slot.
    registry = HookRegistry()
    log = []
    registry.register("pre_run", lambda _: STOP)
    registry.register("pre_run", lambda _: log.append("ran"))
    registry.dispatch("pre_run", {})
    assert log == ["ran"]


# ---------------------------------------------------------------------------
# Isolation between hook names
# ---------------------------------------------------------------------------


def test_hooks_for_different_names_are_independent():
    registry = HookRegistry()
    pre_log, post_log = [], []
    registry.register("pre_run", lambda _: pre_log.append("p"))
    registry.register("post_run", lambda _: post_log.append("q"))

    registry.dispatch("pre_run", "x")
    assert pre_log == ["p"]
    assert post_log == []

    registry.dispatch("post_run", "x")
    assert pre_log == ["p"]
    assert post_log == ["q"]
