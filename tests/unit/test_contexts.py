# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for ``lub.governance.contexts``."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lub.governance.contexts import (
    DEFAULT_CONTEXTS,
    BoundedContext,
    ContextRegistry,
    default_registry,
)


@pytest.fixture
def sample_context() -> BoundedContext:
    """Return a representative bounded context for tests."""
    return BoundedContext(
        name="test-ctx",
        domain="test-domain",
        calibration_target_ece=0.04,
        coverage_target=0.9,
        risk_ceiling=0.02,
        tier_order=["haiku", "sonnet"],
    )


@pytest.fixture
def empty_registry() -> ContextRegistry:
    """Return a fresh, empty ContextRegistry."""
    return ContextRegistry()


class TestBoundedContext:
    def test_construct_with_required_fields_uses_defaults(self) -> None:
        ctx = BoundedContext(name="x", domain="y")
        assert ctx.name == "x"
        assert ctx.domain == "y"
        assert ctx.calibration_target_ece == 0.05
        assert ctx.coverage_target == 0.80
        assert ctx.risk_ceiling == 0.02
        assert ctx.tier_order == []
        assert ctx.abstain_marker == "[ABSTAIN]"

    def test_construct_with_all_fields(self, sample_context: BoundedContext) -> None:
        assert sample_context.name == "test-ctx"
        assert sample_context.tier_order == ["haiku", "sonnet"]
        assert sample_context.calibration_target_ece == 0.04

    def test_is_frozen(self, sample_context: BoundedContext) -> None:
        with pytest.raises(ValidationError):
            sample_context.name = "mutated"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            BoundedContext(name="x", domain="y", unknown_field=1)  # type: ignore[call-arg]

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BoundedContext(name="", domain="y")

    def test_empty_domain_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BoundedContext(name="x", domain="")

    @pytest.mark.parametrize(
        "field,value",
        [
            ("calibration_target_ece", -0.1),
            ("calibration_target_ece", 1.5),
            ("coverage_target", -0.01),
            ("coverage_target", 1.01),
            ("risk_ceiling", -0.1),
            ("risk_ceiling", 2.0),
        ],
    )
    def test_out_of_range_floats_rejected(self, field: str, value: float) -> None:
        kwargs: dict[str, object] = {"name": "x", "domain": "y", field: value}
        with pytest.raises(ValidationError):
            BoundedContext(**kwargs)  # type: ignore[arg-type]

    def test_custom_abstain_marker(self) -> None:
        ctx = BoundedContext(name="x", domain="y", abstain_marker="NÃO SEI")
        assert ctx.abstain_marker == "NÃO SEI"


class TestContextRegistry:
    def test_register_and_get(
        self, empty_registry: ContextRegistry, sample_context: BoundedContext
    ) -> None:
        empty_registry.register(sample_context)
        assert empty_registry.get("test-ctx") is sample_context

    def test_register_duplicate_raises(
        self, empty_registry: ContextRegistry, sample_context: BoundedContext
    ) -> None:
        empty_registry.register(sample_context)
        with pytest.raises(ValueError, match="already registered"):
            empty_registry.register(sample_context)

    def test_get_missing_raises_keyerror(self, empty_registry: ContextRegistry) -> None:
        with pytest.raises(KeyError, match="No BoundedContext registered"):
            empty_registry.get("nonexistent")

    def test_all_returns_shallow_copy(
        self, empty_registry: ContextRegistry, sample_context: BoundedContext
    ) -> None:
        empty_registry.register(sample_context)
        snapshot = empty_registry.all()
        assert snapshot == {"test-ctx": sample_context}
        snapshot.clear()
        assert empty_registry.get("test-ctx") is sample_context

    def test_all_empty(self, empty_registry: ContextRegistry) -> None:
        assert empty_registry.all() == {}

    def test_to_dict_serializes_all(
        self, empty_registry: ContextRegistry, sample_context: BoundedContext
    ) -> None:
        empty_registry.register(sample_context)
        dumped = empty_registry.to_dict()
        assert "test-ctx" in dumped
        assert dumped["test-ctx"]["name"] == "test-ctx"
        assert dumped["test-ctx"]["tier_order"] == ["haiku", "sonnet"]
        assert dumped["test-ctx"]["calibration_target_ece"] == 0.04

    def test_to_dict_empty(self, empty_registry: ContextRegistry) -> None:
        assert empty_registry.to_dict() == {}

    def test_register_multiple_distinct(self, empty_registry: ContextRegistry) -> None:
        a = BoundedContext(name="a", domain="da")
        b = BoundedContext(name="b", domain="db")
        empty_registry.register(a)
        empty_registry.register(b)
        assert set(empty_registry.all().keys()) == {"a", "b"}


class TestDefaultContexts:
    def test_default_contexts_count(self) -> None:
        assert len(DEFAULT_CONTEXTS) == 4

    def test_default_context_names(self) -> None:
        names = {c.name for c in DEFAULT_CONTEXTS}
        assert names == {
            "regulatory-qa",
            "retail-credit",
            "fraud-alerts",
            "investor-advisory",
        }

    def test_regulatory_qa_is_strictest(self) -> None:
        by_name = {c.name: c for c in DEFAULT_CONTEXTS}
        reg = by_name["regulatory-qa"]
        fraud = by_name["fraud-alerts"]
        assert reg.calibration_target_ece < fraud.calibration_target_ece
        assert reg.risk_ceiling < fraud.risk_ceiling
        assert reg.coverage_target < fraud.coverage_target

    def test_all_default_contexts_have_tier_order(self) -> None:
        for ctx in DEFAULT_CONTEXTS:
            assert len(ctx.tier_order) >= 1
            assert "haiku" in ctx.tier_order


class TestDefaultRegistry:
    def test_default_registry_populated(self) -> None:
        reg = default_registry()
        assert len(reg.all()) == 4

    def test_default_registry_contains_canonical_contexts(self) -> None:
        reg = default_registry()
        for ctx in DEFAULT_CONTEXTS:
            assert reg.get(ctx.name) == ctx

    def test_default_registry_returns_independent_instances(self) -> None:
        reg1 = default_registry()
        reg2 = default_registry()
        assert reg1 is not reg2
        reg1.register(BoundedContext(name="extra", domain="d"))
        with pytest.raises(KeyError):
            reg2.get("extra")
