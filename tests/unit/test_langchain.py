# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for lub.integrations.langchain.LUBCallbackHandler."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from lub.integrations.langchain import LUBCallbackHandler

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class FakeResult:
    """Minimal stand-in for lub.types.UncertaintyResult."""

    confidence: float
    should_refuse: bool
    answer: str = ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def high_confidence_result() -> FakeResult:
    return FakeResult(confidence=0.95, should_refuse=False, answer="CET1 is...")


@pytest.fixture
def low_confidence_result() -> FakeResult:
    return FakeResult(confidence=0.12, should_refuse=True, answer="")


@pytest.fixture
def mock_pipeline(high_confidence_result: FakeResult) -> MagicMock:
    pipe = MagicMock()
    pipe.answer.return_value = high_confidence_result
    return pipe


@pytest.fixture
def handler(mock_pipeline: MagicMock) -> LUBCallbackHandler:
    return LUBCallbackHandler(pipeline=mock_pipeline)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    def test_default_state(self, mock_pipeline: MagicMock) -> None:
        h = LUBCallbackHandler(pipeline=mock_pipeline)
        assert h.pipeline is mock_pipeline
        assert h.results == []
        assert h.last_result is None

    def test_each_handler_has_independent_state(
        self, mock_pipeline: MagicMock
    ) -> None:
        h1 = LUBCallbackHandler(pipeline=mock_pipeline)
        h2 = LUBCallbackHandler(pipeline=mock_pipeline)
        h1.results.append(FakeResult(confidence=0.5, should_refuse=False))
        assert h2.results == []


# ---------------------------------------------------------------------------
# on_llm_start — the core scoring path
# ---------------------------------------------------------------------------


class TestOnLLMStart:
    def test_scores_single_prompt(
        self,
        handler: LUBCallbackHandler,
        mock_pipeline: MagicMock,
        high_confidence_result: FakeResult,
    ) -> None:
        handler.on_llm_start({"name": "ChatOpenAI"}, ["What is CET1 capital?"])
        mock_pipeline.answer.assert_called_once_with("What is CET1 capital?")
        assert handler.results == [high_confidence_result]
        assert handler.last_result is high_confidence_result

    def test_scores_multiple_prompts(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        prompts = ["q1", "q2", "q3"]
        handler.on_llm_start({}, prompts)
        assert mock_pipeline.answer.call_count == 3
        assert [c.args[0] for c in mock_pipeline.answer.call_args_list] == prompts
        assert len(handler.results) == 3

    def test_empty_prompts_list_is_noop(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        handler.on_llm_start({}, [])
        mock_pipeline.answer.assert_not_called()
        assert handler.last_result is None
        assert handler.results == []

    def test_empty_string_prompt_still_scored(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        handler.on_llm_start({}, [""])
        mock_pipeline.answer.assert_called_once_with("")
        assert handler.last_result is not None

    def test_last_result_reflects_last_prompt(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        seq = [
            FakeResult(confidence=0.9, should_refuse=False),
            FakeResult(confidence=0.3, should_refuse=True),
        ]
        mock_pipeline.answer.side_effect = seq
        handler.on_llm_start({}, ["first", "second"])
        assert handler.last_result is seq[1]
        assert handler.results == seq

    def test_accepts_extra_kwargs(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        # LangChain forwards run_id, tags, parent_run_id, metadata, etc.
        handler.on_llm_start(
            {"name": "ChatOpenAI"},
            ["query"],
            run_id="abc-123",
            parent_run_id=None,
            tags=["banking"],
            metadata={"customer_id": "X"},
        )
        mock_pipeline.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_pipeline_exception_is_swallowed(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        mock_pipeline.answer.side_effect = RuntimeError("backend timeout")
        # Must not raise — callbacks should never break the host chain.
        handler.on_llm_start({}, ["query"])
        assert handler.results == []
        assert handler.last_result is None

    def test_partial_failure_continues_processing(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        ok1 = FakeResult(confidence=0.8, should_refuse=False)
        ok2 = FakeResult(confidence=0.7, should_refuse=False)
        mock_pipeline.answer.side_effect = [ok1, RuntimeError("transient"), ok2]
        handler.on_llm_start({}, ["a", "b", "c"])
        assert handler.results == [ok1, ok2]
        assert handler.last_result is ok2

    def test_value_error_from_pipeline(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        mock_pipeline.answer.side_effect = ValueError("invalid response shape")
        handler.on_llm_start({}, ["q"])
        assert handler.results == []

    def test_on_llm_error_does_not_raise(
        self, handler: LUBCallbackHandler
    ) -> None:
        handler.on_llm_error(RuntimeError("API down"))
        handler.on_llm_error(ValueError("bad"), run_id="abc")
        # No mutation, no exception
        assert handler.results == []


# ---------------------------------------------------------------------------
# on_llm_end — pure no-op
# ---------------------------------------------------------------------------


class TestOnLLMEnd:
    def test_does_not_mutate_state(self, handler: LUBCallbackHandler) -> None:
        handler.on_llm_end({"generations": [[{"text": "hello"}]]})
        assert handler.results == []
        assert handler.last_result is None

    def test_accepts_kwargs(self, handler: LUBCallbackHandler) -> None:
        handler.on_llm_end({}, run_id="abc-123")


# ---------------------------------------------------------------------------
# get_summary — aggregate confidence / refusal stats
# ---------------------------------------------------------------------------


class TestGetSummary:
    def test_empty(self, handler: LUBCallbackHandler) -> None:
        assert handler.get_summary() == {"n_calls": 0}

    def test_all_high_confidence(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        mock_pipeline.answer.side_effect = [
            FakeResult(confidence=0.90, should_refuse=False),
            FakeResult(confidence=0.85, should_refuse=False),
        ]
        handler.on_llm_start({}, ["a", "b"])
        s = handler.get_summary()
        assert s["n_calls"] == 2
        assert s["mean_confidence"] == pytest.approx(0.875)
        assert s["min_confidence"] == pytest.approx(0.85)
        assert s["max_confidence"] == pytest.approx(0.90)
        assert s["n_refused"] == 0
        assert s["refusal_rate"] == 0.0

    def test_mixed_confidence(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        mock_pipeline.answer.side_effect = [
            FakeResult(confidence=0.1, should_refuse=True),
            FakeResult(confidence=0.9, should_refuse=False),
            FakeResult(confidence=0.2, should_refuse=True),
        ]
        handler.on_llm_start({}, ["a", "b", "c"])
        s = handler.get_summary()
        assert s["n_calls"] == 3
        assert s["n_refused"] == 2
        assert s["refusal_rate"] == pytest.approx(2 / 3)
        assert s["min_confidence"] == pytest.approx(0.1)
        assert s["max_confidence"] == pytest.approx(0.9)
        assert s["mean_confidence"] == pytest.approx((0.1 + 0.9 + 0.2) / 3)

    def test_all_refused(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        mock_pipeline.answer.side_effect = [
            FakeResult(confidence=0.1, should_refuse=True),
            FakeResult(confidence=0.05, should_refuse=True),
        ]
        handler.on_llm_start({}, ["a", "b"])
        s = handler.get_summary()
        assert s["refusal_rate"] == 1.0
        assert s["n_refused"] == 2

    def test_single_call(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        mock_pipeline.answer.return_value = FakeResult(
            confidence=0.42, should_refuse=False
        )
        handler.on_llm_start({}, ["q"])
        s = handler.get_summary()
        assert s["n_calls"] == 1
        assert s["mean_confidence"] == pytest.approx(0.42)
        assert s["min_confidence"] == pytest.approx(0.42)
        assert s["max_confidence"] == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# Banking scenarios — confidence thresholds drive escalation
# ---------------------------------------------------------------------------


class TestBankingScenarios:
    def test_low_confidence_marks_refusal(
        self,
        handler: LUBCallbackHandler,
        mock_pipeline: MagicMock,
        low_confidence_result: FakeResult,
    ) -> None:
        mock_pipeline.answer.return_value = low_confidence_result
        handler.on_llm_start({}, ["Should I invest in this crypto?"])
        assert handler.last_result is not None
        assert handler.last_result.should_refuse is True
        assert handler.last_result.confidence < 0.5

    def test_high_confidence_passes_through(
        self,
        handler: LUBCallbackHandler,
        mock_pipeline: MagicMock,
        high_confidence_result: FakeResult,
    ) -> None:
        mock_pipeline.answer.return_value = high_confidence_result
        handler.on_llm_start({}, ["What is the CET1 ratio?"])
        assert handler.last_result is not None
        assert handler.last_result.should_refuse is False
        assert handler.last_result.confidence > 0.9

    def test_pii_query_is_scored_not_filtered_by_handler(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        # The handler does NOT filter PII — it delegates to the pipeline.
        # Here we assert it forwards the prompt verbatim.
        prompt = "My CPF is 123.456.789-00, transfer R$1000 to account X"
        mock_pipeline.answer.return_value = FakeResult(
            confidence=0.15, should_refuse=True
        )
        handler.on_llm_start({}, [prompt])
        mock_pipeline.answer.assert_called_once_with(prompt)
        assert handler.last_result.should_refuse is True

    def test_invalid_amount_query_handled_gracefully(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        # Garbage prompt — pipeline returns low confidence, no crash.
        mock_pipeline.answer.return_value = FakeResult(
            confidence=0.05, should_refuse=True
        )
        handler.on_llm_start({}, ["transfer -$NaN to ???"])
        s = handler.get_summary()
        assert s["n_refused"] == 1
        assert s["refusal_rate"] == 1.0

    def test_batch_of_mixed_banking_queries(
        self, handler: LUBCallbackHandler, mock_pipeline: MagicMock
    ) -> None:
        # Simulate a batch where some queries are clear, others need escalation.
        mock_pipeline.answer.side_effect = [
            FakeResult(confidence=0.97, should_refuse=False),  # "what is Pix?"
            FakeResult(confidence=0.30, should_refuse=True),   # "should I invest?"
            FakeResult(confidence=0.88, should_refuse=False),  # "show balance"
        ]
        handler.on_llm_start(
            {},
            [
                "What is Pix?",
                "Should I move my savings into stocks?",
                "Show my checking account balance",
            ],
        )
        s = handler.get_summary()
        assert s["n_calls"] == 3
        assert s["n_refused"] == 1
        assert s["refusal_rate"] == pytest.approx(1 / 3)
        assert s["max_confidence"] == pytest.approx(0.97)
        assert s["min_confidence"] == pytest.approx(0.30)
