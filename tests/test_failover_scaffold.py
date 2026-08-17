# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Scaffold-state tests for FailoverChain.

The class is in NotImplementedError state per pass 23 (spec
planning/25_Ruflo_Patterns_Audit_2026-04-25.md §3.1). These tests
lock the API shape so v0.3.x implementation can swap stubs for real
behavior without renaming public symbols.
"""

from __future__ import annotations

import pytest

from lub.orchestration import (
    FailoverChain,
    FailoverExhausted,
    Tier,
    TieredRouter,
)


class _SentinelPipeline:
    """Minimal stand-in for an UncertaintyPipeline; not used in stub-only tests."""

    def answer(self, prompt: str, **kwargs) -> None:
        raise NotImplementedError("Sentinel pipeline - not a real backend")


def _stub_router() -> TieredRouter:
    """Build a TieredRouter with one fake tier — enough to satisfy ctor."""
    return TieredRouter(
        tiers=[
            Tier(name="dummy", pipeline=_SentinelPipeline(), threshold=0.5, cost=0.0),
        ],
    )


def test_failover_exhausted_is_a_runtime_error():
    """FailoverExhausted should be a RuntimeError subclass for catch compatibility."""
    assert issubclass(FailoverExhausted, RuntimeError)


def test_failover_chain_requires_at_least_one_router():
    with pytest.raises(ValueError, match="at least one router"):
        FailoverChain(routers=[])


def test_failover_chain_constructor_accepts_one_router():
    chain = FailoverChain(routers=[_stub_router()])
    assert chain is not None


def test_failover_chain_answer_raises_not_implemented():
    """NotImplementedError is NOT transient, so it propagates directly
    through the FailoverChain without triggering failover."""
    chain = FailoverChain(routers=[_stub_router()])
    with pytest.raises(NotImplementedError, match=r"Sentinel pipeline"):
        chain.answer("What is the Basel III CET1 ratio?")


def test_failover_chain_batch_raises_not_implemented():
    """batch() delegates to answer() per prompt; NotImplementedError propagates."""
    chain = FailoverChain(routers=[_stub_router(), _stub_router()])
    with pytest.raises(NotImplementedError, match=r"Sentinel pipeline"):
        chain.batch(["q1", "q2"])
