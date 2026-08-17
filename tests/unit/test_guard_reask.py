# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Exhaustive tests for the REASK policy path in UncertaintyGuard.

Covers every branch of ``_handle_reask()`` plus interactions with
``gated_tool_call()`` and custom ``abstain_marker``.
"""

from __future__ import annotations

from typing import Any

import pytest

from lub.guard import DEFAULT_ABSTAIN_MARKER, GuardResult, UncertaintyGuard
from lub.policies import PolicyDecision
from lub.types import UncertaintyResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SequencePipeline:
    """Pipeline that returns a different confidence on each call.

    ``confidences`` is consumed in order; extra calls recycle the last value.
    Records every prompt it receives so tests can inspect what REASK sent.
    """

    def __init__(self, confidences: list[float]) -> None:
        self._confidences = list(confidences)
        self._idx = 0
        self.prompts: list[str] = []

    def answer(self, prompt: str, **kwargs: Any) -> UncertaintyResult:
        self.prompts.append(prompt)
        conf = self._confidences[min(self._idx, len(self._confidences) - 1)]
        self._idx += 1
        return UncertaintyResult(
            answer=f"answer-{self._idx}",
            confidence=conf,
            raw_scores={"agreement": conf},
        )


# ---------------------------------------------------------------------------
# 1. REASK succeeds on retry
# ---------------------------------------------------------------------------


class TestReaskSucceeds:
    def test_decision_is_reask(self) -> None:
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("question")
        assert result.outcome.decision is PolicyDecision.REASK

    def test_output_is_retry_answer(self) -> None:
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("question")
        assert result.output == "answer-2"

    def test_passed_is_true(self) -> None:
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("question")
        assert result.outcome.passed is True

    def test_raw_is_retry_result(self) -> None:
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("question")
        assert result.raw.confidence == 0.8

    def test_rmf_subcategory_is_manage_2_4(self) -> None:
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("question")
        assert result.rmf_subcategory == "MANAGE 2.4"

    def test_reason_contains_reask_succeeded(self) -> None:
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("question")
        assert "reask succeeded" in result.outcome.reason

    def test_retry_prompt_has_corrective_prefix(self) -> None:
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        guard("original question")
        assert len(pipe.prompts) == 2
        assert pipe.prompts[0] == "original question"
        assert pipe.prompts[1].endswith("original question")
        assert "reconsider" in pipe.prompts[1].lower()


# ---------------------------------------------------------------------------
# 2. REASK fails on retry → falls to ABSTAIN
# ---------------------------------------------------------------------------


class TestReaskFallsToAbstain:
    def test_decision_is_abstain(self) -> None:
        pipe = _SequencePipeline([0.2, 0.3])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.decision is PolicyDecision.ABSTAIN

    def test_passed_is_false(self) -> None:
        pipe = _SequencePipeline([0.2, 0.3])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.passed is False

    def test_output_is_abstain_marker(self) -> None:
        pipe = _SequencePipeline([0.2, 0.3])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.output == DEFAULT_ABSTAIN_MARKER

    def test_reason_contains_reask_failed(self) -> None:
        pipe = _SequencePipeline([0.2, 0.3])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert "reask failed" in result.outcome.reason

    def test_rmf_maps_to_manage_2_3_on_abstain(self) -> None:
        pipe = _SequencePipeline([0.2, 0.3])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.rmf_subcategory == "MANAGE 2.3"

    def test_raw_is_retry_result_even_on_failure(self) -> None:
        """Guard should expose the retry result, not the first pass."""
        pipe = _SequencePipeline([0.2, 0.3])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.raw.confidence == 0.3


# ---------------------------------------------------------------------------
# 3. REASK skipped when first pass passes threshold
# ---------------------------------------------------------------------------


class TestReaskSkippedWhenConfident:
    def test_high_confidence_bypasses_reask(self) -> None:
        """If confidence >= threshold on first pass, REASK is never triggered."""
        pipe = _SequencePipeline([0.9])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.decision is PolicyDecision.PASSTHROUGH
        assert len(pipe.prompts) == 1  # only one call, no retry

    def test_exactly_at_threshold_passes(self) -> None:
        pipe = _SequencePipeline([0.5])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.decision is PolicyDecision.PASSTHROUGH
        assert len(pipe.prompts) == 1


# ---------------------------------------------------------------------------
# 4. REASK metadata includes first_pass_confidence
# ---------------------------------------------------------------------------


class TestReaskMetadata:
    def test_first_pass_confidence_present_on_success(self) -> None:
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.metadata["first_pass_confidence"] == 0.3

    def test_first_pass_confidence_present_on_failure(self) -> None:
        pipe = _SequencePipeline([0.2, 0.3])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.metadata["first_pass_confidence"] == 0.2

    def test_reask_attempted_flag(self) -> None:
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.metadata["reask_attempted"] is True

    def test_reask_succeeded_true_on_success(self) -> None:
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.metadata["reask_succeeded"] is True

    def test_reask_succeeded_false_on_failure(self) -> None:
        pipe = _SequencePipeline([0.3, 0.4])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.metadata["reask_succeeded"] is False

    def test_retry_raw_scores_in_metadata(self) -> None:
        """Metadata should include the retry's raw_scores (agreement key)."""
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.metadata["agreement"] == 0.8

    def test_confidence_field_is_retry_confidence(self) -> None:
        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.confidence == 0.8

    def test_no_reask_metadata_when_skipped(self) -> None:
        """When first pass passes, metadata should NOT have reask keys."""
        pipe = _SequencePipeline([0.9])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert "reask_attempted" not in result.outcome.metadata
        assert "first_pass_confidence" not in result.outcome.metadata


# ---------------------------------------------------------------------------
# 5. REASK interacts correctly with gated_tool_call
# ---------------------------------------------------------------------------


class TestReaskWithGatedToolCall:
    def test_reask_guard_with_confident_tool_call_skips_tool(self) -> None:
        """If first pass is confident, tool is skipped even with REASK policy."""
        pipe = _SequencePipeline([0.9])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        tool_called = False

        def tool(prompt: str) -> str:
            nonlocal tool_called
            tool_called = True
            return "tool output"

        result = guard.gated_tool_call("q", tool)
        assert not tool_called
        assert result.outcome.metadata["tool_invoked"] is False

    def test_reask_guard_with_uncertain_tool_call_invokes_tool(self) -> None:
        """If first pass is uncertain, tool is invoked; second pass runs through REASK guard."""
        # First call: 0.3 (uncertain, triggers tool)
        # REASK triggered on first call: 0.3 first, 0.4 retry → ABSTAIN
        # After tool: second self() call: 0.3 first, 0.9 retry → REASK success
        pipe = _SequencePipeline([0.3, 0.4, 0.3, 0.9])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]

        def tool(prompt: str) -> str:
            return "regulatory context from RAG"

        guard.gated_tool_call("q", tool)
        # The second self() call should have triggered REASK path
        assert len(pipe.prompts) >= 3  # at least: first, reask, tool-augmented

    def test_reask_guard_tool_failure_abstains(self) -> None:
        """If tool raises and REASK is the policy, result is ABSTAIN."""
        pipe = _SequencePipeline([0.3, 0.4])  # first call uncertain, reask fails
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]

        def bad_tool(prompt: str) -> str:
            raise RuntimeError("RAG service down")

        result = guard.gated_tool_call("q", bad_tool)
        assert result.outcome.decision is PolicyDecision.ABSTAIN
        assert result.outcome.metadata["tool_invoked"] is True
        assert "tool_error" in result.outcome.metadata


# ---------------------------------------------------------------------------
# 6. max_reask_retries=0 skips reask entirely
# ---------------------------------------------------------------------------


class TestReaskMaxRetriesZero:
    def test_skips_retry_entirely(self) -> None:
        """With max_reask_retries=0, pipeline is called once → immediate ABSTAIN."""
        pipe = _SequencePipeline([0.3, 0.99])  # second value should never be used
        guard = UncertaintyGuard(
            pipe, threshold=0.5, on_fail=PolicyDecision.REASK, max_reask_retries=0,
        )  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.decision is PolicyDecision.ABSTAIN
        assert result.outcome.passed is False
        assert len(pipe.prompts) == 1

    def test_output_is_abstain_marker(self) -> None:
        pipe = _SequencePipeline([0.3])
        guard = UncertaintyGuard(
            pipe, threshold=0.5, on_fail=PolicyDecision.REASK, max_reask_retries=0,
        )  # type: ignore[arg-type]
        result = guard("q")
        assert result.output == DEFAULT_ABSTAIN_MARKER

    def test_reason_mentions_max_reask_retries(self) -> None:
        pipe = _SequencePipeline([0.3])
        guard = UncertaintyGuard(
            pipe, threshold=0.5, on_fail=PolicyDecision.REASK, max_reask_retries=0,
        )  # type: ignore[arg-type]
        result = guard("q")
        assert "max_reask_retries=0" in result.outcome.reason

    def test_metadata_reask_attempted_false(self) -> None:
        pipe = _SequencePipeline([0.3])
        guard = UncertaintyGuard(
            pipe, threshold=0.5, on_fail=PolicyDecision.REASK, max_reask_retries=0,
        )  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.metadata["reask_attempted"] is False
        assert result.outcome.metadata["reask_succeeded"] is False

    def test_first_pass_confidence_in_metadata(self) -> None:
        pipe = _SequencePipeline([0.35])
        guard = UncertaintyGuard(
            pipe, threshold=0.5, on_fail=PolicyDecision.REASK, max_reask_retries=0,
        )  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.metadata["first_pass_confidence"] == pytest.approx(0.35)

    def test_raw_is_first_pass(self) -> None:
        """When reask is skipped, raw should be the first (and only) pass."""
        pipe = _SequencePipeline([0.3])
        guard = UncertaintyGuard(
            pipe, threshold=0.5, on_fail=PolicyDecision.REASK, max_reask_retries=0,
        )  # type: ignore[arg-type]
        result = guard("q")
        assert result.raw.confidence == pytest.approx(0.3)

    def test_rmf_subcategory_is_manage_2_3(self) -> None:
        pipe = _SequencePipeline([0.3])
        guard = UncertaintyGuard(
            pipe, threshold=0.5, on_fail=PolicyDecision.REASK, max_reask_retries=0,
        )  # type: ignore[arg-type]
        result = guard("q")
        assert result.rmf_subcategory == "MANAGE 2.3"

    def test_gated_tool_call_with_max_retries_zero(self) -> None:
        """gated_tool_call still works when reask is disabled."""
        pipe = _SequencePipeline([0.3, 0.9])  # first: low → tool invoked; second: high
        guard = UncertaintyGuard(
            pipe, threshold=0.5, on_fail=PolicyDecision.REASK, max_reask_retries=0,
        )  # type: ignore[arg-type]
        tool_calls: list[str] = []

        result = guard.gated_tool_call("q", lambda q: (tool_calls.append(q) or "ctx"))  # type: ignore[func-returns-value]
        assert tool_calls == ["q"]
        # Only 2 pipeline calls: first pass + augmented (no reask retry).
        assert len(pipe.prompts) == 2
        assert result.outcome.passed is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestReaskEdgeCases:
    def test_custom_abstain_marker_on_reask_fallthrough(self) -> None:
        pipe = _SequencePipeline([0.2, 0.1])
        guard = UncertaintyGuard(
            pipe,
            threshold=0.5,
            on_fail=PolicyDecision.REASK,
            abstain_marker='{"action":"escalate_to_human"}',
        )  # type: ignore[arg-type]
        result = guard("q")
        assert result.output == '{"action":"escalate_to_human"}'
        assert result.outcome.decision is PolicyDecision.ABSTAIN

    def test_reask_with_threshold_at_boundary(self) -> None:
        """Retry confidence exactly at threshold should pass."""
        pipe = _SequencePipeline([0.3, 0.5])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.decision is PolicyDecision.REASK
        assert result.outcome.passed is True

    def test_reask_with_zero_first_confidence(self) -> None:
        pipe = _SequencePipeline([0.0, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        assert result.outcome.decision is PolicyDecision.REASK
        assert result.outcome.metadata["first_pass_confidence"] == 0.0

    def test_batch_with_reask_policy(self) -> None:
        """batch() should handle REASK without crashing."""
        pipe = _SequencePipeline([0.3, 0.8, 0.2, 0.1])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        results = guard.batch(["q1", "q2"])
        assert len(results) == 2
        assert all(isinstance(r, GuardResult) for r in results)

    def test_to_dict_serializable_after_reask(self) -> None:
        """GuardResult from REASK path must be JSON-serializable."""
        import json

        pipe = _SequencePipeline([0.3, 0.8])
        guard = UncertaintyGuard(pipe, threshold=0.5, on_fail=PolicyDecision.REASK)  # type: ignore[arg-type]
        result = guard("q")
        blob = json.dumps(result.to_dict(), sort_keys=True)
        parsed = json.loads(blob)
        assert parsed["outcome"]["decision"] == "reask"
        assert parsed["outcome"]["metadata"]["reask_attempted"] is True
