# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import pytest

from lub.pipeline import UncertaintyPipeline
from lub.types import UncertaintyResult
from lub.wrappers.dummy import DummyBackend


def test_from_pretrained_dummy_token_logprob() -> None:
    pipe = UncertaintyPipeline.from_pretrained(
        model="dummy-0", backend="dummy", estimator="token_logprob"
    )
    assert isinstance(pipe.backend, DummyBackend)
    result = pipe.answer("What is 2+2?")
    assert isinstance(result, UncertaintyResult)
    assert 0.0 <= result.confidence <= 1.0


def test_unknown_estimator_rejected() -> None:
    with pytest.raises(ValueError):
        UncertaintyPipeline.from_pretrained(
            model="dummy-0", backend="dummy", estimator="nope"
        )


def test_unknown_backend_rejected() -> None:
    with pytest.raises(ValueError):
        UncertaintyPipeline.from_pretrained(
            model="dummy-0", backend="nope", estimator="token_logprob"
        )


def test_refusal_threshold_forces_should_refuse() -> None:
    pipe = UncertaintyPipeline.from_pretrained(
        model="dummy-0",
        backend="dummy",
        estimator="token_logprob",
        refusal_threshold=0.99,
    )
    result = pipe.answer("anything")
    assert result.should_refuse is True


def test_batch_answer_returns_one_per_prompt() -> None:
    pipe = UncertaintyPipeline.from_pretrained(
        model="dummy-0", backend="dummy", estimator="token_logprob"
    )
    results = pipe.batch_answer(["q1", "q2", "q3"])
    assert len(results) == 3
    assert all(isinstance(r, UncertaintyResult) for r in results)


def test_to_dict_from_dict_round_trip() -> None:
    pipe = UncertaintyPipeline.from_pretrained(
        model="dummy-0",
        backend="dummy",
        estimator="self_consistency",
        refusal_threshold=0.4,
    )
    data = pipe.to_dict()
    # to_dict() emits the stable REGISTRY_KEY, not the class name.
    assert data["backend"] == "dummy"
    assert data["model"] == "dummy-0"
    assert data["estimator"] == "self_consistency"
    assert data["refusal_threshold"] == 0.4

    rebuilt = UncertaintyPipeline.from_dict(data)
    assert rebuilt.to_dict() == data
    assert isinstance(rebuilt.backend, DummyBackend)


def test_from_dict_accepts_legacy_class_name_key() -> None:
    """Older persisted records stored the class name; still loadable."""
    legacy = {
        "backend": "DummyBackend",
        "model": "dummy-0",
        "estimator": "self_consistency",
        "refusal_threshold": 0.4,
    }
    rebuilt = UncertaintyPipeline.from_dict(legacy)
    assert isinstance(rebuilt.backend, DummyBackend)
    # Re-serialization emits the new stable key.
    assert rebuilt.to_dict()["backend"] == "dummy"
