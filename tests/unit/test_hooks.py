# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lub.orchestration.hooks import (
    HookContext,
    HookedPipeline,
    HookRegistry,
)
from lub.types import UncertaintyResult


@dataclass
class _FakePipeline:
    confidence: float = 0.6
    _answer_text: str = "fake"

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        return UncertaintyResult(answer=self._answer_text, confidence=self.confidence)


def test_pre_and_post_hooks_fire_in_order() -> None:
    reg = HookRegistry()
    order: list[str] = []
    reg.add_pre(lambda ctx: order.append("pre1"))
    reg.add_pre(lambda ctx: order.append("pre2"))
    reg.add_post(lambda ctx: order.append("post1"))
    reg.add_post(lambda ctx: order.append("post2"))

    pipe = HookedPipeline(_FakePipeline(), reg)
    pipe.answer("x")
    assert order == ["pre1", "pre2", "post1", "post2"]


def test_result_is_visible_to_post_hooks() -> None:
    reg = HookRegistry()
    captured: list[UncertaintyResult] = []
    reg.add_post(lambda ctx: captured.append(ctx.result) if ctx.result is not None else None)
    HookedPipeline(_FakePipeline(confidence=0.42), reg).answer("x")
    assert len(captured) == 1
    assert captured[0].confidence == 0.42


def test_pre_hooks_see_no_result() -> None:
    reg = HookRegistry()
    saw_result: list[bool] = []
    reg.add_pre(lambda ctx: saw_result.append(ctx.result is not None))
    HookedPipeline(_FakePipeline(), reg).answer("x")
    assert saw_result == [False]


def test_hook_exception_does_not_break_pipeline() -> None:
    reg = HookRegistry()

    def _bad(ctx: HookContext) -> None:
        raise RuntimeError("boom")

    reg.add_pre(_bad)
    reg.add_post(_bad)
    pipe = HookedPipeline(_FakePipeline(), reg)
    result = pipe.answer("x")  # must not raise
    assert result.confidence == 0.6


def test_shared_state_survives_between_hooks() -> None:
    reg = HookRegistry()
    reg.add_pre(lambda ctx: ctx.state.update(foo="bar"))
    seen: list[str | None] = []
    reg.add_post(lambda ctx: seen.append(ctx.state.get("foo")))
    HookedPipeline(_FakePipeline(), reg).answer("x")
    assert seen == ["bar"]
