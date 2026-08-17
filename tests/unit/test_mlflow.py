# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for ``lub.integrations.mlflow``.

These tests mock the third-party ``mlflow`` module so they run without
the optional dependency installed. They focus on the integration's
own logic: metric/tag emission, dedup of typed-vs-dict metrics,
conditional OSCAL artifact paths, prompt truncation, and the
ImportError surface when ``mlflow`` is unavailable.
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from lub.guard import GuardResult, PolicyDecision, PolicyOutcome
from lub.types import UncertaintyResult
from tests import make_benchmark_result

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mlflow() -> MagicMock:
    """Return a MagicMock standing in for the ``mlflow`` module."""
    return MagicMock()


@pytest.fixture
def patched_mlflow(mock_mlflow: MagicMock):
    """Patch ``sys.modules['mlflow']`` so ``import mlflow`` resolves to the mock."""
    with patch.dict(sys.modules, {"mlflow": mock_mlflow}):
        yield mock_mlflow


def _make_guard_result(
    *,
    confidence: float = 0.9,
    decision: PolicyDecision = PolicyDecision.PASSTHROUGH,
    threshold: float = 0.5,
    answer: str = "ok",
) -> GuardResult:
    raw = UncertaintyResult(answer=answer, confidence=confidence)
    outcome = PolicyOutcome(
        decision=decision,
        confidence=confidence,
        threshold=threshold,
        passed=confidence >= threshold,
        answer=answer,
        reason="",
        metadata={},
    )
    return GuardResult(
        raw=raw,
        outcome=outcome,
        output=answer,
        rmf_subcategory="MEASURE-2.3",
    )


# ---------------------------------------------------------------------------
# log_benchmark_result — metrics & tags
# ---------------------------------------------------------------------------


class TestLogBenchmarkResultMetrics:
    def test_logs_all_metrics_with_lub_prefix(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result()
        log_benchmark_result(result, log_oscal=False, log_assessment=False)

        logged_keys = {call.args[0] for call in patched_mlflow.log_metric.call_args_list}
        for k in result.metrics:
            assert f"lub.{k}" in logged_keys

    def test_does_not_double_log_typed_fields_when_present_in_metrics(
        self, patched_mlflow: MagicMock
    ) -> None:
        """Dedup: accuracy/ece/refusal_auroc appear in ``result.metrics`` already."""
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result()
        log_benchmark_result(result, log_oscal=False, log_assessment=False)

        all_keys = [c.args[0] for c in patched_mlflow.log_metric.call_args_list]
        # Each of these three should appear exactly once.
        for typed in ("lub.accuracy", "lub.ece", "lub.refusal_auroc"):
            assert all_keys.count(typed) == 1

    def test_logs_typed_fields_via_fallback_when_metrics_empty(
        self, patched_mlflow: MagicMock
    ) -> None:
        """When ``metrics`` is empty, fallback path still logs typed fields."""
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result(metrics={})
        log_benchmark_result(result, log_oscal=False, log_assessment=False)

        logged = {c.args[0]: c.args[1] for c in patched_mlflow.log_metric.call_args_list}
        assert logged["lub.accuracy"] == result.accuracy
        assert logged["lub.ece"] == result.ece
        assert logged["lub.refusal_auroc"] == result.refusal_auroc

    def test_partial_metrics_uses_fallback_only_for_missing(
        self, patched_mlflow: MagicMock
    ) -> None:
        """If ``metrics`` has accuracy but not ece, only ece falls back."""
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result(metrics={"accuracy": 0.9, "custom_metric": 0.5})
        log_benchmark_result(result, log_oscal=False, log_assessment=False)

        all_keys = [c.args[0] for c in patched_mlflow.log_metric.call_args_list]
        # accuracy logged exactly once (from the metrics dict), ece logged once (fallback)
        assert all_keys.count("lub.accuracy") == 1
        assert all_keys.count("lub.ece") == 1
        assert all_keys.count("lub.refusal_auroc") == 1
        assert "lub.custom_metric" in all_keys

    def test_sets_required_tags(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result()
        log_benchmark_result(result, log_oscal=False, log_assessment=False)

        tags = dict(call.args for call in patched_mlflow.set_tag.call_args_list)
        assert tags["lub.backend"] == result.backend
        assert tags["lub.estimator"] == result.estimator
        assert tags["lub.dataset"] == result.dataset
        assert tags["lub.repo_version"] == result.repo_version

    def test_sets_git_sha_tag_when_present(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result(git_sha="abc1234")
        log_benchmark_result(result, log_oscal=False, log_assessment=False)

        tags = dict(call.args for call in patched_mlflow.set_tag.call_args_list)
        assert tags.get("lub.git_sha") == "abc1234"

    def test_omits_git_sha_tag_when_none(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result(git_sha=None)
        log_benchmark_result(result, log_oscal=False, log_assessment=False)

        tag_keys = [call.args[0] for call in patched_mlflow.set_tag.call_args_list]
        assert "lub.git_sha" not in tag_keys


# ---------------------------------------------------------------------------
# log_benchmark_result — artifacts
# ---------------------------------------------------------------------------


class TestLogBenchmarkResultArtifacts:
    def test_logs_benchmark_json_only_when_oscal_disabled(
        self, patched_mlflow: MagicMock
    ) -> None:
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result()
        log_benchmark_result(result, log_oscal=False, log_assessment=False)

        assert patched_mlflow.log_artifact.call_count == 1

    def test_logs_oscal_component_definition_when_enabled(
        self, patched_mlflow: MagicMock
    ) -> None:
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result()
        log_benchmark_result(result, log_oscal=True, log_assessment=False)

        paths = [call.args[0] for call in patched_mlflow.log_artifact.call_args_list]
        assert any("oscal_component_definition.json" in p for p in paths)
        assert patched_mlflow.log_artifact.call_count == 2

    def test_logs_assessment_results_when_enabled(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result()
        log_benchmark_result(result, log_oscal=False, log_assessment=True)

        paths = [call.args[0] for call in patched_mlflow.log_artifact.call_args_list]
        assert any("oscal_assessment_results.json" in p for p in paths)
        assert patched_mlflow.log_artifact.call_count == 2

    def test_logs_all_three_artifacts_by_default(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result()
        log_benchmark_result(result)  # defaults: log_oscal=True, log_assessment=True

        assert patched_mlflow.log_artifact.call_count == 3
        paths = [call.args[0] for call in patched_mlflow.log_artifact.call_args_list]
        assert any("benchmark_result.json" in p for p in paths)
        assert any("oscal_component_definition.json" in p for p in paths)
        assert any("oscal_assessment_results.json" in p for p in paths)

    def test_uses_custom_artifact_subdir(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result()
        log_benchmark_result(
            result,
            log_oscal=False,
            log_assessment=False,
            artifact_subdir="custom/sub",
        )

        for call in patched_mlflow.log_artifact.call_args_list:
            assert call.args[1] == "custom/sub"

    def test_default_subdir_is_lub(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result()
        log_benchmark_result(result, log_oscal=False, log_assessment=False)

        for call in patched_mlflow.log_artifact.call_args_list:
            assert call.args[1] == "lub"

    def test_benchmark_result_artifact_is_valid_json(
        self, patched_mlflow: MagicMock, tmp_path
    ) -> None:
        """Capture the artifact path before tempdir teardown and assert valid JSON."""
        captured: list[bytes] = []

        def capture_log_artifact(path: str, _subdir: str) -> None:
            from pathlib import Path

            captured.append(Path(path).read_bytes())

        patched_mlflow.log_artifact.side_effect = capture_log_artifact

        from lub.integrations.mlflow import log_benchmark_result

        result = make_benchmark_result()
        log_benchmark_result(result, log_oscal=False, log_assessment=False)

        assert len(captured) == 1
        parsed = json.loads(captured[0].decode("utf-8"))
        assert parsed["backend"] == result.backend
        assert parsed["estimator"] == result.estimator


# ---------------------------------------------------------------------------
# log_benchmark_result — error handling
# ---------------------------------------------------------------------------


class TestLogBenchmarkResultErrors:
    def test_raises_import_error_when_mlflow_unavailable(self) -> None:
        with patch.dict(sys.modules, {"mlflow": None}):
            import lub.integrations.mlflow as mod

            importlib.reload(mod)
            with pytest.raises(ImportError, match="mlflow"):
                mod.log_benchmark_result(make_benchmark_result())

        # Restore for downstream tests by reloading without the None entry.
        import lub.integrations.mlflow as mod

        importlib.reload(mod)


# ---------------------------------------------------------------------------
# log_guard_result
# ---------------------------------------------------------------------------


class TestLogGuardResult:
    def test_logs_confidence_metric(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_guard_result

        gr = _make_guard_result(confidence=0.87)
        log_guard_result("what is CET1?", gr)

        patched_mlflow.log_metric.assert_called_once_with(
            "lub.guard.confidence", 0.87, step=None
        )

    def test_passes_step_through(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_guard_result

        gr = _make_guard_result(confidence=0.5)
        log_guard_result("hello", gr, step=42)

        patched_mlflow.log_metric.assert_called_once_with(
            "lub.guard.confidence", 0.5, step=42
        )

    def test_logs_decision_and_passed_tags(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_guard_result

        gr = _make_guard_result(
            confidence=0.95, decision=PolicyDecision.PASSTHROUGH, threshold=0.5
        )
        log_guard_result("query", gr)

        tags = dict(call.args for call in patched_mlflow.set_tag.call_args_list)
        assert tags["lub.guard.decision"] == "passthrough"
        assert tags["lub.guard.passed"] == "True"

    def test_low_confidence_below_threshold_escalates(
        self, patched_mlflow: MagicMock
    ) -> None:
        """Below-threshold confidence with ABSTAIN decision is faithfully logged."""
        from lub.integrations.mlflow import log_guard_result

        gr = _make_guard_result(
            confidence=0.1, decision=PolicyDecision.ABSTAIN, threshold=0.5
        )
        log_guard_result("transfer R$100k now", gr)

        tags = dict(call.args for call in patched_mlflow.set_tag.call_args_list)
        assert tags["lub.guard.decision"] == "abstain"
        assert tags["lub.guard.passed"] == "False"

    def test_high_confidence_above_threshold_passes(
        self, patched_mlflow: MagicMock
    ) -> None:
        from lub.integrations.mlflow import log_guard_result

        gr = _make_guard_result(
            confidence=0.99, decision=PolicyDecision.PASSTHROUGH, threshold=0.5
        )
        log_guard_result("what is my balance?", gr)

        tags = dict(call.args for call in patched_mlflow.set_tag.call_args_list)
        assert tags["lub.guard.passed"] == "True"

    def test_prompt_truncated_to_250_chars(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_guard_result

        long_prompt = "x" * 1000
        gr = _make_guard_result()
        log_guard_result(long_prompt, gr)

        tags = dict(call.args for call in patched_mlflow.set_tag.call_args_list)
        assert len(tags["lub.guard.prompt"]) == 250
        assert tags["lub.guard.prompt"] == "x" * 250

    def test_short_prompt_preserved(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_guard_result

        gr = _make_guard_result()
        log_guard_result("short", gr)

        tags = dict(call.args for call in patched_mlflow.set_tag.call_args_list)
        assert tags["lub.guard.prompt"] == "short"

    def test_empty_prompt_does_not_crash(self, patched_mlflow: MagicMock) -> None:
        from lub.integrations.mlflow import log_guard_result

        gr = _make_guard_result()
        log_guard_result("", gr)

        tags = dict(call.args for call in patched_mlflow.set_tag.call_args_list)
        assert tags["lub.guard.prompt"] == ""

    def test_pii_prompt_truncated_not_redacted(self, patched_mlflow: MagicMock) -> None:
        """The integration truncates but does not redact; that's a downstream concern."""
        from lub.integrations.mlflow import log_guard_result

        pii = "CPF 123.456.789-00, " * 20  # well over 250 chars
        gr = _make_guard_result()
        log_guard_result(pii, gr)

        tags = dict(call.args for call in patched_mlflow.set_tag.call_args_list)
        assert len(tags["lub.guard.prompt"]) == 250

    def test_raises_import_error_when_mlflow_unavailable(self) -> None:
        with patch.dict(sys.modules, {"mlflow": None}):
            import lub.integrations.mlflow as mod

            importlib.reload(mod)
            gr = _make_guard_result()
            with pytest.raises(ImportError, match="mlflow"):
                mod.log_guard_result("prompt", gr)

        import lub.integrations.mlflow as mod

        importlib.reload(mod)
