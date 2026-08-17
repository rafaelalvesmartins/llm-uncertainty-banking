# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Minimal tests for lub.governance.adr."""

from __future__ import annotations

from pathlib import Path

import pytest

from lub.governance.adr import ADR, ADRRegistry, PolicyViolation, assert_policy
from lub.governance.contexts import BoundedContext
from lub.types import UncertaintyResult

ADR_TEXT = """\
---
status: accepted
owners: [rafael]
---
# Body

Body text here.
"""


def _write_adr(dir_: Path, name: str, text: str = ADR_TEXT) -> Path:
    p = dir_ / name
    p.write_text(text, encoding="utf-8")
    return p


def test_adr_from_path_parses_frontmatter_and_id(tmp_path: Path) -> None:
    path = _write_adr(tmp_path, "0001-pick-conformal.md")
    adr = ADR.from_path(path)
    assert adr.id == "0001"
    assert adr.title == "pick conformal"
    assert adr.metadata == {"status": "accepted", "owners": ["rafael"]}
    assert "Body text here." in adr.body


def test_adr_from_path_rejects_missing_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "0002-bad.md"
    path.write_text("no frontmatter here\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing YAML front-matter"):
        ADR.from_path(path)


def test_adr_from_path_rejects_bad_filename(tmp_path: Path) -> None:
    path = _write_adr(tmp_path, "not-numbered.md")
    with pytest.raises(ValueError, match="NNNN-title.md"):
        ADR.from_path(path)


def test_registry_loads_and_gets(tmp_path: Path) -> None:
    _write_adr(tmp_path, "0001-first.md")
    _write_adr(tmp_path, "0002-second.md")
    reg = ADRRegistry(tmp_path)
    assert set(reg.all().keys()) == {"0001", "0002"}
    assert reg.get("0001").title == "first"


def test_registry_get_missing_raises(tmp_path: Path) -> None:
    reg = ADRRegistry(tmp_path)
    with pytest.raises(KeyError):
        reg.get("9999")


def test_registry_all_returns_copy(tmp_path: Path) -> None:
    _write_adr(tmp_path, "0001-x.md")
    reg = ADRRegistry(tmp_path)
    snapshot = reg.all()
    snapshot.clear()
    assert "0001" in reg.all()


def test_registry_handles_missing_root(tmp_path: Path) -> None:
    reg = ADRRegistry(tmp_path / "does-not-exist")
    assert reg.all() == {}


def _ctx(**overrides: float) -> BoundedContext:
    base: dict[str, object] = {
        "name": "test-ctx",
        "domain": "test",
        "calibration_target_ece": 0.05,
        "risk_ceiling": 0.02,
    }
    base.update(overrides)
    return BoundedContext(**base)  # type: ignore[arg-type]


def test_assert_policy_accepts_when_confidence_above_floor() -> None:
    result = UncertaintyResult(answer="yes", confidence=0.99, should_refuse=False)
    assert_policy(result, _ctx(risk_ceiling=0.02))


def test_assert_policy_rejects_when_confidence_below_floor() -> None:
    result = UncertaintyResult(answer="yes", confidence=0.50, should_refuse=False)
    with pytest.raises(PolicyViolation, match="risk floor"):
        assert_policy(result, _ctx(risk_ceiling=0.02))


def test_assert_policy_skips_confidence_check_when_refusing() -> None:
    result = UncertaintyResult(answer="[ABSTAIN]", confidence=0.10, should_refuse=True)
    assert_policy(result, _ctx(risk_ceiling=0.02))


def test_assert_policy_rejects_when_measured_ece_exceeds_target() -> None:
    result = UncertaintyResult(answer="yes", confidence=0.99, should_refuse=False)
    with pytest.raises(PolicyViolation, match="measured ECE"):
        assert_policy(result, _ctx(calibration_target_ece=0.03), measured_ece=0.10)


def test_assert_policy_accepts_when_measured_ece_within_target() -> None:
    result = UncertaintyResult(answer="yes", confidence=0.99, should_refuse=False)
    assert_policy(result, _ctx(calibration_target_ece=0.05), measured_ece=0.04)
