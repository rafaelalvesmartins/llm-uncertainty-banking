# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests targeting specific uncovered lines across the codebase.

This module closes coverage gaps identified in the 2026-04-20 audit.
Each test function is annotated with the file and line(s) it covers.
"""

from __future__ import annotations

import math

import pytest

from lub.types import Generation, UncertaintyResult
from lub.wrappers.dummy import DummyBackend
from tests import make_benchmark_result

# ===== graph_laplacian.py: lines 55, 92-99, 126, 132, 136 =====


class _NoEmbedBackend(DummyBackend):
    """Backend that raises NotImplementedError on embed (triggers Jaccard fallback)."""

    def embed(self, text: str) -> None:  # type: ignore[override]
        raise NotImplementedError("No embedding support")


def test_graph_laplacian_jaccard_fallback() -> None:
    """Cover lines 92-99: Jaccard fallback when embed raises NotImplementedError."""
    from lub.uncertainty.graph_laplacian import GraphLaplacianEstimator

    est = GraphLaplacianEstimator(n_samples=3)
    backend = _NoEmbedBackend()
    result = est.score(backend, "What is Basel III?")
    assert 0.0 <= result.confidence <= 1.0
    assert result.raw_scores["n_samples"] == 3.0


def test_graph_laplacian_single_component() -> None:
    """Cover lines 126, 132, 136: all texts identical → 1 component."""
    from lub.uncertainty.graph_laplacian import GraphLaplacianEstimator

    # DummyBackend returns same text for all samples with same prompt
    est = GraphLaplacianEstimator(n_samples=4, similarity_threshold=0.0)
    backend = DummyBackend()
    result = est.score(backend, "fixed prompt")
    assert result.raw_scores["num_sem_sets"] >= 1.0


def test_jaccard_one_empty_one_not() -> None:
    """Cover line 55: union is non-empty but one set is empty."""
    from lub.uncertainty.graph_laplacian import _jaccard

    assert _jaccard("", "hello world") == 0.0
    assert _jaccard("hello world", "") == 0.0


# ===== sar.py: lines 70, 73-74 =====


class _NoLogprobBackend(DummyBackend):
    """Backend that returns generations with no logprobs."""

    def generate(self, prompt: str, **kwargs) -> list[Generation]:  # type: ignore[override]
        return [Generation(text="answer", logprobs=None)]


class _ZeroLogprobBackend(DummyBackend):
    """Backend that returns logprobs of all zeros (relevance sum = 0)."""

    def generate(self, prompt: str, **kwargs) -> list[Generation]:  # type: ignore[override]
        return [Generation(text="answer", logprobs=[0.0, 0.0, 0.0])]


def test_sar_no_logprobs() -> None:
    """Cover lines 73-74: fallback when logprobs is None."""
    from lub.uncertainty.sar import TokenSAREstimator

    est = TokenSAREstimator()
    result = est.score(_NoLogprobBackend(), "q")
    assert result.confidence == 0.0
    assert math.isnan(result.raw_scores["sar"])


def test_sar_zero_relevance() -> None:
    """Cover line 70: r_sum == 0 fallback (all logprobs are 0)."""
    from lub.uncertainty.sar import TokenSAREstimator

    est = TokenSAREstimator()
    result = est.score(_ZeroLogprobBackend(), "q")
    # When all logprobs are 0, relevance = [-0, -0, -0] = [0, 0, 0]
    # r_sum = 0, fallback: sar = mean(logprobs) = 0, confidence = exp(0) = 1.0
    assert result.confidence == pytest.approx(1.0)


# ===== sentence_sar.py: lines 49, 54, 101, 118 =====


class _NoLogprobMultiBackend(DummyBackend):
    """Backend returning multiple generations with no logprobs."""

    def generate(self, prompt: str, **kwargs) -> list[Generation]:  # type: ignore[override]
        n = kwargs.get("n_samples", 5)
        return [Generation(text=f"answer {i}", logprobs=None) for i in range(n)]


class _MixedLogprobBackend(DummyBackend):
    """Backend returning some generations with logprobs, some without."""

    def generate(self, prompt: str, **kwargs) -> list[Generation]:  # type: ignore[override]
        n = kwargs.get("n_samples", 5)
        gens = []
        for i in range(n):
            if i % 2 == 0:
                gens.append(Generation(text=f"answer {i}", logprobs=[-1.0, -0.5]))
            else:
                gens.append(Generation(text=f"answer {i}", logprobs=None))
        return gens


class _ZeroRelevanceMultiBackend(DummyBackend):
    """Backend returning generations where all logprobs are 0."""

    def generate(self, prompt: str, **kwargs) -> list[Generation]:  # type: ignore[override]
        n = kwargs.get("n_samples", 5)
        return [Generation(text=f"answer {i}", logprobs=[0.0, 0.0]) for i in range(n)]


def test_sentence_sar_no_logprobs() -> None:
    """Cover lines 49, 101: _token_sar returns -inf, all filtered → confidence 0."""
    from lub.uncertainty.sentence_sar import SentenceSAREstimator

    est = SentenceSAREstimator(n_samples=3)
    result = est.score(_NoLogprobMultiBackend(), "q")
    assert result.confidence == 0.0
    assert result.should_refuse is True


def test_sentence_sar_zero_relevance() -> None:
    """Cover line 118: r_sum == 0 fallback in sentence-level weighting."""
    from lub.uncertainty.sentence_sar import SentenceSAREstimator

    est = SentenceSAREstimator(n_samples=3)
    result = est.score(_ZeroRelevanceMultiBackend(), "q")
    # All logprobs 0 → token SAR = 0 for each gen → relevances = [0,0,0] → fallback mean
    assert result.confidence == pytest.approx(1.0)


def test_sentence_sar_mixed_logprobs() -> None:
    """Cover line 54: _token_sar with r_sum > 0 path."""
    from lub.uncertainty.sentence_sar import SentenceSAREstimator

    est = SentenceSAREstimator(n_samples=4)
    result = est.score(_MixedLogprobBackend(), "q")
    assert 0.0 <= result.confidence <= 1.0
    assert result.raw_scores["n_valid"] > 0


# ===== perplexity.py: lines 68-70 =====


def test_perplexity_no_logprobs() -> None:
    """Cover lines 68-70: generation has no logprobs."""
    from lub.uncertainty.perplexity import PerplexityEstimator

    est = PerplexityEstimator()
    result = est.score(_NoLogprobBackend(), "q")
    assert result.confidence == 0.0
    assert math.isnan(result.raw_scores["mean_logprob"])
    assert result.raw_scores["perplexity"] == float("inf")


# ===== conformal_sampling.py: lines 64, 66, 68, 138-139 =====


def test_conformal_sampling_validation_errors() -> None:
    """Cover lines 64, 66, 68: validation in __init__."""
    from lub.uncertainty.conformal_sampling import ConformalSamplingEstimator

    with pytest.raises(ValueError, match="alpha"):
        ConformalSamplingEstimator(alpha=0.0)
    with pytest.raises(ValueError, match="alpha"):
        ConformalSamplingEstimator(alpha=1.0)
    with pytest.raises(ValueError, match="n_samples"):
        ConformalSamplingEstimator(n_samples=1)
    with pytest.raises(ValueError, match="temperature"):
        ConformalSamplingEstimator(temperature=0.0)
    with pytest.raises(ValueError, match="min_admit_fraction"):
        ConformalSamplingEstimator(min_admit_fraction=-0.1)


def test_conformal_sampling_no_admitted() -> None:
    """Cover lines 138-139: no generations admitted → pick lowest nonconformity."""
    from lub.uncertainty.conformal_sampling import ConformalSamplingEstimator

    est = ConformalSamplingEstimator(n_samples=3, alpha=0.1)
    backend = DummyBackend()
    # Fit with a very strict threshold
    est.fit([("q1", "a1"), ("q2", "a2"), ("q3", "a3")], backend=backend)
    # Set tau_admit to something impossibly low
    est.tau_admit = -999.0
    result = est.score(backend, "test question")
    # Should still return an answer (best among non-admitted)
    assert result.answer
    assert result.confidence == 0.0


# ===== reports/renderer.py: lines 40-42, 115-117, 135, 146 =====


def test_renderer_encode_png_none() -> None:
    """Cover line 40-42: _encode_png with None input."""
    from lub.reports.renderer import _encode_png

    assert _encode_png(None) is None
    assert _encode_png(b"hello") is not None


def test_renderer_custom_template_path(tmp_path) -> None:
    """Cover lines 115-117: custom template_path."""
    from lub.reports.renderer import AIRMFReporter

    template = tmp_path / "custom.md.j2"
    template.write_text("# Custom Report\n{{ results | length }} runs")

    result = make_benchmark_result()
    reporter = AIRMFReporter([result], template_path=str(template))
    rendered = reporter.render(format="md")
    assert "Custom Report" in rendered
    assert "1 runs" in rendered


def test_renderer_invalid_format() -> None:
    """Cover line 135: invalid format raises ValueError."""
    from lub.reports.renderer import AIRMFReporter

    result = make_benchmark_result()
    reporter = AIRMFReporter([result])
    with pytest.raises(ValueError, match="json"):
        reporter.render(format="json")  # type: ignore[arg-type]


# ===== reports/__init__.py: lines 65, 70 =====


def test_reports_init_exports() -> None:
    """Cover reports/__init__.py lazy imports."""
    from lub.reports import AIRMFReporter, OscalBatchReporter, create_reporter

    assert AIRMFReporter is not None
    assert OscalBatchReporter is not None
    assert create_reporter is not None


# ===== reports/factory.py: lines 60-62, 68 =====


def test_reports_factory_unknown_format() -> None:
    """Cover factory.py error path for unknown report_type."""
    from lub.reports.factory import create_reporter

    result = make_benchmark_result()
    with pytest.raises(ValueError, match="unknown report type"):
        create_reporter([result], report_type="invalid_format")  # type: ignore[arg-type]


# ===== reports/protocol.py: lines 42, 59 =====


def test_reports_protocol_abstract() -> None:
    """Cover protocol.py abstract methods."""
    from lub.reports.protocol import ReportGenerator

    # Verify it's a Protocol (can't be instantiated directly)
    assert hasattr(ReportGenerator, "render")
    assert hasattr(ReportGenerator, "save")


# ===== uncertainty/__init__.py: line 54 =====


def test_uncertainty_init_lazy_load() -> None:
    """Cover uncertainty/__init__.py __getattr__ lazy import (line 54)."""
    from lub.uncertainty import SelfConsistencyEstimator

    assert SelfConsistencyEstimator is not None


def test_uncertainty_init_unknown_attr() -> None:
    """Cover uncertainty/__init__.py __getattr__ AttributeError (line 54)."""
    import lub.uncertainty

    with pytest.raises(AttributeError, match="has no attribute"):
        _ = lub.uncertainty.NonExistentEstimator  # type: ignore[attr-defined]


# ===== benchmarks/__init__.py: line 38 =====


def test_benchmarks_init_exports() -> None:
    """Cover benchmarks/__init__.py lazy imports."""
    from lub.benchmarks import BenchmarkRunner, Dataset

    assert BenchmarkRunner is not None
    assert Dataset is not None


# ===== mahalanobis.py: lines 56, 81-82, 94-95 =====


class _ShortEmbedBackend(DummyBackend):
    """Backend with very short embeddings."""

    def embed(self, text: str) -> list[float]:  # type: ignore[override]
        # Return a consistent embedding based on text hash
        h = hash(text) % 100
        return [float(h), float(h + 1), float(h + 2)]


def test_mahalanobis_score() -> None:
    """Cover mahalanobis.py score path."""
    from lub.uncertainty.mahalanobis import MahalanobisEstimator

    est = MahalanobisEstimator()
    backend = _ShortEmbedBackend()
    result = est.score(backend, "test question")
    assert 0.0 <= result.confidence <= 1.0


# ===== calibration/normalizers.py: lines 42, 46, 107-108, etc. =====


def test_isotonic_normalizer() -> None:
    """Cover isotonic normalizer path."""
    import numpy as np

    from lub.calibration.normalizers import IsotonicNormalizer

    norm = IsotonicNormalizer()
    confs = np.array([0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.4, 0.6, 0.85])
    labels = np.array([0, 0, 0, 1, 1, 1, 1, 0, 1, 1])
    norm.fit(confs, labels)
    calibrated = norm.transform(confs)
    assert len(calibrated) == len(confs)


def test_quantile_normalizer() -> None:
    """Cover quantile normalizer path."""
    import numpy as np

    from lub.calibration.normalizers import QuantileNormalizer

    norm = QuantileNormalizer()
    confs = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    labels = np.array([0, 0, 0, 0, 1, 1, 1, 1, 1, 1])
    norm.fit(confs, labels)
    calibrated = norm.transform(confs)
    assert len(calibrated) == len(confs)


def test_minmax_normalizer() -> None:
    """Cover MinMaxNormalizer path."""
    import numpy as np

    from lub.calibration.normalizers import MinMaxNormalizer

    norm = MinMaxNormalizer()
    confs = np.array([0.1, 0.5, 0.9])
    labels = np.array([0, 1, 1])
    norm.fit(confs, labels)
    calibrated = norm.transform(confs)
    assert len(calibrated) == len(confs)


# ===== giskard_reporter.py: lines 34, 62-63 =====


def test_giskard_reporter_import() -> None:
    """Cover giskard_reporter.py import and basic structure."""
    from lub.reports.giskard_reporter import GiskardBatchReporter

    assert GiskardBatchReporter is not None


# ===== Round 2: 2026-04-21 coverage push =====


# ===== self_consistency.py: lines 48, 50 (validation) =====


def test_self_consistency_validation_errors() -> None:
    """Cover lines 48, 50: __init__ validation."""
    from lub.uncertainty.self_consistency import SelfConsistencyEstimator

    with pytest.raises(ValueError, match="n_samples"):
        SelfConsistencyEstimator(n_samples=0)
    with pytest.raises(ValueError, match="temperature"):
        SelfConsistencyEstimator(temperature=0.0)


# ===== ensemble.py: lines 58, 61 (validation) =====


def test_ensemble_validation_errors() -> None:
    """Cover lines 58, 61: negative weights and zero weights."""
    from lub.uncertainty.ensemble import EnsembleEstimator
    from lub.uncertainty.self_consistency import SelfConsistencyEstimator

    e1, e2 = SelfConsistencyEstimator(), SelfConsistencyEstimator()
    with pytest.raises(ValueError, match="weights must be >= 0"):
        EnsembleEstimator(estimators=[e1, e2], weights=[-1.0, 1.0])
    with pytest.raises(ValueError, match="weights must not all be zero"):
        EnsembleEstimator(estimators=[e1, e2], weights=[0.0, 0.0])


# ===== eigenscore.py: lines 78-79 (no embed support) =====


def test_eigenscore_no_embed() -> None:
    """Cover lines 78-79: backend without embed raises TypeError."""
    from lub.uncertainty.eigenscore import EigenScoreEstimator

    class _NoEmbedBackend2(DummyBackend):
        def embed(self, text: str) -> list[float]:  # type: ignore[override]
            raise NotImplementedError

    est = EigenScoreEstimator(n_samples=3)
    with pytest.raises(TypeError, match="embed"):
        est.score(_NoEmbedBackend2(), "test")


# ===== verbalized.py: lines 67, 85, 174 =====


def test_clip_percent_boundaries() -> None:
    """Cover line 67: _clip_percent with value < 0."""
    from lub.uncertainty.verbalized import _clip_percent

    assert _clip_percent(-5) == 0.0
    assert _clip_percent(150) == 1.0
    assert _clip_percent(50) == 0.5


def test_parse_two_shot_rating_no_match() -> None:
    """Cover line 85: no integer found in rating text."""
    from lub.uncertainty.verbalized import _parse_two_shot_rating

    assert _parse_two_shot_rating("no numbers here") is None


def test_verbalized_two_shot_no_rating() -> None:
    """Cover line 174: unparseable rating → confidence 0."""
    from lub.uncertainty.verbalized import VerbalizedTwoShot

    class _NoRatingBackend(DummyBackend):
        _call_count = 0

        def generate(self, prompt: str, **kwargs) -> list[Generation]:  # type: ignore[override]
            self._call_count += 1
            # First call is the answer, second is the rating
            if self._call_count == 1:
                return [Generation(text="Basel III is a regulatory framework")]
            return [Generation(text="I cannot provide a numeric rating")]

    est = VerbalizedTwoShot()
    result = est.score(_NoRatingBackend(), "What is Basel III?")
    assert result.confidence == 0.0
    assert result.raw_scores["parsed"] == 0.0


# ===== reports/protocol.py: lines 42, 59 (Protocol body) =====


def test_report_save_mixin(tmp_path) -> None:
    """Cover ReportSaveMixin.save() method."""
    from lub.reports.protocol import ReportSaveMixin

    class _TestReporter(ReportSaveMixin):
        def render(self, format="md"):
            return "# Test Report\nAll good."

    reporter = _TestReporter()
    out = reporter.save(tmp_path / "sub" / "report.md")
    assert out.exists()
    assert "Test Report" in out.read_text()


# ===== reports/__init__.py: lines 65, 70 (lazy load + unknown) =====


def test_reports_init_unknown_attr() -> None:
    """Cover line 65: AttributeError for unknown name."""
    import lub.reports

    with pytest.raises(AttributeError, match="has no attribute"):
        _ = lub.reports.NonExistentReporter


# ===== benchmarks/__init__.py: line 38 (unknown attr) =====


def test_benchmarks_init_unknown_attr() -> None:
    """Cover line 38: AttributeError for unknown name."""
    import lub.benchmarks

    with pytest.raises(AttributeError, match="has no attribute"):
        _ = lub.benchmarks.NonExistentDataset


# ===== reports/factory.py: lines 60-62 (oscal + giskard paths) =====


def test_factory_oscal_reporter() -> None:
    """Cover factory.py oscal branch."""
    from lub.reports.factory import create_reporter

    result = make_benchmark_result()
    reporter = create_reporter([result], report_type="oscal")
    assert reporter is not None


def test_factory_giskard_reporter() -> None:
    """Cover factory.py giskard branch."""
    from lub.reports.factory import create_reporter

    result = make_benchmark_result()
    reporter = create_reporter([result], report_type="giskard")
    assert reporter is not None


def test_factory_unknown_reporter() -> None:
    """Cover factory.py ValueError branch."""
    from lub.reports.factory import create_reporter

    result = make_benchmark_result()
    with pytest.raises(ValueError, match="unknown report type"):
        create_reporter([result], report_type="invalid")  # type: ignore[arg-type]


# ===== guard.py: lines 170-183 (to_otel_attributes edge cases) =====


def test_guard_result_otel_attributes() -> None:
    """Cover lines 170-183: to_otel_attributes with metadata."""
    from lub.guard import GuardResult, PolicyDecision, PolicyOutcome

    outcome = PolicyOutcome(
        decision=PolicyDecision.FLAG,
        confidence=0.7,
        threshold=0.5,
        passed=True,
        answer="test",
        metadata={"tool_invoked": True, "uala_gate": 0.8},
    )
    raw = UncertaintyResult(
        answer="test", confidence=0.7, raw_scores={}, samples=[], should_refuse=False
    )
    gr = GuardResult(raw=raw, outcome=outcome, output="test", rmf_subcategory="MANAGE 2.4")
    attrs = gr.to_otel_attributes()
    assert attrs["lub.guard.tool_invoked"] is True
    assert attrs["lub.guard.uala_gate"] == 0.8
    assert attrs["gen_ai.system"] == "lub"


# ===== wrappers/base.py: lines 88-90 (registry overwrite warning) =====


def test_backend_registry_overwrite_warning() -> None:
    """Cover lines 88-90: duplicate REGISTRY_KEY warns."""
    import warnings

    from lub.wrappers.base import ModelBackend

    # First registration
    class _Backend1(ModelBackend):
        REGISTRY_KEY = "_test_dup_key"
        def generate(self, prompt, **kw):
            return []

    # Second registration of same key should warn
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        class _Backend2(ModelBackend):
            REGISTRY_KEY = "_test_dup_key"
            def generate(self, prompt, **kw):
                return []

        assert any("overwritten" in str(warning.message) for warning in w)

    # Cleanup
    ModelBackend._registry.pop("_test_dup_key", None)
