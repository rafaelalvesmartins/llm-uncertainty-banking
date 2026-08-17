# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for optional integrations (MLflow, LangChain).

These tests mock the third-party dependencies so they run without
installing mlflow or langchain-core.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lub.pipeline import UncertaintyPipeline
from lub.uncertainty.base import get_estimator_cls
from lub.wrappers.dummy import DummyBackend
from tests import make_benchmark_result

# ---------------------------------------------------------------------------
# MLflow integration
# ---------------------------------------------------------------------------


class TestMLflowIntegration:
    def test_log_benchmark_result_calls_mlflow(self) -> None:
        mock_mlflow = MagicMock()
        with patch.dict("sys.modules", {"mlflow": mock_mlflow}):
            from lub.integrations.mlflow import log_benchmark_result

            result = make_benchmark_result()
            log_benchmark_result(result, log_oscal=False, log_assessment=False)

            # Should have logged metrics
            assert mock_mlflow.log_metric.call_count >= 3
            # Should have set tags
            assert mock_mlflow.set_tag.call_count >= 4

    def test_log_benchmark_result_logs_oscal_artifacts(self) -> None:
        mock_mlflow = MagicMock()
        with patch.dict("sys.modules", {"mlflow": mock_mlflow}):
            from lub.integrations.mlflow import log_benchmark_result

            result = make_benchmark_result()
            log_benchmark_result(result, log_oscal=True, log_assessment=True)

            # Should have logged 3 artifacts (result + OSCAL CD + OSCAL AR)
            assert mock_mlflow.log_artifact.call_count == 3

    def test_log_benchmark_result_raises_without_mlflow(self) -> None:
        with patch.dict("sys.modules", {"mlflow": None}):
            # Force reimport
            import importlib

            import lub.integrations.mlflow as mod

            importlib.reload(mod)
            with pytest.raises(ImportError, match="mlflow"):
                mod.log_benchmark_result(make_benchmark_result())

    def test_log_guard_result(self) -> None:
        mock_mlflow = MagicMock()
        with patch.dict("sys.modules", {"mlflow": mock_mlflow}):
            from lub.integrations.mlflow import log_guard_result

            backend = DummyBackend(model_id="dummy-test")
            est = get_estimator_cls("token_logprob")()
            pipe = UncertaintyPipeline(backend=backend, estimator=est)
            from lub.guard import UncertaintyGuard

            guard = UncertaintyGuard(pipe, threshold=0.5)
            gr = guard("test prompt")
            log_guard_result("test prompt", gr, step=1)

            mock_mlflow.log_metric.assert_called()
            mock_mlflow.set_tag.assert_called()


# ---------------------------------------------------------------------------
# LangChain integration
# ---------------------------------------------------------------------------


class TestLangChainIntegration:
    def _make_handler(self) -> object:
        from lub.integrations.langchain import LUBCallbackHandler
        from lub.uncertainty.token_logprob import TokenLogprobEstimator

        backend = DummyBackend(model_id="dummy-test")
        est = TokenLogprobEstimator()
        pipe = UncertaintyPipeline(backend=backend, estimator=est)
        return LUBCallbackHandler(pipeline=pipe)

    def test_on_llm_start_scores_prompts(self) -> None:
        handler = self._make_handler()
        handler.on_llm_start({}, ["What is CET1?"])  # type: ignore[attr-defined]
        assert len(handler.results) == 1  # type: ignore[attr-defined]
        assert handler.last_result is not None  # type: ignore[attr-defined]
        assert 0.0 <= handler.last_result.confidence <= 1.0  # type: ignore[attr-defined]

    def test_on_llm_start_multiple_prompts(self) -> None:
        handler = self._make_handler()
        handler.on_llm_start({}, ["Q1", "Q2", "Q3"])  # type: ignore[attr-defined]
        assert len(handler.results) == 3  # type: ignore[attr-defined]

    def test_get_summary_empty(self) -> None:
        handler = self._make_handler()
        summary = handler.get_summary()  # type: ignore[attr-defined]
        assert summary["n_calls"] == 0

    def test_get_summary_after_calls(self) -> None:
        handler = self._make_handler()
        handler.on_llm_start({}, ["Q1", "Q2"])  # type: ignore[attr-defined]
        summary = handler.get_summary()  # type: ignore[attr-defined]
        assert summary["n_calls"] == 2
        assert "mean_confidence" in summary
        assert "min_confidence" in summary
        assert "refusal_rate" in summary

    def test_on_llm_error_does_not_crash(self) -> None:
        handler = self._make_handler()
        handler.on_llm_error(RuntimeError("test error"))  # type: ignore[attr-defined]

    def test_on_llm_end_does_not_crash(self) -> None:
        handler = self._make_handler()
        handler.on_llm_end(None)  # type: ignore[attr-defined]
