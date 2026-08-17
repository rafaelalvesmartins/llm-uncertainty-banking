# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""LangChain callback handler for emitting uncertainty scores per chain node.

Banks adopting LangChain/LangGraph for agentic workflows need uncertainty
scores at each node without refactoring their chains. This handler plugs
into any LangChain chain via ``chain.invoke(input, config={"callbacks":
[LUBCallbackHandler(pipeline)]})`` and emits structured uncertainty
metadata per LLM call.

Usage::

    from langchain_openai import ChatOpenAI
    from lub.integrations.langchain import LUBCallbackHandler
    from lub.pipeline import UncertaintyPipeline

    pipe = UncertaintyPipeline.from_pretrained(
        model="gpt-4o", backend="openai", estimator="token_logprob",
    )
    handler = LUBCallbackHandler(pipeline=pipe)

    llm = ChatOpenAI(model="gpt-4o")
    result = llm.invoke("What is CET1?", config={"callbacks": [handler]})
    print(handler.last_result)  # UncertaintyResult

Requires: ``pip install langchain-core``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from lub.protocols import PipelineProto
    from lub.types import UncertaintyResult

_LOG = structlog.get_logger("lub.integrations.langchain")

# NOTE: we intentionally don't import langchain-core at module level and
# don't ship an ``_MISSING_MSG`` guard here - this handler implements the
# LangChain callback protocol via duck typing (see class docstring), so
# the library can be used without langchain-core installed as long as the
# *user's* code brings it in at the invocation boundary.


class LUBCallbackHandler:
    """LangChain callback handler that scores each LLM call with LUB.

    Stores the last uncertainty result in :attr:`last_result` and
    accumulates all results in :attr:`results` for batch inspection.

    This is a lightweight, synchronous handler that works with any
    LangChain ``BaseChatModel`` or ``BaseLLM``. It does NOT subclass
    ``BaseCallbackHandler`` to avoid the langchain-core import at
    module level — instead it implements the callback protocol via
    duck typing so the import is deferred to runtime.
    """

    def __init__(self, pipeline: PipelineProto) -> None:
        self.pipeline = pipeline
        self.results: list[UncertaintyResult] = []
        self.last_result: UncertaintyResult | None = None

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        """Called when LLM starts generating. Score each prompt."""
        for prompt in prompts:
            _LOG.debug("langchain.on_llm_start", prompt_len=len(prompt))
            try:
                result = self.pipeline.answer(prompt)
                self.results.append(result)
                self.last_result = result
                _LOG.debug(
                    "langchain.scored",
                    confidence=f"{result.confidence:.4f}",
                    should_refuse=result.should_refuse,
                )
            except Exception as exc:
                _LOG.warning("langchain.score_failed", error=str(exc))

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """Called when LLM finishes. No-op for now."""

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        """Called on LLM error. Log it."""
        _LOG.warning("langchain.llm_error", error=str(error))

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of all scored calls."""
        if not self.results:
            return {"n_calls": 0}
        confs = [r.confidence for r in self.results]
        refused = sum(1 for r in self.results if r.should_refuse)
        return {
            "n_calls": len(self.results),
            "mean_confidence": sum(confs) / len(confs),
            "min_confidence": min(confs),
            "max_confidence": max(confs),
            "n_refused": refused,
            "refusal_rate": refused / len(self.results),
        }


__all__ = ["LUBCallbackHandler"]
