# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :class:`lub.uncertainty.lmpolygraph.LMPolygraphEstimator`.

The real ``lm-polygraph`` package is heavy (pulls torch, transformers,
sentence-transformers, datasets, and sometimes unbabel-comet) and is
gated behind an optional extra. These tests therefore exercise only the
branches that LUB itself owns — validation, HFBackend requirement, the
raw-to-confidence map, and a successful run path using a mocked
``lm_polygraph`` module injected into ``sys.modules``.
"""

from __future__ import annotations

import math
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from lub.types import UncertaintyResult
from lub.uncertainty.lmpolygraph import LMPolygraphEstimator, _raw_to_confidence
from lub.wrappers.dummy import DummyBackend


def test_constructor_validates_refusal_threshold() -> None:
    with pytest.raises(ValueError):
        LMPolygraphEstimator(method="Foo", refusal_threshold=1.5)
    with pytest.raises(ValueError):
        LMPolygraphEstimator(method="Foo", refusal_threshold=-0.1)


def test_constructor_rejects_empty_method() -> None:
    with pytest.raises(ValueError):
        LMPolygraphEstimator(method="")


def test_raw_to_confidence_monotone_and_bounded() -> None:
    assert _raw_to_confidence(0.0) == pytest.approx(1.0)
    assert 0.0 < _raw_to_confidence(1.0) < 1.0
    assert _raw_to_confidence(10.0) < _raw_to_confidence(1.0)
    assert _raw_to_confidence(-3.0) == pytest.approx(_raw_to_confidence(3.0))
    # NaN / inf degrade safely.
    assert _raw_to_confidence(float("nan")) == 0.0
    assert _raw_to_confidence(float("inf")) == 0.0


def test_score_rejects_non_hf_backend() -> None:
    est = LMPolygraphEstimator(method="MaximumSequenceProbability")
    with pytest.raises(TypeError, match="HFBackend"):
        est.score(DummyBackend(), "any prompt")


def test_score_raises_import_error_when_lmpolygraph_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installing the extra is the user's responsibility — fail loudly if not."""
    monkeypatch.setitem(sys.modules, "lm_polygraph", None)  # type: ignore[arg-type]
    est = LMPolygraphEstimator(method="MaximumSequenceProbability")

    class _FakeHF:
        """Duck-types as HFBackend just enough to reach the SDK import."""

        model_id = "fake/model"

        def _load(self) -> tuple[Any, Any, str]:  # pragma: no cover - not reached
            return object(), object(), "cpu"

    # Route through the real isinstance check by patching _require_whitebox to a pass.
    monkeypatch.setattr(est, "_require_whitebox", lambda backend: backend)
    with pytest.raises(ImportError, match="lm-polygraph"):
        est.score(_FakeHF(), "prompt")  # type: ignore[arg-type]


def _install_fake_lmpolygraph(
    monkeypatch: pytest.MonkeyPatch,
    raw_uncertainty: float,
    generation_text: str,
) -> None:
    """Inject a minimal fake ``lm_polygraph`` into ``sys.modules``."""
    fake_pkg = ModuleType("lm_polygraph")
    fake_utils = ModuleType("lm_polygraph.utils")
    fake_model_mod = ModuleType("lm_polygraph.utils.model")
    fake_factory_mod = ModuleType("lm_polygraph.utils.factory_estimator")

    class _FakeWhiteboxModel:
        def __init__(self, base_model: Any, tokenizer: Any, model_path: str) -> None:
            self.base_model = base_model
            self.tokenizer = tokenizer
            self.model_path = model_path

    class _FakeFactoryEstimator:
        def __init__(self, name: str, **kwargs: Any) -> None:
            self.name = name
            self.kwargs = kwargs

    def _fake_estimate(
        model: Any, estimator: Any, input_text: str
    ) -> SimpleNamespace:
        return SimpleNamespace(
            uncertainty=raw_uncertainty,
            generation_text=generation_text,
            input_text=input_text,
        )

    fake_pkg.estimate_uncertainty = _fake_estimate  # type: ignore[attr-defined]
    fake_model_mod.WhiteboxModel = _FakeWhiteboxModel  # type: ignore[attr-defined]
    fake_factory_mod.FactoryEstimator = _FakeFactoryEstimator  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "lm_polygraph", fake_pkg)
    monkeypatch.setitem(sys.modules, "lm_polygraph.utils", fake_utils)
    monkeypatch.setitem(sys.modules, "lm_polygraph.utils.model", fake_model_mod)
    monkeypatch.setitem(
        sys.modules, "lm_polygraph.utils.factory_estimator", fake_factory_mod
    )


def test_score_happy_path_with_fake_lmpolygraph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_lmpolygraph(
        monkeypatch, raw_uncertainty=0.5, generation_text="the answer is 42"
    )
    est = LMPolygraphEstimator(
        method="MaximumSequenceProbability", refusal_threshold=0.5
    )

    class _FakeHF:
        model_id = "fake/model"

        def _load(self) -> tuple[Any, Any, str]:
            return object(), object(), "cpu"

    monkeypatch.setattr(est, "_require_whitebox", lambda backend: backend)
    result = est.score(_FakeHF(), "what is the answer?")  # type: ignore[arg-type]

    assert isinstance(result, UncertaintyResult)
    assert result.answer == "the answer is 42"
    assert result.raw_scores["lmpolygraph_uncertainty"] == pytest.approx(0.5)
    assert result.confidence == pytest.approx(math.exp(-0.5))
    assert result.should_refuse is False


def test_registered_in_pipeline_factory() -> None:
    from lub.uncertainty.base import get_estimator_cls

    assert get_estimator_cls("lmpolygraph") is LMPolygraphEstimator
