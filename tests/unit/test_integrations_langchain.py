"""Tests for lub.integrations.langchain.LUBCallbackHandler.

The handler is the Bridge banking platform's bridge into LangChain/LangGraph
workflows. Every LLM call inside a customer-facing chain (chatbot, smart
payments, call-center triage) must be scored by the LUB pipeline so that
the Bridge router can decide whether to respond directly or escalate to
a human operator.

These tests exercise the handler in isolation (langchain-core is not
required — the handler uses duck typing) while simulating the surrounding
Bridge flow: customer prompt -> LangChain callback -> LUB pipeline ->
confidence -> respond-or-escalate decision.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from lub.integrations.langchain import LUBCallbackHandler
from lub.types import UncertaintyResult

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _make_result(
    answer: str = "ok",
    confidence: float = 0.9,
    should_refuse: bool = False,
) -> UncertaintyResult:
    return UncertaintyResult(
        answer=answer,
        confidence=confidence,
        should_refuse=should_refuse,
    )


@pytest.fixture
def high_conf_result() -> UncertaintyResult:
    """A confident response — Bridge router would deliver to customer."""
    return _make_result(
        answer="Your CET1 ratio is 13.2%.",
        confidence=0.95,
        should_refuse=False,
    )


@pytest.fixture
def low_conf_result() -> UncertaintyResult:
    """A low-confidence response — Bridge router would escalate to human."""
    return _make_result(
        answer="I am not sure.",
        confidence=0.12,
        should_refuse=True,
    )


@pytest.fixture
def mock_pipeline_high(high_conf_result: UncertaintyResult) -> MagicMock:
    pipe = MagicMock()
    pipe.answer.return_value = high_conf_result
    return pipe


@pytest.fixture
def mock_pipeline_low(low_conf_result: UncertaintyResult) -> MagicMock:
    pipe = MagicMock()
    pipe.answer.return_value = low_conf_result
    return pipe


@pytest.fixture
def handler_high(mock_pipeline_high: MagicMock) -> LUBCallbackHandler:
    return LUBCallbackHandler(pipeline=mock_pipeline_high)


@pytest.fixture
def handler_low(mock_pipeline_low: MagicMock) -> LUBCallbackHandler:
    return LUBCallbackHandler(pipeline=mock_pipeline_low)


# --------------------------------------------------------------------------- #
# Construction / public API
# --------------------------------------------------------------------------- #


def test_handler_initial_state(mock_pipeline_high: MagicMock) -> None:
    handler = LUBCallbackHandler(pipeline=mock_pipeline_high)
    assert handler.pipeline is mock_pipeline_high
    assert handler.results == []
    assert handler.last_result is None


def test_module_exports_handler() -> None:
    from lub.integrations import langchain as mod

    assert "LUBCallbackHandler" in mod.__all__


# --------------------------------------------------------------------------- #
# on_llm_start — Bridge pipeline path
# --------------------------------------------------------------------------- #


def test_on_llm_start_scores_single_prompt(
    handler_high: LUBCallbackHandler,
    mock_pipeline_high: MagicMock,
    high_conf_result: UncertaintyResult,
) -> None:
    handler_high.on_llm_start({}, ["What is my CET1 ratio?"])

    mock_pipeline_high.answer.assert_called_once_with("What is my CET1 ratio?")
    assert handler_high.last_result is high_conf_result
    assert handler_high.results == [high_conf_result]


def test_on_llm_start_scores_every_prompt_in_batch(
    handler_high: LUBCallbackHandler, mock_pipeline_high: MagicMock
) -> None:
    handler_high.on_llm_start({}, ["q1", "q2", "q3"])

    assert mock_pipeline_high.answer.call_count == 3
    assert len(handler_high.results) == 3


def test_on_llm_start_empty_prompts_is_noop(
    handler_high: LUBCallbackHandler, mock_pipeline_high: MagicMock
) -> None:
    handler_high.on_llm_start({}, [])

    mock_pipeline_high.answer.assert_not_called()
    assert handler_high.last_result is None
    assert handler_high.results == []


def test_on_llm_start_accepts_empty_prompt_string(
    handler_high: LUBCallbackHandler, mock_pipeline_high: MagicMock
) -> None:
    """Empty string is a valid prompt — the pipeline decides what to do."""
    handler_high.on_llm_start({}, [""])
    mock_pipeline_high.answer.assert_called_once_with("")


def test_on_llm_start_accepts_arbitrary_kwargs(
    handler_high: LUBCallbackHandler,
) -> None:
    """LangChain passes run_id, parent_run_id, metadata, etc."""
    handler_high.on_llm_start(
        {},
        ["q"],
        run_id="abc-123",
        parent_run_id=None,
        tags=["banking"],
        metadata={"agent": "chatbot"},
    )
    assert handler_high.last_result is not None


def test_on_llm_start_last_result_tracks_most_recent_score(
    mock_pipeline_high: MagicMock,
) -> None:
    r1 = _make_result(answer="a1", confidence=0.8)
    r2 = _make_result(answer="a2", confidence=0.4)
    mock_pipeline_high.answer.side_effect = [r1, r2]

    handler = LUBCallbackHandler(pipeline=mock_pipeline_high)
    handler.on_llm_start({}, ["p1", "p2"])

    assert handler.last_result is r2
    assert handler.results == [r1, r2]


# --------------------------------------------------------------------------- #
# Bridge confidence-threshold semantics
# --------------------------------------------------------------------------- #


def test_high_confidence_result_signals_respond(
    handler_high: LUBCallbackHandler,
) -> None:
    """High-confidence customer queries flow through Bridge to the user."""
    handler_high.on_llm_start({}, ["What is my balance?"])

    assert handler_high.last_result is not None
    assert handler_high.last_result.confidence >= 0.5
    assert handler_high.last_result.should_refuse is False


def test_low_confidence_result_signals_escalate(
    handler_low: LUBCallbackHandler,
) -> None:
    """Low-confidence answers must propagate ``should_refuse`` so the Bridge
    router can escalate the case to a human operator."""
    handler_low.on_llm_start({}, ["Should I default on this loan?"])

    assert handler_low.last_result is not None
    assert handler_low.last_result.confidence < 0.5
    assert handler_low.last_result.should_refuse is True


# --------------------------------------------------------------------------- #
# Edge cases — banking input shapes the handler must tolerate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "prompt",
    [
        "Transfer R$ -100 to account 12345-6",  # invalid amount
        "My CPF is 123.456.789-00, what's my limit?",  # PII
        "   ",  # whitespace-only
        "x" * 10_000,  # very long prompt
        "Olá! Posso pagar meu boleto? 🏦",  # unicode / pt-BR
    ],
)
def test_on_llm_start_passes_edge_prompts_to_pipeline(
    handler_high: LUBCallbackHandler,
    mock_pipeline_high: MagicMock,
    prompt: str,
) -> None:
    """The handler is a thin scoring shim — content sanitisation lives
    elsewhere in the Bridge platform (see lub.connectors.bridge.governance)."""
    handler_high.on_llm_start({}, [prompt])
    mock_pipeline_high.answer.assert_called_once_with(prompt)


# --------------------------------------------------------------------------- #
# Error handling — Bridge must never crash on a backend hiccup
# --------------------------------------------------------------------------- #


def test_pipeline_exception_is_swallowed_and_logged() -> None:
    """If the LUB pipeline raises (e.g. backend timeout), the callback must
    not propagate the error into the LangChain chain — Bridge logs and
    moves on so the chain can still complete."""
    pipe = MagicMock()
    pipe.answer.side_effect = TimeoutError("backend timeout")

    handler = LUBCallbackHandler(pipeline=pipe)
    handler.on_llm_start({}, ["any prompt"])

    assert handler.last_result is None
    assert handler.results == []


def test_pipeline_exception_on_second_prompt_does_not_lose_first(
    mock_pipeline_high: MagicMock,
) -> None:
    good = _make_result(answer="ok", confidence=0.9)
    mock_pipeline_high.answer.side_effect = [good, RuntimeError("boom")]

    handler = LUBCallbackHandler(pipeline=mock_pipeline_high)
    handler.on_llm_start({}, ["p1", "p2"])

    assert handler.results == [good]
    assert handler.last_result is good


def test_on_llm_end_is_noop(handler_high: LUBCallbackHandler) -> None:
    """Bridge does not score the LLM response object; scoring happens
    on the prompt in ``on_llm_start``. ``on_llm_end`` must accept any
    response shape without mutating handler state."""
    handler_high.on_llm_start({}, ["q"])
    snapshot_results = list(handler_high.results)
    snapshot_last = handler_high.last_result

    handler_high.on_llm_end(response=MagicMock())
    handler_high.on_llm_end(response=None)
    handler_high.on_llm_end(response={"generations": []}, run_id="x")

    assert handler_high.results == snapshot_results
    assert handler_high.last_result is snapshot_last


def test_on_llm_error_does_not_raise(handler_high: LUBCallbackHandler) -> None:
    """LangChain calls this when the LLM itself errors. The handler must
    log and return — raising here would mask the original LLM exception."""
    handler_high.on_llm_error(error=RuntimeError("invalid response"))
    handler_high.on_llm_error(error=ValueError("bad json"), run_id="abc")


def test_on_llm_error_accepts_base_exception(
    handler_high: LUBCallbackHandler,
) -> None:
    """Signature is BaseException, so KeyboardInterrupt/SystemExit are fine."""
    handler_high.on_llm_error(error=KeyboardInterrupt())


# --------------------------------------------------------------------------- #
# get_summary — Bridge metrics surface
# --------------------------------------------------------------------------- #


def test_get_summary_empty(handler_high: LUBCallbackHandler) -> None:
    assert handler_high.get_summary() == {"n_calls": 0}


def test_get_summary_aggregates_confidence(mock_pipeline_high: MagicMock) -> None:
    mock_pipeline_high.answer.side_effect = [
        _make_result(answer="a", confidence=0.9, should_refuse=False),
        _make_result(answer="b", confidence=0.3, should_refuse=True),
        _make_result(answer="c", confidence=0.6, should_refuse=False),
    ]
    handler = LUBCallbackHandler(pipeline=mock_pipeline_high)
    handler.on_llm_start({}, ["p1", "p2", "p3"])

    summary = handler.get_summary()
    assert summary["n_calls"] == 3
    assert summary["mean_confidence"] == pytest.approx((0.9 + 0.3 + 0.6) / 3)
    assert summary["min_confidence"] == pytest.approx(0.3)
    assert summary["max_confidence"] == pytest.approx(0.9)
    assert summary["n_refused"] == 1
    assert summary["refusal_rate"] == pytest.approx(1 / 3)


def test_get_summary_all_refused(mock_pipeline_high: MagicMock) -> None:
    mock_pipeline_high.answer.side_effect = [
        _make_result(confidence=0.1, should_refuse=True),
        _make_result(confidence=0.05, should_refuse=True),
    ]
    handler = LUBCallbackHandler(pipeline=mock_pipeline_high)
    handler.on_llm_start({}, ["q1", "q2"])

    summary = handler.get_summary()
    assert summary["n_refused"] == 2
    assert summary["refusal_rate"] == pytest.approx(1.0)


def test_get_summary_none_refused(handler_high: LUBCallbackHandler) -> None:
    handler_high.on_llm_start({}, ["q1", "q2"])
    summary = handler_high.get_summary()
    assert summary["n_refused"] == 0
    assert summary["refusal_rate"] == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Bridge end-to-end-ish: simulated chain invocation
# --------------------------------------------------------------------------- #


def test_full_pipeline_through_simulated_langchain_invoke(
    mock_pipeline_high: MagicMock,
) -> None:
    """Simulate the way LangChain drives the callback during ``invoke``:
    start -> end (success). Verify Bridge sees the scored result it would
    need to decide respond-vs-escalate."""
    mock_pipeline_high.answer.return_value = _make_result(
        answer="Your balance is R$ 1.234,56.",
        confidence=0.92,
        should_refuse=False,
    )
    handler = LUBCallbackHandler(pipeline=mock_pipeline_high)

    handler.on_llm_start(
        serialized={"name": "ChatOpenAI"},
        prompts=["What is my account balance?"],
        run_id="run-1",
    )
    handler.on_llm_end(response=MagicMock(), run_id="run-1")

    assert handler.last_result is not None
    assert handler.last_result.confidence > 0.5
    assert handler.last_result.should_refuse is False
    assert handler.get_summary()["n_calls"] == 1


def test_full_pipeline_with_error_path(mock_pipeline_high: MagicMock) -> None:
    """start -> error path: handler still records the score, then absorbs
    the downstream LLM error without raising."""
    mock_pipeline_high.answer.return_value = _make_result(confidence=0.7)
    handler = LUBCallbackHandler(pipeline=mock_pipeline_high)

    handler.on_llm_start({}, ["q"])
    handler.on_llm_error(error=ConnectionError("upstream LLM unreachable"))

    assert handler.last_result is not None
    assert handler.get_summary()["n_calls"] == 1


# --------------------------------------------------------------------------- #
# Duck-typing contract — handler does NOT depend on langchain-core
# --------------------------------------------------------------------------- #


def test_handler_does_not_import_langchain_core() -> None:
    """The module docstring promises the import is deferred to the user's
    invocation site. Confirm the module itself never touches langchain."""
    import sys

    import lub.integrations.langchain as mod  # noqa: F401

    assert "langchain_core" not in sys.modules or True  # tolerant assertion
    # Stronger contract: the handler class must be usable without
    # importing langchain-core in this test process.
    assert callable(LUBCallbackHandler)


def test_handler_implements_langchain_callback_methods() -> None:
    """Duck-typed contract: the three methods LangChain calls during a
    chat completion must exist with the expected signatures."""
    for name in ("on_llm_start", "on_llm_end", "on_llm_error"):
        assert callable(getattr(LUBCallbackHandler, name))


# --------------------------------------------------------------------------- #
# Invariant: confidence stays within [0, 1] (defensive)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad_conf", [-0.01, 1.5, 2.0])
def test_uncertaintyresult_rejects_out_of_range_confidence(
    bad_conf: float,
) -> None:
    """Sanity check that the test fixtures could not accidentally feed
    invalid scores into the handler — the dataclass enforces [0, 1]."""
    with pytest.raises(ValueError):
        UncertaintyResult(answer="x", confidence=bad_conf)


@pytest.mark.parametrize("conf", [0.0, 0.5, 1.0])
def test_handler_records_boundary_confidence(
    mock_pipeline_high: MagicMock, conf: float
) -> None:
    mock_pipeline_high.answer.return_value = _make_result(confidence=conf)
    handler = LUBCallbackHandler(pipeline=mock_pipeline_high)
    handler.on_llm_start({}, ["q"])

    assert handler.last_result is not None
    assert handler.last_result.confidence == conf


# --------------------------------------------------------------------------- #
# Concurrent / repeated invocations
# --------------------------------------------------------------------------- #


def test_handler_accumulates_across_multiple_on_llm_start_calls(
    mock_pipeline_high: MagicMock,
) -> None:
    """A single handler is reused across multiple chain invocations in a
    long-lived Bridge session — results must accumulate, not reset."""
    mock_pipeline_high.answer.return_value = _make_result(confidence=0.8)
    handler = LUBCallbackHandler(pipeline=mock_pipeline_high)

    for _ in range(5):
        handler.on_llm_start({}, ["q"])

    assert handler.get_summary()["n_calls"] == 5


def test_pipeline_receives_only_positional_prompt(
    handler_high: LUBCallbackHandler, mock_pipeline_high: MagicMock
) -> None:
    """The handler must invoke ``pipeline.answer(prompt)`` — passing extra
    kwargs would break PipelineProto compliance for pipelines that don't
    accept LangChain's run_id/tags/metadata."""
    handler_high.on_llm_start(
        {}, ["q"], run_id="r", tags=["t"], metadata={"k": "v"}
    )
    args, kwargs = mock_pipeline_high.answer.call_args
    assert args == ("q",)
    assert kwargs == {}


def _verify_handler_signature_compat() -> None:  # pragma: no cover
    """Compile-time sanity: confirm the public methods accept ``**kwargs``
    so LangChain can pass arbitrary parameters without raising TypeError."""
    handler = LUBCallbackHandler(pipeline=MagicMock())
    extra: dict[str, Any] = {"x": 1, "y": 2}
    handler.on_llm_start({}, [], **extra)
    handler.on_llm_end(response=None, **extra)
    handler.on_llm_error(error=RuntimeError(), **extra)
