# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from lub.governance import (
    ADR,
    ADRRegistry,
    BoundedContext,
    ContextRegistry,
    PolicyViolation,
    assert_policy,
)
from lub.governance.contexts import default_registry
from lub.types import UncertaintyResult


def test_default_registry_has_four_contexts() -> None:
    reg = default_registry()
    names = set(reg.all().keys())
    assert names == {"regulatory-qa", "retail-credit", "fraud-alerts", "investor-advisory"}


def test_context_registration_is_duplicate_safe() -> None:
    reg = ContextRegistry()
    c = BoundedContext(name="x", domain="x")
    reg.register(c)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(c)


def test_assert_policy_accepts_confident_answer() -> None:
    ctx = BoundedContext(name="t", domain="t", risk_ceiling=0.05)
    res = UncertaintyResult(answer="x", confidence=0.98, should_refuse=False)
    assert_policy(res, ctx)  # must not raise


def test_assert_policy_rejects_low_confidence_accept() -> None:
    ctx = BoundedContext(name="t", domain="t", risk_ceiling=0.05)  # floor 0.95
    res = UncertaintyResult(answer="x", confidence=0.5, should_refuse=False)
    with pytest.raises(PolicyViolation, match="risk floor"):
        assert_policy(res, ctx)


def test_assert_policy_accepts_refusal_even_if_low_confidence() -> None:
    ctx = BoundedContext(name="t", domain="t", risk_ceiling=0.01)
    res = UncertaintyResult(answer="x", confidence=0.1, should_refuse=True)
    assert_policy(res, ctx)  # refused, no violation


def test_assert_policy_raises_on_ece_breach() -> None:
    ctx = BoundedContext(name="t", domain="t", calibration_target_ece=0.05)
    res = UncertaintyResult(answer="x", confidence=0.99, should_refuse=False)
    with pytest.raises(PolicyViolation, match="ECE"):
        assert_policy(res, ctx, measured_ece=0.10)


def test_adr_loads_from_markdown_file() -> None:
    body = """---
id: "0042"
title: "Test ADR"
status: accepted
---

# ADR 0042 — Test ADR

Body content.
"""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "0042-test-adr.md"
        p.write_text(body, encoding="utf-8")
        adr = ADR.from_path(p)
        assert adr.id == "0042"
        assert adr.metadata["title"] == "Test ADR"
        assert "Body content" in adr.body


def test_adr_registry_loads_directory() -> None:
    body1 = '---\nid: "0001"\ntitle: "A"\n---\n\n# A\n'
    body2 = '---\nid: "0002"\ntitle: "B"\n---\n\n# B\n'
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "0001-a.md").write_text(body1, encoding="utf-8")
        (root / "0002-b.md").write_text(body2, encoding="utf-8")
        reg = ADRRegistry(root)
        assert set(reg.all().keys()) == {"0001", "0002"}


def test_adr_rejects_missing_frontmatter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "0001-bad.md"
        p.write_text("no frontmatter here\n", encoding="utf-8")
        with pytest.raises(ValueError, match="front-matter"):
            ADR.from_path(p)


def test_adr_rejects_bad_filename() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "badname.md"
        p.write_text('---\nid: "0001"\ntitle: "x"\n---\n\nbody\n', encoding="utf-8")
        with pytest.raises(ValueError, match="NNNN-title"):
            ADR.from_path(p)
